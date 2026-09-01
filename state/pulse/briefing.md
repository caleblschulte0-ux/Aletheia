# Fleet briefing

Generated 2026-09-01T16:43:31Z from fleet registry rev 4 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `d2b801a7c884` at 2026-09-01T15:21:18Z: brief: 2026-09-01

Watched workflows:
- `pulse.yml`: in_progress at 2026-09-01T16:43:28Z
- `ci.yml`: success at 2026-09-01T02:46:38Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `bda489e4a923` at 2026-09-01T16:37:36Z: watchdog: chatgpt task verdicts 20260901 [skip ci]

Vitals — trending posted: 300 · explainer posted: 218 · third posted: 398 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-08-31T19:34:27Z
- `exchange_phase_a.yml`: success at 2026-09-01T14:17:09Z
- `exchange_phase_b.yml`: success at 2026-08-31T20:14:07Z
- `story_forge.yml`: success at 2026-09-01T10:13:40Z
- `third.yml`: failure at 2026-09-01T15:30:57Z
- `explainer.yml`: failure at 2026-09-01T01:13:02Z
- `retro.yml`: success at 2026-09-01T05:13:42Z
- `doctor.yml`: success at 2026-09-01T10:02:27Z

## 🔴 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `98b0f779b477` at 2026-08-28T18:36:58Z: sell-brain: update exit decisions [skip ci]

Vitals — realized P&L: $-40.82 · win rate: 14.3% · closed trades: 14 · open positions: 13 · cash: $2.50

Watched workflows:
- `sell-brain.yml`: failure at 2026-09-01T15:35:27Z
- `watchdog.yml`: success at 2026-08-31T23:15:16Z

## 💤 `Money_Machine` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

