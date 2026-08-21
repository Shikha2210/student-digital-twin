/* ============================================================
   StudyTwin  ·  Daily journal

   The one screen in this product where a student WRITES. Everything
   else renders stored pipeline output; this renders, and accepts,
   a person's own account of their days.

   Three rules govern every line below.

   1. NOTHING IS SHOWN THAT WAS NOT RECORDED. A day with no mood has
      no mood tile - not a dash in a tile, not a zero, not a greyed
      placeholder shaped like a value. The API omits the key and this
      file omits the element. That is the same rule the rest of the
      application follows for model output, applied to raw input.

   2. THERE IS NO LOCAL FALLBACK. If the API is unreachable the
      journal says so and refuses to pretend. A write that "succeeds"
      into localStorage while the server is down is precisely the
      failure this feature exists to remove: the student closes the
      tab believing their week is saved. On a failed save the form
      keeps everything typed, so nothing is lost while they fix it.

   3. RAW, DERIVED AND MODEL STAY APART. Tiles a student typed are
      labelled "recorded". The weekly summary is labelled "derived"
      and shows its own coverage. Neither is ever placed next to a
      latent-state chart as though the three were one kind of number.

   Depends on app.js for the shared helpers (el, icon, fmt, go) and
   on api.js for transport. No framework, no build step, consistent
   with the rest of web/.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------------------------------------- module state ----
     Kept at module scope rather than threaded through every function
     because this is one screen with one selection. `render()` is
     called fresh by the router each time; `reset()` clears anything
     that must not survive a profile change. */
  let X = null;             // helpers handed in by app.js
  let PID = null;           // server profile id
  let VOCAB = null;         // /api/daily/vocabulary, fetched once
  let TIMELINE = null;      // /api/profiles/{id}/timeline
  let WEEK = null;          // /api/profiles/{id}/weeks/{n}
  let selWeek = null;
  let selDate = null;
  let editingDay = false;   // day panel in form mode
  let addingActivity = false;
  let editingActivity = null;
  let busy = false;
  let root = null;          // the node the router mounted

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];

  /* Date handling is deliberately string-first. `new Date("2026-08-13")`
     parses as UTC midnight and then formats in local time, which renders
     the 12th for anybody west of Greenwich. Splitting the ISO string
     avoids a whole class of off-by-one-day bugs. */
  function parts(iso) {
    const p = String(iso).split("-");
    return { y: +p[0], m: +p[1], d: +p[2] };
  }
  function longDate(iso) {
    const p = parts(iso);
    return p.d + " " + MONTHS[p.m - 1] + " " + p.y;
  }
  function shortDate(iso) {
    const p = parts(iso);
    return p.d + " " + MONTHS[p.m - 1].slice(0, 3);
  }
  function rangeLabel(a, b) {
    const pa = parts(a), pb = parts(b);
    return pa.m === pb.m
      ? pa.d + "-" + pb.d + " " + MONTHS[pa.m - 1] + " " + pb.y
      : shortDate(a) + " - " + shortDate(b) + " " + pb.y;
  }
  function hhmm(v) { return v || null; }
  function duration(mins) {
    if (mins === null || mins === undefined) return null;
    const h = Math.floor(mins / 60), m = mins % 60;
    return (h ? h + "h" : "") + (m ? (h ? " " : "") + m + "m" : (h ? "" : "0m"));
  }

  const metricSpec = (name) =>
    (VOCAB && VOCAB.metrics.find((m) => m.value === name)) || null;
  const categoryLabel = (v) => {
    const f = VOCAB && VOCAB.activity_categories.find((c) => c.value === v);
    return f ? f.label : v;
  };

  /* ============================================================
     PROFILE IDENTITY

     Daily records need a row in `profiles`, because that is the
     table they hang off. Before this screen existed, onboarding
     wrote only to localStorage and the POST /api/profiles route the
     backend already shipped had no caller at all - so a Twin
     survived a refresh only as long as that browser's storage did.

     The id is kept in localStorage because there is no auth in this
     prototype (documented as a hard blocker in README §12). It is a
     pointer to a server row, not the data itself.
     ============================================================ */
  const IdStore = {
    KEY: "studytwin.profile.id",
    read() { try { return localStorage.getItem(this.KEY) || null; } catch (e) { return null; } },
    write(id) { try { localStorage.setItem(this.KEY, id); return true; }
                catch (e) { return false; } },
    clear() { try { localStorage.removeItem(this.KEY); } catch (e) { } },
  };

  /** Create the server row for a locally-created Twin.

      Returns the profile id. The onboarding answers travel as `payload`
      exactly as the profiles table already stores them - verbatim JSON,
      no model input, which is what `model_input: false` on the response
      asserts. */
  async function ensureProfile(local) {
    const existing = IdStore.read();
    if (existing) {
      // Verify it is still there. A database that was rebuilt leaves a
      // stale id behind, and every subsequent call would 404 with no
      // explanation the user could act on.
      try {
        await window.ST_Api.profiles.get(existing);
        return existing;
      } catch (err) {
        if (err.status !== 404) throw err;
        IdStore.clear();
      }
    }
    const p = local || {};
    const created = await window.ST_Api.profiles.create({
      display_name: (p.identity && p.identity.name) || p.name || null,
      consent: !!p.consent,
      payload: p,
      term_start: p.term_start || null,
    });
    IdStore.write(created.profile_id);
    return created.profile_id;
  }

  /* ============================================================
     LOADING
     ============================================================ */

  async function loadVocabulary() {
    if (!VOCAB) VOCAB = await window.ST_Api.daily.vocabulary();
    return VOCAB;
  }

  async function loadTimeline() {
    TIMELINE = await window.ST_Api.daily.timeline(PID);
    if (selWeek === null) {
      // Open on the week containing today when the student has one, else
      // the last week they wrote in. Never week 1 by default: an empty
      // first week is the least useful thing to land on.
      const current = TIMELINE.weeks.find(
        (w) => w.start_date <= TIMELINE.today && TIMELINE.today <= w.end_date);
      const lastWithData = [...TIMELINE.weeks].reverse().find((w) => w.has_data);
      selWeek = (current || lastWithData || TIMELINE.weeks[TIMELINE.weeks.length - 1]
                 || { week: 1 }).week;
    }
    return TIMELINE;
  }

  async function loadWeek(week) {
    WEEK = await window.ST_Api.daily.week(PID, week);
    selWeek = week;
    return WEEK;
  }

  const daySlot = (date) => (WEEK ? WEEK.slots.find((s) => s.date === date) : null);
  const dayData = (date) => (WEEK ? WEEK.days.find((d) => d.date === date) : null);

  /* ============================================================
     RENDER
     ============================================================ */

  function el(t, a, k) { return X.el(t, a, k); }
  function icon(n, sz) { return X.icon(n, sz); }

  function skeleton(msg) {
    return el("div", { class: "jn-load" }, [
      el("div", { class: "jn-load-bar" }, [el("i", {})]),
      el("p", { class: "jn-load-t", text: msg || "Loading your daily record" }),
    ]);
  }

  function errorState(err, retry) {
    const wrap = el("div", { class: "empty err" }, [
      el("p", { class: "empty-title", text: "The daily record could not be loaded" }),
      el("p", { class: "empty-why", html:
        "<code>" + escapeHtml(err && err.message ? err.message : String(err)) + "</code><br>" +
        "Daily records live in the database and there is deliberately no local " +
        "copy, so nothing can be shown while the API is unreachable. Nothing has " +
        "been lost." }),
    ]);
    if (retry) {
      const b = el("button", { type: "button", class: "btn btn-ghost",
        style: "margin-top:1rem", text: "Try again" });
      b.addEventListener("click", retry);
      wrap.appendChild(b);
    }
    return wrap;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** A one-line message under an action. Used for save failures so the
      error appears where the click was, not at the top of the page. */
  function inlineError(node, message) {
    const old = node.querySelector(".jn-err");
    if (old) old.remove();
    if (!message) return;
    node.appendChild(el("p", { class: "jn-err", html:
      "<b>Not saved.</b> " + escapeHtml(message) }));
  }

  /* ---------------------------------------------- the screen ---- */

  function paint() {
    if (!root) return;
    root.innerHTML = "";
    root.appendChild(header());
    root.appendChild(weekStrip());
    root.appendChild(weekPanel());
    if (selDate) root.appendChild(dayPanel(selDate));
    root.appendChild(derivedPanel());
    root.appendChild(provenanceNote());
  }

  function header() {
    const days = TIMELINE ? TIMELINE.days_recorded : 0;
    const head = el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "Daily journal" }),
        el("p", { class: "view-s", text:
          "Your own account of each day: what you did, how it went, and what you " +
          "made of it. Stored in the database, aggregated into weeks, and read by " +
          "no model." }),
      ]),
      el("span", { class: "chip " + (days ? "chip-observed" : "") }, [
        el("i", { class: "chip-dot" }),
        el("span", { text: days + (days === 1 ? " day recorded" : " days recorded") })]),
    ]);
    const actions = el("div", { class: "jn-actions" });
    const add = el("button", { type: "button", class: "btn btn-primary" },
      [el("span", { text: "Add today's data" }), icon("arrow", 16)]);
    add.addEventListener("click", () => openDate(TIMELINE.today, true));
    actions.appendChild(add);
    head.appendChild(actions);
    return head;
  }

  /* ---- the week rail. Length comes from the data, never a constant. */
  function weekStrip() {
    const panel = el("section", { class: "panel jn-strip" });
    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Timeline" }),
        el("p", { class: "panel-s", text: TIMELINE.term_start_declared
          ? "Week 1 begins " + longDate(TIMELINE.term_start) + ", the study period you set."
          : (TIMELINE.days_recorded
              ? "Week 1 is inferred from your earliest recorded day. Set a start "
                + "date on your profile to fix the numbering."
              : "Weeks are numbered from your first recorded day.") }),
      ]),
      el("span", { class: "tl-w", text: TIMELINE.n_weeks + " weeks" }),
    ]));

    const steps = el("div", { class: "tl-steps", role: "group",
      "aria-label": "Select a week" });
    TIMELINE.weeks.forEach((w) => {
      const b = el("button", { type: "button",
        class: "tl-step jn-week" + (w.has_data ? " has" : ""),
        "aria-pressed": String(w.week === selWeek),
        "aria-label": "Week " + w.week + ", " + w.days_recorded + " days recorded",
        title: rangeLabel(w.start_date, w.end_date) + " - " +
               (w.has_data ? w.days_recorded + "/7 days recorded" : "no data") });
      b.appendChild(el("span", { class: "jn-week-n",
        text: "W" + String(w.week).padStart(2, "0") }));
      // Seven pips, filled for days that hold a row. A count would be as
      // accurate; the pips make an empty week visibly empty at a glance
      // without printing a zero.
      const pips = el("span", { class: "jn-pips" });
      for (let i = 0; i < 7; i++) {
        pips.appendChild(el("i", { class: i < w.days_recorded ? "on" : "" }));
      }
      b.appendChild(pips);
      b.addEventListener("click", () => selectWeek(w.week));
      steps.appendChild(b);
    });
    panel.appendChild(steps);
    return panel;
  }

  function weekPanel() {
    const panel = el("section", { class: "panel" });
    const nav = el("div", { class: "jn-wknav" });
    const prev = el("button", { type: "button", class: "btn btn-quiet",
      "aria-label": "Previous week" }, [icon("back", 15)]);
    prev.disabled = selWeek <= 1;
    prev.addEventListener("click", () => selectWeek(selWeek - 1));
    const next = el("button", { type: "button", class: "btn btn-quiet",
      "aria-label": "Next week" }, [icon("arrow", 15)]);
    next.disabled = selWeek >= TIMELINE.n_weeks;
    next.addEventListener("click", () => selectWeek(selWeek + 1));
    nav.appendChild(prev);
    nav.appendChild(next);

    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Week " + WEEK.week }),
        el("p", { class: "panel-s", text: rangeLabel(WEEK.start_date, WEEK.end_date) }),
      ]),
      nav,
    ]));

    const grid = el("div", { class: "jn-days" });
    WEEK.slots.forEach((slot) => grid.appendChild(dayCard(slot)));
    panel.appendChild(grid);
    return panel;
  }

  /** One of seven. Three states, and they look different on purpose:
      recorded, empty, and not-yet-happened. */
  function dayCard(slot) {
    const isSel = slot.date === selDate;
    const card = el("button", { type: "button",
      class: "jn-day" + (slot.recorded ? " has" : "") +
             (slot.is_future ? " future" : "") + (isSel ? " sel" : ""),
      "aria-pressed": String(isSel) });
    card.appendChild(el("span", { class: "jn-day-w", text: slot.weekday }));
    card.appendChild(el("span", { class: "jn-day-d num",
      text: String(parts(slot.date).d) }));

    if (slot.is_future && !slot.recorded) {
      card.appendChild(el("span", { class: "jn-day-s", text: "Not yet" }));
      card.disabled = true;
      return card;
    }
    if (!slot.recorded) {
      card.appendChild(el("span", { class: "jn-day-s", text: "No data" }));
      card.appendChild(el("span", { class: "jn-day-add", text: "+ Add data" }));
      card.addEventListener("click", () => openDate(slot.date, true));
      return card;
    }

    const bits = [];
    if (slot.n_activities) {
      bits.push(slot.n_activities + (slot.n_activities === 1 ? " activity" : " activities"));
    }
    if (slot.n_metrics) bits.push(slot.n_metrics + " recorded");
    if (slot.n_reflections) bits.push("reflection");
    card.appendChild(el("span", { class: "jn-day-s",
      text: bits.length ? bits.join(" · ") : "Opened, nothing recorded" }));
    card.addEventListener("click", () => openDate(slot.date, false));
    return card;
  }

  /* ============================================================
     THE DAY
     ============================================================ */

  function dayPanel(date) {
    const slot = daySlot(date);
    const day = dayData(date);
    const panel = el("section", { class: "panel jn-daypanel" });

    const close = el("button", { type: "button", class: "btn btn-quiet",
      text: "Close" });
    close.addEventListener("click", () => { selDate = null; editingDay = false; paint(); });

    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t",
          text: (slot ? slot.weekday + ", " : "") + longDate(date) }),
        el("p", { class: "panel-s", text: day
          ? "Recorded by you. Last edited " + day.updated_at.replace("T", " ").replace("+00:00", " UTC")
          : "Nothing recorded for this day yet." }),
      ]),
      close,
    ]));

    if (editingDay || !day) {
      panel.appendChild(dayForm(date, day));
    } else {
      panel.appendChild(dayReadout(day));
    }
    panel.appendChild(activitiesSection(date, day));
    if (day) panel.appendChild(dangerRow(date));
    return panel;
  }

  /* ---- read mode: only what exists ---- */

  function dayReadout(day) {
    const wrap = el("div", { class: "jn-read" });

    const head = el("div", { class: "jn-sec-h" }, [
      el("h3", { class: "jn-sec-t", text: "Daily state" }),
      el("span", { class: "jn-tag", text: "recorded by you" }),
    ]);
    const edit = el("button", { type: "button", class: "btn btn-quiet",
      text: "Edit day" });
    edit.addEventListener("click", () => { editingDay = true; paint(); });
    head.appendChild(edit);
    wrap.appendChild(head);

    const keys = VOCAB.metrics.map((m) => m.value)
      .filter((m) => day.observations[m] !== undefined);
    if (!keys.length) {
      wrap.appendChild(el("p", { class: "jn-none",
        text: "No daily state recorded. Nothing is shown here because nothing was "
            + "entered - there is no default value for a day you did not rate." }));
    } else {
      const strip = el("div", { class: "mstrip jn-metrics" });
      keys.forEach((k) => {
        const spec = metricSpec(k);
        const v = day.observations[k];
        strip.appendChild(el("div", { class: "mchip" }, [el("div", { class: "mchip-l" }, [
          el("span", { class: "mchip-lbl", text: spec ? spec.label : k }),
          el("span", { class: "mchip-val num",
            text: (Number.isInteger(v) ? v : v.toFixed(1)) +
                  (spec ? spec.unit : "") }),
          el("span", { class: "mchip-sub", text: "self-reported" }),
        ])]));
      });
      wrap.appendChild(strip);
    }

    wrap.appendChild(el("div", { class: "jn-sec-h" }, [
      el("h3", { class: "jn-sec-t", text: "Reflection" }),
    ]));
    const answered = VOCAB.reflection_prompts.filter(
      (p) => day.reflections[p.value] !== undefined);
    if (!answered.length) {
      wrap.appendChild(el("p", { class: "jn-none", text: "Nothing written for this day." }));
    } else {
      const dl = el("div", { class: "jn-refl" });
      answered.forEach((p) => {
        dl.appendChild(el("div", { class: "jn-refl-r" }, [
          el("p", { class: "jn-refl-q", text: p.label }),
          el("p", { class: "jn-refl-a", text: day.reflections[p.value] }),
        ]));
      });
      wrap.appendChild(dl);
    }
    return wrap;
  }

  /* ---- edit mode ---- */

  function dayForm(date, day) {
    const form = el("div", { class: "jn-form" });
    const values = Object.assign({}, day ? day.observations : {});
    const bodies = Object.assign({}, day ? day.reflections : {});

    form.appendChild(el("div", { class: "jn-sec-h" }, [
      el("h3", { class: "jn-sec-t", text: "Daily state" }),
      el("span", { class: "jn-tag", text: "optional - leave blank if you did not track it" }),
    ]));

    VOCAB.metrics.forEach((spec) => {
      form.appendChild(metricField(spec, values));
    });

    form.appendChild(el("div", { class: "jn-sec-h" }, [
      el("h3", { class: "jn-sec-t", text: "Reflection" }),
    ]));
    VOCAB.reflection_prompts.forEach((p) => {
      const id = "jn-refl-" + p.value;
      const ta = el("textarea", { class: "inp ta", id: id, rows: "2",
        placeholder: "Leave empty to skip" });
      ta.value = bodies[p.value] || "";
      ta.addEventListener("input", () => { bodies[p.value] = ta.value; });
      form.appendChild(el("div", { class: "jn-fld" }, [
        el("label", { class: "jn-lbl", for: id, text: p.label }), ta]));
    });

    const acts = el("div", { class: "jn-formacts" });
    const save = el("button", { type: "button", class: "btn btn-primary" },
      [el("span", { text: day ? "Save changes" : "Save this day" }), icon("check", 16)]);
    save.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      save.disabled = true;
      save.querySelector("span").textContent = "Saving...";
      inlineError(acts, null);
      try {
        // One call. PUT is create-or-replace on the date, so a brand new
        // day and an edit to an existing one are the same request.
        await window.ST_Api.daily.saveDay(PID, date, {
          observations: cleanNumbers(values),
          reflections: cleanText(bodies),
        });
        editingDay = false;
        await refresh(date);
      } catch (err) {
        inlineError(acts, err.message);
        save.disabled = false;
        save.querySelector("span").textContent = day ? "Save changes" : "Save this day";
      } finally {
        busy = false;
      }
    });
    acts.appendChild(save);

    if (day) {
      const cancel = el("button", { type: "button", class: "btn btn-ghost",
        text: "Cancel" });
      cancel.addEventListener("click", () => { editingDay = false; paint(); });
      acts.appendChild(cancel);
    }
    form.appendChild(acts);
    return form;
  }

  /** A 1-5 scale, or a number field for sleep hours.

      "Not recorded" is a real, selectable state and it is the default.
      A slider that starts at 3 would have every unfilled day claiming a
      middling mood the student never entered. */
  function metricField(spec, values) {
    const fld = el("div", { class: "jn-fld" });
    fld.appendChild(el("span", { class: "jn-lbl", text: spec.label }));

    if (spec.value === "sleep_hours") {
      const inp = el("input", { class: "inp jn-num", type: "number",
        min: String(spec.min), max: String(spec.max), step: "0.5",
        placeholder: "hours - leave blank if not tracked",
        "aria-label": spec.label + " in hours" });
      if (values[spec.value] !== undefined) inp.value = String(values[spec.value]);
      inp.addEventListener("input", () => {
        if (inp.value === "") delete values[spec.value];
        else values[spec.value] = Number(inp.value);
      });
      fld.appendChild(inp);
      return fld;
    }

    const scale = el("div", { class: "scale jn-scale",
      role: "group", "aria-label": spec.label });
    const buttons = [];
    for (let v = spec.min; v <= spec.max; v += spec.step) {
      const n = v;
      const b = el("button", { type: "button", class: "scale-b",
        "aria-pressed": String(values[spec.value] === n),
        "aria-label": spec.label + " " + n + " of " + spec.max }, [
        el("span", { class: "scale-n", text: String(n) })]);
      b.addEventListener("click", () => {
        // Clicking the selected value clears it. Without that there is no
        // way back to "not recorded" once a button has been pressed, and
        // a mis-click would become permanent data.
        if (values[spec.value] === n) delete values[spec.value];
        else values[spec.value] = n;
        buttons.forEach((x) => x.b.setAttribute("aria-pressed",
          String(values[spec.value] === x.n)));
      });
      buttons.push({ b: b, n: n });
      scale.appendChild(b);
    }
    fld.appendChild(scale);
    return fld;
  }

  function cleanNumbers(v) {
    const out = {};
    Object.keys(v).forEach((k) => {
      if (v[k] !== undefined && v[k] !== null && v[k] !== "" && !Number.isNaN(v[k])) {
        out[k] = Number(v[k]);
      }
    });
    return out;
  }
  function cleanText(v) {
    const out = {};
    Object.keys(v).forEach((k) => { if (v[k] && v[k].trim()) out[k] = v[k].trim(); });
    return out;
  }

  /* ---- activities ---- */

  function activitiesSection(date, day) {
    const sec = el("div", { class: "jn-acts" });
    const head = el("div", { class: "jn-sec-h" }, [
      el("h3", { class: "jn-sec-t", text: "Activities" }),
      el("span", { class: "jn-tag", text: "recorded by you" }),
    ]);
    sec.appendChild(head);

    const list = (day && day.activities) || [];
    if (!list.length && !addingActivity) {
      sec.appendChild(el("p", { class: "jn-none", text: day
        ? "No activities recorded for this day."
        : "Save the day first, then add what you did." }));
    }

    list.forEach((a) => {
      sec.appendChild(editingActivity === a.activity_id
        ? activityForm(date, a)
        : activityRow(date, a));
    });

    if (addingActivity) {
      sec.appendChild(activityForm(date, null));
    } else if (day) {
      const add = el("button", { type: "button", class: "btn btn-ghost jn-addact",
        text: "+ Add activity" });
      add.addEventListener("click", () => { addingActivity = true; paint(); });
      sec.appendChild(add);
    }
    return sec;
  }

  function activityRow(date, a) {
    const row = el("div", { class: "jn-act" });
    // A time column that is blank when no clock time was recorded, rather
    // than showing 00:00. Same rule as everywhere else on this screen.
    row.appendChild(el("span", { class: "jn-act-t num",
      text: a.start_time || "" }));
    const body = el("div", { class: "jn-act-b" });
    body.appendChild(el("p", { class: "jn-act-title", text: a.title }));
    const meta = [categoryLabel(a.category)];
    if (a.subject) meta.push(a.subject);
    if (a.minutes) meta.push(duration(a.minutes));
    if (a.status) meta.push(statusLabel(a.status));
    if (a.importance) meta.push("importance " + a.importance + "/5");
    body.appendChild(el("p", { class: "jn-act-m", text: meta.join(" · ") }));
    if (a.detail) body.appendChild(el("p", { class: "jn-act-d", text: a.detail }));
    row.appendChild(body);

    const tools = el("div", { class: "jn-act-x" });
    const ed = el("button", { type: "button", class: "btn btn-quiet",
      text: "Edit", "aria-label": "Edit " + a.title });
    ed.addEventListener("click", () => { editingActivity = a.activity_id; paint(); });
    const rm = el("button", { type: "button", class: "btn btn-quiet jn-del",
      text: "Delete", "aria-label": "Delete " + a.title });
    rm.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      rm.disabled = true;
      try {
        await window.ST_Api.daily.deleteActivity(PID, a.activity_id);
        await refresh(date);
      } catch (err) {
        inlineError(row, err.message);
        rm.disabled = false;
      } finally { busy = false; }
    });
    tools.appendChild(ed);
    tools.appendChild(rm);
    row.appendChild(tools);
    return row;
  }

  function statusLabel(v) {
    const f = VOCAB && VOCAB.activity_statuses.find((s) => s.value === v);
    return f ? f.label : v;
  }

  function activityForm(date, a) {
    const form = el("div", { class: "jn-actform" });
    const draft = {
      title: a ? a.title : "",
      category: a ? a.category : "study",
      subject: a ? (a.subject || "") : "",
      detail: a ? (a.detail || "") : "",
      start_time: a ? (a.start_time || "") : "",
      end_time: a ? (a.end_time || "") : "",
      minutes: a && a.minutes ? String(a.minutes) : "",
      status: a ? (a.status || "") : "",
      importance: a && a.importance ? a.importance : null,
    };

    const title = el("input", { class: "inp", type: "text", maxlength: "200",
      placeholder: "What did you do? e.g. DBMS lecture", "aria-label": "Activity title" });
    title.value = draft.title;
    title.addEventListener("input", () => { draft.title = title.value; });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Activity" }), title]));

    const seg = el("div", { class: "seg wrap tiny", role: "group",
      "aria-label": "Category" });
    const catBtns = [];
    VOCAB.activity_categories.forEach((c) => {
      const b = el("button", { type: "button", class: "seg-b",
        "aria-pressed": String(draft.category === c.value), text: c.label });
      b.addEventListener("click", () => {
        draft.category = c.value;
        catBtns.forEach((x) => x.b.setAttribute("aria-pressed",
          String(draft.category === x.v)));
      });
      catBtns.push({ b: b, v: c.value });
      seg.appendChild(b);
    });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Category" }), seg]));

    const times = el("div", { class: "jn-times" });
    const start = el("input", { class: "inp", type: "time", "aria-label": "Start time" });
    start.value = draft.start_time;
    start.addEventListener("input", () => { draft.start_time = start.value; });
    const end = el("input", { class: "inp", type: "time", "aria-label": "End time" });
    end.value = draft.end_time;
    end.addEventListener("input", () => { draft.end_time = end.value; });
    const mins = el("input", { class: "inp", type: "number", min: "1", max: "1440",
      placeholder: "minutes", "aria-label": "Duration in minutes" });
    mins.value = draft.minutes;
    mins.addEventListener("input", () => { draft.minutes = mins.value; });
    times.appendChild(el("div", {}, [
      el("span", { class: "jn-lbl", text: "Start" }), start]));
    times.appendChild(el("div", {}, [
      el("span", { class: "jn-lbl", text: "End" }), end]));
    times.appendChild(el("div", {}, [
      el("span", { class: "jn-lbl", text: "Or duration" }), mins]));
    form.appendChild(times);
    form.appendChild(el("p", { class: "jn-hint", text:
      "Give a start and an end and the duration is worked out for you. Leave all "
      + "three blank if you do not remember - a blank duration is left out of the "
      + "weekly total rather than counted as zero." }));

    const subject = el("input", { class: "inp", type: "text", maxlength: "120",
      placeholder: "Course, module or topic", "aria-label": "Subject" });
    subject.value = draft.subject;
    subject.addEventListener("input", () => { draft.subject = subject.value; });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Subject or topic" }), subject]));

    const detail = el("textarea", { class: "inp ta", rows: "2",
      placeholder: "Anything worth remembering about it",
      "aria-label": "Activity detail" });
    detail.value = draft.detail;
    detail.addEventListener("input", () => { draft.detail = detail.value; });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Detail" }), detail]));

    const stseg = el("div", { class: "seg wrap tiny", role: "group",
      "aria-label": "Status" });
    const stBtns = [];
    [{ value: "", label: "No status" }].concat(VOCAB.activity_statuses).forEach((s) => {
      const b = el("button", { type: "button", class: "seg-b",
        "aria-pressed": String(draft.status === s.value), text: s.label });
      b.addEventListener("click", () => {
        draft.status = s.value;
        stBtns.forEach((x) => x.b.setAttribute("aria-pressed",
          String(draft.status === x.v)));
      });
      stBtns.push({ b: b, v: s.value });
      stseg.appendChild(b);
    });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Status" }), stseg]));

    /* Importance. "Not rated" is the default and is selectable, so a
       mis-click can be undone - the same rule the daily scales follow. */
    const impseg = el("div", { class: "seg wrap tiny", role: "group",
      "aria-label": "Importance" });
    const impBtns = [];
    [{ v: null, l: "Not rated" }, { v: 1, l: "1" }, { v: 2, l: "2" },
     { v: 3, l: "3" }, { v: 4, l: "4" }, { v: 5, l: "5" }].forEach((o) => {
      const b = el("button", { type: "button", class: "seg-b",
        "aria-pressed": String(draft.importance === o.v),
        "aria-label": o.v === null ? "Importance not rated"
                                   : "Importance " + o.v + " of 5",
        text: o.l });
      b.addEventListener("click", () => {
        draft.importance = o.v;
        impBtns.forEach((x) => x.b.setAttribute("aria-pressed",
          String(draft.importance === x.v)));
      });
      impBtns.push({ b: b, v: o.v });
      impseg.appendChild(b);
    });
    form.appendChild(el("div", { class: "jn-fld" }, [
      el("span", { class: "jn-lbl", text: "Importance" }), impseg]));

    const acts = el("div", { class: "jn-formacts" });
    const save = el("button", { type: "button", class: "btn btn-primary" },
      [el("span", { text: a ? "Save activity" : "Add activity" })]);
    save.addEventListener("click", async () => {
      if (busy) return;
      if (!draft.title.trim()) {
        inlineError(acts, "An activity needs a title.");
        return;
      }
      busy = true;
      save.disabled = true;
      inlineError(acts, null);
      const body = {
        title: draft.title.trim(),
        category: draft.category,
        subject: draft.subject.trim() || null,
        detail: draft.detail.trim() || null,
        start_time: hhmm(draft.start_time),
        end_time: hhmm(draft.end_time),
        minutes: draft.minutes ? Number(draft.minutes) : null,
        status: draft.status || null,
        importance: draft.importance,
      };
      try {
        if (a) await window.ST_Api.daily.updateActivity(PID, a.activity_id, body);
        else await window.ST_Api.daily.addActivity(PID, date, body);
        addingActivity = false;
        editingActivity = null;
        await refresh(date);
      } catch (err) {
        inlineError(acts, err.message);
        save.disabled = false;
      } finally { busy = false; }
    });
    acts.appendChild(save);
    const cancel = el("button", { type: "button", class: "btn btn-ghost", text: "Cancel" });
    cancel.addEventListener("click", () => {
      addingActivity = false; editingActivity = null; paint();
    });
    acts.appendChild(cancel);
    form.appendChild(acts);
    return form;
  }

  function dangerRow(date) {
    const row = el("div", { class: "jn-danger" });
    const del = el("button", { type: "button", class: "btn btn-quiet jn-del",
      text: "Delete this day" });
    let armed = false;
    del.addEventListener("click", async () => {
      if (!armed) {
        armed = true;
        del.textContent = "Delete permanently - click again";
        return;
      }
      if (busy) return;
      busy = true;
      del.disabled = true;
      try {
        await window.ST_Api.daily.deleteDay(PID, date);
        selDate = null;
        editingDay = false;
        await refresh(null);
      } catch (err) {
        inlineError(row, err.message);
        del.disabled = false;
      } finally { busy = false; }
    });
    row.appendChild(del);
    row.appendChild(el("span", { class: "jn-hint",
      text: "Removes the day and everything recorded in it. There is no undo." }));
    return row;
  }

  /* ============================================================
     DERIVED  —  and labelled as such, beside the raw rows it sums
     ============================================================ */

  function derivedPanel() {
    const r = WEEK.rollup;
    const panel = el("section", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Week " + WEEK.week + " summary" }),
        el("p", { class: "panel-s", text:
          "Derived: arithmetic over the days above, computed when this page "
          + "loaded. Not a model output and not comparable to a latent state." }),
      ]),
      el("span", { class: "chip", text: "derived" }),
    ]));

    if (!r.days_recorded) {
      panel.appendChild(el("p", { class: "jn-none", text:
        "Nothing recorded in this week, so there is nothing to summarise. "
        + "A row of zeros here would read as a measurement." }));
      return panel;
    }

    const strip = el("div", { class: "mstrip" });
    const chip = (lbl, val, sub) => el("div", { class: "mchip" },
      [el("div", { class: "mchip-l" }, [
        el("span", { class: "mchip-lbl", text: lbl }),
        el("span", { class: "mchip-val num", text: val }),
        el("span", { class: "mchip-sub", text: sub })])]);
    strip.appendChild(chip("Days recorded", r.days_recorded + " / 7",
      r.days_with_content + " with content"));
    strip.appendChild(chip("Activities", String(r.n_activities),
      r.by_category.length + " categories"));
    strip.appendChild(chip("Time logged", duration(r.minutes_logged) || "0m",
      // The coverage caveat rides with the number rather than under it. With
      // no activities at all there is no coverage to report, and claiming
      // "every activity has a duration" over an empty set reads as a
      // reassurance about data that does not exist.
      !r.n_activities ? "no activities logged"
        : r.activities_without_duration
          ? r.activities_without_duration + " with no duration - partial sum"
          : "every activity has a duration"));
    strip.appendChild(chip("Written answers", String(r.n_reflections), "across the week"));
    panel.appendChild(strip);

    if (r.by_category.length) {
      const max = Math.max.apply(null, r.by_category.map((c) => c.n_activities));
      const bars = el("div", { class: "jn-cats" });
      r.by_category.forEach((c) => {
        bars.appendChild(el("div", { class: "jn-cat" }, [
          el("span", { class: "jn-cat-n", text: categoryLabel(c.category) }),
          el("span", { class: "jn-cat-t" }, [
            el("i", { class: "jn-cat-b",
              style: "width:" + Math.round(100 * c.n_activities / max) + "%" })]),
          el("span", { class: "jn-cat-v num", text: String(c.n_activities) +
            (c.minutes ? " · " + duration(c.minutes) : "") }),
        ]));
      });
      panel.appendChild(bars);
    }

    if (r.metrics.length) {
      const dl = el("div", { class: "dl" });
      r.metrics.forEach((m) => {
        const spec = metricSpec(m.metric);
        dl.appendChild(el("div", { class: "dl-r" }, [
          el("span", { class: "dl-k", text: spec ? spec.label : m.metric }),
          el("span", {}, [
            el("span", { class: "dl-v", text: m.mean.toFixed(1) +
              (spec ? spec.unit : "") }),
            // n travels with the mean. A weekly average over one day and one
            // over seven are different claims and must not look the same.
            el("span", { class: "sub", text: "mean of " + m.n +
              (m.n === 1 ? " day" : " days") + " · range " +
              m.min + "-" + m.max })]),
        ]));
      });
      panel.appendChild(dl);
    }
    return panel;
  }

  function provenanceNote() {
    return el("div", { class: "note warn" }, [icon("alert", 16),
      el("div", { html:
        "<b>None of this is model input.</b> Daily records are persisted, " +
        "aggregated into the weekly summary above, and displayed. The inference " +
        "model reads weekly behavioural channels from a pipeline run; no emission " +
        "model has been fitted for self-reported daily scales, so feeding these " +
        "numbers into it would mean inventing one. The schema already names the " +
        "route for doing it properly later - the <code>lifestyle</code> and " +
        "<code>self_report</code> channels, which every adapter currently declares " +
        "unavailable." })]);
  }

  /* ============================================================
     ACTIONS
     ============================================================ */

  async function selectWeek(week) {
    if (week < 1 || week > TIMELINE.n_weeks) return;
    root.innerHTML = "";
    root.appendChild(skeleton("Loading week " + week));
    try {
      selDate = null;
      editingDay = false;
      addingActivity = false;
      editingActivity = null;
      await loadWeek(week);
      paint();
    } catch (err) {
      root.innerHTML = "";
      root.appendChild(errorState(err, () => selectWeek(week)));
    }
  }

  /** Open a date, moving to its week first if it is not in the loaded one.

      `startEditing` is true when the student clicked "Add data" on an
      empty slot: they asked to write, so the panel opens in form mode
      rather than showing them an empty read view they then have to click
      a second time to edit. */
  async function openDate(date, startEditing) {
    const target = TIMELINE.weeks.find(
      (w) => w.start_date <= date && date <= w.end_date);
    if (!target) {
      // Outside the derived span - which happens only if today is before
      // week 1, i.e. the declared term start is in the future.
      root.innerHTML = "";
      root.appendChild(errorState(new Error(
        longDate(date) + " falls outside this timeline. Your study period starts " +
        longDate(TIMELINE.term_start || date) + "."), () => reload()));
      return;
    }
    if (!WEEK || WEEK.week !== target.week) {
      root.innerHTML = "";
      root.appendChild(skeleton("Loading week " + target.week));
      try {
        await loadWeek(target.week);
      } catch (err) {
        root.innerHTML = "";
        root.appendChild(errorState(err, () => openDate(date, startEditing)));
        return;
      }
    }
    selDate = date;
    editingDay = !!startEditing && !dayData(date);
    addingActivity = false;
    editingActivity = null;
    paint();
    const panel = root.querySelector(".jn-daypanel");
    if (panel && panel.scrollIntoView) {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  /** Re-read from the server after a write, so what is on screen is what
      is stored. Optimistic local mutation would let the two diverge on a
      partial failure, and the whole point of this screen is that the
      display and the database agree. */
  async function refresh(keepDate) {
    await loadTimeline();
    await loadWeek(selWeek);
    if (keepDate) selDate = keepDate;
    paint();
  }

  async function reload() {
    root.innerHTML = "";
    root.appendChild(skeleton());
    try {
      await loadVocabulary();
      await loadTimeline();
      await loadWeek(selWeek);
      paint();
    } catch (err) {
      root.innerHTML = "";
      root.appendChild(errorState(err, reload));
    }
  }

  /* ============================================================
     ENTRY POINT
     ============================================================ */

  /** Mount the journal. Returns a node immediately; content arrives.

      `ctx` carries app.js's helpers plus `local`, the onboarding answers
      from localStorage. The profile row is created on first use if the
      Twin has never been saved to the server. */
  function render(ctx) {
    X = ctx;
    root = X.el("div", { class: "view jn" });
    root.appendChild(skeleton("Opening your daily record"));

    (async function () {
      try {
        PID = await ensureProfile(ctx.local);
      } catch (err) {
        root.innerHTML = "";
        root.appendChild(noProfileState(err, ctx));
        return;
      }
      await reload();
    })();

    return root;
  }

  function noProfileState(err, ctx) {
    const wrap = el("div", { class: "empty err" }, [
      el("p", { class: "empty-title", text: "Your Twin has no record on the server" }),
      el("p", { class: "empty-why", html:
        "Daily records are rows in the database, so they need a profile there to " +
        "belong to. Creating one failed: <code>" +
        escapeHtml(err && err.message ? err.message : String(err)) + "</code><br>" +
        "Start the API and try again - nothing you entered during onboarding has " +
        "been lost, it is still on this device." }),
    ]);
    const retry = el("button", { type: "button", class: "btn btn-primary",
      style: "margin-top:1rem" }, [el("span", { text: "Try again" })]);
    retry.addEventListener("click", () => {
      const fresh = render(ctx);
      root.replaceWith(fresh);
    });
    wrap.appendChild(retry);
    return wrap;
  }

  /** Drop everything cached. Called when the Twin is deleted, so the next
      visit does not read a previous account's week off stale state. */
  function reset() {
    PID = null; TIMELINE = null; WEEK = null;
    selWeek = null; selDate = null;
    editingDay = false; addingActivity = false; editingActivity = null;
  }

  window.ST_Journal = {
    render: render,
    reset: reset,
    ensureProfile: ensureProfile,
    profileId: () => IdStore.read(),
    clearProfileId: () => IdStore.clear(),
  };
})();
