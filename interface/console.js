/* Everything in one spot — the page behind the front door.
 *
 * This is the sitting-down moment: what needs a decision, what she is
 * working on, what she has been doing. It deliberately does NOT ask
 * questions — phone.html owns talking — because two surfaces that both
 * half-do the same thing is how each ends up worse than one that commits.
 *
 * Transport, token and helpers come from thea.js so the two pages cannot
 * drift on what "unauthorized" means.
 */
(() => {
  "use strict";
  const T = window.Thea;
  const $ = (id) => document.getElementById(id);
  const esc = T.esc, ago = T.ago;
  let timer = null;

  const toastEl = $("toast");
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  function problem(text) {
    const el = $("problem");
    el.textContent = text || "";
    el.hidden = !text;
  }

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

  async function refresh(spin) {
    if (spin) $("refresh").classList.add("spin");
    try {
      const [status, approvals, notices, journal] = await Promise.all([
        T.api("/api/status"),
        T.api("/api/approvals").catch(() => []),
        T.api("/api/notifications").catch(() => []),
        T.api("/api/journal?limit=8").catch(() => []),
      ]);
      problem("");
      paintState(status);
      const pending = (Array.isArray(approvals) ? approvals : [])
        .filter((a) => a.state === "PENDING");
      const unread = (Array.isArray(notices) ? notices : [])
        .filter((n) => n.state !== "ACKNOWLEDGED").slice(0, 6);
      paintNeeds(pending, unread);
      paintGlance(status);
      paintWork(status.mission);
      paintRecent(Array.isArray(journal) ? journal : []);
      // An empty page should say it is empty, not look broken.
      $("allQuiet").hidden = !(
        !pending.length && !unread.length &&
        $("glanceSec").hidden && $("workSec").hidden);
    } catch (err) {
      $("orb").className = "orb";
      if (err.unauthorized) {
        $("state").textContent = "This device needs an access token";
        problem("Tap Access below and paste one minted with " +
                "`python -m aletheia.access mint`.");
      } else {
        $("state").textContent = "Can't reach the Core";
        problem("Is it running, and is this device on the tailnet?");
      }
    } finally {
      setTimeout(() => $("refresh").classList.remove("spin"), 700);
    }
  }


  document.addEventListener("click", async (e) => {
    const yes = e.target.closest("[data-approve]");
    const no = e.target.closest("[data-deny]");
    const seen = e.target.closest("[data-seen]");
    if (!yes && !no && !seen) return;
    e.target.disabled = true;
    try {
      if (seen) {
        await T.api("/api/notifications/ack", {
          method: "POST", body: JSON.stringify({ id: seen.dataset.seen }),
        });
      } else {
        const id = yes ? yes.dataset.approve : no.dataset.deny;
        await T.api("/api/command", {
          method: "POST",
          body: JSON.stringify({ kind: yes ? "approve" : "deny", id }),
        });
        toast(yes ? "Approved" : "Left pending");
      }
      refresh(false);
    } catch (err) {
      e.target.disabled = false;
      problem("That did not go through: " + err.message);
    }
  });

  $("refresh").addEventListener("click", () => refresh(true));

  $("haltBtn").addEventListener("click", async () => {
    if (!confirm("Stop everything Thea is doing?")) return;
    try {
      await T.api("/api/command", {
        method: "POST",
        body: JSON.stringify({ kind: "halt", reason: "from my phone" }),
      });
      toast("Halted");
      refresh(false);
    } catch (err) { problem("Could not halt: " + err.message); }
  });

  $("tokenBtn").addEventListener("click", () => {
    const next = prompt("Access token for this device (blank to clear):",
                        T.getToken());
    if (next === null) return;
    T.setToken(next);
    toast(T.getToken() ? "Token saved on this device" : "Token cleared");
    refresh(true);
  });

  // Poll while he is looking; stop in a pocket, so it does not wake the
  // radio every fifteen seconds for a page nobody is reading.
  function startPolling() {
    stopPolling();
    timer = setInterval(() => refresh(false), 15000);
  }
  function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling();
    else { refresh(false); startPolling(); }
  });

  refresh(true);
  startPolling();
})();
