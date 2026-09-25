# Fleet briefing

Generated 2026-09-25T05:03:42Z from fleet registry rev 5 via GitHubSource.

## ⚪ `Aletheia` — hub (active)

The fleet's single pane of truth: registry, pulse collector, interface, ChatGPT suggestion inbox.

Last commit `ef1eccbbc4c2` at 2026-09-25T04:59:09Z: Merge pull request #210 from caleblschulte0-ux/claude/instagram-with-instagram-login

Watched workflows:
- `pulse.yml`: in_progress at 2026-09-25T05:03:39Z
- `ci.yml`: in_progress at 2026-09-25T04:59:15Z

## 🟢 `Shorts-pipeline` — youtube-automation (active)

Multi-channel automated YouTube pipeline (trending, explainer, curiosity, third) with Claude brains, a fail-closed showrunner gate, and a daily ChatGPT media/authoring exchange.

Last commit `1b859f4209fb` at 2026-09-25T04:47:41Z: claim: mailbox verdicts 2026-09-25T04:47Z [skip ci]

Vitals — trending posted: 353 · explainer posted: 270 · third posted: 666 · curiosity posted: 1

Watched workflows:
- `daily.yml`: success at 2026-09-24T23:37:55Z
- `exchange_phase_a.yml`: success at 2026-09-25T02:30:15Z
- `exchange_phase_b.yml`: success at 2026-09-24T18:30:14Z
- `story_forge.yml`: success at 2026-09-24T20:37:41Z
- `third.yml`: success at 2026-09-24T23:52:46Z
- `explainer.yml`: success at 2026-09-24T20:43:56Z
- `retro.yml`: success at 2026-09-25T05:00:46Z
- `doctor.yml`: success at 2026-09-24T09:56:56Z

## 🟢 `schwab-trader` — trading-bot (active)

Guardrailed paper-trading system. The SELL brain and executor watchdog are active; the subscription-backed BUY brain and trade executor are intentionally paused until the operator resumes them.

Last commit `a47211bd3f39` at 2026-09-24T21:28:53Z: bot: daily snapshot [skip ci]
Vitals withheld (5, on his own screen): realized P&L, win rate, closed trades, open positions, cash

Watched workflows:
- `sell-brain.yml`: success at 2026-09-22T18:37:07Z
- `watchdog.yml`: success at 2026-09-24T23:57:53Z

## 🟢 `Money_Machine` — product-ventures (active)

Product ventures monorepo. main holds only a README; the work lives on long-running branches (Barkly, the Open Range demo films, the holdco platform), each carried by a charter in plans/.

Last commit `53c6507f6afe` at 2026-08-05T19:11:54Z: Initial commit

Watched workflows:
- `barkly-ci.yml`: success at 2026-09-23T14:54:09Z

## 💤 `etsy_maker` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

**Unreachable:** HTTPError: HTTP Error 404: Not Found

## 💤 `fosstester` — unbuilt (stub)

Empty stub — nothing but a README. No behaviour to observe yet.

Last commit `41ea84afb060` at 2026-06-03T15:08:19Z: Initial commit

## Charters

- **Barkly** (`Money_Machine` @ `claude/barkley-mvp-mobile-qbegtj`, low risk): 0/8 steps; last human or builder commit 2026-09-23T14:39:43Z; next step 1 (thea): Get Barkly CI green on the project branch: its 'Production dependency audit' step fails on every push
- **Holdco platform** (`Money_Machine` @ `claude/ai-holdco-master-playbook-i5q80w`, low risk): 0/5 steps; last human or builder commit 2026-08-06T02:51:23Z; next step 1 (caleb): Pick the one offer to test first and write it as one sentence in docs/NEXT_OFFER.md on the holdco branch (or tell any Claude session to)
- **Instagram Auto Post Setup** (`Aletheia` @ `live`, high risk): 0/4 steps; last human or builder commit 2026-09-25T04:59:09Z; next step 1 (caleb): Switch the Instagram account to a professional account. This is first, and everything else fails without it: the Meta app cannot see a personal account. In the Instagram app: your profile -> the three-line menu -> Settings and privacy -> Account type and tools -> Switch to professional account -> Business.
- **Open Range demo films** (`Money_Machine` @ `claude/open-range-promo-video-4n7k7o`, low risk): 0/4 steps; last human or builder commit 2026-09-23T12:07:14Z; next step 1 (thea): Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered, where each master and contact sheet lives, and what is still open
- **Schwab trader** (`schwab-trader` @ `main`, high risk): 0/5 steps; last human or builder commit 2026-09-24T11:51:35Z; next step 1 (caleb): Answer the sell approval waiting since June 26 (schwab-trader issue #5): comment approve, hold, or close it

