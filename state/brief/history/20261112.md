# ☀️ Fleet brief — 2026-11-12

**All quiet.** No faults anywhere in the fleet.

## 🧭 Your one thing today
Schwab trader: review and merge pull request #16, watchdog: name which of the two likely causes a stall is (https://github.com/caleblschulte0-ux/schwab-trader/pull/16)

## Job hunt
- **Yesterday:** 2 sent, 0 heard back, 0 interview(s)
- **Last 7 days:** 13 sent, 0 heard back, 0 interview(s), 0 said no
- **Last 30 days:** 46 sent, 26 heard back, 11 interview(s), 8 said no
- **Waiting:** 26 stopped on a question only you can answer; 8 wait for your own OK (part-time, contract or judged by her own model); 21 failed to send.

## Projects
- **Barkly** — 0/8 steps · last moved 49 days ago · Thea next: Get Barkly CI green on the project branch: its 'Production dependency audit' step fails on every push · yours next: Turn on GitHub Pages for Money_Machine (Settings, Pages, Source: GitHub Actions) so the playtest link goes live · 1 open builder pull request
- **Holdco platform** — 0/5 steps · last moved 98 days ago · Thea next: Bring the platform up to date and confirm pnpm test, typecheck and build still pass (last verified 2026-08-06) · yours next: Pick the one offer to test first and write it as one sentence in docs/NEXT_OFFER.md on the holdco branch (or tell any Claude session to) · 1 open builder pull request
- **Instagram Auto Post Setup** — 0/4 steps · moved today · yours next: Switch the Instagram account to a professional account. This is first, and everything else fails without it: the Meta app cannot see a personal account. In the Instagram app: your profile -> the three-line menu -> Settings and privacy -> Account type and tools -> Switch to professional account -> Business.
- **Open Range demo films** — 0/4 steps · last moved 49 days ago · Thea next: Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open · 1 open builder pull request
- **Schwab trader** — 0/5 steps · no real work in at least 14 days (only machine commits) · Thea next: Make the watchdog say which of the two likely causes a stall is (no trigger runs at all, or runs that fail) so the next stall names itself · yours next: Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it · 1 open builder pull request

## Aletheia — OPERATIONAL
- last commit `986842a2e8b0`: core: state checkpoint

## Shorts-pipeline — OPERATIONAL
- trending posted 547 · explainer posted 396 (+2) · third posted 1,334 · curiosity posted 1
- last commit `656ae2f39f8b`: story forge: new real-data stories [skip ci]

## schwab-trader — OPERATIONAL
- last commit `48bc8271864f`: bot: daily snapshot [skip ci]

## Money_Machine — NO TELEMETRY
- last commit `53c6507f6afe`: Initial commit

## Changes since the last pulse
- `Shorts-pipeline` went red → **green**

## Plans in motion
- **Barkly** — 0/8 steps done (`barkly`)
- **Holdco platform** — 0/5 steps done (`holdco-platform`)
- **Instagram Auto Post Setup** — 0/4 steps done (`instagram-auto-post-setup`)
- **Light up the wall** — 3/4 steps done (`light-up-the-wall`)
- **Open Range demo films** — 0/4 steps done (`open-range-promo`)
- **Schwab trader** — 0/5 steps done (`schwab-trader`)

## Tasks in flight
- [QUEUED] Shorts-pipeline daily.yml + third.yml red since 2026-08-14: nobody authors the day's packages. run_trending_daily refuses with 'validated production manifest is incomplete: found 0/6 packages in state/trending_packages/<date>' — the fail-closed gate working correctly on an upstream authoring outage (the Routine and the ChatGPT takeover are both producing nothing). Zero-upload days have driven the failure counter to 2, its auto-pause threshold. Fix belongs in Shorts-pipeline, on its own branch. (`shorts-daily-authoring-outage`)
- [QUEUED] Point a ChatGPT scheduled task at state/pulse/briefing.md with the exchange/README.md contract (`light-up-the-wall-s4`)
- [QUEUED] Verify or repair capability message.send (`verify-message-send`) → claude

## Inbox: 1 ChatGPT suggestion(s) awaiting a ruling
Rule with `python -m aletheia.suggestions list --state new`.

## Last 24h in the journal
- `07:20` [recovery] repo:shorts_pipeline: health red -> green
- `07:20` [recovery] sentinel: fleet recovered — alert issue closed

---
pulse `2026-11-12T07:19:59Z` · registry rev 7 · composed by `aletheia.brief`
