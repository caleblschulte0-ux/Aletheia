# Caleb's checklist

The Windows path is intentionally one command. Development tests run in CI;
the operator PC only proves the live machine-specific pieces it actually needs.

## 1. Turn on Pages — 30 seconds

https://github.com/caleblschulte0-ux/Aletheia/settings/pages →
Source: **GitHub Actions**.

The `pages` workflow deploys the wall and redeploys after every pulse.

Wall, once live — fullscreen with F11 on the projector:
`https://caleblschulte0-ux.github.io/Aletheia/`

## 2. Remote voice through ChatGPT — optional

`exchange/CHATGPT_PROJECT.md` sets up ChatGPT Voice as a remote intercom from
your phone. It relays commands through Aletheia's gates; ChatGPT is a worker,
not Aletheia itself.

The signed-in ChatGPT **browser reasoning** adapter is a different thing and is
now fail-closed for unattended runtime. Always-on Core/voice/watchdogs do not
open visible ChatGPT conversations if local/Claude reasoning is unavailable.

## 3. Bring Aletheia up on Windows — 1 command

PowerShell:

```powershell
irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
```

That URL now delegates to the bounded Windows bring-up path. It:

- stops stale Core/voice watchdogs before touching the checkout;
- refreshes `~\Aletheia` to reviewed `main`;
- checks Python and required runtime data;
- runs short registry/live preflights — **not** the 1,200+ development suite;
- smoke-gates and activates the local model pool;
- proves unattended ChatGPT browser reasoning is blocked;
- installs and proves the persistent Core;
- repairs/proves the local room voice;
- verifies both watchdogs and local reasoning;
- resumes only after those machine-specific checks succeed.

If any required step fails, it stops there instead of half-starting Thea. Full
Linux and Windows test suites remain GitHub CI's job.

After success:

- Wall: http://127.0.0.1:8777/
- Command Center: http://127.0.0.1:8777/command.html
- Room voice: say a **full command**, e.g. *"Thea, what needs my attention?"*

The Core and room voice are watchdog-backed Windows tasks, so they survive
reboots and repair process deaths automatically.

## Optional later

- **Remote phone access** — use `python -m aletheia.setup` for the current
  TLS/token requirements.
- **`FLEET_TOKEN`** — only if a private fleet repo must be watched. Public repos
  do not need it.
- **Privacy** — this repo is public, so keep genuinely private facts out of
  tracked `memory/` and `state/`, or move the repo to an appropriate private
  setup.

---

Status any time: `python -m aletheia.capabilities` · `python -m
aletheia.tasks list` · `python -m aletheia.policy status`
