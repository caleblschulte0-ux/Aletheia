# Fleet briefing

Generated 2026-09-02T04:42:01Z from fleet registry rev 4 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `d0aa5327c405` at 2026-09-01T23:42:44Z: docs: make Aletheia single-front-door end state explicit

Watched workflows:
- `pulse.yml`: in_progress at 2026-09-02T04:41:59Z
- `ci.yml`: success at 2026-09-01T23:43:49Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `79e75da2f656` at 2026-09-01T22:07:44Z: explainer: update posted log + analytics [skip ci]

Vitals — trending posted: 300 · explainer posted: 219 · third posted: 398 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-09-01T17:25:34Z
- `exchange_phase_a.yml`: success at 2026-09-01T14:17:09Z
- `exchange_phase_b.yml`: success at 2026-09-01T17:53:52Z
- `story_forge.yml`: success at 2026-09-01T20:00:00Z
- `third.yml`: failure at 2026-09-01T15:30:57Z
- `explainer.yml`: success at 2026-09-01T22:07:50Z
- `retro.yml`: success at 2026-09-02T04:38:42Z
- `doctor.yml`: success at 2026-09-01T10:02:27Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `4dedfcb6247e` at 2026-09-01T18:36:36Z: sell-brain: update exit decisions [skip ci]

Vitals — realized P&L: $-40.82 · win rate: 14.3% · closed trades: 14 · open positions: 13 · cash: $2.50

Watched workflows:
- `sell-brain.yml`: success at 2026-09-01T18:36:42Z
- `watchdog.yml`: success at 2026-09-01T22:13:04Z

## 💤 `Money_Machine` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

