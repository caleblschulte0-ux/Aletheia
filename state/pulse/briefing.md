# Fleet briefing

Generated 2026-08-27T22:19:04Z from fleet registry rev 4 via GitHubSource.

## 🔴 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `1e69505b308d` at 2026-08-27T22:12:00Z: core: state checkpoint

Watched workflows:
- `pulse.yml`: in_progress at 2026-08-27T22:19:01Z
- `ci.yml`: failure at 2026-08-27T21:48:35Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `4c2f208e8873` at 2026-08-27T22:14:27Z: watchdog: chatgpt task verdicts 20260827 [skip ci]

Vitals — trending posted: 287 · explainer posted: 204 · third posted: 387 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-08-26T14:31:04Z
- `exchange_phase_a.yml`: success at 2026-08-27T19:59:28Z
- `exchange_phase_b.yml`: success at 2026-08-26T15:57:38Z
- `story_forge.yml`: success at 2026-08-27T16:35:26Z
- `third.yml`: failure at 2026-08-27T21:02:32Z
- `explainer.yml`: cancelled at 2026-08-27T00:24:38Z
- `retro.yml`: success at 2026-08-27T09:52:46Z
- `doctor.yml`: success at 2026-08-27T16:28:26Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `e957a7f0f370` at 2026-08-27T18:36:46Z: sell-brain: update exit decisions [skip ci]

Vitals — realized P&L: $-40.82 · win rate: 14.3% · closed trades: 14 · open positions: 13 · cash: $2.50

Watched workflows:
- `sell-brain.yml`: success at 2026-08-27T18:36:51Z
- `watchdog.yml`: success at 2026-08-27T01:03:05Z

## 💤 `Money_Machine` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

