"""Work Packet intake rule and deterministic signal classification."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

CONTRACT = "workpacket-intake"
CONTRACT_VERSION = "1.0"
RULE_CONTRACT = "workpacket-intake-rule"

WORKPACKET_STATES = [
    "detected",
    "grounded",
    "proposed",
    "approved",
    "running",
    "waiting",
    "verified",
    "closed",
]

AUTHORITY_LEVELS = [
    {
        "level": "L0_ignore_or_record",
        "meaning": "No actionable work packet. Keep as context, receipt, or noise.",
        "requires_human_approval": False,
    },
    {
        "level": "L1_read_and_prepare",
        "meaning": "Read local context and prepare a plan, draft, or dry-run.",
        "requires_human_approval": False,
    },
    {
        "level": "L2_local_write",
        "meaning": "Write local files or run local tests inside the current workspace.",
        "requires_human_approval": False,
    },
    {
        "level": "L3_approval_before_external_action",
        "meaning": "External write or stakeholder-facing action requires explicit approval.",
        "requires_human_approval": True,
    },
    {
        "level": "L4_delegated_low_risk_external_write",
        "meaning": "Pre-approved, low-risk external writes only, with receipts.",
        "requires_human_approval": "policy_dependent",
    },
    {
        "level": "L5_autonomous_execution",
        "meaning": "Autonomous execution only for bounded, audited, reversible workflows.",
        "requires_human_approval": "policy_dependent",
    },
]

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "crm": ("attio", "crm", "hubspot", "deal", "prospect", "pipeline", "contact"),
    "communication": ("email", "gmail", "mail", "relance", "reponds", "réponds", "whatsapp", "message"),
    "finance": ("facture", "pennylane", "qonto", "devis", "paiement", "encaisse", "encaissé"),
    "meeting_followup": ("meeting", "réunion", "reunion", "fireflies", "calendar", "compte rendu"),
    "orchestration": ("workpacket", "work packet", "zab", "/goal", "/loop", "intake", "cron", "scheduled"),
    "implementation": ("code", "implémente", "implemente", "développe", "developpe", "fix", "test", "pytest", "api", "cli"),
    "research": ("cherche", "recherche", "audit", "analyse", "sota", "benchmark", "synthèse", "synthese"),
}

EXTERNAL_WRITE_TERMS = (
    "envoie",
    "send",
    "publie",
    "publish",
    "supprime",
    "delete",
    "archive",
    "attio",
    "gmail",
    "email",
    "whatsapp",
    "pennylane",
    "qonto",
    "notion",
    "linear",
    "fullenrich",
    "phantombuster",
)

HARNESS_NOISE_TERMS = (
    "<environment_context>",
    "<recommended_plugins>",
    "toolcall",
    "tool schema",
    '"parameters":',
    "sandbox_mode",
    "approval policy",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _matching_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _signal_hash(signal: str, source: str, project: str | None) -> str:
    material = "\n".join([source.strip().lower(), project or "", signal.strip()])
    return sha256(material.encode("utf-8")).hexdigest()


def _excerpt(signal: str, limit: int = 360) -> str:
    compact = " ".join(signal.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _title(signal: str) -> str:
    for raw_line in signal.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<"):
            continue
        if line.startswith("/goal"):
            line = line.replace("/goal", "", 1).strip()
        if line:
            return _excerpt(line, limit=96)
    return "Untitled work packet"


def _event_type(normalized: str) -> dict[str, Any]:
    if _contains_any(normalized, HARNESS_NOISE_TERMS):
        return {
            "type": "harness_noise",
            "action": "ignore",
            "confidence": 0.9,
            "reason": "The signal looks like environment, harness, or tool metadata.",
        }
    if "/goal" in normalized:
        return {
            "type": "goal",
            "action": "create_parent_packet",
            "confidence": 0.94,
            "reason": "Explicit persistent goal marker.",
        }
    if "/loop" in normalized:
        return {
            "type": "loop",
            "action": "create_child_run",
            "confidence": 0.9,
            "reason": "Explicit iterative run marker.",
        }
    if "scheduled task" in normalized or "cron" in normalized or "scheduler" in normalized:
        return {
            "type": "scheduled_run",
            "action": "attach_run_receipt_or_create_packet",
            "confidence": 0.78,
            "reason": "Scheduled or automatic run signal.",
        }
    if any(term in normalized for term in ("preuve", "receipt", "done", "terminé", "termine", "exit_code", "tests pass")):
        return {
            "type": "agent_receipt",
            "action": "append_receipt",
            "confidence": 0.7,
            "reason": "The signal appears to report execution evidence.",
        }
    return {
        "type": "human_message",
        "action": "create_packet",
        "confidence": 0.72,
        "reason": "Default actionable human signal.",
    }


def _intent(normalized: str) -> dict[str, Any]:
    matches: dict[str, list[str]] = {}
    for kind, keywords in INTENT_KEYWORDS.items():
        hit = _matching_terms(normalized, keywords)
        if hit:
            matches[kind] = hit
    if not matches:
        return {"kind": "general_work", "confidence": 0.42, "matches": {}}
    priority = ["crm", "finance", "communication", "meeting_followup", "orchestration", "implementation", "research"]
    selected = max(matches, key=lambda kind: (len(matches[kind]), -priority.index(kind) if kind in priority else -999))
    confidence = min(0.92, 0.55 + 0.1 * len(matches[selected]))
    return {"kind": selected, "confidence": round(confidence, 2), "matches": matches}


def _priority(normalized: str, intent_kind: str) -> str:
    if any(term in normalized for term in ("urgent", "aujourd'hui", "today", "bloquant", "critique")):
        return "P1"
    if intent_kind in {"crm", "communication", "finance"}:
        return "P2"
    return "P3"


def _authority(normalized: str, intent_kind: str, event_type: str) -> dict[str, Any]:
    if event_type == "harness_noise":
        return {
            "level": "L0_ignore_or_record",
            "requires_human_approval": False,
            "allowed_without_approval": ["record dismissal reason"],
            "blocked_without_approval": [],
            "reason": "No actionable business intent should be inferred from harness metadata.",
        }
    external_terms = _matching_terms(normalized, EXTERNAL_WRITE_TERMS)
    if external_terms or intent_kind in {"crm", "communication", "finance"}:
        return {
            "level": "L3_approval_before_external_action",
            "requires_human_approval": True,
            "allowed_without_approval": [
                "read local or cached context",
                "build research packet",
                "prepare dry-run or draft",
                "list proposed external mutations",
            ],
            "blocked_without_approval": [
                "send email or message",
                "create/update/delete CRM records",
                "create finance records or payments",
                "launch enrichment or prospecting automation",
            ],
            "reason": "The signal touches an external system or stakeholder-facing workflow.",
            "matched_terms": external_terms,
        }
    if any(term in normalized for term in ("développe", "developpe", "implémente", "implemente", "modifie", "fix", "corrige", "test")):
        return {
            "level": "L2_local_write",
            "requires_human_approval": False,
            "allowed_without_approval": [
                "edit local workspace files",
                "run local tests",
                "produce receipts and diffs",
            ],
            "blocked_without_approval": ["external writes", "sending messages", "CRM or finance mutations"],
            "reason": "The user asks for local implementation or verification.",
        }
    return {
        "level": "L1_read_and_prepare",
        "requires_human_approval": False,
        "allowed_without_approval": ["read local context", "prepare plan", "produce dry-run"],
        "blocked_without_approval": ["external writes", "destructive local commands"],
        "reason": "No explicit local-write or external-write permission was detected.",
    }


def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = row.get("id") or repr(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _sources(intent_kind: str, matched_kinds: list[str] | None = None) -> list[dict[str, str]]:
    base = [
        {"id": "zab_global_rule", "kind": "policy", "requirement": "Apply the global intake rule before execution."},
        {"id": "project_instructions", "kind": "local_file", "requirement": "Read AGENTS.md/agent.md and local routing docs when a project is known."},
    ]
    by_intent: dict[str, list[dict[str, str]]] = {
        "crm": [
            {"id": "crm_record", "kind": "external_read", "requirement": "Resolve company/contact/deal before proposing mutations."},
            {"id": "direct_sources", "kind": "evidence", "requirement": "Capture direct URLs or local evidence first."},
        ],
        "communication": [
            {"id": "thread_context", "kind": "external_read", "requirement": "Resolve thread, recipient identity, and relationship history."},
            {"id": "tone_policy", "kind": "policy", "requirement": "Confirm tone, sender identity, and validation gate."},
        ],
        "finance": [
            {"id": "finance_record", "kind": "external_read", "requirement": "Verify invoice/payment/devis state from finance source."},
        ],
        "meeting_followup": [
            {"id": "calendar_or_transcript", "kind": "source", "requirement": "Use meeting date, participants, transcript or notes."},
        ],
        "implementation": [
            {"id": "repo_tests", "kind": "local_command", "requirement": "Identify targeted test command before closing."},
        ],
        "orchestration": [
            {"id": "parent_goal", "kind": "state", "requirement": "Resolve whether this creates a parent packet or updates one."},
        ],
    }
    rows = list(base)
    for kind in matched_kinds or [intent_kind]:
        rows.extend(by_intent.get(kind, []))
    return _dedupe_rows(rows)


def _projections(intent_kind: str, matched_kinds: list[str] | None = None) -> list[dict[str, str]]:
    projections = [
        {"id": "workpacket_state", "target": "zab", "requirement": "Persist state and receipts before closure."},
        {"id": "operator_cockpit", "target": "cockpit", "requirement": "Expose next action or blocked state if operationally relevant."},
    ]
    for kind in matched_kinds or [intent_kind]:
        if kind == "crm":
            projections.append({"id": "crm_projection", "target": "crm", "requirement": "Sync CRM only after approval and receipt."})
        if kind == "communication":
            projections.append({"id": "communication_projection", "target": "mail_or_message", "requirement": "Draft/send status must be explicit."})
        if kind == "finance":
            projections.append({"id": "finance_projection", "target": "finance", "requirement": "Attach invoice/payment proof."})
        if kind == "implementation":
            projections.append({"id": "code_projection", "target": "git_or_tests", "requirement": "Attach diff summary and test evidence."})
    return _dedupe_rows(projections)


def _definition_of_done(intent_kind: str, authority: dict[str, Any]) -> list[str]:
    done = [
        "Intent is classified and linked to a packet idempotency key.",
        "Required sources are checked or explicitly marked unavailable.",
        "Policy gates are listed before any mutation.",
        "Execution receipt contains commands, outputs, links, or artifacts.",
        "Mandatory projections are synced or explicitly waived with reason.",
        "Packet state is `verified` before it can become `closed`.",
    ]
    if authority.get("requires_human_approval"):
        done.insert(3, "Human approval is captured before external write or stakeholder-facing action.")
    if intent_kind in {"crm", "communication", "finance"}:
        done.append("External system state is re-read after mutation to prove completion.")
    return done


def _policy_gates(intent_kind: str, authority: dict[str, Any]) -> list[dict[str, Any]]:
    gates = [
        {
            "id": "grounding_required",
            "status": "required",
            "rule": "No proposal without source requirements or explicit source gaps.",
        },
        {
            "id": "receipt_required",
            "status": "required",
            "rule": "No closure without typed receipt and verification evidence.",
        },
    ]
    if authority.get("requires_human_approval"):
        gates.append(
            {
                "id": "human_approval_required",
                "status": "required",
                "rule": "Approval is required before external write, message send, CRM mutation, finance mutation, enrichment, or prospecting automation.",
            }
        )
    if intent_kind in {"crm", "communication", "finance"}:
        gates.append(
            {
                "id": "external_reread_required",
                "status": "required",
                "rule": "After approved mutation, re-read the external system and attach a receipt.",
            }
        )
    return gates


def _next_actions(event: dict[str, Any], intent_kind: str, authority: dict[str, Any]) -> list[str]:
    if event["type"] == "harness_noise":
        return ["Ignore as non-actionable harness metadata unless a human explicitly references it."]
    actions = [
        "Create or locate the parent Work Packet using the idempotency key.",
        "Build the research packet from required sources.",
        "Propose the smallest next action and expected receipt.",
    ]
    if authority.get("requires_human_approval"):
        actions.append("Stop at dry-run/draft until explicit human approval is captured.")
    else:
        actions.append("Execute the local action, then attach test or verification evidence.")
    if intent_kind in {"crm", "communication", "finance"}:
        actions.append("Re-read the external source after any approved mutation before closing.")
    return actions


def get_global_rule() -> dict[str, Any]:
    """Return the global Work Packet intake rule."""

    return {
        "contract": RULE_CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": _now(),
        "name": "Global Work Packet Intake Rule",
        "summary": "Every actionable signal becomes a typed Work Packet or an explicit dismissal. Closure requires grounding, authority, receipt, projections, and verification.",
        "applies_to": [
            "human_message",
            "goal",
            "loop",
            "scheduled_run",
            "agent_receipt",
            "external_signal",
        ],
        "state_machine": WORKPACKET_STATES,
        "invariants": [
            "Do not treat chat, task rows, CRM records, or emails as the source of truth for work state.",
            "The Work Packet is the execution contract; external systems are projections.",
            "No external write or stakeholder-facing action without the applicable authority gate.",
            "No packet can close without a typed receipt and verification evidence.",
            "Scheduled runs and agent receipts update packets; they do not automatically create human actions.",
            "Harness metadata is ignored unless a human explicitly turns it into work.",
        ],
        "authority_levels": AUTHORITY_LEVELS,
        "default_definition_of_done": _definition_of_done("general_work", {"requires_human_approval": False}),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    """Render an intake payload as a compact operator-facing Markdown packet."""

    packet = payload.get("workpacket") or {}
    lines = [
        "# Work Packet Intake",
        "",
        f"- Contract: `{payload.get('contract')}`",
        f"- Event: `{payload.get('event_type', {}).get('type')}`",
        f"- Action: `{payload.get('event_type', {}).get('action')}`",
        f"- Intent: `{packet.get('intent', {}).get('kind')}`",
        f"- State: `{packet.get('state')}`",
        f"- Priority: `{packet.get('priority')}`",
        f"- Idempotency key: `{packet.get('idempotency_key')}`",
        f"- Authority: `{packet.get('authority', {}).get('level')}`",
        "",
        "## Next Actions",
    ]
    lines.extend(f"- {item}" for item in packet.get("next_actions") or [])
    lines.extend(["", "## Definition of Done"])
    lines.extend(f"- {item}" for item in packet.get("definition_of_done") or [])
    return "\n".join(lines)


def intake_from_params(
    signal: str,
    *,
    source: str = "manual",
    project: str | None = None,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Classify an incoming signal into the Work Packet execution contract."""

    normalized = _normalize(signal)
    event = _event_type(normalized)
    intent = _intent(normalized)
    intent_kind = str(intent["kind"])
    matched_kinds = list((intent.get("matches") or {}).keys()) or [intent_kind]
    authority = _authority(normalized, intent_kind, str(event["type"]))
    should_create = event["action"] not in {"ignore"} and event["type"] != "harness_noise"
    key_hash = _signal_hash(signal, source, project)
    workpacket = {
        "should_create": should_create,
        "idempotency_key": f"wp-{key_hash[:16]}",
        "title": _title(signal),
        "state": "detected" if should_create else "closed",
        "priority": _priority(normalized, intent_kind),
        "owner": requested_by or "human",
        "project": project,
        "intent": intent,
        "authority": authority,
        "required_sources": _sources(intent_kind, matched_kinds),
        "policy_gates": _policy_gates(intent_kind, authority),
        "required_projections": _projections(intent_kind, matched_kinds),
        "definition_of_done": _definition_of_done(intent_kind, authority),
        "next_actions": _next_actions(event, intent_kind, authority),
    }
    payload = {
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": _now(),
        "global_rule_ref": RULE_CONTRACT,
        "signal": {
            "source": source,
            "project": project,
            "requested_by": requested_by,
            "hash": key_hash,
            "excerpt": _excerpt(signal),
        },
        "event_type": event,
        "workpacket": workpacket,
        "warnings": [] if signal.strip() else ["empty_signal"],
    }
    payload["markdown"] = render_markdown(payload)
    return payload
