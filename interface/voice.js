// Voice for the wall and the Command Center — the page IS the interface.
// Ears: Web Speech API (Chrome/Edge, local browser capability, no keys).
// Mouth: speechSynthesis. Brain+gates: POST /api/voice on the Core.
//
// Always listening once armed. Say "Thea, ..." — the wake word is checked
// here AND server-side (strip_wake_word), so a stray sentence without it
// is ignored. Click the indicator to arm/disarm (browsers require one
// user gesture before the microphone can start).
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

  if (!SR) {
    label.textContent = "voice needs Chrome or Edge";
    return;
  }

  let armed = false, rec = null, busy = false;

  function setUI(state, text) {
    label.textContent = text;
    dot.style.background =
      state === "listening" ? "#39d98a" :
      state === "heard" ? "#f5c542" :
      state === "off" ? "#4a5a70" : "#e0556a";
  }

  function speak(text) {
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05;
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    } catch (e) { /* silent page still shows the text */ }
  }

  async function send(transcript) {
    busy = true;
    setUI("heard", "…" + transcript.slice(0, 60));
    try {
      const r = await fetch("/api/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript }),
      });
      const res = await r.json();
      const say = res.say || res.detail || "done";
      setUI("heard", say.slice(0, 80));
      speak(say);
      if (typeof refresh === "function") refresh();
    } catch (e) {
      setUI("error", "core unreachable");
    }
    busy = false;
    setTimeout(() => { if (armed) setUI("listening", 'say "Thea, …"'); }, 4000);
  }

  function start() {
    rec = new SR();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (ev) => {
      const t = ev.results[ev.results.length - 1][0].transcript.trim();
      if (WAKE.test(t) && !busy) send(t);
    };
    rec.onend = () => { if (armed) { try { rec.start(); } catch (e) {} } };
    rec.onerror = (ev) => {
      if (ev.error === "not-allowed") { armed = false; setUI("error", "mic blocked"); }
    };
    try { rec.start(); setUI("listening", 'say "Thea, …"'); }
    catch (e) { setUI("error", "mic failed"); }
  }

  el.onclick = () => {
    armed = !armed;
    if (armed) start();
    else { try { rec && rec.stop(); } catch (e) {} setUI("off", "voice off — click to listen"); }
  };
  setUI("off", "click to give Thea ears");
})();
