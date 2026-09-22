# Fleet briefing

Generated 2026-09-22T21:24:05Z from fleet registry rev 5 via GitHubSource.

## ⚪ `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `da4ec01aec9f` at 2026-09-22T20:18:39Z: Merge pull request #145 from caleblschulte0-ux/claude/the-pc-runs-old-code

Watched workflows:
- `pulse.yml`: in_progress at 2026-09-22T21:24:02Z
- `ci.yml`: in_progress at 2026-09-22T21:14:10Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `147ad546bf96` at 2026-09-22T20:52:51Z: exchange: phase A bundle for 20260922 [skip ci]

Vitals — trending posted: 346 · explainer posted: 262 · third posted: 618 · curiosity posted: 1

Watched workflows:
- `daily.yml`: failure at 2026-09-22T20:23:30Z
- `exchange_phase_a.yml`: success at 2026-09-22T20:52:56Z
- `exchange_phase_b.yml`: success at 2026-09-22T18:10:53Z
- `story_forge.yml`: success at 2026-09-22T20:16:25Z
- `third.yml`: success at 2026-09-22T20:11:24Z
- `explainer.yml`: in_progress at 2026-09-22T20:33:03Z
- `retro.yml`: success at 2026-09-22T05:00:22Z
- `doctor.yml`: success at 2026-09-22T09:54:23Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `3a76bffdf678` at 2026-09-22T18:37:03Z: sell-brain: update exit decisions [skip ci]
Vitals withheld (5, on his own screen): realized P&L, win rate, closed trades, open positions, cash

Watched workflows:
- `sell-brain.yml`: success at 2026-09-22T18:37:07Z
- `watchdog.yml`: success at 2026-09-22T20:19:57Z

## 🟢 `Money_Machine` — product-ventures (active)

Product ventures monorepo. main holds only a README; the work lives on long-running branches (Barkly, the Open Range demo films, the holdco platform), each carried by a charter in plans/.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

Watched workflows:
- `barkly-ci.yml`: success at 2026-09-22T20:14:39Z

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

## Charters

- **Barkly** (`Money_Machine` @ `claude/barkley-mvp-mobile-qbegtj`, low risk): 0/8 steps; last human or builder commit 2026-09-22T19:58:18Z; next step 1 (thea): Get Barkly CI green on the project branch: its 'Production dependency audit' step fails on every push
- **Holdco platform** (`Money_Machine` @ `claude/ai-holdco-master-playbook-i5q80w`, low risk): 0/5 steps; last human or builder commit 2026-08-06T02:51:23Z; next step 1 (caleb): Pick the one offer to test first and write it as one sentence in docs/NEXT_OFFER.md on the holdco branch (or tell any Claude session to)
- **Open Range demo films** (`Money_Machine` @ `claude/open-range-promo-video-4n7k7o`, low risk): 0/4 steps; last human or builder commit 2026-09-22T21:09:20Z; next step 1 (thea): Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open
- **Schwab trader** (`schwab-trader` @ `main`, high risk): 0/5 steps; last human or builder commit never; next step 1 (caleb): Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it

