// Browser voice is a deliberate fallback, not a second always-on room listener.
//
// The Windows room process owns hands-free "Thea, ...". Keeping Chrome's Web
// Speech recognizer armed at the same time makes one utterance hit both stacks:
// duplicate Core requests, duplicate mouths, and potentially duplicate actions.
// The wall/Command Center therefore use one-shot push-to-talk: click once, say
// the command WITHOUT the wake word, receive one answer, and the browser mic is
// closed again. The server still receives "thea ...", so the same voice gates
// and command grammar apply.
(function () {
  const WAKE = /^\s*(thea|theia|tia|althea|aletheia)\b/i;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  const el = document.createElement("div");
  el.id = "thea-voice";
  el.style.cssText =
    "position:fixed;bottom:16px;right:16px;z-index:99;display:flex;gap:10px;" +
    "align-items:center;font:13px system-ui;color:#8ea0b5;cursor:pointer;" +
    "background:rgba(10,14,20,.85);padding:8px 14px;border-radius:999px;" +
    "border:1px solid #253247;user-select:none";
  const dot = document.createElement("span");
  dot.style.cssText = "width:10px;height:10px;border-radius:50%;background:#4a5a70";
  const label = document.createElement("span");
  el.append(dot, label);
  document.body.appendChild(el);

  if (!SR || navigator.brave) {
    label.textContent = "browser mic needs Chrome or Edge";
    return;
  }

  let rec = null;
  let listening = false;
  let busy = false;

  function setUI(state, text) {
    label.textContent = text;
    dot.style.background =
      state === "listening" ? "#39d98a" :
      state === "heard" ? "#f5c542" :
      // she is away thinking, not broken — the error colour would say the
      // opposite of what is happening
      state === "thinking" ? "#6aa9ff" :
      state === "off" ? "#4a5a70" : "#e0556a";
  }

  function bestVoice() {
    const voices = speechSynthesis.getVoices ? speechSynthesis.getVoices() : [];
    const preferred = [
      /ryan.*natural/i,
      /george.*english.*united kingdom/i,
      /google uk english male/i,
      /daniel.*english/i,
      /en[-_ ]gb/i,
    ];
    for (const pattern of preferred) {
      const hit = voices.find((v) => pattern.test(`${v.name} ${v.lang}`));
      if (hit) return hit;
    }
    return voices.find((v) => /^en[-_]GB/i.test(v.lang)) || null;
  }

  function speak(text) {
    return new Promise((resolve) => {
      try {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-GB";
        u.rate = 1.03;
        u.pitch = 0.96;
        const voice = bestVoice();
        if (voice) u.voice = voice;
        u.onend = resolve;
        u.onerror = resolve;
        speechSynthesis.cancel();
        speechSynthesis.speak(u);
      } catch (e) {
        resolve();
      }
    });
  }

  // The answer he actually asked for.
  //
  // A request the planner has to think about takes ten to thirty seconds, so
  // POST /api/voice answers immediately with an acknowledgement and a
  // `followup_id`, and the real sentence lands in that slot later. The room
  // microphone already collected it. THE WALL DID NOT — it spoke "one moment"
  // and stopped, which is exactly what the operator reported: he asked, heard
  // that she was working on it, and never got the answer. Silence is the bug,
  // so a slot that fails is spoken too.
  async function collect(followupId) {
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1200));
      let slot;
      try {
        const r = await fetch(
          "/api/voice/followup?id=" + encodeURIComponent(followupId));
        if (!r.ok) continue;
        slot = await r.json();
      } catch (e) {
        continue;               // a dropped beat is not an answer
      }
      if (slot.state === "PENDING") continue;
      return {
        id: followupId,
        say: slot.say || (slot.state === "FAILED"
          ? "I could not finish that one."
          : "That is done."),
      };
    }
    return { id: null,
             say: "That is taking longer than it should — it is in your notifications." };
  }

  // Only after it has actually been SAID. The GET is a pure read, so a
  // dropped response costs a retry rather than the answer itself.
  // Injected by the Core into every page it serves; a loopback WRITE must
  // carry it (2026-09-03: 127.0.0.1 proves origin, not authorization).
  const localSecret = () => {
    const m = document.querySelector('meta[name="aletheia-local"]');
    return m ? m.content : "";
  };

  async function acknowledge(followupId) {
    if (!followupId) return;
    try {
      await fetch("/api/voice/followup/ack", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "X-Aletheia-Local": localSecret() },
        body: JSON.stringify({ id: followupId }),
      });
    } catch (e) {
      // it stays collectable; the notification carries it either way
    }
  }

  async function sendCommand(command) {
    busy = true;
    const transcript = `thea ${command}`;
    setUI("heard", "…" + command.slice(0, 60));
    try {
      const r = await fetch("/api/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "X-Aletheia-Local": localSecret() },
        body: JSON.stringify({ transcript }),
      });
      const res = await r.json();
      const say = res.say || res.detail || "done";
      setUI("heard", say.slice(0, 80));
      await speak(say);
      if (res.followup_id) {
        setUI("thinking", "thinking…");
        const answer = await collect(res.followup_id);
        setUI("heard", answer.say.slice(0, 80));
        await speak(answer.say);
        await acknowledge(answer.id);
      }
      if (typeof refresh === "function") refresh();
      setUI("off", "click to talk · no wake word");
    } catch (e) {
      setUI("error", "core unreachable");
    } finally {
      busy = false;
    }
  }

  function startOneShot() {
    if (busy || listening) return;
    // Do not let the browser transcribe its own prior TTS tail.
    try { speechSynthesis.cancel(); } catch (e) {}

    rec = new SR();
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    listening = true;

    rec.onresult = (ev) => {
      listening = false;
      const t = ev.results[ev.results.length - 1][0].transcript.trim();
      if (!t) {
        setUI("off", "didn't catch that · click to retry");
        return;
      }
      if (WAKE.test(t)) {
        // The native room listener owns wake-word speech. Sending this from the
        // browser too would duplicate the command if both listeners are alive.
        setUI("off", 'hands-free hears "Thea" · click then speak without it');
        return;
      }
      sendCommand(t);
    };

    rec.onend = () => {
      listening = false;
      if (!busy) setUI("off", "click to talk · no wake word");
    };

    rec.onerror = (ev) => {
      listening = false;
      if (ev.error === "no-speech" || ev.error === "aborted") {
        setUI("off", "click to talk · no wake word");
      } else if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
        setUI("error", "mic blocked — allow it in site settings");
      } else if (ev.error === "network") {
        setUI("error", "browser speech service unreachable");
      } else if (ev.error === "audio-capture") {
        setUI("error", "no microphone found");
      } else {
        setUI("error", "speech error: " + ev.error);
      }
    };

    try {
      rec.start();
      setUI("listening", "listening once · don't say Thea");
    } catch (e) {
      listening = false;
      setUI("error", "mic failed");
    }
  }

  el.onclick = startOneShot;
  setUI("off", "click to talk · no wake word");
})();
