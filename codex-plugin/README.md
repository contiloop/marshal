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
  marketplace.json            # marketplace; source -> "./plugin"
  plugin/
    .codex-plugin/plugin.json # plugin manifest (name "marshal")
    hooks/*.json              # the 3 hook -> `marshal hook <event>` bindings
  README.md
```

This mirrors the canonical Codex marketplace layout, where the marketplace file
sits a level above the plugin directory (compare
`oh-my-openagent/packages/omo-codex/marketplace.json` with its plugin in
`oh-my-openagent/packages/omo-codex/plugin/`).

## Enable the plugin in Codex

1. Register this directory as a marketplace with your Codex CLI / app (point it at
   `marshal/codex-plugin/`; the marketplace `source` resolves the plugin in
   `./plugin`).
2. Enable the `marshal` plugin (`marshal@marshal`) in `~/.codex/config.toml`.
3. Start a Codex session in a repo that has a Marshal platoon
   (`marshal init ...`). On each turn the `UserPromptSubmit` hook injects squad
   status, and `Stop`/`SubagentStop` keep Codex working an active squad.

The exact marketplace/enable keys depend on your Codex version; the load contract
is only that Codex fires the three events at the commands above.

## Relationship to OMO

Marshal is standalone: with only this plugin installed, Marshal is the control-plane
entry point and owns squad continuation end to end.

Caveat if you ALSO run OMO/LazyCodex: OMO's own `start-work-continuation` Stop hook
drives Boulder continuation, and for a plan that is both Marshal-managed and tracked
in OMO's `boulder.json` it would emit its own directive too -- so the two would both
fire on the same Stop. Making OMO defer to Marshal for Marshal-managed plans is a
separate, optional change in the OMO repo and is NOT part of this plugin.
