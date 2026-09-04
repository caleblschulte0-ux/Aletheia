/* Everything — written fresh, not spliced.
 *
 * The previous file carried TWO `refresh()` definitions, the first one
 * dead and calling a bare `api()` that does not exist here. It worked only
 * because the later declaration wins, which is the kind of thing that
 * works right up until somebody reorders a file. Gone.
 *
 * Three rules this page follows now:
 *
 *  - Only what changes what he should DO. Metric tiles counting live tasks
 *    do not; they went.
 *  - Human words. "Thea is here", not "heard from 8s ago". Local times,
 *    never UTC. A heartbeat age is a diagnostic and lives in System.
 *  - Say what a button does. "Not now" LEAVES IT PENDING and sends
 *    nothing; refusing is a separate, quieter action that says Deny and
 *    means it. The old version labelled a deny "Not now" and then toasted
 *    "Left pending" — three different meanings for one tap.
 */
(() => {
  "use strict";
  const T = window.Thea;
  const $ = (id) => document.getElementById(id);

  let timer = null;
  // Approvals he tapped "Not now" on: hidden for this visit only. Nothing
  // is sent, so they are still pending on the Core and will be back.
  const deferred = new Set();

  const toastEl = $("toast");
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  function trouble(text) {
    $("trouble").textContent = text || "";
    $("trouble").hidden = !text;
  }

  /* Local time, never UTC — he is not in UTC and neither is his day. */
  function clock(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  // ---- painters --------------------------------------------------------
  function paintState(status) {
    const halted = status.halted;
    const alive = status.liveness && status.liveness.alive;
    const el = $("state");
    if (halted) {
      const why = (halted.reason || "").trim();
      el.innerHTML = "<b>Stopped</b>" + (why ? " · " + T.esc(why) : "");
    } else if (alive) {
      el.innerHTML = "<b>Thea is here</b>";
    } else {
      el.innerHTML = "<b>Not running</b> on your PC";
    }
    const btn = $("haltBtn");
    btn.textContent = halted ? "Let her start again" : "Stop everything";
    btn.classList.toggle("resume", !!halted);
    $("haltNote").textContent = halted
      ? "Nothing is running. She will not take new work until you resume."
      : "Ends anything running and refuses new work until you resume.";
  }

  function paintNeeds(approvals, notices) {
    const box = $("needs");
    const html = [];
    for (const a of approvals) {
      if (deferred.has(a.id)) continue;
      // WHAT he is being asked, in words. `requested_action` is a digest
      // for anything content-bound — "browser.interact:9f3c..." — and a
      // phone that asks you to approve a hash is asking you to guess.
      // The digest stays, small, because it is what he is approving.
      html.push(
        '<div class="ask">' +
          "<h3>" + T.esc(a.reason || a.requested_action || a.id) + "</h3>" +
          (a.reason ? '<p class="what">' + T.esc(a.requested_action || "") + "</p>" : "") +
          (a.consequence ? "<p>" + T.esc(a.consequence) + "</p>" : "") +
          '<div class="choices">' +
            '<button class="yes" data-approve="' + T.esc(a.id) + '">Approve</button>' +
            '<button class="later" data-later="' + T.esc(a.id) + '">Not now</button>' +
          "</div>" +
          '<button class="refuse" data-deny="' + T.esc(a.id) + '">Deny this</button>' +
        "</div>");
    }
    for (const n of notices) {
      html.push(
        '<div class="note">' +
          "<h3>" + T.esc(n.title) + "</h3>" +
          (n.body ? "<p>" + T.esc(n.body) + "</p>" : "") +
          '<div class="row">' +
            '<span class="when">' + T.esc(clock(n.created_at)) + "</span>" +
            '<button class="seen" data-seen="' + T.esc(n.id) + '">Got it</button>' +
          "</div>" +
        "</div>");
    }
    box.innerHTML = html.join("");
    $("needsSec").hidden = html.length === 0;
    return html.length;
  }

  function paintWork(mission) {
    const section = $("workSec");
    if (!mission || !mission.running) { section.hidden = true; return false; }
    const pct = mission.budget
      ? Math.round((mission.used / mission.budget) * 100) : 0;
    $("work").innerHTML =
      '<div class="work">' +
        "<h3>" + T.esc(mission.goal || mission.kind) + "</h3>" +
        "<p>" + T.esc(mission.used) + " of " + T.esc(mission.budget) +
          " done · until " + T.esc(clock(mission.expires)) + "</p>" +
        '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      "</div>";
    section.hidden = false;
    return true;
  }

  function paintLately(entries) {
    const rows = entries.slice(0, 5).filter((e) => e && (e.summary || e.subject));
    if (!rows.length) { $("latelySec").hidden = true; return false; }
    $("lately").innerHTML = rows.map((e) =>
      "<div><em>" + T.esc(clock(e.at)) + "</em><span>" +
      T.esc(e.summary || e.subject) + "</span></div>").join("");
    $("latelySec").hidden = false;
    return true;
  }

  // ---- load ------------------------------------------------------------
  async function refresh() {
    try {
      const [status, approvals, notices, journal] = await Promise.all([
        T.api("/api/status"),
        T.api("/api/approvals").catch(() => []),
        T.api("/api/notifications").catch(() => []),
        T.api("/api/journal?limit=8").catch(() => []),
      ]);
      trouble("");
      paintState(status);
      const pending = (Array.isArray(approvals) ? approvals : [])
        .filter((a) => a.state === "PENDING");
      const unread = (Array.isArray(notices) ? notices : [])
        .filter((n) => n.state !== "ACKNOWLEDGED").slice(0, 5);
      const needs = paintNeeds(pending, unread);
      const working = paintWork(status.mission);
      const lately = paintLately(Array.isArray(journal) ? journal : []);
      // An empty page should say it is empty rather than look broken.
      $("calm").hidden = !!(needs || working || lately);
      paintSystem(status);
    } catch (err) {
      if (err.unauthorized) {
        $("state").innerHTML = "<b>Not linked</b>";
        trouble("This phone hasn't been linked yet. Open System and add the "
                + "link code from your PC.");
      } else {
        $("state").innerHTML = "<b>Can't reach her</b>";
        trouble("Is the Core running, and is this phone on the tailnet?");
      }
      paintSystem(null);
    }
  }

  // ---- the System sheet: diagnostics, out of the way -------------------
  function paintSystem(status) {
    $("linkState").textContent = T.getToken()
      ? "Linked. The code is stored on this phone only."
      : "Not linked. On loopback it works without one; over Tailscale it "
        + "needs a code. On your PC run:  python -m aletheia.access mint "
        + "phone --scope full";
    $("tokenBtn").textContent = T.getToken() ? "Replace or remove the code"
                                             : "Link this phone";
    if (!status) { $("connDetail").textContent = "Not reachable right now."; return; }
    const age = status.liveness && status.liveness.heartbeat_age_s;
    $("connDetail").textContent = age == null
      ? "Connected. No heartbeat recorded yet."
      : `Connected. Last heartbeat ${Math.round(age)}s ago.`;
    const pulse = status.pulse || {};
    $("whereShe").textContent = pulse.generated_at
      ? `Fleet last looked at ${clock(pulse.generated_at)}.`
      : "No fleet reading yet.";
  }

  function openSheet(open) {
    $("sheet").toggleAttribute("open", open);
    $("sheet").setAttribute("aria-hidden", open ? "false" : "true");
  }
  $("sysBtn").addEventListener("click", () => openSheet(true));
  $("veil").addEventListener("click", () => openSheet(false));
  $("closeSheet").addEventListener("click", () => openSheet(false));

  $("tokenBtn").addEventListener("click", () => {
    const next = prompt("Link code for this phone (blank to remove):",
                        T.getToken());
    if (next === null) return;
    T.setToken(next);
    toast(T.getToken() ? "This phone is linked" : "Link removed");
    paintSystem(null);
    refresh();
  });

  // ---- decisions -------------------------------------------------------
  document.addEventListener("click", async (e) => {
    const yes = e.target.closest("[data-approve]");
    const later = e.target.closest("[data-later]");
    const no = e.target.closest("[data-deny]");
    const seen = e.target.closest("[data-seen]");
    if (!yes && !later && !no && !seen) return;

    if (later) {
      // Sends NOTHING. It stays pending on the Core, which is exactly what
      // the words say, and it comes back next time.
      deferred.add(later.dataset.later);
      toast("Left pending");
      refresh();
      return;
    }

    if (no && !confirm("Deny this? She will not do it.")) return;
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
        toast(yes ? "Approved" : "Denied");
      }
      refresh();
    } catch (err) {
      e.target.disabled = false;
      trouble("That didn't go through: " + err.message);
    }
  });

  $("haltBtn").addEventListener("click", async () => {
    const halting = !$("haltBtn").classList.contains("resume");
    if (halting && !confirm("Stop everything Thea is doing?")) return;
    try {
      await T.api("/api/command", {
        method: "POST",
        body: JSON.stringify(halting
          ? { kind: "halt", reason: "from my phone" }
          : { kind: "resume" }),
      });
      toast(halting ? "Stopped" : "Running again");
      refresh();
    } catch (err) { trouble("That didn't go through: " + err.message); }
  });

  // Poll while he is looking; nothing while it sits in a pocket.
  function start() { stop(); timer = setInterval(refresh, 15000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop(); else { refresh(); start(); }
  });

  refresh();
  start();
})();
