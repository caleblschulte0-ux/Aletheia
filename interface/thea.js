/* The transport, and the only one.
 *
 * ONE page is the product now (thea.html), on the PC and on the phone, so
 * this file is no longer "shared by two surfaces" — it is the part of that
 * page that talks to the Core. It stays its own file because the service
 * worker caches it, the tests read it, and the page's painting has no
 * business knowing about bearer tokens.
 *
 * Every URL is relative on purpose: the same files serve correctly on
 * 127.0.0.1, on a tailnet name, and behind a `tailscale cert` hostname,
 * with no build step and nothing to reconfigure when the address changes.
 */
window.Thea = (() => {
  "use strict";

  const TOKEN_KEY = "thea.token";
  const OUTBOX_KEY = "thea.outbox";
  let token = "";
  try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* private mode */ }

  function getToken() { return token; }
  function setToken(next) {
    token = (next || "").trim();
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode: this session only */ }
  }

  // A one-tap pairing link: ?token=... saves it and is then scrubbed from
  // the address bar/history, so the credential does not sit there in
  // plaintext after the first open. This is what the QR on his PC encodes,
  // and it is why getting Thea onto a new phone is a scan and not a
  // forty-character password typed on glass. Added 2026-09-03 alongside the
  // server requiring a real token for every remote device (tailscale serve
  // makes a phone request look identical to a local one at the socket
  // level, so "on the tailnet" stopped being enough on its own).
  try {
    const fromLink = new URL(location.href).searchParams.get("token");
    if (fromLink) {
      setToken(fromLink);
      const clean = new URL(location.href);
      clean.searchParams.delete("token");
      history.replaceState(null, "", clean.pathname + clean.search + clean.hash);
    }
  } catch { /* malformed URL or a browser that refuses history edits: token
              is still saved, the address bar just keeps the query string */ }

  // Injected by the Core into every page it serves FROM LOOPBACK (never
  // over Tailscale/remote — 2026-09-03). A write from loopback must carry
  // it: 127.0.0.1 proves origin, not that Caleb sent it. It travels
  // separately from `token`, which is the real minted credential a phone
  // presents over Tailscale; the two are never the same value and this
  // page only ever has one of them populated. Its presence is also how the
  // page knows it is running ON HIS PC rather than on the phone.
  function localSecret() {
    const m = document.querySelector('meta[name="aletheia-local"]');
    return m ? m.content : "";
  }
  function onHisPC() { return !!localSecret(); }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers);
    if (token) headers.Authorization = "Bearer " + token;
    const method = (options.method || "GET").toUpperCase();
    // Independent of `token`, not "else": the two prove different things
    // (a remote device's minted grant vs. "this request reached the Core
    // from its own machine") and the server checks them in separate
    // branches, so there is no reason for one stored value to shadow the
    // other. Found live 2026-09-03: a phone with ANY token already saved
    // — even a stale or read-only one from earlier testing — silently
    // never tried the local secret at all, because this was `else`-shaped
    // when it did not need to be. Harmless to always attach: on a
    // genuinely remote (non-loopback) request `localSecret()` is "" (the
    // Core only ever injects it into loopback-served pages), so the
    // header is simply omitted.
    if (method !== "GET" && method !== "HEAD") {
      const local = localSecret();
      if (local) headers["X-Aletheia-Local"] = local;
    }
    if (options.body) headers["Content-Type"] = "application/json";
    const res = await fetch(path, Object.assign({}, options, { headers, cache: "no-store" }));
    if (res.status === 401) {
      const err = new Error("unauthorized");
      err.unauthorized = true;
      throw err;
    }
    if (!res.ok) throw new Error(path + " → " + res.status);
    return res.json();
  }

  /* Every decision this page makes goes through /api/command, which is the
   * intercom's own grammar and gates. There is no second approval path and
   * no button here that the Core does not already accept. */
  function command(payload) {
    return api("/api/command", { method: "POST", body: JSON.stringify(payload) });
  }

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  function ago(iso) {
    if (!iso) return "";
    const secs = (Date.now() - Date.parse(iso)) / 1000;
    if (!isFinite(secs)) return "";
    if (secs < 90) return "just now";
    if (secs < 3600) return Math.round(secs / 60) + "m ago";
    if (secs < 86400) return Math.round(secs / 3600) + "h ago";
    return Math.round(secs / 86400) + "d ago";
  }

  /* Local time, never UTC — he is not in UTC and neither is his day. */
  function clock(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const today = new Date();
    const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return d.toDateString() === today.toDateString()
      ? t : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + t;
  }

  /* ---- WHY it is not answering ------------------------------------------
   *
   * "Offline" is three different situations and they want three different
   * sentences. His phone has silently dropped off the tailnet before, and a
   * page that says "can't reach her" for that is telling him to go and look
   * at the PC that is working fine.
   *
   *   no signal        the device itself says it has no network
   *   off the tailnet  the network is up, but even a STATIC file from her
   *                    machine does not answer — so the phone is not on the
   *                    tailnet (or serve is down), and her PC is irrelevant
   *   asleep           static files answer, the API does not: the machine
   *                    is reachable and Thea is not running on it
   *
   * The probe is a static file with a unique query, so no service worker
   * can answer it from yesterday's cache and call that a connection.
   */
  async function diagnose() {
    if (navigator.onLine === false) return "no-signal";
    try {
      const res = await fetch("/interface/manifest.webmanifest?probe=" + Date.now(),
                              { cache: "no-store" });
      return res.ok ? "asleep" : "asleep";
    } catch {
      return "unreachable";
    }
  }

  /* ---- what he typed while she was unreachable ---------------------------
   *
   * It is queued on the device and sent when she answers again. Nothing is
   * ever quietly dropped: an ask that is still queued SAYS it is queued, and
   * one that could not be sent says that instead. */
  function outbox() {
    try { return JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]"); }
    catch { return []; }
  }
  function saveOutbox(rows) {
    try { localStorage.setItem(OUTBOX_KEY, JSON.stringify(rows.slice(-20))); }
    catch { /* private mode: it lives for this session in memory only */ }
  }
  function queueAsk(text) {
    const row = { id: "q" + Date.now() + Math.random().toString(36).slice(2, 6),
                  text: String(text || "").trim(), at: new Date().toISOString() };
    saveOutbox(outbox().concat([row]));
    return row;
  }
  function dropQueued(id) { saveOutbox(outbox().filter((r) => r.id !== id)); }

  /* A slow ask must not hold the screen: POST /api/voice returns at once
   * with a followup_id and the real sentence lands later. The GET is a
   * pure read, so a dropped response costs a retry rather than the answer;
   * the ack is sent only after the caller has SHOWN it.
   *
   * The wait has to outlast the Core's worst case, or the phone gives up on
   * an answer that is about to arrive. 300s matches the follow-up store's
   * own TTL. */
  const WAIT_MS = 300000;

  async function collect(id, onWait) {
    const started = Date.now();
    while (Date.now() - started < WAIT_MS) {
      await new Promise((r) => setTimeout(r, 1400));
      let slot;
      try { slot = await api("/api/voice/followup?id=" + encodeURIComponent(id)); }
      catch { continue; }
      if (slot.state === "PENDING") {
        if (onWait) onWait(Math.round((Date.now() - started) / 1000));
        continue;
      }
      return { id, say: slot.say || (slot.state === "FAILED"
        ? "I could not finish that one." : "That is done.") };
    }
    return { id: null, say: "Still going — it will land in what needs you." };
  }

  async function ack(id) {
    if (!id) return;
    try {
      await api("/api/voice/followup/ack", {
        method: "POST", body: JSON.stringify({ id }),
      });
    } catch { /* it stays collectable; the notification carries it anyway */ }
  }

  /* One ask, start to finish. `show(text)` is called as the answer
   * develops, so the page can render it as it likes. */
  async function ask(text, show, onThinking) {
    const said = String(text || "").trim();
    if (!said) return null;
    show("…");
    const res = await api("/api/voice", {
      method: "POST",
      body: JSON.stringify({ transcript: "thea " + said }),
    });
    show(res.say || res.detail || "Done.");
    if (!res.followup_id) return res;
    if (onThinking) onThinking(0);
    const answer = await collect(res.followup_id, onThinking);
    show(answer.say);
    ack(answer.id);
    return res;
  }

  /* iOS Safari has no SpeechRecognition. A mic that silently does nothing
   * is worse than no mic, so callers get an honest capability flag and can
   * fall back to typing rather than pretending. */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canListen = !!SR;

  function listen({ onStart, onEnd, onResult, onError }) {
    if (!SR) { if (onError) onError("unsupported"); return null; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onstart = () => onStart && onStart();
    rec.onend = () => onEnd && onEnd();
    rec.onerror = (e) => onError && onError(e.error);
    rec.onresult = (e) => onResult && onResult(e.results[0][0].transcript);
    try { rec.start(); } catch { if (onError) onError("start-failed"); }
    return rec;
  }

  /* SPEAKING BACK.
   *
   * Two rules, both about not being annoying. Only what he ASKED for out
   * loud is answered out loud — typing in a quiet room and having the phone
   * start talking is wrong, and no setting is needed to express "voice in,
   * voice out". And she speaks a REPLY, not a document: a 6,000-character
   * answer read aloud is a hostage situation, so it stops at a sentence
   * boundary near SPEAK_CHARS and says that the rest is on screen. The card
   * has the whole thing, so nothing is lost by not saying it.
   */
  const SPEAK_CHARS = 420;

  function spokenForm(text) {
    const body = String(text || "").trim();
    if (body.length <= SPEAK_CHARS) return body;
    const cut = body.slice(0, SPEAK_CHARS);
    const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "),
                          cut.lastIndexOf("! "), cut.lastIndexOf("\n"));
    const head = stop > SPEAK_CHARS * 0.4 ? cut.slice(0, stop + 1) : cut;
    return head.trim() + " The rest is on screen.";
  }

  /* iOS will not start speech outside a user gesture, and the gesture that
   * began this (tapping her) is several awaits in the past by the time an
   * answer exists. Priming inside the gesture with a silent utterance
   * unlocks the queue so the real one is allowed later. */
  function unlockSpeech() {
    try {
      if (!window.speechSynthesis) return;
      const u = new SpeechSynthesisUtterance(" ");
      u.volume = 0;
      speechSynthesis.speak(u);
    } catch { /* nothing is lost: the answer is on screen either way */ }
  }

  function hush() {
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch {}
  }

  function speaking() {
    try { return !!(window.speechSynthesis && speechSynthesis.speaking); }
    catch { return false; }
  }

  function speak(text) {
    try {
      const body = spokenForm(text);
      if (!window.speechSynthesis || !body) return;
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(body);
      u.rate = 1.0;
      speechSynthesis.speak(u);
    } catch { /* speaking is a bonus, never the delivery */ }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/interface/sw.js").catch(() => {});
  }

  // What the page uses, and nothing else. `collect`, `ack` and `spokenForm`
  // are `ask`'s own business; exporting them made three names nobody called,
  // which is how `speak()` sat here unwired for a whole release.
  return { api, command, ask, getToken, setToken, esc, ago, clock,
           diagnose, outbox, queueAsk, dropQueued, onHisPC,
           canListen, listen, speak, unlockSpeech, hush, speaking };
})();
