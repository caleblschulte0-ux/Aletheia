# Caleb's checklist

**Three things left.** Everything else is done, merged, and verified
running live on `main`.

## ✅ Already done (Claude did these)

- Merged to `main` (PR #1) — CI green
- Ran `pulse`, `brief`, `intercom` live on main; all pass
- The sentinel opened a real fleet alert (issue #2) — see the bottom
- Wrote the Pages workflow, the Windows installer, and the ChatGPT paste
- Found + fixed a delegation bug the first live pulse exposed
- Discovered `FLEET_TOKEN` isn't needed for public repos — dropped it
  from this list

---

## 1. Turn on Pages — 30 seconds

https://github.com/caleblschulte0-ux/Aletheia/settings/pages →
Source: **GitHub Actions**. Done.

The `pages` workflow is already written and waiting; it deploys the wall
and redeploys after every pulse. (Claude can't flip this — GitHub blocks
Pages creation for workflow tokens.)

Wall, once live — fullscreen with F11 on the projector:
`https://caleblschulte0-ux.github.io/Aletheia/`

## 2. Give Thea her voice — 0 minutes (it's on the page)

The wall and the Command Center listen themselves. Click the small
indicator in the bottom-right corner once (the browser asks for the
microphone once), then just talk:

- *"Thea, what's going on?"* — she says the live status out loud
- *"Thea, read the verge dot com"* — she reads the page back
- *"Thea, stop everything"* / *"Thea, resume"* — the kill switch
- *"Thea, approve"* — grants the pending approval (refuses to guess
  if there's more than one)
- *"Thea, add a task to ..."* / *"Thea, note ..."*

Needs Chrome or Edge. Anything she doesn't have a command for gets
journaled, and she says so — she never guesses.

**Optional, for away from home:** `exchange/CHATGPT_PROJECT.md` sets up
ChatGPT Voice as the remote channel — same commands, from your phone.

## 3. Run the Core on your PC — 1 command

PowerShell:

```powershell
irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
```

It checks git/Python, clones to `~\Aletheia`, runs the tests, offers to
register Aletheia to **start at every logon** (say Y), and starts it
under the supervisor with the wall open in a tab.

After that there is nothing to maintain: it survives reboots, restarts
itself if it crashes, and **updates itself** — when new code merges to
`main`, the Core pulls it and restarts onto it within about a minute.

- Wall (leave this tab open / point the projector at it, F11):
  http://127.0.0.1:8777/
- Command Center: http://127.0.0.1:8777/command.html
- If you skipped auto-start: double-click `start-aletheia.bat`

---

## Then say "keep building"

Next up, in order: **Windows computer control → browser control → voice
wake word → Phone V0 → email**. Steps 1–3 are what unlock them.

## Optional

- **`FLEET_TOKEN`** — only if you want `etsy_maker` (private) watched.
  Fine-grained PAT, Contents+Actions read → repo Settings → Secrets →
  Actions → name it `FLEET_TOKEN`. Every public repo already works
  without it.
- **Privacy** — this repo is public, so `memory/`, `state/` and the
  journal are world-readable. Keep genuinely private facts out, or make
  the repo private (Pages then needs a paid plan; nothing else changes).

## Heads up — Aletheia's first real catch

Issue #2 is not noise. The pulse found **Shorts-pipeline `daily.yml`
failing** and **all three schwab-trader workflows failing** (`brain`,
`sell-brain`, `trader`). Say the word and that gets fixed next.

---

Status any time: `python -m aletheia.capabilities` · `python -m
aletheia.tasks list` · `python -m aletheia.policy status`
