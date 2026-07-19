"""Pre-publish privacy guard for zab source releases.

The guard is intentionally source-control aware: the default scan checks
committed files, and the pre-push mode checks only the objects about to leave
the machine. Reports never include matched values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


ZERO_SHA_RE = re.compile(r"^0{40,64}$")
TEXT_SCAN_LIMIT_BYTES = 2_000_000

SKIP_CONTENT_BASENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "uv.lock",
    "yarn.lock",
}

SAFE_ENV_BASENAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
}

PRIVATE_DIR_NAMES = {
    ".claude",
    ".codex",
    ".cursor",
    ".gemini",
    ".hermes",
    ".screenshots",
    "backups",
    "dumps",
    "exports",
    "private",
    "scratch",
    "sessions",
    "tmp",
}

DATA_EXTENSIONS = {
    ".csv",
    ".db",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".parquet",
    ".pdf",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".tsv",
    ".txt",
    ".webp",
    ".zip",
}

BINARY_OR_SECRET_EXTENSIONS = {
    ".key",
    ".kdbx",
    ".p12",
    ".pem",
    ".pfx",
}

PLACEHOLDER_HOME_USERS = {
    "example",
    "runner",
    "user",
    "username",
    "votre_user",
    "your-user",
    "your_user",
}


@dataclass(frozen=True)
class Candidate:
    path: str
    origin: str
    blob_spec: str | None = None


@dataclass(frozen=True)
class Finding:
    path: str
    rule_id: str
    message: str
    severity: str = "error"
    origin: str = ""
    line: int | None = None


@dataclass(frozen=True)
class ScanResult:
    mode: str
    scanned_files: int
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "scanned_files": self.scanned_files,
            "finding_count": len(self.findings),
            "findings": [asdict(finding) for finding in self.findings],
        }


class PublishGuardError(RuntimeError):
    """Raised when the git surface cannot be inspected."""


def _repo_root(repo: Path | None = None) -> Path:
    if repo is not None:
        return repo.resolve()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PublishGuardError("not inside a git repository")
    return Path(proc.stdout.strip()).resolve()


def _git_bytes(repo: Path, args: Sequence[str], *, input_text: str | None = None) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_text.encode("utf-8") if input_text is not None else None,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise PublishGuardError(detail or f"git {' '.join(args)} failed")
    return proc.stdout


def _git_text(repo: Path, args: Sequence[str]) -> str:
    return _git_bytes(repo, args).decode("utf-8", errors="replace")


def _split_nul(data: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in data.split(b"\0") if item]


def _has_head(repo: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True, check=False)
    return proc.returncode == 0


def _is_zero_sha(value: str) -> bool:
    return bool(ZERO_SHA_RE.fullmatch(value))


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str | None, str]] = set()
    out: list[Candidate] = []
    for candidate in candidates:
        key = (candidate.path, candidate.blob_spec, candidate.origin)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _tracked_candidates(repo: Path) -> list[Candidate]:
    treeish = "HEAD" if _has_head(repo) else ":"
    candidates = []
    for path in _split_nul(_git_bytes(repo, ["ls-files", "-z"])):
        blob_spec = f"{treeish}:{path}" if treeish != ":" else f":{path}"
        candidates.append(Candidate(path=path, origin=treeish, blob_spec=blob_spec))
    return candidates


def _staged_candidates(repo: Path) -> list[Candidate]:
    paths = _split_nul(_git_bytes(repo, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]))
    return [Candidate(path=path, origin="index", blob_spec=f":{path}") for path in paths]


def _worktree_candidates(repo: Path) -> list[Candidate]:
    paths = _split_nul(_git_bytes(repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]))
    return [Candidate(path=path, origin="worktree") for path in paths]


def _pre_push_candidates(repo: Path, stdin_text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts[:4]
        if _is_zero_sha(local_sha):
            continue

        if _is_zero_sha(remote_sha):
            paths = _split_nul(_git_bytes(repo, ["ls-tree", "-r", "--name-only", "-z", local_sha]))
        else:
            paths = _split_nul(
                _git_bytes(repo, ["diff", "--name-only", "-z", "--diff-filter=ACMR", f"{remote_sha}..{local_sha}"])
            )

        origin = f"{local_ref}->{remote_ref}"
        candidates.extend(Candidate(path=path, origin=origin, blob_spec=f"{local_sha}:{path}") for path in paths)
    return _dedupe(candidates)


def _read_candidate(repo: Path, candidate: Candidate) -> bytes | None:
    if candidate.blob_spec:
        try:
            return _git_bytes(repo, ["show", candidate.blob_spec])
        except PublishGuardError:
            return None

    path = repo / candidate.path
    try:
        if not path.is_file() and not path.is_symlink():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _norm_path(path: str) -> str:
    return path.replace(os.sep, "/")


def _path_parts(path: str) -> list[str]:
    return [part for part in _norm_path(path).split("/") if part]


def _is_safe_env_path(path: str) -> bool:
    basename = Path(path).name.lower()
    return basename in SAFE_ENV_BASENAMES or basename.endswith((".example", ".sample", ".template"))


def _is_env_path(path: str) -> bool:
    basename = Path(path).name.lower()
    return basename == ".env" or basename.startswith(".env.")


def _path_findings(candidate: Candidate) -> list[Finding]:
    path = _norm_path(candidate.path)
    lower = path.lower()
    basename = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    parts = [part.lower() for part in _path_parts(path)]
    findings: list[Finding] = []

    def add(rule_id: str, message: str) -> None:
        findings.append(Finding(path=path, origin=candidate.origin, rule_id=rule_id, message=message))

    if _is_env_path(path) and not _is_safe_env_path(path):
        add("path.env_file", "Environment files with real local values must stay out of git.")

    if suffix in BINARY_OR_SECRET_EXTENSIONS:
        add("path.secret_material", "Private keys or credential containers must not be published.")

    if basename in {"state.db", "webui.db"} or suffix in {".db", ".sqlite", ".sqlite3"}:
        add("path.local_database", "Local databases and generated state are private workspace data.")

    if path in {"agent.md", "vision.md", "exampleconf.txt"}:
        add("path.operator_note", "Operator notes and local agent guidance are not part of the public zab tool.")

    if lower.startswith("docs/plans/"):
        add("path.operator_plan", "Local plans can contain private workspace context and should not be published.")

    if any(part in PRIVATE_DIR_NAMES for part in parts):
        add("path.private_directory", "Private cache, scratch, export, or session directories must stay local.")

    if re.search(r"(^|/)evolution-[^/]+\.(json|png|jpg|jpeg|webp|zip)$", lower):
        add("path.channel_export", "Evolution or channel exports are personal content, not source code.")

    if re.search(r"(^|/)(messages?|threads?|transcripts?|sessions?|exports?|dumps?)-[^/]+\.(json|jsonl|csv|txt|md|zip)$", lower):
        add("path.content_dump", "Message, transcript, session, export, and dump files must not be published.")

    if suffix in DATA_EXTENSIONS and re.search(r"(^|/)(qr|personal|perso|private)[^/]*\.", lower):
        add("path.personal_artifact", "Personal artifacts must not be published with the zab source.")

    return findings


CONTENT_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "secret.private_key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        "Private key material detected.",
    ),
    (
        "secret.openai",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
        "OpenAI API key-like token detected.",
    ),
    (
        "secret.github",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        "GitHub token-like value detected.",
    ),
    (
        "secret.gitlab",
        re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
        "GitLab token-like value detected.",
    ),
    (
        "secret.google_api",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        "Google API key-like value detected.",
    ),
    (
        "secret.slack",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        "Slack token-like value detected.",
    ),
    (
        "secret.telegram",
        re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35,}\b"),
        "Telegram bot token-like value detected.",
    ),
    (
        "secret.aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "AWS access key-like value detected.",
    ),
    (
        "secret.composio",
        re.compile(r"\buak_[A-Za-z0-9]{16,}\b"),
        "Composio user API key-like value detected.",
    ),
)

HOME_PATH_RE = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]{2,})(?:/|$)")
DATABASE_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^:\s/@]+:[^@\s]+@([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
DATA_EXPORT_MARKERS_RE = re.compile(
    r'"(?:body|chatId|conversation|messageTimestamp|messages|participants|pushName|remoteJid|sender|threadId)"\s*:',
    re.IGNORECASE,
)


def _line_for_match(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:4096]


def _safe_database_host(host: str) -> bool:
    lowered = host.lower()
    return lowered in {"localhost", "127.0.0.1", "::1"} or lowered.endswith((".example.com", ".test", ".invalid"))


def _content_findings(candidate: Candidate, data: bytes) -> list[Finding]:
    path = _norm_path(candidate.path)
    basename = Path(path).name
    suffix = Path(path).suffix.lower()
    if basename in SKIP_CONTENT_BASENAMES or _is_binary(data):
        return []

    findings: list[Finding] = []
    if len(data) > TEXT_SCAN_LIMIT_BYTES:
        if suffix in DATA_EXTENSIONS:
            findings.append(
                Finding(
                    path=path,
                    origin=candidate.origin,
                    rule_id="content.large_data_file",
                    message="Large data-like files are not part of the publishable zab source surface.",
                )
            )
        data = data[:TEXT_SCAN_LIMIT_BYTES]

    text = data.decode("utf-8", errors="ignore")

    for rule_id, pattern, message in CONTENT_RULES:
        match = pattern.search(text)
        if match:
            findings.append(
                Finding(
                    path=path,
                    origin=candidate.origin,
                    rule_id=rule_id,
                    message=message,
                    line=_line_for_match(text, match.start()),
                )
            )

    for match in HOME_PATH_RE.finditer(text):
        user = match.group(1).lower()
        if user in PLACEHOLDER_HOME_USERS:
            continue
        findings.append(
            Finding(
                path=path,
                origin=candidate.origin,
                rule_id="private.home_path",
                message="Absolute home paths can expose the local operator or machine layout.",
                line=_line_for_match(text, match.start()),
            )
        )
        break

    for match in DATABASE_URL_RE.finditer(text):
        if _safe_database_host(match.group(1)):
            continue
        findings.append(
            Finding(
                path=path,
                origin=candidate.origin,
                rule_id="secret.database_url",
                message="Database URL with embedded credentials detected.",
                line=_line_for_match(text, match.start()),
            )
        )
        break

    if suffix in {".json", ".jsonl", ".csv", ".txt"}:
        marker_names = {m.group(0).split('"', 2)[1].lower() for m in DATA_EXPORT_MARKERS_RE.finditer(text)}
        if len(marker_names) >= 2:
            findings.append(
                Finding(
                    path=path,
                    origin=candidate.origin,
                    rule_id="content.message_export",
                    message="Message or conversation export-shaped data detected.",
                )
            )

    return findings


def _candidates_for_mode(repo: Path, mode: str, pre_push_stdin: str | None) -> list[Candidate]:
    if mode == "tracked":
        return _tracked_candidates(repo)
    if mode == "staged":
        return _staged_candidates(repo)
    if mode == "worktree":
        return _worktree_candidates(repo)
    if mode == "pre-push":
        return _pre_push_candidates(repo, pre_push_stdin or "")
    raise ValueError(f"unsupported mode: {mode}")


def scan_publish_surface(
    *,
    mode: str = "tracked",
    repo: Path | None = None,
    pre_push_stdin: str | None = None,
) -> ScanResult:
    """Scan a git publish surface for secrets and private content artifacts."""

    root = _repo_root(repo)
    candidates = _dedupe(_candidates_for_mode(root, mode, pre_push_stdin))
    findings: list[Finding] = []

    for candidate in candidates:
        findings.extend(_path_findings(candidate))
        data = _read_candidate(root, candidate)
        if data is not None:
            findings.extend(_content_findings(candidate, data))

    return ScanResult(mode=mode, scanned_files=len(candidates), findings=tuple(findings))


def format_report(result: ScanResult) -> str:
    lines = [f"zab publish guard: scanned {result.scanned_files} file(s) in {result.mode} mode"]
    if result.ok:
        lines.append("zab publish guard: OK")
        return "\n".join(lines)

    lines.append(f"zab publish guard: FAILED ({len(result.findings)} finding(s))")
    for finding in result.findings:
        location = f":{finding.line}" if finding.line else ""
        origin = f" [{finding.origin}]" if finding.origin else ""
        lines.append(f"- {finding.rule_id} {finding.path}{location}{origin}: {finding.message}")
    lines.append("No matched values are printed by this guard.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan zab publish surfaces without printing raw secret values.")
    parser.add_argument(
        "--mode",
        choices=("tracked", "staged", "worktree", "pre-push"),
        default="tracked",
        help="Git surface to scan. pre-push reads the standard Git hook ref lines from stdin.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human report.")
    args = parser.parse_args(argv)

    try:
        stdin_text = sys.stdin.read() if args.mode == "pre-push" else None
        result = scan_publish_surface(mode=args.mode, pre_push_stdin=stdin_text)
    except (PublishGuardError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"zab publish guard: ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
