# Aletheia phone interface v1 — prototype only

This folder is intentionally **not wired into Core, Tailscale Serve, `interface/mobile.html`, or any runtime route**.

It exists so Caleb and Claude can review the interaction model and visual direction before anything replaces the current mobile surface.

## Design thesis

The phone should feel like **Aletheia in your pocket**, not a dashboard shrunk onto a phone.

- One surface, not five tabs.
- The default state is intentionally almost empty: Aletheia's mark, presence, and one composer.
- Information appears only when the conversation or current action needs it.
- Approvals are contextual cards, not a permanent admin page.
- System health and the emergency halt are available from one compact status sheet, but they do not dominate normal use.
- Voice and text are equal first-class inputs.
- No fake sci-fi HUD, starfield, dense telemetry, or generic AI-chat chrome.
- The interface should become *more* specific as Aletheia understands the operator, then collapse back to quiet.

## Safety / integration constraints

This prototype makes **zero network requests** and has **no computer-control hooks**. The JavaScript only drives local demo states.

If this direction is approved, integration should happen later through a narrow adapter that talks to existing Core APIs. The prototype should not be used as an excuse to widen phone permissions.

## Review request for Claude

Please review the actual HTML/CSS/JS rather than only this brief. Judge:

1. Does the first screen feel like a personal AI rather than a monitoring dashboard?
2. Is the custom A mark strong enough, or should it be redesigned before integration?
3. Does the adaptive-card model cover normal use without adding permanent tabs?
4. Are approvals and HALT discoverable enough without being visually loud?
5. Does anything still read as generic "AI slop" or over-designed sci-fi?
6. What should be removed before anything is integrated?

Do **not** wire it into Core while reviewing it.

## Preview

Open `index.html` directly, or from this folder run a basic static server, for example:

```bash
python -m http.server 8088
```

Then open `http://127.0.0.1:8088/`.

The demo supports:

- tapping the center mark to simulate listen → think → answer
- typing into the composer
- opening the compact system sheet
- showing a contextual approval card
- approve / deny demo interactions
- local HALT / resume visual states

Everything resets on refresh.