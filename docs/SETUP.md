# Caleb's checklist — get Aletheia running

Six steps. Everything else is already built and tested; these are the
things only you can do. Do them in order; each one takes minutes.

## 1. Merge the branch

Open https://github.com/caleblschulte0-ux/Aletheia/branches — click
**New pull request** on `claude/project-alathea-interface-ah59fv`, then
merge it. (Or run `git checkout main && git merge
claude/project-alathea-interface-ah59fv && git push`.)

## 2. Add the FLEET_TOKEN secret — makes the pulse see all six repos

1. https://github.com/settings/personal-access-tokens/new
2. Fine-grained token, **All repositories** (or pick the six),
   permissions: **Contents: Read** and **Actions: Read**. Create it, copy it.
3. https://github.com/caleblschulte0-ux/Aletheia/settings/secrets/actions
   → **New repository secret** → name it exactly `FLEET_TOKEN`, paste, save.

Check: Actions tab → run **pulse** → the repos stop saying NO TELEMETRY.

## 3. Turn on GitHub Pages — puts the wall on your projector

https://github.com/caleblschulte0-ux/Aletheia/settings/pages →
Source: **Deploy from a branch**, Branch: **main / (root)**, Save.

Wall URL (open fullscreen with F11):
`https://caleblschulte0-ux.github.io/Aletheia/interface/`

## 4. Give Thea her voice (ChatGPT — no API keys)

1. In the ChatGPT app: **Projects → New project**, name it **Aletheia**.
2. Enable the **GitHub connector** for it.
3. Open `exchange/INTERCOM.md` in this repo, copy the block under
   "ChatGPT Project instructions", paste it as the project instructions.
4. Optional: add a ChatGPT **scheduled task** — "Read Aletheia's brief
   and message me the highlights" — for a morning voice check-in.

Test it: say *"Thea, what's going on?"* then *"Thea, leave a note that
the intercom works."* — a receipt lands in `exchange/commands/`.

## 5. Run the Core on your Windows PC

Install Python 3.11+ and git, then in PowerShell:

```powershell
git clone https://github.com/caleblschulte0-ux/Aletheia.git
cd Aletheia
python -m aletheia.core
```

Then open:
- the wall → http://127.0.0.1:8777/
- the Command Center → http://127.0.0.1:8777/command.html

Keep the window open (it is the service). To refresh its data:
`git pull`.

## 6. Come back and say "keep building"

Then the next session builds, in this order:

1. **Windows computer control** — Aletheia operates apps on your PC
2. **Browser control** — a logged-in browser it can drive
3. **Voice wake word** — say "Thea" without touching anything
4. **Phone V0** — calls through virtual audio + ChatGPT Voice
5. **Email** with an approval gate

Steps 1–3 unlock those. Nothing here costs money except, eventually, a
telephony provider if you outgrow Phone V0.

---

Status any time: `python -m aletheia.capabilities` (what Thea can
really do) · `python -m aletheia.tasks list` (what's queued) ·
`python -m aletheia.policy status` (halted or running).
