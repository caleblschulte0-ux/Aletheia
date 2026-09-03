/* Thea on a phone.
 *
 * Reachable over Tailscale, which is why every URL here is RELATIVE: the
 * page works the same on 127.0.0.1, on the tailnet name, and behind a
 * `tailscale cert` hostname, without a build step or a hard-coded host.
 *
 * Three things it does differently from the wall:
 *
 *  - It answers the question "does anything need me?" before anything
 *    else, and renders NOTHING when the answer is no. A phone that always
 *    has something on it is a phone you stop reading.
 *  - The ask bar is pinned under the thumb and is the primary action.
 *    Voice where the browser has it; typing everywhere else, because
 *    iOS Safari has no SpeechRecognition and a mic button that silently
 *    does nothing is worse than no mic button.
 *  - A slow ask does not hold the screen: POST /api/voice answers
 *    immediately with a followup_id, and the real sentence is collected
 *    from /api/voice/followup afterwards. That is the same delivery bug
 *    the wall had — acknowledged, then never delivered.
 *
 * Off-loopback the Core wants a bearer token (aletheia.access). It is
 * kept in localStorage on this device only and sent on every request;
 * a 401 asks for it rather than showing an empty page that looks broken.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "thea.token";
  let token = "";
  try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* private mode */ }

  let busy = false;
  let timer = null;

  // ---- transport ----------------------------------------------------
  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers);
    if (token) headers.Authorization = "Bearer " + token;
    if (options.body) headers["Content-Type"] = "application/json";
    const res = await fetch(path, Object.assign({}, options, { headers }));
    if (res.status === 401) {
      const err = new Error("unauthorized");
      err.unauthorized = true;
      throw err;
    }
    if (!res.ok) throw new Error(path + " → " + res.status);
    return res.json();
  }

  const toastEl = $("toast");
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  function say(text, isError) {
    const el = $("said");
    el.textContent = text || "";
    el.classList.toggle("err", !!isError);
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

  // ---- render -------------------------------------------------------
  function paintState(status) {
    const orb = $("orb");
    const halted = status && status.halted;
    const alive = status && status.liveness && status.liveness.alive;
    orb.className = "orb " + (halted ? "halted" : alive ? "live" : "cold");
    // Never colour alone: the sentence says it too.
    if (halted) {
      const why = (halted.reason || "").trim();
      $("state").textContent = "Halted" + (why ? " — " + why : "");
    } else if (alive) {
      const age = status.liveness.heartbeat_age_s;
      $("state").textContent = age == null ? "Running"
        : "Running · heard from " + Math.round(age) + "s ago";
    } else {
      $("state").textContent = "The Core is not running on your PC";
    }
  }

  function paintNeeds(approvals, notices) {
    const box = $("needs");
    const cards = [];
    for (const a of approvals) {
      cards.push(
        '<div class="card attention">' +
          "<p>" + esc(a.requested_action || a.id) + "</p>" +
          (a.reason ? '<p class="why">' + esc(a.reason) + "</p>" : "") +
          (a.consequence ? '<p class="why">' + esc(a.consequence) + "</p>" : "") +
          '<div class="choices">' +
            '<button class="yes" data-approve="' + esc(a.id) + '">Approve</button>' +
            '<button class="no" data-deny="' + esc(a.id) + '">Not now</button>' +
          "</div>" +
        "</div>");
    }
    for (const n of notices) {
      cards.push(
        '<div class="card">' +
          "<p>" + esc(n.title) + "</p>" +
          (n.body ? '<p class="why">' + esc(n.body) + "</p>" : "") +
          '<p class="when">' + esc(ago(n.created_at)) + "</p>" +
          '<div class="choices">' +
            '<button class="no" data-seen="' + esc(n.id) + '">Got it</button>' +
          "</div>" +
        "</div>");
    }
    box.innerHTML = cards.join("");
    $("needsSec").hidden = cards.length === 0;
  }

  function paintWork(mission) {
    const section = $("workSec");
    if (!mission || !mission.running) { section.hidden = true; return; }
    const pct = mission.budget ? Math.round((mission.used / mission.budget) * 100) : 0;
    $("work").innerHTML =
      '<div class="card">' +
        "<p>" + esc(mission.goal || mission.kind) + "</p>" +
        '<p class="why">' + esc(mission.used) + " of " + esc(mission.budget) +
          " done · until " + esc((mission.expires || "").slice(11, 16)) + " UTC</p>" +
        '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      "</div>";
    section.hidden = false;
  }

  function paintGlance(status) {
    const live = status.tasks ? status.tasks.live : 0;
    const alerts = status.pulse ? (status.pulse.alerts || 0) : 0;
    const tiles = [];
    if (live) tiles.push(["" + live, live === 1 ? "task running" : "tasks running"]);
    if (alerts) tiles.push(["" + alerts, alerts === 1 ? "fleet alert" : "fleet alerts"]);
    $("tiles").innerHTML = tiles
      .map((t) => '<div class="tile"><b>' + esc(t[0]) + "</b><span>" + esc(t[1]) + "</span></div>")
      .join("");
    $("glanceSec").hidden = tiles.length === 0;
  }

  function paintRecent(entries) {
    if (!entries.length) { $("recentSec").hidden = true; return; }
    $("recent").innerHTML = entries.slice(0, 6).map((e) =>
      '<div class="line"><em>' + esc(ago(e.at)) + "</em><span>" +
      esc(e.summary || e.subject || "") + "</span></div>").join("");
    $("recentSec").hidden = false;
  }

  // ---- load ---------------------------------------------------------
  async function refresh(spin) {
    if (spin) $("refresh").classList.add("spin");
    try {
      const [status, approvals, notices, journal] = await Promise.all([
        api("/api/status"),
        api("/api/approvals").catch(() => []),
        api("/api/notifications").catch(() => []),
        api("/api/journal?limit=8").catch(() => []),
      ]);
      paintState(status);
      const pending = (Array.isArray(approvals) ? approvals : approvals.approvals || [])
        .filter((a) => a.state === "PENDING");
      const unread = (Array.isArray(notices) ? notices : notices.notifications || [])
        .filter((n) => n.state !== "ACKNOWLEDGED").slice(0, 6);
      paintNeeds(pending, unread);
      paintGlance(status);
      paintWork(status.mission);
      paintRecent(Array.isArray(journal) ? journal : journal.entries || []);
      if (!pending.length && !unread.length) say("");
    } catch (err) {
      if (err.unauthorized) {
        $("state").textContent = "This device needs an access token";
        say("Tap Access below and paste a token minted with " +
            "`python -m aletheia.access mint`.", true);
      } else {
        $("orb").className = "orb cold";
        $("state").textContent = "Can't reach the Core";
        say("Is it running, and is this device on the tailnet?", true);
      }
    } finally {
      setTimeout(() => $("refresh").classList.remove("spin"), 700);
    }
  }

  // ---- asking -------------------------------------------------------
  async function collect(id) {
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1400));
      let slot;
      try { slot = await api("/api/voice/followup?id=" + encodeURIComponent(id)); }
      catch { continue; }                       // a dropped beat is not an answer
      if (slot.state === "PENDING") continue;
      return { id, say: slot.say || (slot.state === "FAILED"
        ? "I could not finish that one." : "That is done.") };
    }
    return { id: null, say: "Still going — it will land in your notifications." };
  }

  async function ask(text) {
    if (busy || !text.trim()) return;
    busy = true;
    $("go").disabled = true;
    say("…");
    try {
      const res = await api("/api/voice", {
        method: "POST",
        body: JSON.stringify({ transcript: "thea " + text.trim() }),
      });
      say(res.say || res.detail || "Done.");
      if (res.followup_id) {
        const answer = await collect(res.followup_id);
        say(answer.say);
        if (answer.id) {
          // Only after it has been SEEN: the GET is a pure read, so a
          // dropped response costs a retry rather than the answer.
          api("/api/voice/followup/ack", {
            method: "POST", body: JSON.stringify({ id: answer.id }),
          }).catch(() => {});
        }
      }
      $("q").value = "";
      refresh(false);
    } catch (err) {
      say(err.unauthorized ? "This device is not authorized yet."
                           : "That did not go through: " + err.message, true);
    } finally {
      busy = false;
      $("go").disabled = false;
    }
  }

  // ---- voice, where the browser actually has it ----------------------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = $("mic");
  if (!SR) {
    // iOS Safari has no SpeechRecognition. A mic button that silently does
    // nothing is worse than no mic button, so it says why when tapped.
    mic.disabled = true;
    mic.title = "This browser has no speech recognition";
    mic.addEventListener("click", () =>
      toast("This browser can't listen — type it instead"));
  } else {
    let listening = false;
    mic.addEventListener("click", () => {
      if (listening) return;
      const rec = new SR();
      rec.lang = "en-US";
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onstart = () => { listening = true; mic.classList.add("on"); say("Listening…"); };
      rec.onerror = (e) => {
        listening = false; mic.classList.remove("on");
        say(e.error === "not-allowed"
          ? "Microphone is blocked for this site — allow it in Settings."
          : "Didn't catch that.", true);
      };
      rec.onend = () => { listening = false; mic.classList.remove("on"); };
      rec.onresult = (e) => {
        const said = e.results[0][0].transcript;
        $("q").value = said;
        ask(said);
      };
      try { rec.start(); } catch { say("Could not open the microphone.", true); }
    });
  }

  // ---- controls ------------------------------------------------------
  $("go").addEventListener("click", () => ask($("q").value));
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); ask($("q").value); }
  });
  $("refresh").addEventListener("click", () => refresh(true));

  document.addEventListener("click", async (e) => {
    const yes = e.target.closest("[data-approve]");
    const no = e.target.closest("[data-deny]");
    const seen = e.target.closest("[data-seen]");
    if (!yes && !no && !seen) return;
    e.target.disabled = true;
    try {
      if (seen) {
        await api("/api/notifications/ack", {
          method: "POST",
          body: JSON.stringify({ id: seen.dataset.seen }),
        });
      } else {
        const id = yes ? yes.dataset.approve : no.dataset.deny;
        await api("/api/command", {
          method: "POST",
          body: JSON.stringify({ kind: yes ? "approve" : "deny", id }),
        });
        toast(yes ? "Approved" : "Left pending");
      }
      refresh(false);
    } catch (err) {
      e.target.disabled = false;
      say("That did not go through: " + err.message, true);
    }
  });

  $("haltBtn").addEventListener("click", async () => {
    if (!confirm("Stop everything Thea is doing?")) return;
    try {
      await api("/api/command", {
        method: "POST",
        body: JSON.stringify({ kind: "halt", reason: "from my phone" }),
      });
      toast("Halted");
      refresh(false);
    } catch (err) { say("Could not halt: " + err.message, true); }
  });

  $("tokenBtn").addEventListener("click", () => {
    const next = prompt("Access token for this device (blank to clear):", token);
    if (next === null) return;
    token = next.trim();
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode: it lasts this session only */ }
    toast(token ? "Token saved on this device" : "Token cleared");
    refresh(true);
  });

  // Poll while looking at it; stop when backgrounded, so it does not sit
  // in a pocket waking the radio every ten seconds.
  function startPolling() {
    stopPolling();
    timer = setInterval(() => { if (!busy) refresh(false); }, 15000);
  }
  function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling();
    else { refresh(false); startPolling(); }
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/interface/sw.js").catch(() => {});
  }

  refresh(true);
  startPolling();
})();
