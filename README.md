# Marshal

Marshal is a standalone Python CLI prototype for platoon and squad orchestration.

Marshal writes orchestration artifacts under a caller-provided `.omo` root and
prints JSON for machine use. Runtime dependencies are intentionally empty;
development tooling is managed through `uv`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

## CLI

```bash
uv run marshal --help
uv run marshal --version
```

## Manual mode vs adapter mode

Marshal never imports, copies, or executes start-work internals. There are two
ways to hand a gated squad off to start-work:

- **Manual mode** — `delegate-start-work` prints the command and JSON payload,
  and you (or another tool) run start-work yourself. In other words,
  **start-work is emitted, not invoked**: Marshal hands you the packet and stops
  at the boundary.
- **Adapter mode** — `run-start-work` takes the same payload and pipes it (as
  JSON on stdin) to an external runner you point it at with `--runner` or the
  `MARSHAL_START_WORK_RUNNER` environment variable. The runner is what actually
  invokes start-work; Marshal only records that the dispatch happened.

## MVP Workflow

The `--scope` format is:

```text
<squad-id>|<goal>|<depends_csv_or_->
```

Exact workflow commands:

```bash
QA_ROOT=$(mktemp -d /tmp/marshal-task9-happy.XXXXXX)
mkdir -p "$QA_ROOT/.omo/plans"
printf '# squad-a work plan\n' > "$QA_ROOT/.omo/plans/squad-a.md"

uv run marshal init --root "$QA_ROOT" --goal "Ship cache and dashboard" --scope "squad-a|Redis cache|-" --scope "squad-b|Admin dashboard|squad-a"
uv run marshal state init --root "$QA_ROOT" --squad squad-a --plan ".omo/plans/squad-a.md"
uv run marshal start-gate --root "$QA_ROOT" --squad squad-a --source assignment --example "If design flaw appears, route to plan."
uv run marshal route --root "$QA_ROOT" --squad squad-a --source work --type design_flaw --detail "unexpected dependency" --finding "plan missing dependency edge"
uv run marshal start-gate --root "$QA_ROOT" --squad squad-a --source plan --example "If plan restarts, verify attempt 2 before work."
uv run marshal ledger latest --root "$QA_ROOT" --squad squad-a
uv run marshal delegate-start-work --root "$QA_ROOT" --squad squad-a
```

## Operating the platoon

The commands above create artifacts. The commands below drive them: they read
the live `state.json`, `start-gate.json`, and ledger of every squad to answer
"where are we, what can I start, and what comes next". All output is JSON.

- `status` — one snapshot of every squad: stage, active attempt, whether it is
  blocked/aborted/done, whether a fresh start gate has passed, whether its
  dependencies are satisfied, and which squads are runnable next.
- `next` — only the squads whose dependencies are done and that have not been
  dispatched yet, ordered by the global dependency waves.
- `run-start-work` — adapter mode for one squad (see above). Requires a fresh,
  passed start gate; records a `dispatched` ledger event with the runner's exit
  code.
- `dispatch` — `run-start-work` plus dependency checks. With `--squad` it
  validates that squad; without `--squad` it auto-selects the first runnable
  squad from `next`.
- `handover` — a self-contained packet for the next agent (assignment + state +
  ledger + start gate + surrounding platoon + a plain next-action summary),
  also written to `.omo/squad/<id>/handover.json`.
- `evidence check` — verifies that the evidence files recorded in the active
  attempt actually exist. `--strict` exits non-zero when a path is missing;
  add `--require-real-surface` to also require real-surface proof.
- `complete` — records an evidence-backed `done` claim. It refuses unless every
  `--evidence` path exists, then advances the squad to `done` so dependent
  squads become runnable.
- `abort` — stops a squad (`--squad`) or every active squad (`--all`), records
  the reason in state and the ledger, and blocks any later delegation or
  start-work for that squad.
- `conversation` — the Platoon Leader question queue. Workers, work, and review
  never message the user directly; sync and plan own question content but still
  need permission. Every user-facing question is posted to
  `.omo/platoon/questions.jsonl` with `conversation ask`, listed with
  `conversation list`, and resolved with `conversation answer` so the Platoon
  Leader serialises them.

```bash
# Where are we, and what can start next?
uv run marshal status --root "$QA_ROOT"
uv run marshal next --root "$QA_ROOT"

# Adapter mode: invoke an external start-work runner for a gated squad.
export MARSHAL_START_WORK_RUNNER="my-start-work-runner"
uv run marshal run-start-work --root "$QA_ROOT" --squad squad-a
uv run marshal run-start-work --root "$QA_ROOT" --squad squad-a --dry-run

# Dependency-gated dispatch (auto-selects the next runnable squad).
uv run marshal dispatch --root "$QA_ROOT"

# Hand off, verify evidence, then claim done.
uv run marshal handover --root "$QA_ROOT" --squad squad-a
uv run marshal evidence check --root "$QA_ROOT" --squad squad-a --strict
uv run marshal complete --root "$QA_ROOT" --squad squad-a --evidence ".omo/evidence/squad-a-e2e.log" --detail "cache shipped; real-surface QA green"

# User changes direction: abort everything still active.
uv run marshal abort --root "$QA_ROOT" --all --reason "pivot to a new plan"

# Conversation queue: a worker asks instead of contacting the user directly.
uv run marshal conversation ask --root "$QA_ROOT" --squad squad-a --source worker --question "TTL 60s or 300s?"
uv run marshal conversation list --root "$QA_ROOT"
uv run marshal conversation answer --root "$QA_ROOT" --id q-0001 --answer "Use 300s"
```

## Codex hook entry points

Marshal can be the control-plane entry point for a Codex session. The `hook`
command reads a Codex hook payload on stdin (only a non-empty `cwd` is required)
and writes the Codex hook response on stdout. Malformed or absent input yields
empty output and exit 0, so a hook can never crash or stall Codex.

- `hook user-prompt-submit` — injects the live platoon/squad status as additional
  context; silent when no platoon exists.
- `hook stop` / `hook subagent-stop` — blocks (continues) when a squad is active
  (`sync`/`plan`/`work`/`review`) with a fresh, passed start gate; silent when no
  such squad exists, when `stop_hook_active` is set, or under context pressure.

```bash
printf '{"cwd":"%s"}' "$QA_ROOT" | uv run marshal hook stop
printf '{"cwd":"%s"}' "$QA_ROOT" | uv run marshal hook user-prompt-submit
```

The `codex-plugin/` directory packages these as a Codex plugin so Marshal owns the
`UserPromptSubmit`, `Stop`, and `SubagentStop` events directly (Marshal-first; OMO
and LazyCodex become execution substrates). Install `marshal` on PATH
(`uv tool install .`) and see [`codex-plugin/README.md`](codex-plugin/README.md).
