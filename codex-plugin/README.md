# marshal-codex

A Codex plugin that makes **Marshal the control-plane entry point**. Codex's
hooks call `marshal hook <event>` directly; Marshal reads its own platoon/squad
artifacts and decides what Codex should do. Codex, OMO, and LazyCodex are
execution substrates that Marshal directs, not the other way around.

```
Codex hook  ->  marshal-codex plugin  ->  marshal hook <event>  ->  marshal control-plane
```

## Hooks

| Codex event       | Command                            | Behavior |
|-------------------|------------------------------------|----------|
| `UserPromptSubmit`| `marshal hook user-prompt-submit`  | Injects the live platoon/squad status as additional context (silent when no platoon exists). |
| `Stop`            | `marshal hook stop`                | Blocks to continue an active, freshly-gated squad under Marshal; silent otherwise. |
| `SubagentStop`    | `marshal hook subagent-stop`       | Same continuation check after a subagent finishes. |

All three are quiet by contract: malformed/absent input, an uninitialised
platoon, `stop_hook_active`, or a context-pressure transcript yields empty output
and exit 0, so a hook can never crash or stall Codex.

## Prerequisite: put `marshal` on PATH

The hooks invoke the `marshal` console script, so it must be installed and
resolvable on PATH. From the Marshal repo root:

```bash
uv tool install .        # or: pipx install .
marshal --version        # confirm it resolves on PATH
```

## Layout

```
marshal/codex-plugin/
  .agents/plugins/marketplace.json # marketplace; source -> "./plugin"
  marketplace.json            # plain catalog mirror for tools that read root JSON
  plugin/
    .codex-plugin/plugin.json # plugin manifest (name "marshal")
    hooks/*.json              # the 3 hook -> `marshal hook <event>` bindings
  README.md
```

The repo root also includes `.agents/plugins/marketplace.json`, so either the
whole Marshal repo or this subdirectory can be registered as a Codex marketplace.

## Enable the plugin in Codex

1. Register either the Marshal repo root or this `codex-plugin/` directory as a
   marketplace:

   ```bash
   codex plugin marketplace add /path/to/marshal
   # or, for this subdirectory only:
   codex plugin marketplace add /path/to/marshal/codex-plugin
   ```

   For the GitHub-hosted repo, use the same marketplace name after adding the repo:

   ```bash
   codex plugin marketplace add contiloop/marshal --ref main
   codex plugin add marshal@marshal
   ```

2. Install and enable the `marshal` plugin:

   ```bash
   codex plugin add marshal@marshal
   ```

3. Start a Codex session in a repo that has a Marshal platoon
   (`marshal init ...`). On each turn the `UserPromptSubmit` hook injects squad
   status, and `Stop`/`SubagentStop` keep Codex working an active squad.

The exact marketplace source can be local or Git-backed. The load contract is
only that Codex fires the three events at the commands above.

## Relationship to OMO

Marshal is standalone: with only this plugin installed, Marshal is the control-plane
entry point and owns squad continuation end to end.

Caveat if you ALSO run OMO/LazyCodex: OMO's own `start-work-continuation` Stop hook
drives Boulder continuation, and for a plan that is both Marshal-managed and tracked
in OMO's `boulder.json` it would emit its own directive too -- so the two would both
fire on the same Stop. Making OMO defer to Marshal for Marshal-managed plans is a
separate, optional change in the OMO repo and is NOT part of this plugin.
