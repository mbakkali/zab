# Agent Improvements

This file is a public-safe roadmap of frictions observed by agents while using Zab.
Do not add user data, private workspace data, secrets, raw logs, or customer context.

## 2026-08-16 - Weekly hygiene pass: manifest was healthy, two stale status labels, one closed debt item

- Trigger: mention
- Context: the weekly hygiene routine ran the offline parts of `docs/capability-audit.md` against a fresh checkout — full test suite, `ruff check .`, the UI typecheck, the publish guard, a static parity check of all 30 declared capabilities' CLI forms (including flags) and API routes, a scan for data that should not be in a public repository, and one open debt item from this file.
- Observation: base health was clean — `uv run pytest zab/tests -q` passed 524/524 with no `gcloud`/`composio` on `PATH`, `npx tsc --noEmit` was clean, and `./scripts/publish-check.sh` stayed green. The static parity sweep found every declared CLI command resolving with every declared flag present in its `--help`, and every declared API route registered on the real FastAPI app — the two gaps `docs/capability-audit.md` flags as historically known (`tasks.sources_status` → `zab config --json`, `channels.list` missing `--json`) were already fixed in the 2026-08-02/2026-08-09 passes, contrary to what this file's own status labels said: two entries (`2026-07-28` workstation status, `2026-07-31` conversation digest boilerplate/counters) were still marked `captured` despite their fixes having shipped weeks ago — a false "still broken" signal for the next agent to trip over. One real finding survived: the manifest's `channels.list.cli` field still read `zab channels list` with no `--json`, even though the command has supported `--json` since 2026-08-09 — the declaration undersold what the CLI actually does, in the same direction as the original bug (contract says `json_cli: true`, declared invocation doesn't show it). The privacy scan found no new secret, absolute path or real identity in the diff since last week (there is none — no commits landed between the 2026-08-09 merge and this pass); the pre-existing hardcoded personal Gmail addresses in `channel_bindings.py`/`preflight.py` (present since the repository's first commit, same family as the 2026-08-02 open item) are unchanged and still a business decision, not re-flagged as new.
- Improvement: pointed `channels.list.cli` at `zab channels list --json`, the invocation the manifest's own `json_cli: true` contract promises, and updated the two tests that pinned the stale string. Corrected the two mislabeled `captured` entries to `verified` with the commit that actually fixed them, instead of re-doing already-shipped work. Closed the one remaining real friction in the `2026-07-31` conversation-digest entry: added `zab conversations digest --cwd <dir>`, filtering the digest to conversations whose transcript path/session id actually carries the given working directory — independent of the semantic org/project match, which by design can label a session from a client sub-folder under the client's canonical project.
- Evidence: `uv run pytest zab/tests -q` passes 525/525 (524 + 1 new test pinning `--cwd`); `zab/tests/test_capabilities_manifest_parity.py` and `zab/tests/test_capabilities.py` assert the manifest's `channels.list` field now includes `--json` and that the command still returns valid JSON; `zab/tests/test_conversation_digest.py::test_digest_cwd_filter_selects_the_session_that_ran_there` shows two same-project-labelled sessions from different directories narrowed to one by `--cwd`, and shows the filter is a no-op (`cwd_filter: null`) when omitted. `ruff check .` stayed at 10 findings (import-order and single-letter-variable style choices already triaged as lower-value than the mass-cleanup risk of touching them; left alone). `./scripts/publish-check.sh` stayed green throughout.
- Status: verified

## 2026-08-09 - Weekly hygiene pass: crashing tool catalog, silent CLI parity gaps, a leaked email

- Trigger: mention
- Context: the weekly hygiene routine ran the offline parts of `docs/capability-audit.md` against a fresh checkout — full test suite, `ruff check .`, the UI typecheck, the publish guard, and a static parity check of every capability the manifest declares.
- Observation: `uv run pytest zab/tests -q` failed 31 of 513 tests on a machine without the `composio` CLI installed. All 31 traced to one line: `any((shutil.which("composio") or composio_cli_path()) and env_keys)` calls `any()` on a scalar expression, not an iterable — when neither resolves, the expression is `None` and `any(None)` raises `TypeError`. This runs inside `build_tools_catalog()`, which nearly every CLI and API path calls, so it took down far more than its own domain. `ruff check .` then caught a second, live bug in the same function: the sibling branch (connector registered, `env_keys` declared — the real shape of the Fireflies tool entry) calls `os.environ.get()` without the file ever importing `os`, a `NameError` no existing test exercised. Separately, one ledger regression test (`internal_calendar_is_not_a_client`) failed on any machine without the operator's private `~/.config/zab/conversation-ledger-entities.yaml`: the internal-organization fallback that AGENT_IMPROVEMENTS already described as fixed (2026-08-01, "Trigger WorkPackets on intent") only worked when that private file existed, so a fresh checkout — this sandbox, any CI runner — silently dropped internal mail to no organization at all. A `test_remote_vm.py` test had the same class of bug for a different reason: it mocked `_gcloud` but not `resolve_bin`, so on a machine without the `gcloud` binary it silently took the REST fallback path instead of the mock and failed on missing Application Default Credentials. The static parity check found the two gaps `docs/capability-audit.md` already recorded (`tasks.sources_status` declaring `zab config --json`, which doesn't exist; `channels.list` declaring a CLI form with no `--json`, contradicting the manifest's own `json_cli: true` contract) and no new ones — the other 28 declared capabilities' CLI forms (including flags) and API routes all resolve for real. Reading this week's diff by hand (the publish guard only scans for secrets and paths, not names) found one real personal email address committed as the illustrative example in a code comment and its paired test fixture, introduced by the 2026-08-05 IAP-SSO change.
- Improvement: fixed the `any()`/`os` import bugs in `tool_catalog.py` with a dedicated regression test module pinning both branches; made `INTERNAL_ORG_DOMAINS` build from the merged builtin+local profile set instead of the local document alone, adding a builtin `org_upfund` internal profile so the default resolves without any local config; fixed the `test_remote_vm` test to force the CLI branch like its siblings already do; added `zab tasks sources --json` (wired to the same `task_sources_status()` core function the manifest already points MCP/API at) and `--json` on `zab channels list`, then repointed the manifest at the real commands; replaced the real email with `user@example.com` in both the comment and the test. Also restored `zab ws status --json`, closing a separate captured debt item (2026-07-28) that had the command failing with "No such command 'status'" even though the underlying read-only status logic was already wired to the API. Ran `ruff check . --fix` and removed 33 unused imports/dead locals it found beyond the two live bugs above — checked each dead local before deleting (`pull()`'s discarded `local_changed` shadowed a finer-grained check a few lines later; `_make_archive()`'s unused `home` duplicated resolution `_iter_profile_files()` already does).
- Evidence: `uv run pytest zab/tests -q` went from 31 failed / 482 passed to 522 passed / 522 on a clean `HOME` with no `gcloud` on `PATH`; each fix was verified to fail without it and pass with it (tool_catalog: reverting the import while keeping the new tests reproduces `NameError`; ws status: reverting the CLI addition reproduces the exact "No such command" error). `ruff check .` went from 46 to 10 remaining findings (import-order and single-letter-variable style choices, left alone as lower-value than the mass-cleanup risk of touching them). `npx tsc --noEmit -p tsconfig.app.json` is clean. `./scripts/publish-check.sh` stayed green throughout.
- Status: verified

## 2026-08-02 - Weekly hygiene sweep: a real crash, two manifest lies, one noisy digest

- Trigger: mention
- Context: the weekly repository-hygiene routine ran the capability-audit method against a fresh checkout with no access to the operator's real Postgres, config or transcripts — everything below was found and proven from the repository alone.
- Observation: `build_tools_catalog` called `any()` on a boolean expression instead of an iterable whenever a connector probe had no matching entry, crashing every code path that touches `zab sync` / `build_state` and taking 31 tests down with it — a one-character defect (`any(x and y)` instead of `x and y`) invisible unless that exact probe branch runs. Separately, `test_vm_state_reports_running_session` mocked the gcloud transport but never forced `resolve_bin("gcloud")` to report the binary present, so on a runner without `gcloud` installed the code silently took the REST transport instead and failed on real Google ADC lookup — passing only by accident on a machine that happens to have `gcloud` on PATH. The capability manifest also had two declarations that lied about the CLI: `tasks.sources_status` pointed at `zab config --json`, an option `zab config` never had, and `channels.list` advertised the `json_cli` contract while `zab channels list` had no `--json` flag at all. Finally, the conversation digest's `intent` field picked whichever user turn came first, including a boilerplate turn some CLI providers inject (a recommended-plugins list, an environment-context block) before the real question — making `intent` identical and useless across many unrelated conversations from the same provider.
- Improvement: fixed the boolean expression; pinned the gcloud-transport test the same way its sibling tests already do; added `zab tasks sources --json` (a thin wrapper around the existing `agent_context.task_sources_status()`) and pointed the manifest at it; added `--json` to `zab channels list`; reused the existing `conversation_ledger.intent_signals.classify_intent` boilerplate/automated classifier — already built and tested for WorkPacket intent extraction — to skip non-human turns when deriving the digest's `intent`, instead of writing a second copy of the same heuristic.
- Evidence: `uv run pytest zab/tests -q` moved from 31 failing / 470 passing to 502 passing (one pre-existing test still fails here only because it needs the operator's private local organization profile, which this sandbox correctly has no access to); a new test pins the digest boilerplate skip and is shown to fail without the fix; a new test pins both manifest CLI forms actually round-tripping through the CLI; a full automated pass over every declared capability's CLI form (invoked with `--help`, no side effects) confirms no other command is missing or lacks a promised `--json`.
- Status: verified
- Open item (not fixed, needs a human call): `zab/services/conversation_ledger/org_profiles.py` hardcodes several real, named client organizations (with mail domains and Gmail search queries) as built-in seed data, and at least one real contact email address at a client appears in `eval.py` and a test fixture — present since the repository's first commit and referenced again by name in two docs files. This is a public repository; scrubbing the current files would not remove the exposure from git history, and deciding what (if anything) needs to change — repository visibility, history rewrite, client notification — is a business decision, not a hygiene fix. Flagged to the operator directly rather than acted on.

## 2026-08-01 - Trigger WorkPackets on intent rather than on inbound mail

- Trigger: mention
- Context: an operator running dozens of agent sessions a day found only fourteen WorkPackets, and expected a packet to represent a task they start.
- Observation: three compounding causes. Discovery clustered inbound client mail by organisation and workstream, so fourteen was the arithmetic ceiling — the number of client-workstream pairs — no matter how many threads ran; a single packet covered a workstream holding 226 distinct subjects. A hand audit of forty random ledger rows then showed the stream itself is 43% automated mail and 38% personal messages, with only 20% real work, and that recruitment and newsletter mail naming a client was being attributed to that client. Finally, every domain belonging to the operator's own companies was declared internal and therefore excluded, so work that was not for a client had nowhere to land at all.
- Improvement: classify senders and opening messages by shape rather than by subject. Automated mail no longer attributes to anyone, on a three-day sample of agent conversations 63% proved to be cron or scheduled runs and 14% tool boilerplate, and the remaining human intents — about sixteen a day — each become a packet grouped by project and restated-intent key. Internal exchanges resolve to an internal organisation, last in the chain and never through name aliases, since one's own company name appears in every signature. Project-to-organisation resolution reuses the mail resolver plus the `<org>-cowork` directory convention.
- Evidence: `uv run pytest zab/tests -q` passes 498 tests, including one per classification trap; on a real corpus the packet count moved from 14 to 74, of which 60 are tasks the operator started, and a second run created none.
- Status: verified

## 2026-07-31 - Join projects and people to the ledger organizations

- Trigger: mention
- Context: a workspace wanted every object — work packets, interactions, repositories, recurring contacts — anchored to an organization, a project and the people who matter.
- Observation: two organization namespaces coexisted without ever meeting. The ledger holds client organizations with their email domains and aliases; local projects carry an organization derived from their parent folder, often suffixed with a workspace marker. Nothing joined them, so across 32550 events only 3 carried a project link, no person entity existed at all, and every work packet knew its client but never the repository. Ranking contacts by volume was also useless: the top "people" were newsletters, because a mailing list sends far more than a client writes.
- Improvement: added an entity graph joining projects and people to organizations on explainable rules only — declared alias, normalized slug, or email domain — each link carrying its reason and confidence, and anything unmatched left unlinked rather than guessed. A counterpart is redefined as someone the operator wrote to or met, which removes newsletters from the ranking. Recurring counterparts whose domain no organization claims are grouped into domain suggestions, since a missing link is nearly always a missing profile entry rather than an algorithm failure. The work packet backfill now fills project references and key people, and a scheduled job refreshes the whole graph daily because repositories appear, move and are renamed continuously.
- Evidence: `uv run pytest zab/tests -q` passes 472 tests, including 8 that pin the join rules (workspace suffix stripping, alias precedence, newsletter exclusion, domain attachment, internal-domain filtering, suggestion grouping). On a real corpus the graph attached 28 of 106 projects and 163 of 511 real counterparts, and raised work packets carrying key people from 0 to 13 of 14; the remaining gaps are reported as domain suggestions rather than hidden.
- Status: verified

## 2026-07-31 - Give WorkPackets a next action instead of a template

- Trigger: mention
- Context: a workspace had a dozen discovered WorkPackets, each covering a real client thread with dozens of attached events.
- Observation: discovery named every packet after its own cluster key (`Organization - Workstream`), copied the same four generic intake steps into each one as its action list, and left every packet in `candidate` indefinitely. The result was a list where no two rows could be told apart and none answered "what do I do next", even though the ledger already held everything needed to answer it. The dashboard made it worse by showing a title, a state and an organization column that repeated the title.
- Improvement: added a backfill that re-reads the events attached to each packet and derives a title, a canonical state and one to three actions that cite dated facts — who wrote last and in which direction, how long the silence has run, which meeting is scheduled. Four correctness traps only appeared when running it on real data: a message timestamped in the future is clock skew rather than a deadline, and silently dropping it selected the previous day's contact; only calendar entries are deadlines, so an email must never become "a meeting to prepare"; the operator's own identities have to be learned from their outbound messages, otherwise a thread they appear in yields "reply to yourself"; and a past meeting owes a follow-up, not a reply. The list view now shows the first action under each title and orders deadlines before replies owed.
- Evidence: `uv run pytest zab/tests/test_workpacket_backfill.py -q` (10 tests, one per trap plus idempotency); `uv run pytest zab/tests -q` passes 464 tests; on a real corpus the command rewrote every packet on first run and reported zero changes on the second.
- Status: verified

## 2026-07-31 - Make the VM control app deployable to a serverless container

- Trigger: mention
- Context: the control app served from a laptop is useless in the exact case it was built for — the laptop being asleep. Moving it to a managed container runtime in the same cloud project removes that dependency.
- Observation: four things only surfaced against the real platform. Shelling out to the cloud SDK is not viable in a container (roughly a gigabyte of image for three API calls), so the service needs a REST transport. The managed frontend reserves `/healthz` and answers 404 before the request ever reaches the container, so a health probe on that path silently disappears. When the service is private, the platform consumes the `Authorization` header for its own IAM check, colliding with the app's bearer token — the platform offers a second header for its own token precisely for this. And an inherited organisation policy restricting IAM members to the workspace domain blocks public invocation entirely, so a phone browser cannot reach a service that is otherwise perfectly deployed.
- Improvement: added a REST transport to `remote_vm` — Compute instance read, start, stop, machine type, and the BigQuery billing query — selected automatically when the binaries are absent, using the environment's default credentials. Configuration now also comes from environment variables, since a container has no user config file. Renamed the probe to `/ping`. Endpoints that report purely local facts (SSH connections, file sync) now carry an `observable` flag, because a remote server answering "zero connections" reads as "nothing is running" instead of "I cannot see". The container runs unprivileged from a slim base image.
- Evidence: `uv run pytest zab/tests -q` passes 454 tests, including five new ones covering the REST path, its error reporting, the operation response, BigQuery row flattening, and the observability flags — the missing `httpx` import that broke the container was invisible locally because the binary path never exercised that branch. Deployed revision verified end to end: instance state and real spend returned through the REST transport under a service account holding admin rights on a single instance.
- Status: verified

## 2026-07-31 - Ship a narrow, token-protected control app for the remote dev VM

- Trigger: mention
- Context: a user wanted to start their remote dev VM from a phone, and asked whether exposing the zab dashboard would do it.
- Observation: exposing the dashboard is the wrong instinct — the API can scan the workspace, read configuration and run jobs, so anyone past the front door owns the machine. Three further constraints only appeared once building: starting a VM and resuming a file synchroniser takes minutes, far beyond any HTTP proxy timeout, so a synchronous endpoint cannot work; a phone needs a real home-screen app, and iOS refuses SVG for its touch icon, so PNG icons are mandatory; and a double tap on a big mobile button will happily fire two starts.
- Improvement: added a second FastAPI application, separate from the dashboard, exposing only status/start/stop/sync-action behind a bearer token compared in constant time, plus an installable PWA. Actions are asynchronous jobs with a single-flight lock returning 409 on a concurrent request; the pairing token travels in the URL fragment so it never reaches the server or a proxy log, and the page strips it from the address bar; the service worker caches the app shell but never API responses, because a stale VM state is worse than none. Icons are generated by a dependency-free PNG writer rather than adding an imaging library for three fixed images.
- Evidence: `uv run pytest zab/tests/test_remote_app.py -q` (10 tests: public probe, token rejection paths, missing-token lockout, shell serving, single-flight 409, failure reported not raised, action allowlist, token file mode and rotation, environment precedence); `uv run pytest zab/tests -q` passes 449 tests; the app was exercised end to end over a private-network address, including an asynchronous sync action reaching `done`.
- Status: verified

## 2026-07-31 - Audit the capability manifest across every surface

- Trigger: debug
- Context: an agent exercised every capability the manifest declares — each CLI command, every parameterless GET route, and the dashboard pages — to separate what works from what does not.
- Observation: the surfaces are broadly healthy (the CLI answers all declared read commands; the HTTP API answers its parameterless GET routes; the pages render). Five real defects surfaced. First, the conversation digest parsed every transcript on disk before applying its time window, costing minutes for a one-day window. Second, the overview counted connectors from a two-file legacy config block, showing `0/0` on a workspace exposing nine MCP servers, while the connectors tab and the local-first index both reported nine. Third, two OS-scheduler routines still pointed at the repository's previous directory, so one had silently stopped running for nine days and the other failed every probe with a missing-directory error that was indistinguishable from a genuine auth failure. Fourth, that same watchdog crashed while writing its snapshot because a subprocess timeout returns raw bytes even in text mode. Fifth, the manifest declares a CLI form for one capability that the CLI does not implement, and one declared command has no JSON mode although the manifest advertises a JSON CLI contract.
- Improvement: filter transcripts by modification date before parsing, with a safety margin and explicit parsed/skipped counters; read the overview connector count from the real aggregation with the legacy computation as a fallback; repoint the stale routines and make the watchdog resolve the repository root tolerantly and decode timeout output; add error and scheduler-source filters to the crons page so a dead routine is visible without scrolling. The two manifest parity gaps are recorded, not yet fixed.
- Evidence: `uv run pytest zab/tests -q`; the digest drops from about two and a half minutes to under one on the same corpus with an unchanged retained set; the overview card matches the index; both repaired routines exit zero and produce real measurements; screenshots of the pages before and after.
- Status: verified

## 2026-07-31 - Turn the Workstation page into a remote dev VM cockpit

- Trigger: mention
- Context: a user runs a remote development VM that mirrors a local workspace directory, with a file synchronizer over SSH and a coding agent on the far side. The Workstation page only knew about an older Cloud Workstation plus GCS bucket layout, so nothing reported what the VM actually costs, how long it has been running, whether any SSH connection is live, or how far the file sync has progressed.
- Observation: four blind spots, each with a different source of truth. Spend and historical runtime only exist in the resource-level billing export, not in the compute API; the current session length is only derivable from the instance start timestamp; SSH liveness is a local fact (multiplexing socket, tunnel processes, synchronizer agents), not a cloud one; and file counts and drift live in the synchronizer daemon. A single "status" call could not answer any of them.
- Improvement: added `zab/services/remote_vm.py`, a provider-generic monitor that reads compute state, derives running hours from instance-core usage divided by the machine type's vCPU count, classifies billing SKUs into compute/storage/network, and reports per-session file counts, drift and conflicts from the synchronizer. Every resource identifier comes from user configuration (`remote_vm` block, optionally pre-filled from a deployment descriptor JSON), so no environment-specific value lives in the repository. Billing queries are cached on disk with a stale-cache fallback, and the SQL is built only from a validated table identifier and validated match patterns. Exposed as `/api/remote-vm/*`, `zab vm status|cost|sync`, and a Workstation page showing stacked daily cost bars with a runtime curve, a live session counter, SSH connection list and per-session sync progress. The legacy Cloud Workstation block now hides itself when unconfigured.
- Evidence: `uv run pytest zab/tests/test_remote_vm.py -q` (15 tests: config merge, SQL injection guards, hour derivation, cache and stale fallback, process classification, session filtering, API routes); `uv run pytest zab/tests -q` passes; `npm run build` and `npx playwright test e2e/pages-load.spec.ts` pass with the Workstation view mounting without JS errors.
- Status: verified

## 2026-07-31 - Make `dashboard-dev` survive a busy API port and stop leaking orphans

- Trigger: debug
- Context: a desktop launcher shortcut that runs `zab dashboard-dev` in the background stopped opening the dashboard; it silently opened a dead browser tab after a 30-second wait.
- Observation: five compounding defects. First, an unrelated always-on service supervised by the OS service manager had taken the dev API port, and the launcher aborted with `Port API explicite déjà occupé` instead of reusing a healthy zab API that was already answering `/api/health`. Second, the automatic port fallback was dead code: the CLI always exported `ZAB_DASHBOARD_PORT` from its own option default, so every port looked explicit. Third, the launcher ended with `exec npm run dev`, which replaced the shell and disabled the cleanup trap, so a dying Vite left the API orphaned (reparented to init) and holding the port for every later run. Fourth, the port probe bound without `SO_REUSEADDR`, so a port merely in `TIME_WAIT` was reported as occupied. Fifth, a diagnostic `lsof` pipeline with no match aborted the whole script under `set -o pipefail`.
- Improvement: reuse an already-listening zab API instead of failing, and print how to get a dedicated `--reload` API on another port; only export host/port/ui-port when the caller passed them; `exec` the launcher script from the CLI so a launcher's signal reaches the shell that owns the cleanup trap; kill the whole process tree of both the API and Vite on exit; run Vite in the background when there is no TTY so a `SIGTERM` is not deferred; set `SO_REUSEADDR` in the port probe; guard the diagnostic pipeline; resolve Node on `PATH` before the first npm call; and name the process holding a busy port in the error output.
- Evidence: `bash scripts/zab-dashboard-dev.sh` under a minimal environment covers the three paths — reuse of a live API, a dedicated port with `--reload`, and an explicit port held by a non-zab service (now reported with the holder). After `SIGTERM` on the launcher PID, no API or Vite process survives. `uv run pytest zab/tests -q` passes 422 tests.
- Status: verified

## 2026-07-31 - Make the conversation digest usable for per-workspace review

- Trigger: CLI
- Context: an agent used the local conversation digest to review the most recent conversations attached to a single workspace directory.
- Observation: three frictions. First, the digest reports an `intent` taken from the first user message, but some CLI providers prepend a boilerplate block (recommended plugins, environment context) so the intent field is identical across many unrelated conversations and unusable for triage. Second, project attribution is semantic, so sessions started inside a workspace directory can be labelled with a sub-project name, and there is no flag to select conversations by working directory. Third, `--limit` is capped at 300 while the retained set can be larger, and the truncation is silent for anyone filtering the result afterwards.
- Improvement: skip known provider boilerplate prefixes when deriving `intent` and fall back to the first non-boilerplate user message; add an explicit working-directory filter alongside the semantic project match; and surface a clear "retained but not shown" count so downstream filters do not mistake truncation for an empty set. The first and third points landed in the 2026-08-02 pass (this entry's status was left at `captured` by mistake). This pass closes the second: a `--cwd <dir>` option filters the digest to conversations whose transcript path or session identifier actually carries that directory, independent of the semantic org/project match — the two can disagree (a session run inside a client sub-folder gets classified under the client's canonical project by alias/content matching, which is correct for grouping but wrong when the question is "what ran in this exact folder").
- Evidence: `zab conversations digest --days 14 --limit 300 --json` returns `scanned/retained/shown` counters where `retained > shown`, and repeated `intent` values are gone for providers with boilerplate turns. `zab tests/test_conversation_digest.py::test_digest_cwd_filter_selects_the_session_that_ran_there` pins `--cwd` narrowing two same-project-labelled sessions from different directories down to the one whose transcript actually carries the requested path, and shows it is a no-op (`cwd_filter: null`) when omitted.
- Status: verified

## 2026-07-29 - Make historical interaction backfills classifiable and storage-safe

- Trigger: debug
- Context: an agent prepared a historical Conversation Ledger backfill after restoring the recurring local sync.
- Observation: organization matching could not load private local profiles, related messages were not propagated through unique threads or known contacts, calendar and meeting connectors did not page through the requested history, Evolution's global message endpoint exposed only a recent sample, unresolved secret references produced a false-green messaging channel, and every unchanged reindex appended the full event set to the JSONL journal.
- Improvement: load organization/workstream profiles from a private user-level YAML file, preserve public-repository separation, add bounded history-assisted resolution, index calendar attendees, honor historical windows and pagination, enumerate WhatsApp chats before bounded parallel history reads, reject unresolved secret references, make event journaling change-idempotent, add recoverable journal compaction, and prioritize new WorkPacket candidates within the anti-flood limit.
- Evidence: the full test suite, lint checks, isolated database reclassification, repeated reindex with zero journal growth on the second pass, bounded source backfills, and a historical WorkPacket dry-run.
- Status: verified
- Fix commits: `8abf6b0`, `e112878`, `92b982b`, `dbd1deb`, `6e35b1e`

## 2026-07-29 - Keep local dashboard data fresh without storage blowups

- Trigger: debug
- Context: an agent repaired a local dashboard whose interactions and WorkPackets had stopped refreshing after a storage interruption and a checkout relocation.
- Observation: the health endpoint did not probe the primary store, background jobs retained stale working directories, channel checks blocked initial rendering, WorkPacket discovery was not part of the recurring interaction sync, overlapping conversation imports could hold long transactions, and full structured messages were repeated in every search chunk.
- Improvement: add a real store readiness probe, load channel bindings before optional live checks, isolate development API ports, make WorkPacket discovery bounded and since-aware, schedule it after interaction sync, serialize conversation imports, make append mode hash-idempotent, and keep structured messages only in the canonical conversation archive.
- Evidence: backend contract tests, production UI build, focused browser E2E for Interactions and WorkPackets, incremental re-run with zero inserts for unchanged documents, current launchd receipts, and a compacted search index more than forty times smaller than the duplicated form.
- Status: verified
- Fix commit: this commit

## 2026-07-28 - Verify complete cloud workstation decommissioning

- Trigger: CLI
- Context: an agent used the generic decommissioning runbook to retire a single-user managed cloud workstation stack and stop all associated recurring costs.
- Observation: the runbook deleted the workstation, its configuration, and its cluster, but a persistent regional disk configured with `RETAIN` and dedicated synchronization buckets required explicit cleanup outside the script; the private service endpoint disappeared with the cluster.
- Improvement: extend dry-run and apply modes to discover retained regional disks and optionally remove dedicated buckets only behind explicit flags, including soft-delete policy clearing and propagation checks.
- Evidence: public `gcloud` list, describe, and delete commands for managed workstations, regional disks, private service endpoints, and dedicated storage buckets.
- Status: verified

## 2026-07-28 - Restore a side-effect-free workstation status command

- Trigger: CLI
- Context: an agent audited whether a previously provisioned cloud development workstation was still present before recommending a replacement architecture.
- Observation: the public workstation service still exposes read-only status logic, but the documented `zab ws status --json` command is absent from the current CLI and exits with `No such command 'status'`.
- Improvement: restore a `zab ws status --json` alias backed by `get_workstation_status()`, or update every reference and dashboard call to the canonical replacement command.
- Evidence: `uv run zab ws status --json` exits with code 2; `uv run zab ws --help` should be used to identify the currently exposed surface before implementing the fix.
- Status: verified — landed in the 2026-08-09 pass (commit `feat(ws): restore 'zab ws status --json' documented in AGENT_IMPROVEMENTS`); `uv run zab ws status --json` now answers. This entry's status was left at `captured` by mistake and is corrected here rather than re-implemented.

## 2026-07-27 - Restore Fireflies interaction sync

- Trigger: debug
- Context: an agent continued validating the local-first Conversation Ledger sync after contact-level Gmail fixes.
- Observation: Fireflies channel checks could see only the absence of a local API key, and after the key was made available the Fireflies GraphQL query still returned no data because it used stale transcript fields.
- Improvement: load checkout-local `.env.local` / `.env` files in the standard dotenv chain, keep user secrets in local config outside the repository, and update the Fireflies transcript query to use current schema fields and aliases.
- Evidence: `uv run pytest zab/tests/test_dotenv_locate.py zab/tests/test_ledger_contracts.py -q`, `uv run zab interactions sync --since 30d --sources fireflies --max-per-channel 20 --json`, `uv run zab interactions sync --since 14d --sources gmail,calendar,whatsapp,fireflies --max-per-channel 1200 --json`, launchd kickstart/status for `ai.zab.interactions-sync`.
- Status: verified
- Fix commit: this commit

## 2026-07-26 - Make local interaction sync automatic and contact-complete

- Trigger: debug
- Context: an agent audited local-first Conversation Ledger sync freshness and contact-level completeness.
- Observation: the local launchd runner could point to a moved checkout, no dedicated interaction sync agent existed, Gmail metadata search was capped to a single page, recipient headers were not indexed, and metadata-only refreshes could overwrite previously enriched event content.
- Improvement: add a dedicated hourly local interaction sync job, paginate Gmail searches with `--all` when a high per-channel limit is requested, expose `--max-per-channel` in CLI/API, extract recipient headers during Gmail enrichment, resolve entities from counterparties, and preserve enriched fields during sync refreshes.
- Evidence: `uv run pytest zab/tests/test_ledger_contracts.py zab/tests/test_ledger_real_cases.py -q`, `uv run zab interactions sync --since 14d --sources gmail,calendar,whatsapp,fireflies --max-per-channel 1200 --json`, `uv run zab interactions enrich-content --limit 3000 --max-fetch 1800 --json`, `uv run zab interactions reindex --json`, launchd kickstart/status for `ai.zab.interactions-sync`.
- Status: verified
- Fix commit: this commit

## 2026-07-26 - Complete interaction channel sync

- Trigger: debug
- Context: an agent audited the Conversation Ledger interactions surface and communication channels.
- Observation: CLI ledger checks did not load the same local env files as the dashboard, WhatsApp/iMessage bindings were listed but not synced, Gmail search snippets could be dropped before body enrichment, and preflight JSON could include raw provider output.
- Improvement: load standard Zab dotenv files in CLI services, branch WhatsApp and local iMessage fetchers into `zab interactions sync`, preserve Gmail snippets, extract common WhatsApp message bodies, normalize structured Fireflies summaries/transcripts, and keep preflight details privacy-safe.
- Evidence: `uv run pytest zab/tests -q`, `cd zab-ui && npm run build`, `uv run zab interactions channels --json`, `uv run zab interactions sync --since 7d --sources gmail,calendar,whatsapp --json`, `uv run zab ledger preflight --json`.
- Status: verified
- Fix commit: this commit

## 2026-07-23 - Repair moved editable CLI install

- Trigger: debug
- Context: a local checkout was moved, while the global `zab` command still used an editable install pointing at the previous checkout path.
- Observation: `zab` failed with `ModuleNotFoundError: No module named 'zab'`; `uv run zab ...` still worked from the repository because the package was on the current working directory.
- Improvement: refresh the global CLI with `uv tool install --reinstall --editable . --python "$(command -v python3.11)"`, document the reinstall command, and make `scripts/install-zab-shell.sh` smoke-test an existing `zab` binary before trusting it.
- Evidence: `zab --help`, `zab workpacket rule --json`, and `zab doctor` pass from a directory outside the checkout after reinstall; `uv run pytest zab/tests -q` passes; `npm run build` passes in `zab-ui`.
- Status: verified
- Fix commit: this commit

## 2026-07-23 - Reuse dashboard UI conventions

- Trigger: mention
- Context: an agent used the public dashboard code as a visual and structural reference for another local operational interface.
- Observation: the compact sidebar, Geist typography, Tailwind v4 tokens, shadcn primitives and dense table patterns were straightforward to identify and reuse without copying domain data.
- Improvement: keep the UI stack and reusable primitives explicit in `zab-ui/package.json` and `src/components/ui/`; no product change was required during this interaction.
- Evidence: read-only inspection of the UI package, navigation and primitive components; the consuming interface passed its independent TypeScript build and responsive browser checks.
- Status: verified

## 2026-07-30 - Classify an approved client email reply

- Trigger: CLI
- Context: an agent classified a user-requested reply to an existing client email thread; all business details were kept outside the public repository.
- Observation: `zab workpacket intake` returned the expected communication contract, approval gate, source requirements, and reread receipt requirement.
- Improvement: no product change required; keep the explicit L3 approval and post-send verification contract for message actions.
- Evidence: `zab workpacket intake "<anonymized email-reply signal>" --source codex --project flowmetrik-cowork --json`.
- Status: verified

## 2026-07-30 - Classify an approved invoice-and-email workflow

- Trigger: CLI
- Context: an agent classified a user-approved finance record and administrative email workflow; all customer, amount, invoice and recipient details stayed outside the public repository.
- Observation: `zab workpacket intake` correctly returned L3 approval, finance-source grounding and post-mutation reread requirements.
- Improvement: no product change required; the contract usefully enforced duplicate checking, explicit authority and separate finance/email receipts.
- Evidence: `zab workpacket intake "<anonymized invoice-send signal>" --source codex --project flowmetrik-cowork --json`.
- Status: verified

## 2026-07-23 - Make WorkPacket discovery idempotent

- Trigger: integration
- Context: a local dashboard can rerun event indexing and WorkPacket discovery on demand.
- Observation: repeated discovery inserted a new WorkPacket even when the same organization and workstream already had a canonical packet.
- Improvement: reuse the existing WorkPacket identity and display ID, preserve its creation timestamp, and report separate created and updated counts.
- Evidence: the ledger contract suite includes a repeat-discovery regression test; all 16 focused tests pass.
- Status: verified

## 2026-08-01 - Report an unconfigured CLI watchlist instead of a clean bill

- Trigger: CLI
- Context: provisioning a freshly built remote machine so agents could work on it, using the CLI watchlist to tell what was missing.
- Observation: on the new machine the status command answered `0/0 — tous les CLIs surveillés sont présents`, which reads as success. The watchlist simply had not been deployed yet, so the check was reporting on an empty set. The same run also showed that two entries of the watchlist, the GitHub CLI and ripgrep, had no installer at all: they were listed as missing on every pass with no way to obtain them. A third defect belonged to the host rather than to the tool — writing a PATH for non-interactive sessions dropped the distribution's snap directory, which silently hid the cloud SDK from every automation.
- Improvement: the status payload now carries whether a watchlist exists, and the CLI says so rather than declaring victory over nothing. Added installers for the two orphaned entries. The provisioning script keeps the distribution's default directories when it writes the non-interactive PATH.
- Evidence: `uv run pytest zab/tests -q` passes 501 tests, including three new ones pinning the empty-watchlist case, the populated case, and the presence of an installer for the two orphans. On the target machine the watchlist moved from a misleading `0/0` to `36/60`, and the remaining absences are entries for which no installer is declared.
- Status: verified

## 2026-08-01 - Audit remote VM readiness from Zab

- Trigger: CLI
- Context: an agent performed a privacy-safe, read-only readiness audit of a remote development VM from a local control machine.
- Observation: `zab vm status --json` correctly reported the running VM, active SSH control connection and conflict-free synchronization sessions. On the remote host, the login shell exposed the expected Node, Python and agent CLIs, while a non-login SSH command did not inherit the toolchain path. The user configuration parent directory was not writable, so the repository-local `uv run zab doctor` could not create its configuration. The generic CLI check also reported several installed tools as failed because it used unsupported `--version` flags.
- Improvement: add a remote readiness contract that checks login and non-login PATH parity, user-config writability, global or repository-local Zab resolution, and Node dependency readiness. Replace generic version flags with tool-specific side-effect-free commands and distinguish a missing executable from an invalid probe command.
- Evidence: `zab vm status --json`, `zab vm sync --json`, remote login/non-login command resolution, repository-local `uv run zab doctor`, dependency-tree inspection, production UI builds on both hosts, and the full backend test suite.
- Status: captured

## 2026-08-01 - Inventory Zab for a local project hub

- Trigger: mention
- Context: an agent inventoried local developer tools for a generic project-and-service hub.
- Observation: Zab exposes distinct CLI, API and dashboard surfaces with documented health endpoints, making it straightforward to represent as one project with several launchable services.
- Improvement: no Zab product change is required; the consuming hub should keep project location, service endpoints and launcher metadata separate instead of duplicating Zab state.
- Evidence: read-only inspection of the public README, package metadata and existing local launcher conventions; the consuming FlowHub now exposes the project through its public-safe name, location, repository link, health route and launcher metadata.
- Status: verified

## 2026-08-02 - Reuse the public Zab mark in the local project hub

- Trigger: code
- Context: a generic local project hub needed one visible mark for every indexed developer tool.
- Observation: the existing public documentation asset is suitable as-is and does not expose workspace data.
- Improvement: no Zab change is required; the consuming hub copies the public mark at build time instead of creating a competing identity.
- Evidence: asset copy, image-load validation and a desktop/mobile render of all project cards.
- Status: verified

## 2026-08-01 - Reuse role-aware conversations for local vocabulary

- Trigger: CLI
- Context: an agent derived a private, local speech-recognition vocabulary from the unified conversation index; no conversation content or derived vocabulary was written to the public repository.
- Observation: `zab workpacket intake` worked, and the conversation store exposed provider-specific user roles suitable for privacy-safe downstream extraction; generic memory chunks were less appropriate because they also mixed in system and tool-harness text.
- Improvement: prefer role-aware conversation projections for local personalization jobs, deduplicate user messages, and apply explicit secret, identifier and harness-noise filters before producing derived artifacts outside the repository.
- Evidence: privacy-safe role/count queries, local vocabulary validation, and an exact-set downstream readback; no private rows, names or terms are stored here.
- Status: verified
