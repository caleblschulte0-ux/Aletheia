# Fleet briefing

Generated 2026-10-22T21:42:04Z from fleet registry rev 7 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `47ab9783ba28` at 2026-10-22T21:20:47Z: Merge pull request #524 from caleblschulte0-ux/claude/probe-next113

Watched workflows:
- `pulse.yml`: success at 2026-10-22T17:16:51Z
- `ci.yml`: success at 2026-10-22T17:47:04Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `f29898e56ef7` at 2026-10-22T20:12:34Z: story forge: new real-data stories [skip ci]

Vitals — trending posted: 466 · explainer posted: 351 · third posted: 1084 · curiosity posted: 1

Watched workflows:
- `daily.yml`: cancelled at 2026-10-22T11:27:34Z
- `exchange_phase_a.yml`: success at 2026-10-22T18:54:14Z
- `exchange_phase_b.yml`: success at 2026-10-22T18:40:25Z
- `story_forge.yml`: success at 2026-10-22T20:12:41Z
- `third.yml`: success at 2026-10-22T15:53:54Z
- `explainer.yml`: success at 2026-10-22T19:25:06Z
- `retro.yml`: success at 2026-10-22T04:53:08Z
- `doctor.yml`: success at 2026-10-22T10:06:55Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `b017121f6572` at 2026-10-22T21:31:15Z: bot: daily snapshot [skip ci]
Vitals withheld (5, on his own screen): realized P&L, win rate, closed trades, open positions, cash

Watched workflows:
- `sell-brain.yml`: success at 2026-09-22T18:37:07Z
- `watchdog.yml`: success at 2026-10-22T00:06:58Z

## ⚪ `Money_Machine` — product-ventures (active)

Product ventures monorepo. main holds only a README; the work lives on long-running branches (Barkly, the Open Range demo films, the holdco platform), each carried by a charter in plans/.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

Watched workflows:
- `barkly-ci.yml`: no finished run on main

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

## Charters

- **Barkly** (`Money_Machine` @ `claude/barkley-mvp-mobile-qbegtj`, low risk): 0/8 steps; last human or builder commit 2026-09-23T14:39:43Z; next step 1 (thea): Get Barkly CI green on the project branch: its 'Production dependency audit' step fails on every push
- **Holdco platform** (`Money_Machine` @ `claude/ai-holdco-master-playbook-i5q80w`, low risk): 0/5 steps; last human or builder commit 2026-08-06T02:51:23Z; next step 1 (caleb): Pick the one offer to test first and write it as one sentence in docs/NEXT_OFFER.md on the holdco branch (or tell any Claude session to)
- **Instagram Auto Post Setup** (`Aletheia` @ `live`, high risk): 0/4 steps; last human or builder commit 2026-10-22T21:20:47Z; next step 1 (caleb): Switch the Instagram account to a professional account. This is first, and everything else fails without it: the Meta app cannot see a personal account. In the Instagram app: your profile -> the three-line menu -> Settings and privacy -> Account type and tools -> Switch to professional account -> Business.
- **Open Range demo films** (`Money_Machine` @ `claude/open-range-promo-video-4n7k7o`, low risk): 0/4 steps; last human or builder commit 2026-09-23T12:07:14Z; next step 1 (thea): Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open
- **Schwab trader** (`schwab-trader` @ `main`, high risk): 0/5 steps; last human or builder commit never; next step 1 (caleb): Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it

