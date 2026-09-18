# Fleet briefing

Generated 2026-09-18T11:23:50Z from fleet registry rev 5 via GitHubSource.

## 🔴 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `c8089d98c3d9` at 2026-09-13T15:52:48Z: Apply anywhere: her texts, four more systems, and no more black boxes

Watched workflows:
- `pulse.yml`: in_progress at 2026-09-18T11:23:47Z
- `ci.yml`: failure at 2026-09-17T22:29:54Z

## 🟢 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `3903dca1f8f3` at 2026-09-18T11:13:39Z: third: checkpoint posted log (claim upload slot) [skip ci]

Vitals — trending posted: 328 · explainer posted: 253 · third posted: 549 · curiosity posted: 1

Watched workflows:
- `daily.yml`: in_progress at 2026-09-18T11:05:01Z
- `exchange_phase_a.yml`: success at 2026-09-18T09:37:21Z
- `exchange_phase_b.yml`: success at 2026-09-17T18:23:02Z
- `story_forge.yml`: success at 2026-09-18T09:53:53Z
- `third.yml`: in_progress at 2026-09-18T11:05:03Z
- `explainer.yml`: in_progress at 2026-09-18T11:05:10Z
- `retro.yml`: success at 2026-09-18T04:47:37Z
- `doctor.yml`: success at 2026-09-18T09:41:40Z

## 🔴 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `ebac659e6fdf` at 2026-09-17T12:36:31Z: sell-brain: update exit decisions [skip ci]
Vitals withheld (5, on his own screen): realized P&L, win rate, closed trades, open positions, cash

Watched workflows:
- `sell-brain.yml`: failure at 2026-09-17T18:35:24Z
- `watchdog.yml`: success at 2026-09-17T22:57:38Z

## 🟢 `Money_Machine` — product-ventures (active)

Product ventures monorepo. main holds only a README; the work lives on long-running branches (Barkly, the Open Range demo films, the holdco platform), each carried by a charter in plans/.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

Watched workflows:
- `barkly-ci.yml`: success at 2026-09-14T03:58:28Z

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

## Charters

- **Barkly** (`Money_Machine` @ `claude/barkley-mvp-mobile-qbegtj`, low risk): 0/8 steps; last human or builder commit 2026-09-13T05:00:51Z; next step 1 (thea): Get Barkly CI green on the project branch: its 'Production dependency audit' step fails on every push
- **Holdco platform** (`Money_Machine` @ `claude/ai-holdco-master-playbook-i5q80w`, low risk): 0/5 steps; last human or builder commit 2026-08-06T02:51:23Z; next step 1 (caleb): Pick the one offer to test first and write it as one sentence in docs/NEXT_OFFER.md on the holdco branch (or tell any Claude session to)
- **Open Range demo films** (`Money_Machine` @ `claude/open-range-promo-video-4n7k7o`, low risk): 0/4 steps; last human or builder commit 2026-09-13T14:44:52Z; next step 1 (thea): Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open
- **Schwab trader** (`schwab-trader` @ `main`, high risk): 0/5 steps; last human or builder commit never; next step 1 (caleb): Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it

