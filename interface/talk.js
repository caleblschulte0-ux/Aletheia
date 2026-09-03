/* The front door. One job: he says a thing, she does it and answers.
 *
 * The whole design question here was what the big button does on a browser
 * with no speech recognition — which is to say, on his iPhone. A mic that
 * silently fails is the worst option; a mic that is greyed out is a dead
 * centre of the screen. So the button is "the way you talk to her", and on
 * a browser that cannot listen it focuses the text field instead. The
 * primary action always does something.
 */
(() => {
  "use strict";
  const T = window.Thea;
  const $ = (id) => document.getElementById(id);

  let busy = false;
  let listening = false;
  let rec = null;
  let idleTimer = null;

  const IDLE = "Tap and talk.";

  function show(text, isError) {
    const el = $("answer");
    el.textContent = text || IDLE;
    el.classList.toggle("idle", !text);
    el.classList.toggle("err", !!isError);
    clearTimeout(idleTimer);
    if (text && !isError) {
      // Fall back to the resting line so the screen is not left holding
      // yesterday's answer the next time he opens it.
      idleTimer = setTimeout(() => {
        $("answer").textContent = IDLE;
        $("answer").classList.add("idle");
      }, 90000);
    }
  }

  function setButton(mode) {
    const b = $("talk");
    b.classList.toggle("on", mode === "listening");
    b.classList.toggle("thinking", mode === "thinking");
    $("glyph").textContent = mode === "listening" ? "■"
      : mode === "thinking" ? "⋯" : "🎤";
    $("cap").textContent = mode === "listening" ? "listening — tap to stop"
      : mode === "thinking" ? "working on it"
      : T.canListen ? "tap and talk" : "tap to type";
  }

  // ---- the state rail, and the badge that earns a second tap ---------
  async function refresh() {
    try {
      const [status, approvals, notices] = await Promise.all([
        T.api("/api/status"),
        T.api("/api/approvals").catch(() => []),
        T.api("/api/notifications").catch(() => []),
      ]);
      const halted = status.halted;
      const alive = status.liveness && status.liveness.alive;
      $("orb").className = "orb " + (halted ? "halted" : alive ? "live" : "");
      // Never colour alone — the words carry it too.
      $("state").textContent = halted ? "Halted"
        : alive ? "Ready" : "Core not running";

      const pending = (Array.isArray(approvals) ? approvals : []).filter(
        (a) => a.state === "PENDING").length;
      const unread = (Array.isArray(notices) ? notices : []).filter(
        (n) => n.state !== "ACKNOWLEDGED").length;
      const need = pending + unread;
      $("badge").textContent = need > 9 ? "9+" : String(need);
      $("more").classList.toggle("needs", need > 0);
    } catch (err) {
      $("orb").className = "orb";
      $("state").textContent = err.unauthorized ? "Needs a token"
                                                : "Can't reach her";
      if (err.unauthorized) {
        show("This device isn't authorized yet — open Everything and tap Access.",
             true);
      }
    }
  }

  // ---- asking --------------------------------------------------------
  async function ask(text) {
    if (busy || !String(text || "").trim()) return;
    busy = true;
    $("send").disabled = true;
    setButton("thinking");
    try {
      await T.ask(text, show, () => setButton("thinking"));
      $("q").value = "";
      refresh();
    } catch (err) {
      show(err.unauthorized ? "This device isn't authorized yet."
                            : "That didn't go through.", true);
    } finally {
      busy = false;
      $("send").disabled = false;
      setButton("idle");
    }
  }

  // ---- the one button ------------------------------------------------
  function startListening() {
    rec = T.listen({
      onStart: () => { listening = true; setButton("listening"); show("Listening…"); },
      onEnd: () => { listening = false; if (!busy) setButton("idle"); },
      onResult: (heard) => { $("q").value = heard; ask(heard); },
      onError: (why) => {
        listening = false;
        setButton("idle");
        show(why === "not-allowed"
          ? "The microphone is blocked for this site — allow it in Settings."
          : "Didn't catch that.", true);
      },
    });
  }

  $("talk").addEventListener("click", () => {
    if (busy) return;
    if (!T.canListen) {
      // No speech in this browser (iOS Safari). The button still does the
      // thing it promises: it gets him to a place he can say it.
      $("q").focus();
      show("This browser can't listen — type it and she'll answer.", true);
      return;
    }
    if (listening) { try { rec && rec.stop(); } catch {} return; }
    startListening();
  });

  $("send").addEventListener("click", () => ask($("q").value));
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); ask($("q").value); }
  });

  // Refresh when he actually looks at it; nothing while it sits in a pocket.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });

  setButton("idle");
  refresh();
  setInterval(() => { if (!document.hidden && !busy) refresh(); }, 30000);
})();
