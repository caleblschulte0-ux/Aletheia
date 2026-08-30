# Fleet briefing

Generated 2026-08-30T11:59:08Z from fleet registry rev 4 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `94081326227d` at 2026-08-30T09:33:41Z: core: state checkpoint

Watched workflows:
- `pulse.yml`: in_progress at 2026-08-30T11:59:07Z
- `ci.yml`: success at 2026-08-30T05:29:44Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `ba29df541382` at 2026-08-30T11:01:46Z: exchange: media worker failed bundle 20260830 [skip ci]

Vitals — trending posted: 300 · explainer posted: 210 · third posted: 398 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-08-29T12:43:29Z
- `exchange_phase_a.yml`: success at 2026-08-29T14:41:23Z
- `exchange_phase_b.yml`: success at 2026-08-29T17:45:47Z
- `story_forge.yml`: success at 2026-08-30T10:33:10Z
- `third.yml`: failure at 2026-08-29T15:40:27Z
- `explainer.yml`: failure at 2026-08-29T23:43:39Z
- `retro.yml`: success at 2026-08-30T05:27:35Z
- `doctor.yml`: success at 2026-08-30T10:27:33Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `98b0f779b477` at 2026-08-28T18:36:58Z: sell-brain: update exit decisions [skip ci]

Vitals — realized P&L: $-40.82 · win rate: 14.3% · closed trades: 14 · open positions: 13 · cash: $2.50

Watched workflows:
- `sell-brain.yml`: success at 2026-08-28T18:37:04Z
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

