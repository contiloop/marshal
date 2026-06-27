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

## MVP Workflow

start-work is emitted, not invoked. `delegate-start-work` prints the command and
JSON payload a caller can pass to a separate start-work runner; Marshal does not
import, copy, or execute start-work internals.

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
