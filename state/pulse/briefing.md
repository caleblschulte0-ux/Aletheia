# Fleet briefing

Generated 2026-10-13T00:47:29Z from fleet registry rev 7 via GitHubSource.

## 🟢 `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `1fbcf79bfe27` at 2026-10-13T00:37:17Z: Merge pull request #434 from caleblschulte0-ux/claude/probe-next38

Watched workflows:
- `pulse.yml`: success at 2026-10-12T15:38:51Z
- `ci.yml`: success at 2026-10-12T23:56:03Z

## 🔴 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `6dd8fb5c3345` at 2026-10-13T00:31:09Z: retro: brief + triage for 20261012 [skip ci]

Vitals — trending posted: 442 · explainer posted: 323 · third posted: 944 · curiosity posted: 1

Watched workflows:
- `daily.yml`: success at 2026-10-12T11:28:15Z
- `exchange_phase_a.yml`: success at 2026-10-13T00:27:05Z
- `exchange_phase_b.yml`: success at 2026-10-12T22:10:54Z
- `story_forge.yml`: success at 2026-10-12T21:05:07Z
- `third.yml`: success at 2026-10-12T20:16:01Z
- `explainer.yml`: cancelled at 2026-10-12T23:11:04Z
- `retro.yml`: success at 2026-10-13T00:31:15Z
- `doctor.yml`: success at 2026-10-12T13:05:57Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `5c041d137bd8` at 2026-10-12T21:44:11Z: bot: daily snapshot [skip ci]
Vitals withheld (5, on his own screen): realized P&L, win rate, closed trades, open positions, cash

Watched workflows:
- `sell-brain.yml`: success at 2026-09-22T18:37:07Z
- `watchdog.yml`: success at 2026-10-10T01:07:02Z

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
- **Instagram Auto Post Setup** (`Aletheia` @ `live`, high risk): 0/4 steps; last human or builder commit 2026-10-13T00:37:17Z; next step 1 (caleb): Switch the Instagram account to a professional account. This is first, and everything else fails without it: the Meta app cannot see a personal account. In the Instagram app: your profile -> the three-line menu -> Settings and privacy -> Account type and tools -> Switch to professional account -> Business.
- **Open Range demo films** (`Money_Machine` @ `claude/open-range-promo-video-4n7k7o`, low risk): 0/4 steps; last human or builder commit 2026-09-23T12:07:14Z; next step 1 (thea): Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open
- **Schwab trader** (`schwab-trader` @ `main`, high risk): 0/5 steps; last human or builder commit 2026-10-01T23:46:23Z; next step 1 (caleb): Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it

