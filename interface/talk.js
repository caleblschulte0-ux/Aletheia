/* The front door. One object on the screen, and it is her.
 *
 * The design correction this file carries: the mark means THEA, not
 * "microphone". Tapping it means "I want you". How the words get there —
 * browser speech where it exists, the keyboard where it does not — is a
 * detail underneath that. The first version made a 152px mic the largest
 * thing on screen and then, on iOS Safari, quietly opened the keyboard
 * instead; the object was making a promise the device could not keep.
 *
 * So: the mark never changes meaning by platform. Only the HINT under it
 * does, and it says the true thing before he taps, not after.
 */
(() => {
  "use strict";
  const T = window.Thea;
  const $ = (id) => document.getElementById(id);

  let busy = false, listening = false, rec = null, restTimer = null;
  // Did THIS ask arrive out loud? Voice in, voice out — and typing stays
  // silent, which is a rule a person understands without a setting.
  let aloud = false;

  /* Reading aloud, as a standing choice.
   *
   * "Voice in, voice out" is the right rule on a device that can HEAR the
   * question — and his phone is an iPhone, where Safari has no
   * SpeechRecognition at all. He dictates with the keyboard's own mic, which
   * arrives here as typing, indistinguishable from typing. So a phone that
   * cannot detect a spoken question cannot infer that he wanted a spoken
   * answer: he says so once, and it sticks on this device. */
  const SPEAK_KEY = "thea.speak";
  let speakBack = false;
  try { speakBack = localStorage.getItem(SPEAK_KEY) === "1"; } catch {}

  function paintVoice() {
    const btn = $("voiceBtn");
    btn.classList.toggle("on", speakBack);
    btn.setAttribute("aria-pressed", speakBack ? "true" : "false");
    btn.setAttribute("aria-label", speakBack ? "Stop reading answers aloud"
                                             : "Read answers aloud");
  }

  $("voiceBtn").addEventListener("click", () => {
    speakBack = !speakBack;
    try { localStorage.setItem(SPEAK_KEY, speakBack ? "1" : "0"); } catch {}
    paintVoice();
    if (speakBack) {
      // Inside the gesture, so iOS allows the real utterance later, and a
      // word back so he knows it took.
      T.unlockSpeech();
      T.speak("I'll read answers out loud.");
    } else {
      T.hush();
    }
  });
  const RESTING = "Tap to speak to her.";

  // ---- her ------------------------------------------------------------
  function state(mode, seconds) {
    const her = $("her");
    her.className = "her " + mode;
    // A long think must not look like a hang. After twenty seconds the hint
    // starts counting, because "thinking, 48s" is a working machine and
    // "thinking" for a silent minute is a broken one.
    const waited = mode === "thinking" && seconds > 20
      ? `thinking · ${seconds}s` : "thinking";
    $("hint").textContent =
      mode === "listening" ? "listening — tap to stop"
      : mode === "thinking" ? waited
      : mode === "halted" ? "halted"
      : T.canListen ? "" : "tap to write";
  }

  /* The reply MORPHS. A short answer is a sentence in her voice; anything
     longer becomes a card that can be read and scrolled, rather than a
     22-character column. The threshold is about where a centred line stops
     being a sentence and starts being a paragraph. */
  function reply(text, kind) {
    const box = $("reply");
    clearTimeout(restTimer);
    const body = String(text == null ? "" : text);
    if (!body) {
      box.innerHTML = '<p class="sentence resting"></p>';
      box.firstChild.textContent = RESTING;
      return;
    }
    if (kind !== "trouble" && body.length > 150) {
      const card = document.createElement("div");
      card.className = "card";
      card.textContent = body;
      box.replaceChildren(card);
    } else {
      const p = document.createElement("p");
      p.className = "sentence" + (kind === "trouble" ? " trouble" : "");
      p.textContent = body;
      box.replaceChildren(p);
    }
    if (kind !== "trouble") {
      // Return to rest, so opening the app later does not show yesterday's
      // answer as though it were current.
      restTimer = setTimeout(() => reply(""), 120000);
    }
  }

  // ---- the state line and the amber dot -------------------------------
  async function refresh() {
    try {
      const [status, approvals, notices] = await Promise.all([
        T.api("/api/status"),
        T.api("/api/approvals").catch(() => []),
        T.api("/api/notifications").catch(() => []),
      ]);
      const halted = status.halted;
      const alive = status.liveness && status.liveness.alive;
      // Human words, never a heartbeat age. "heard from 8s ago" is a
      // diagnostic; "here" is an answer.
      $("where").textContent = halted ? "Halted" : alive ? "Here" : "Not running";
      if (halted && !busy && !listening) state("halted");
      else if (!busy && !listening) state("ready");

      const need =
        (Array.isArray(approvals) ? approvals : []).filter((a) => a.state === "PENDING").length +
        (Array.isArray(notices) ? notices : []).filter((n) => n.state !== "ACKNOWLEDGED").length;
      $("through").classList.toggle("needs", need > 0);
      $("through").setAttribute(
        "aria-label", need ? `Everything — ${need} waiting` : "Everything");
    } catch (err) {
      $("where").textContent = err.unauthorized ? "Not linked" : "Can't reach her";
      if (err.unauthorized) {
        reply("This phone isn't linked yet. Open the aperture, then System.",
              "trouble");
      }
    }
  }

  // ---- asking ---------------------------------------------------------
  async function ask(text, spoken) {
    if (busy || !String(text || "").trim()) return;
    aloud = !!spoken;
    busy = true;
    $("send").disabled = true;
    state("thinking");
    try {
      let last = "";
      await T.ask(text, (t) => { last = t; reply(t); },
                  (secs) => state("thinking", secs));
      $("q").value = "";
      state("answering");
      // Out loud when he asked out loud, or when he has said to.
      if (aloud || speakBack) T.speak(last);
      setTimeout(() => { if (!busy && !listening) state("ready"); }, 600);
      refresh();
    } catch (err) {
      reply(err.unauthorized ? "This phone isn't linked yet."
                             : "That didn't go through.", "trouble");
      state("ready");
    } finally {
      busy = false;
      $("send").disabled = false;
    }
  }

  // ---- tapping her -----------------------------------------------------
  $("her").addEventListener("click", () => {
    // Talking over her is how you stop her talking. A reply already read
    // aloud is still on screen, so cutting it off costs nothing.
    if (T.speaking()) { T.hush(); if (busy) return; }
    if (busy) return;
    if (listening) { try { rec && rec.stop(); } catch {} return; }
    // Inside the gesture, while iOS still allows it: by the time an answer
    // exists this tap is several awaits in the past and speech is refused.
    T.unlockSpeech();
    if (!T.canListen) {
      /* No browser speech here (iOS Safari). The mark still means "I want
       * you" — it just hands him the keyboard, where the phone's own
       * dictation key is one tap away. The hint has already said so, so
       * nothing is discovered by being lied to. */
      $("q").focus();
      return;
    }
    rec = T.listen({
      onStart: () => { listening = true; state("listening"); reply(""); },
      onEnd: () => { listening = false; if (!busy) state("ready"); },
      onResult: (heard) => { $("q").value = heard; ask(heard, true); },
      onError: (why) => {
        listening = false;
        state("ready");
        reply(why === "not-allowed"
          ? "The microphone is blocked for this site — allow it in Settings."
          : "I didn't catch that.", "trouble");
      },
    });
  });

  $("send").addEventListener("click", () => ask($("q").value));
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); ask($("q").value); }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) T.hush(); else refresh();
  });

  paintVoice();
  state("ready");
  reply("");
  refresh();
  setInterval(() => { if (!document.hidden && !busy) refresh(); }, 30000);
})();
