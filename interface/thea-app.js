/* The one page, painted.
 *
 * Four questions, in this order, and nothing else above the fold:
 *
 *   what is she doing   ·   ask her   ·   what needs me   ·   what she's done
 *
 * Two rules it follows everywhere:
 *
 * - NO DEVELOPER WORDS. No capability ids, kind names, model names, run ids,
 *   branches, hashes or JSON in normal use. Where an exact detail genuinely
 *   helps — what an approval will actually do, the record behind a line — it
 *   is one tap away and written in the words the collector wrote. Everything
 *   that is really for a developer is in the drawer at the bottom.
 * - NO SMARTS HERE. Every sentence on this page was written by
 *   mission_control / current_state / speech on the far side. The page maps a
 *   handful of state WORDS to plain English and lays things out; it never
 *   decides what is true.
 */
(() => {
  "use strict";
  const T = window.Thea;
  const $ = (id) => document.getElementById(id);

  // The collectors' state vocabulary, said the way a person says it. This is
  // presentation, not derivation: the sentence beside it is still theirs.
  const STATE_WORD = {
    IDLE: "Resting", LISTENING: "Listening", LOOKING: "Looking",
    THINKING: "Thinking", ACTING: "Working", WAITING: "Waiting",
    "NEEDS YOU": "Needs you", BLOCKED: "Stuck", HALTED: "Stopped",
  };
  const JOB_WORD = {
    "NEEDS YOU": "needs you", BLOCKED: "stuck", RUNNING: "working",
    WAITING: "waiting", OPEN: "not started yet", PROPOSED: "waiting for your yes",
    STOPPED: "stopped", DONE: "done",
  };
  const JOB_CLASS = {
    "NEEDS YOU": "needs", BLOCKED: "stuck", RUNNING: "working",
  };
  // How much of a long list is on screen before he asks for the rest. His
  // standard is that he opens her, understands the four things in ten
  // seconds, and forgets the machinery — which a page seven screens tall
  // cannot do, however honest every line on it is.
  const A_FEW = 3;
  //: How many decisions are on screen before he asks for the rest — a
  //: budget for the whole section, not per group, because his pending
  //: approvals fall into one big group and a long tail of ones and twos.
  const MOST_ROWS = 5;
  // The one command he will ever type because of this page. It is a single
  // literal so a test can lift it out and check it actually parses: the
  // previous version printed `aletheia.access mint`, which had started
  // exiting with "the following arguments are required: label", and a dead
  // end printed in a confident voice is worse than no instruction.
  const MINT = "python -m aletheia.access mint phone --scope full";

  let timer = null;
  let lastMission = null;
  let busy = false, listening = false, rec = null;
  let haltedNow = false;
  let failures = 0;
  // Approvals he tapped "Not now" on: hidden for this visit only. Nothing is
  // sent, so they are still pending on the Core and will be back.
  const deferred = new Set();
  const expanded = new Set();
  // Decision rows whose "what exactly?" he has opened, kept across a repaint
  // so a refresh under his thumb does not close what he is reading.
  const opened = new Set();

  // ---- small helpers ----------------------------------------------------
  const toastEl = $("toast");
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2400);
  }

  function facts(pairs) {
    const rows = pairs.filter((p) => p[1] !== undefined && p[1] !== null && p[1] !== "");
    if (!rows.length) return "";
    return '<dl class="facts">' + rows.map(
      (p) => "<dt>" + T.esc(p[0]) + "</dt><dd>" + T.esc(p[1]) + "</dd>").join("") + "</dl>";
  }

  function peek(label, id, kind) {
    return '<details class="peek" data-peek data-kind="' + T.esc(kind) +
      '" data-id="' + T.esc(id) + '"><summary>' + T.esc(label) +
      '</summary><div class="body">reading it…</div></details>';
  }

  // ---- the rail: is she here, and if not, why ---------------------------
  function paintWhere(kind, detail) {
    const el = $("where");
    el.className = "where" + (kind === "here" ? "" :
      kind === "needs" ? " waiting" : " trouble");
    el.innerHTML = "<b>" + T.esc(detail.head) + "</b>" +
      (detail.tail ? " · " + T.esc(detail.tail) : "");
  }

  const UNREACHABLE = {
    "no-signal": { head: "You're offline", tail: "this phone has no connection" },
    "unreachable-phone": { head: "Can't reach her",
      tail: "this phone may have dropped off Tailscale" },
    "unreachable-pc": { head: "Not running", tail: "Thea isn't running on this PC" },
    "asleep": { head: "Can't reach her", tail: "her PC is asleep, or Thea isn't running on it" },
    "not-linked": { head: "Not linked", tail: "this device needs a link code" },
  };

  // ---- what she is doing -------------------------------------------------
  function paintNow(m) {
    const h = m.header || {};
    const word = STATE_WORD[h.state] || "";
    $("doing").textContent = h.doing || "";
    $("next").textContent = h.next ? "Next: " + h.next : "";
    $("today").textContent = (h.today && h.today.said) || "";
    $("banner").textContent = h.banner || "";
    $("banner").hidden = !h.banner;
    return word;
  }

  // ---- what needs him ----------------------------------------------------
  /* One row of choices, and the only one. Yes, leave it, no — each bound to
   * its own approval id, each going through /api/command exactly as the
   * Core has always taken it. */
  function decisionButtons(id) {
    return '<div class="acts">' +
      '<button class="yes" data-approve="' + T.esc(id) + '">Approve</button>' +
      '<button class="later" data-later="' + T.esc(id) + '">Not now</button>' +
      '<button class="no" data-deny="' + T.esc(id) + '">No</button>' +
      "</div>";
  }

  /* A DECISION AS A ROW, which is what thirty-eight of them have to be.
   *
   * Live on his machine there were thirty-eight pending applications, each
   * rendered as a card with the same first line and three buttons: about
   * nine thousand pixels of wall where a decision should have been. They
   * share a consequence and differ only in WHICH one, so the shared half is
   * said once, above, and each row carries the half that is its own.
   *
   * There is deliberately no bulk control. Every one of these is bound to
   * its own hash and stays its own yes; what changed is how much of the
   * screen it takes to say no to it. */
  function decisionRow(a, lead) {
    const said = a.label || a.consequence || "She needs your yes on something";
    const which = a.about || (lead ? "" : said);
    return '<div class="row-ask">' +
      '<div class="what">' + T.esc(which || said) + "</div>" +
      '<div class="meta">' + T.esc(T.clock(a.requested_at || a.created_at)) +
        ' · <button class="link" data-open="' + T.esc(a.id) + '">what exactly?</button></div>' +
      decisionButtons(a.id) +
      (opened.has(a.id)
        ? '<div class="peeked">' + facts([
            ["It will", a.consequence || said],
            ["Can it be undone", a.reversible === undefined ? ""
              : (a.reversible ? "yes" : "no")],
            ["Exactly", a.requested_action]]) + "</div>"
        : "") +
      "</div>";
  }

  /* A mission's own blocking need, as a row for the same reason. These
   * sentences run to two hundred characters ("Stopped at a CAPTCHA on …:
   * waiting for you. A human check is in the way at …"), so the first two
   * lines are on screen and the rest is a tap: what he needs to know is
   * WHICH one and that it is his, and he gets the whole thing by touching
   * it. */
  function missionNeed(n) {
    return '<div class="row-ask">' +
      '<div class="what clamp" data-unclamp>' + T.esc(n.said || n.title) + "</div>" +
      (n.approval ? decisionButtons(n.approval) : "") +
      (n.receipt ? peek("What led to this?", n.receipt.id, n.receipt.kind) : "") +
      "</div>";
  }

  function noticeCard(n) {
    const heading = n.says || n.title || "";
    const under = n.body && n.body !== heading ? n.body : "";
    // The body is CLAMPED, not cut: one of these is a digest listing every
    // question on every form, twelve lines of it, and three of them made
    // the page longer than everything he can actually act on. Tapping it
    // opens the whole thing; nothing is hidden, it just is not shouted.
    return '<div class="note"><h3>' + T.esc(heading) + "</h3>" +
      (under ? '<p class="clamp" data-unclamp>' + T.esc(under) + "</p>" : "") +
      '<div class="row"><span class="when">' + T.esc(T.clock(n.created_at)) + "</span>" +
      '<button class="seen" data-seen="' + T.esc(n.id) + '">Got it</button></div></div>';
  }

  /** Every decision is a ROW, and rows that share one consequence say the
   *  shared half once above them.
   *
   *  The first try kept a full card for any group smaller than three, which
   *  looked right on the fixture and was wrong on his machine: his
   *  thirty-eight pending applications fall into one group of twenty-two
   *  and a long tail of ones and twos, so most of them came back as cards
   *  and the page was still eight screens. The BUDGET is what has to be
   *  bounded, not the shape of each group — so the section shows a handful
   *  of rows however they are grouped, and the rest is one tap.
   *
   *  There is deliberately no bulk control anywhere in here. */
  function decisionsHTML(approvals) {
    const groups = new Map();
    for (const a of approvals) {
      const key = a.label || a.consequence || "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    }
    const open = expanded.has("needs");
    let budget = open ? 60 : MOST_ROWS;
    const out = [];
    let hidden = 0;
    for (const [key, rows] of groups) {
      const take = rows.slice(0, Math.max(0, budget));
      hidden += rows.length - take.length;
      budget -= take.length;
      if (!take.length) continue;
      const many = rows.length > 1;
      out.push('<div class="group">' +
        (many ? '<p class="lead">' +
          T.esc(rows.length + " are waiting on the same yes — " + key) + "</p>" : "") +
        take.map((a) => decisionRow(a, many)).join("") + "</div>");
    }
    return { html: out.join(""), hidden };
  }

  /** Rows he must DECIDE, then rows he should merely SEE. One place, as the
   *  brief asks, but not one undifferentiated pile: counting 105 unread
   *  notices as "needing him" alongside 38 irreversible decisions makes the
   *  number meaningless and teaches him to ignore it. The count in the rail
   *  is decisions. Returns how many of those there are. */
  function paintNeeds(m, approvals, notices) {
    const live = approvals.filter((a) => !deferred.has(a.id));
    const needs = ((m && m.needs_you) || []).filter((n) => n.kind === "mission");
    const decisions = decisionsHTML(live);
    const open = expanded.has("needs");
    const shownNeeds = open ? needs : needs.slice(0, A_FEW);
    const rest = decisions.hidden + (needs.length - shownNeeds.length);
    const count = live.length + needs.length;
    // Worth seeing is a hundred and five deep and none of it is a decision.
    // One line, folded, newest first when he opens it.
    const worth = notices.length
      ? '<details class="fold"><summary>' +
        T.esc(notices.length === 1 ? "1 thing worth seeing"
                                   : notices.length + " things worth seeing") +
        "</summary>" + notices.slice(0, 25).map(noticeCard).join("") +
        (notices.length > 25
          ? '<p class="calm">and ' + (notices.length - 25) + " older ones</p>" : "") +
        "</details>"
      : "";
    $("needs").innerHTML = (count
        ? decisions.html +
          (shownNeeds.length
            ? '<div class="group">' + shownNeeds.map(missionNeed).join("") + "</div>" : "") +
          (rest ? '<button class="more" data-expand="needs">Show the other ' +
                  rest + "</button>"
                : (open && count > MOST_ROWS
                    ? '<button class="more" data-expand="needs">Show fewer</button>' : ""))
        : '<div class="calm">Nothing needs a decision from you.</div>') + worth;
    return count;
  }

  // ---- what she is working on -------------------------------------------
  /* `said` is what this list has already said. Nineteen browser goals end
   * with the identical sentence "It carries on from here when you do your
   * part; nothing already done is redone." — true once, wallpaper nineteen
   * times. Only EXACT repeats are dropped, and the first one always shows,
   * which is how prose works when it is read top to bottom. */
  function jobCard(c, said) {
    const p = c.progress;
    const bar = p && p.total
      ? '<div class="bar" title="' + T.esc(p.done + " of " + p.total + " " +
          (p.unit || "")) + '"><i style="width:' +
        Math.max(2, Math.round((p.done / p.total) * 100)) + '%"></i></div>'
      : "";
    const receipt = (c.receipts || [])[0];
    const once = (text) => {
      if (!text || said.has(text)) return "";
      said.add(text);
      return text;
    };
    // `stuck` already contains `step` ("Waiting on you: " + the step + why),
    // so printing both says the same thing twice in two type sizes.
    const step = c.stuck && c.step && c.stuck.indexOf(c.step) >= 0 ? "" : c.step;
    return '<div class="job ' + (JOB_CLASS[c.status] || "") + '">' +
      '<div class="top"><h3>' + T.esc(c.title) + "</h3>" +
      '<span class="tag">' + T.esc(JOB_WORD[c.status] || "") + "</span></div>" +
      (c.goal && c.goal !== c.title ? "<p>" + T.esc(c.goal) + "</p>" : "") +
      (step ? "<p>" + T.esc(step) + "</p>" : "") +
      (c.stuck ? '<p class="why clamp" data-unclamp>' + T.esc(c.stuck) + "</p>" : "") +
      (once(c.next) ? "<p>" + T.esc(c.next) + "</p>" : "") + bar +
      (receipt && receipt.id ? peek("How did it get here?", receipt.id, receipt.kind) : "") +
      "</div>";
  }

  function paintWork(m) {
    const all = m.missions || [];
    const open = expanded.has("work");
    const take = open ? all : all.slice(0, A_FEW);
    const said = new Set();
    const rows = take.map((c) => jobCard(c, said));
    $("work").innerHTML = all.length
      ? rows.join("") + (all.length > take.length
          ? '<button class="more" data-expand="work">Show the other ' +
            (all.length - take.length) + "</button>"
          : (open && all.length > A_FEW
              ? '<button class="more" data-expand="work">Show fewer</button>' : ""))
      : '<div class="calm">Nothing is in flight right now.</div>';
  }

  // ---- what she has done -------------------------------------------------
  function paintDone(m) {
    const rows = (m.ribbon || []).filter((r) => r && r.said);
    const open = expanded.has("done");
    const shown = open ? rows.slice(0, 40) : rows.slice(0, A_FEW);
    $("done").innerHTML = rows.length
      ? shown.map((r) =>
          '<div class="li ' + (r.tone === "alert" ? "alert" : "") + '"><em>' +
          T.esc(T.clock(r.at)) + "</em><span>" + T.esc(r.said) +
          (r.receipt && r.receipt.id ? peek("the record", r.receipt.id, r.receipt.kind) : "") +
          "</span></div>").join("") +
        (rows.length > shown.length
          ? '<button class="more" data-expand="done">Show more</button>'
          : (open ? '<button class="more" data-expand="done">Show fewer</button>' : ""))
      : '<div class="calm">Nothing recorded yet today.</div>';
  }

  // ---- the loop ----------------------------------------------------------
  async function refresh() {
    let m = null, status = null;
    // A request that HANGS never rejects, so a page that only says
    // "reconnecting" in its catch sits there showing this morning's state
    // as though it were now. The clock is the honest signal: if she has not
    // answered in five seconds, say so.
    const slow = setTimeout(() => paintWhere("trouble", {
      head: "Reconnecting…",
      tail: lastMission ? "last heard from her " + T.ago(lastMission.as_of) : "",
    }), 5000);
    try {
      [m, status] = await Promise.all([T.api("/api/mission"), T.api("/api/status")]);
      clearTimeout(slow);
    } catch (err) {
      clearTimeout(slow);
      failures++;
      if (err.unauthorized) {
        paintWhere("trouble", UNREACHABLE["not-linked"]);
        $("doing").textContent = "This device isn't linked to her yet.";
        $("next").textContent = "Open the drawer at the bottom and paste the link code from your PC.";
        return;
      }
      paintWhere("trouble", { head: "Reconnecting…",
        tail: lastMission ? "last heard from her " + T.ago(lastMission.as_of) : "" });
      const why = await T.diagnose();
      const said = UNREACHABLE[
        why === "no-signal" ? "no-signal"
        : why === "unreachable" ? (T.onHisPC() ? "unreachable-pc" : "unreachable-phone")
        : "asleep"];
      paintWhere("trouble", said);
      // The rail is a summary and it ellipsises; the REASON has to be
      // somewhere it can be read whole, or the half of the sentence that
      // says whose fault it is gets cut off on a phone.
      $("banner").textContent = said.head + " — " + said.tail + "." +
        (lastMission ? " Nothing below is current; last heard from her " +
          T.ago(lastMission.as_of) + "." : "");
      $("banner").hidden = false;
      return;
    }
    failures = 0;
    lastMission = m;
    const word = paintNow(m);
    haltedNow = !!(status && status.halted);
    $("haltBtn").textContent = haltedNow ? "Let her start again" : "Stop everything";
    $("haltBtn").classList.toggle("resume", haltedNow);
    $("haltNote").textContent = haltedNow
      ? "Nothing is running. She will not take new work until you start her again."
      : "Ends anything running and refuses new work until you start her again.";

    let approvals = [], notices = [];
    try { approvals = (await T.api("/api/approvals")).filter((a) => a.state === "PENDING"); }
    catch { /* the rest of the page is still true */ }
    try { notices = await T.api("/api/notifications?state=UNREAD"); }
    catch { /* likewise */ }

    const needs = paintNeeds(m, approvals, notices);
    paintWork(m);
    paintDone(m);
    paintWhere(haltedNow ? "trouble" : needs ? "needs" : "here", {
      head: haltedNow ? "Stopped" : word || "Here",
      tail: haltedNow ? ((status.halted && status.halted.reason) || "")
        : needs ? needs + (needs === 1 ? " thing needs you" : " things need you") : "",
    });
    paintDrawer(m, status);
    flushOutbox();
  }

  // ---- asking ------------------------------------------------------------
  function turn(who, text, cls) {
    const div = document.createElement("div");
    div.className = "turn " + who + (cls ? " " + cls : "");
    div.textContent = text;
    $("thread").appendChild(div);
    $("thread").scrollTop = $("thread").scrollHeight;
    return div;
  }

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
    if (speakBack) { T.unlockSpeech(); T.speak("I'll read answers out loud."); }
    else T.hush();
  });

  async function send(text, spoken) {
    const said = String(text || "").trim();
    if (!said || busy) return;
    busy = true;
    $("send").disabled = true;
    turn("you", said);
    $("q").value = "";
    const reply = turn("her", "…");
    $("hint").textContent = "thinking…";
    try {
      let last = "";
      await T.ask(said, (t) => { last = t; reply.textContent = t; },
                  (secs) => { $("hint").textContent = secs > 20
                    ? "thinking · " + secs + "s" : "thinking…"; });
      $("hint").textContent = "";
      if (spoken || speakBack) T.speak(last);
      refresh();
    } catch (err) {
      $("hint").textContent = "";
      if (err.unauthorized) {
        reply.textContent = "This device isn't linked to her yet.";
      } else {
        // Nothing is ever quietly dropped: it is queued on this device and
        // sent the moment she answers again.
        const row = T.queueAsk(said);
        reply.remove();
        turn("her", "She's not reachable. I've kept this and will send it when she is.",
             "queued").dataset.queued = row.id;
      }
    } finally {
      busy = false;
      $("send").disabled = false;
    }
  }

  let flushing = false;
  async function flushOutbox() {
    const rows = T.outbox();
    if (!rows.length || flushing || busy) return;
    flushing = true;
    try {
      for (const row of rows) {
        const box = document.querySelector('[data-queued="' + row.id + '"]');
        try {
          const reply = box || turn("her", "…");
          if (box) box.classList.remove("queued");
          await T.ask(row.text, (t) => { reply.textContent = t; });
          T.dropQueued(row.id);
        } catch {
          return;                 // still unreachable; it stays queued
        }
      }
    } finally { flushing = false; }
  }

  $("askForm").addEventListener("submit", (e) => { e.preventDefault(); send($("q").value); });
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("q").value); }
  });
  $("q").addEventListener("input", () => {
    $("q").style.height = "auto";
    $("q").style.height = Math.min($("q").scrollHeight, 112) + "px";
  });

  $("micBtn").addEventListener("click", () => {
    if (T.speaking()) { T.hush(); if (busy) return; }
    if (busy) return;
    if (listening) { try { rec && rec.stop(); } catch {} return; }
    // Inside the gesture, while iOS still allows it: by the time an answer
    // exists this tap is several awaits in the past and speech is refused.
    T.unlockSpeech();
    if (!T.canListen) {
      // iOS Safari has no SpeechRecognition. The button still means "I want
      // to talk to you" — it hands him the keyboard, where the phone's own
      // dictation key is one tap away — and the hint says so rather than
      // letting him find out by being lied to.
      $("hint").textContent = "This browser can't listen — dictate with the keyboard's microphone.";
      $("q").focus();
      return;
    }
    rec = T.listen({
      onStart: () => { listening = true; $("hint").textContent = "listening — tap again to stop"; },
      onEnd: () => { listening = false; if (!busy) $("hint").textContent = ""; },
      onResult: (heard) => send(heard, true),
      onError: (why) => {
        listening = false;
        $("hint").textContent = why === "not-allowed"
          ? "The microphone is blocked for this page — allow it in Settings."
          : "I didn't catch that.";
      },
    });
  });

  // ---- decisions ---------------------------------------------------------
  document.addEventListener("click", async (e) => {
    const expand = e.target.closest("[data-expand]");
    if (expand) {
      const key = expand.dataset.expand;
      if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
      if (lastMission) refresh();
      return;
    }
    const exact = e.target.closest("[data-open]");
    if (exact) {
      const id = exact.dataset.open;
      if (opened.has(id)) opened.delete(id); else opened.add(id);
      refresh();
      return;
    }
    const clamped = e.target.closest("[data-unclamp]");
    if (clamped) { clamped.classList.toggle("clamp"); return; }
    const yes = e.target.closest("[data-approve]");
    const later = e.target.closest("[data-later]");
    const no = e.target.closest("[data-deny]");
    const seen = e.target.closest("[data-seen]");
    if (!yes && !later && !no && !seen) return;
    if (later) {
      // Sends NOTHING. It stays pending on the Core, which is exactly what
      // the words say, and it comes back next time.
      deferred.add(later.dataset.later);
      toast("Left for later");
      refresh();
      return;
    }
    if (no && !confirm("Say no to this? She will not do it.")) return;
    e.target.disabled = true;
    try {
      if (seen) {
        await T.api("/api/notifications/ack", {
          method: "POST", body: JSON.stringify({ id: seen.dataset.seen }) });
      } else {
        const id = yes ? yes.dataset.approve : no.dataset.deny;
        await T.command(yes ? { kind: "approve", id }
                            : { kind: "deny", id, because: "said no from the Thea page" });
        toast(yes ? "Approved" : "Refused");
      }
      refresh();
    } catch (err) {
      e.target.disabled = false;
      toast("That didn't go through.");
    }
  });

  $("haltBtn").addEventListener("click", async () => {
    if (!haltedNow && !confirm("Stop everything Thea is doing?")) return;
    try {
      await T.command(haltedNow ? { kind: "resume" }
                                : { kind: "halt", reason: "he pressed stop on the Thea page" });
      toast(haltedNow ? "Running again" : "Stopped");
      refresh();
    } catch { toast("That didn't go through."); }
  });

  // ---- receipts, one tap away, in her words ------------------------------
  const RECEIPT_WORDS = {
    session: (r) => [["Asked", r.question], ["Answered", r.answer],
                     ["How it ended", String(r.outcome || "").replace(/_/g, " ")],
                     ["Took", r.duration_s ? r.duration_s + " seconds" : ""],
                     ["Saved", T.clock(r.saved_at)]],
    journal: (r) => [["When", T.clock(r.ts)], ["What", r.text]],
    plan: (r) => [["Project", r.title], ["Goal", r.goal],
                  ["Where it is up to", r.state], ["Started", T.clock(r.created)]],
    task: (r) => [["What", r.description], ["Where it is up to", r.status],
                  ["Last moved", T.clock(r.updated_at)], ["Due", r.deadline],
                  ["Result", r.result], ["What went wrong", r.error]],
    mission: (r) => [["Goal", r.goal], ["Where it is up to", r.state],
                     ["Work used", (r.actions_used || 0) + " of " + (r.max_actions || 0)],
                     ["Ended", T.clock(r.ended_at)], ["Because", r.ended_because]],
    application: (r) => [["Where it is up to", r.state], ["Filled in", T.clock(r.staged_at)],
                         ["Sent", T.clock(r.submitted_at)],
                         ["Why it stopped", (r._explained || {}).why_not_sent]],
  };

  async function openPeek(el) {
    const body = el.querySelector(".body");
    if (!body || body.dataset.done) return;
    body.dataset.done = "1";
    try {
      const r = await T.api("/api/mission/receipt?kind=" +
        encodeURIComponent(el.dataset.kind) + "&id=" + encodeURIComponent(el.dataset.id));
      const record = r.record || {};
      const pick = RECEIPT_WORDS[r.kind];
      body.innerHTML = (pick ? facts(pick(record)) : "") +
        '<details class="raw"><summary>Everything on the record</summary><pre>' +
        T.esc(JSON.stringify(record, null, 2)) + "</pre></details>";
    } catch {
      body.textContent = "There is no record behind this one.";
    }
  }
  document.addEventListener("toggle", (e) => {
    const el = e.target;
    if (el.matches && el.matches("[data-peek]") && el.open) openPeek(el);
  }, true);

  // ---- the drawer: the machine's own words -------------------------------
  let KINDS = {};
  function renderArgs() {
    const [req, opt] = KINDS[$("kind").value] || [[], []];
    $("args").innerHTML =
      req.map((a) => '<label for="arg-' + T.esc(a) + '">' + T.esc(a) +
        '</label><input id="arg-' + T.esc(a) + '" name="' + T.esc(a) + '" required>').join("") +
      opt.map((a) => '<label for="arg-' + T.esc(a) + '">' + T.esc(a) +
        ' (optional)</label><input id="arg-' + T.esc(a) + '" name="' + T.esc(a) + '">').join("");
  }

  function paintDrawer(m, status) {
    const code = (m && m.code) || {};
    $("codeLine").textContent = code.readable === false ? "not readable"
      : [code.branch, code.commit, code.subject].filter(Boolean).join(" · ") +
        (code.running_old_code ? " · newer code is on disk than this process is running" : "");
    $("linkState").textContent = T.getToken()
      ? "Linked. The code is stored on this device only."
      : (T.onHisPC()
          ? "This is her own PC; it does not need a code."
          : "Not linked. Paste the code from your PC below.");
    const age = status && status.liveness && status.liveness.heartbeat_age_s;
    $("connDetail").textContent = age == null ? "Connected. No heartbeat recorded yet."
      : "Connected. Last heartbeat " + Math.round(age) + "s ago.";
  }

  $("tokenBtn").addEventListener("click", () => {
    const box = $("linkCode");
    const next = box.value.trim();
    T.setToken(next);
    box.value = "";
    toast(T.getToken() ? "This device is linked" : "Link removed");
    refresh();
  });

  // Her room microphone. His ruling: it is a button he presses, never a
  // thing that is on by default — so the label says the STATE before he
  // presses it, and the Core is asked what happened rather than assumed.
  let micOn = false;
  async function readMic() {
    try {
      const said = await T.command({ kind: "mic" });
      micOn = /microphone is on/i.test(JSON.stringify(said || ""));
    } catch { micOn = false; }
    $("micState").textContent = micOn
      ? "On. She is listening in the room." : "Off unless you turn it on.";
    $("roomMic").textContent = micOn ? "Turn her microphone off" : "Turn her microphone on";
  }
  $("roomMic").addEventListener("click", async () => {
    try { await T.command({ kind: micOn ? "mic_off" : "mic_on" }); } catch {}
    readMic();
  });

  // The setup audit makes REAL network attempts — an IMAP login, a browser
  // probe. A page that polled it every two minutes was opening and closing
  // his signed-in ChatGPT window all day. It runs when he asks and not
  // before.
  $("setupBtn").addEventListener("click", async () => {
    $("setupState").textContent = "checking…";
    try {
      const r = await T.api("/api/setup");
      const left = (r.steps || []).filter((s) => s.state !== "ok" && !s.optional);
      $("setupState").textContent = r.ready || !left.length
        ? "Nothing — everything she needs is configured."
        : left.map((s) => s.title + " — " + s.detail).join("  ·  ");
    } catch { $("setupState").textContent = "Could not check just now."; }
  });

  $("cmdForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cmd = { kind: $("kind").value };
    for (const input of document.querySelectorAll("#args input")) {
      if (input.value.trim() !== "") {
        cmd[input.name] = input.name === "n" ? Number(input.value) : input.value;
      }
    }
    try {
      const res = await T.command(cmd);
      const row = document.createElement("div");
      row.textContent = String(res.outcome).toUpperCase() + " — " + res.detail;
      $("receipts").appendChild(row);
      refresh();
    } catch (err) { toast("That didn't go through."); }
  });

  // ---- getting her onto his phone ----------------------------------------
  // The honest first-run path: he scans this with the camera, the link opens
  // the tailnet URL with the code already on it, and Add to Home Screen is
  // the next tap. Nothing here mints anything — minting a credential is a
  // deliberate act at his own keyboard, and it stays there.
  function paintQR() {
    const url = $("installBlock").dataset.url || "";
    if (!url) { $("qr").hidden = true; return; }
    const code = $("pairCode").value.trim();
    const full = code ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(code) : url;
    $("installUrl").textContent = code ? url + "  (with your code on it)" : url;
    try {
      $("qr").innerHTML = window.TheaQR.svg(full);
      $("qr").hidden = false;
    } catch { $("qr").hidden = true; }
  }

  async function loadPhone() {
    if (!T.onHisPC()) return;
    $("installBlock").hidden = false;
    try {
      const r = await T.api("/api/phone");
      $("installBlock").dataset.url = r.url || "";
      const scan = r.devices
        ? "Scan this with your iPhone camera."
        : "Scan this with your iPhone camera. It will ask for a link code: run  " +
          MINT + "  and paste it below first.";
      $("installWhy").textContent = r.url
        ? (r.why ? scan + " " + r.why : scan)
        : (r.why || "Tailscale isn't set up on this PC yet, so there is no address to scan.");
      paintQR();
    } catch {
      $("installWhy").textContent = "Could not read this PC's network name just now.";
    }
  }
  $("pairCode").addEventListener("input", paintQR);

  $("drawer").addEventListener("toggle", () => {
    if (!$("drawer").open || $("drawer").dataset.loaded) return;
    $("drawer").dataset.loaded = "1";
    T.api("/api/kinds").then((kinds) => {
      KINDS = kinds;
      $("kind").innerHTML = Object.keys(KINDS).sort()
        .map((k) => "<option>" + T.esc(k) + "</option>").join("");
      renderArgs();
    }).catch(() => {});
    $("kind").addEventListener("change", renderArgs);
    readMic();
    loadPhone();
  });

  // ---- polling, and only while he is looking -----------------------------
  function start() { stop(); timer = setInterval(refresh, 15000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { T.hush(); stop(); } else { refresh(); start(); }
  });
  window.addEventListener("online", () => refresh());

  paintVoice();
  refresh();
  start();
})();
