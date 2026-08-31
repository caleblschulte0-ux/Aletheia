# Fleet briefing

Generated 2026-08-31T14:00:09Z from fleet registry rev 4 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `3a9298c2a54b` at 2026-08-31T05:43:49Z: pulse: 2026-08-31T05:43Z

Watched workflows:
- `pulse.yml`: in_progress at 2026-08-31T14:00:07Z
- `ci.yml`: success at 2026-08-31T00:54:53Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `024d81011ca2` at 2026-08-31T12:01:36Z: exchange: media worker started 20260831 [skip ci]

Vitals — trending posted: 300 · explainer posted: 215 · third posted: 398 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-08-30T17:44:11Z
- `exchange_phase_a.yml`: success at 2026-08-30T14:30:35Z
- `exchange_phase_b.yml`: success at 2026-08-30T18:06:22Z
- `story_forge.yml`: success at 2026-08-31T11:41:13Z
- `third.yml`: failure at 2026-08-30T15:30:32Z
- `explainer.yml`: failure at 2026-08-31T00:32:43Z
- `retro.yml`: success at 2026-08-31T05:39:56Z
- `doctor.yml`: success at 2026-08-31T11:33:57Z

## 🔴 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `98b0f779b477` at 2026-08-28T18:36:58Z: sell-brain: update exit decisions [skip ci]

Vitals — realized P&L: $-40.82 · win rate: 14.3% · closed trades: 14 · open positions: 13 · cash: $2.50

Watched workflows:
- `sell-brain.yml`: failure at 2026-08-31T12:35:23Z
- `watchdog.yml`: success at 2026-08-28T22:49:05Z

## 💤 `Money_Machine` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

