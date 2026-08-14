/* ============================================================
   StudyTwin — Create your Twin
   ------------------------------------------------------------
   A declarative onboarding schema. Every field carries a `use`
   flag which drives the honesty layer:

     model    the inference model can consume this today
     context  stored as profile context, NOT model input
     profile  identity/administrative only

   That distinction is not decoration. The model infers from
   weekly behavioural observations; almost nothing collected here
   reaches it yet, and the UI says so per field rather than
   implying that filling a form trains a filter.

   Consumes helpers from app.js via mount(ctx) so there is one
   DOM/element vocabulary across the product.
   ============================================================ */
(function () {
  "use strict";

  let X = null;                 // helpers injected from app.js
  let draft = null, step = 0;

  const USE_LABEL = {
    model:   { t: "Used by the Twin",   c: "use-model" },
    context: { t: "Stored as context",  c: "use-context" },
    profile: { t: "Profile only",       c: "use-profile" },
  };

  /* ---------------------------------------------------------- schema -- */
  const STEPS = [
    {
      id: "welcome", kind: "intro", eyebrow: "Create your Twin",
      title: "Let's build your Twin.",
      lede: "StudyTwin learns what normal looks like for you, revises that picture as " +
            "observations accumulate, and lets you explore how the coming weeks could unfold.",
    },
    {
      id: "identity", eyebrow: "01 · Identity", nav: "Identity", title: "Who is this Twin for?",
      lede: "Only what is useful. None of it needs to be your legal name.",
      group: "required",
      fields: [
        { k: "name", label: "Preferred name", type: "text", req: true, use: "profile",
          ph: "e.g. Sid", hint: "Shown in your dashboard." },
        { k: "year", label: "Year of study", type: "segmented", req: true, use: "profile",
          opts: ["1st", "2nd", "3rd", "4th", "PG"] },
        { k: "institution", label: "Institution", type: "text", use: "profile", ph: "Optional" },
        { k: "programme", label: "Degree / programme", type: "text", use: "profile",
          ph: "e.g. Computer Science" },
      ],
    },
    {
      id: "courses", eyebrow: "02 · Academic context", nav: "Courses", title: "What are you studying this term?",
      lede: "Each course becomes a separate context the Twin can track.",
      group: "required", kind: "courses",
    },
    {
      id: "patterns", eyebrow: "03 · Study patterns", nav: "Study patterns", title: "How does a normal week actually look?",
      lede: "Describe your habit, not your intention. The Twin is trying to learn your normal.",
      group: "signals",
      fields: [
        { k: "hours", label: "Typical study hours per week", type: "slider", use: "context",
          min: 0, max: 45, step: 1, unit: "h", def: 12 },
        { k: "consistency", label: "How consistent is your routine?", type: "scale", use: "context",
          labels: ["Very irregular", "Irregular", "Mixed", "Fairly steady", "Very steady"] },
        { k: "when", label: "When do you usually study?", type: "chips", multi: true, use: "context",
          opts: ["Morning", "Afternoon", "Evening", "Night", "Varies"] },
        { k: "deadlines", label: "How often do you finish work before the deadline?", type: "scale",
          use: "context", labels: ["Rarely", "Sometimes", "About half", "Usually", "Almost always"] },
      ],
    },
    {
      id: "prefs", eyebrow: "04 · Learning preferences", nav: "Learning style", title: "How do you prefer to learn?",
      lede: "Select as many as apply.",
      group: "signals",
      fields: [
        { k: "modes", label: "Preferred formats", type: "chips", multi: true, use: "context",
          opts: ["Videos", "Reading", "Practice problems", "Projects", "Lectures", "Discussion"] },
        { k: "independence", label: "Independent study vs. guided", type: "scale", use: "context",
          labels: ["Strongly guided", "Guided", "Mixed", "Independent", "Strongly independent"] },
        { k: "unfamiliar", label: "Confidence with unfamiliar material", type: "scale", use: "context",
          labels: ["Very low", "Low", "Moderate", "High", "Very high"] },
      ],
    },
    {
      id: "situation", eyebrow: "05 · Right now", nav: "Right now", title: "How is the term going?",
      lede: "A snapshot of where you are today.",
      group: "signals",
      fields: [
        { k: "going", label: "Overall, how are your studies going?", type: "scale", use: "context",
          labels: ["Very difficult", "Difficult", "Manageable", "Good", "Very good"] },
        { k: "pending", label: "Assessments currently pending", type: "slider", use: "context",
          min: 0, max: 12, step: 1, unit: "", def: 2 },
        { k: "strongest", label: "Which subject feels strongest?", type: "course-pick", use: "context" },
        { k: "weakest", label: "Which feels hardest right now?", type: "course-pick", use: "context" },
      ],
    },
    {
      id: "goals", eyebrow: "06 · Goals", nav: "Goals", title: "What are you aiming for this term?",
      lede: "Select any that apply, then say it in your own words.",
      group: "optional",
      fields: [
        { k: "goals", label: "Goals", type: "chips", multi: true, use: "context",
          opts: ["Improve grades", "Maintain grades", "Exam preparation", "Be more consistent",
                 "Understand hard subjects", "Finish projects", "Placement preparation"] },
        { k: "success", label: "What would make this semester feel successful?",
          type: "textarea", use: "context", rows: 3,
          ph: "In your own words…" },
      ],
    },
    {
      id: "baseline", eyebrow: "07 · Personal baseline", kind: "baseline",
      nav: "Personal baseline", title: "Your normal is not everyone else's normal.",
      lede: "The Twin needs a starting picture of what normal looks like for you. " +
            "These are self-reported starting signals, not measurements.",
      group: "required",
    },
    {
      id: "context", eyebrow: "08 · Anything else", nav: "Anything else", title: "What did we not ask about?",
      lede: "Anything about your situation the questions above missed.",
      group: "optional",
      fields: [
        { k: "freeform", label: "Tell your Twin anything else", type: "textarea",
          use: "context", rows: 6,
          ph: "e.g. I work part-time on weekends. My exams are unusually close together. " +
              "I've just switched courses." },
        { k: "commitments", label: "Other commitments", type: "chips", multi: true, use: "context",
          opts: ["Part-time work", "Long commute", "Caring responsibilities", "Sport / society",
                 "Competitive exam prep"] },
      ],
    },
    { id: "privacy", kind: "privacy", eyebrow: "09 · Privacy", nav: "Privacy", title: "What happens to this.",
      lede: "Short version: it stays in this browser.", group: "required" },
    { id: "review", kind: "review", eyebrow: "10 · Review", nav: "Review", title: "Your Twin is ready to begin.",
      lede: "Check anything before it is created. Every section is editable." },
  ];

  const FIELD_STEPS = STEPS.filter((s) => s.fields || s.kind === "courses" || s.kind === "baseline");

  /* -------------------------------------------------- draft & storage -- */
  function blank() {
    return {
      v: 2, created: null, consent: false, observations: 0,
      identity: {}, courses: [], patterns: {}, prefs: {}, situation: {},
      goals: {}, baseline: { hours: 12, consistency: 3, workload: 3, confidence: 3, engagement: 3 },
      context: {},
    };
  }
  const bucketOf = (id) =>
    ({ identity: "identity", patterns: "patterns", prefs: "prefs", situation: "situation",
       goals: "goals", context: "context" }[id]);

  /* ------------------------------------------------------ completeness -- */
  /* Progress is measured by what the Twin actually gains, not by how many
     inputs were touched. Three separate axes, because "17 of 25 questions"
     tells a student nothing about whether their Twin is any good. */
  function coverage() {
    const req = [], sig = [], opt = [];
    const push = (arr, ok) => arr.push(!!ok);

    push(req, draft.identity.name && draft.identity.year);
    push(req, draft.courses.length > 0);
    push(req, draft.baseline && Object.keys(draft.baseline).length >= 5);
    push(req, draft.consent);

    STEPS.filter((s) => s.group === "signals").forEach((s) =>
      (s.fields || []).forEach((f) => push(sig, filled(bucketOf(s.id), f.k))));

    STEPS.filter((s) => s.group === "optional").forEach((s) =>
      (s.fields || []).forEach((f) => push(opt, filled(bucketOf(s.id), f.k))));
    push(opt, !!draft.identity.institution);
    push(opt, !!draft.identity.programme);

    const pctOf = (a) => (a.length ? Math.round((a.filter(Boolean).length / a.length) * 100) : 100);
    const overall = Math.round(pctOf(req) * 0.55 + pctOf(sig) * 0.32 + pctOf(opt) * 0.13);
    return { req: pctOf(req), sig: pctOf(sig), opt: pctOf(opt), overall };
  }
  function filled(bucket, k) {
    if (!bucket) return false;
    const v = (draft[bucket] || {})[k];
    if (v === undefined || v === null || v === "") return false;
    if (Array.isArray(v)) return v.length > 0;
    return true;
  }
  function missing() {
    const out = [];
    STEPS.forEach((s, i) => {
      if (!s.fields) return;
      (s.fields || []).forEach((f) => {
        if (!filled(bucketOf(s.id), f.k)) out.push({ label: f.label, step: i, req: !!f.req });
      });
    });
    if (!draft.courses.length) out.unshift({ label: "At least one course", step: idx("courses"), req: true });
    return out;
  }
  const idx = (id) => STEPS.findIndex((s) => s.id === id);

  /* ============================================================ TWIN VIS */
  /* The Twin gains a layer per section. It is the same object throughout,
     so the student watches one thing being assembled rather than watching a
     progress bar fill. */
  function twinVis(host) {
    const { s, el } = X;
    const W = 340, H = 340, CX = 170, CY = 170;
    const cov = coverage();
    const TEAL = "#22D3B8", TEAL_D = "#0A9C8A", AMB = "#F0A93C", IND = "#7B72FF", MUT = "#6E858C";
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "ob-tw-svg", "aria-hidden": "true" });

    const has = {
      identity: !!draft.identity.name,
      courses: draft.courses.length > 0,
      patterns: Object.keys(draft.patterns || {}).length > 0,
      baseline: step >= idx("baseline"),
      goals: (draft.goals.goals || []).length > 0,
      done: step >= idx("review"),
    };

    // coverage ring — the outer boundary of what is known
    const R = 148, C = 2 * Math.PI * R;
    g.appendChild(s("circle", { cx: CX, cy: CY, r: R, fill: "none",
      stroke: "rgba(232,237,236,.10)", "stroke-width": 3 }));
    g.appendChild(s("circle", { cx: CX, cy: CY, r: R, fill: "none", stroke: TEAL,
      "stroke-width": 3, "stroke-linecap": "round",
      "stroke-dasharray": `${(C * cov.overall) / 100} ${C}`,
      transform: `rotate(-90 ${CX} ${CY})`, class: "ob-tw-arc" }));

    // uncertainty haze — widest early, tightening as sections land
    const haze = 118 - (cov.overall / 100) * 26;
    g.appendChild(s("circle", { cx: CX, cy: CY, r: haze, fill: TEAL, "fill-opacity": .05 }));
    g.appendChild(s("circle", { cx: CX, cy: CY, r: haze, fill: "none", stroke: TEAL,
      "stroke-opacity": .12, "stroke-width": 1 }));

    // baseline ring
    if (has.baseline) {
      g.appendChild(s("circle", { cx: CX, cy: CY, r: 62, fill: "none", stroke: AMB,
        "stroke-width": 1.5, "stroke-dasharray": "6 7", "stroke-opacity": .95, class: "ob-tw-in" }));
    }

    // course nodes orbiting
    if (has.courses) {
      draft.courses.forEach((c, i) => {
        const a = (i / draft.courses.length) * Math.PI * 2 - Math.PI / 2;
        const x = CX + Math.cos(a) * 96, y = CY + Math.sin(a) * 96;
        g.appendChild(s("line", { x1: CX, y1: CY, x2: x, y2: y, stroke: TEAL_D,
          "stroke-width": .9, "stroke-opacity": .32 }));
        const n = s("circle", { cx: x, cy: y, r: 6, fill: TEAL_D, "fill-opacity": .92, class: "ob-tw-in" });
        n.style.animationDelay = (i * 60) + "ms";
        g.appendChild(n);
      });
    }

    // behavioural layer: a dashed inner orbit once patterns exist
    if (has.patterns) {
      g.appendChild(s("circle", { cx: CX, cy: CY, r: 34, fill: "none", stroke: TEAL,
        "stroke-opacity": .4, "stroke-width": 1, "stroke-dasharray": "2 4", class: "ob-tw-in" }));
    }

    // goal vectors
    if (has.goals) {
      (draft.goals.goals || []).slice(0, 5).forEach((_, i) => {
        const a = -Math.PI / 2 + (i - 2) * 0.24;
        g.appendChild(s("line", { x1: CX, y1: CY, x2: CX + Math.cos(a) * 132,
          y2: CY + Math.sin(a) * 132, stroke: IND, "stroke-width": 1.2,
          "stroke-opacity": .45, class: "ob-tw-in" }));
      });
    }

    // the core
    g.appendChild(s("circle", { cx: CX, cy: CY, r: has.identity ? 22 : 16, fill: TEAL,
      "fill-opacity": has.identity ? .16 : .07 }));
    g.appendChild(has.identity
      ? s("circle", { cx: CX, cy: CY, r: 10, fill: TEAL, class: "ob-tw-core" })
      : s("circle", { cx: CX, cy: CY, r: 10, fill: "none", stroke: MUT,
          "stroke-width": 1.3, "stroke-dasharray": "3 3" }));

    host.appendChild(g);

    const STATE = !has.identity ? "TWIN INITIALISING"
      : has.done ? "TWIN READY TO CREATE" : "TWIN BUILDING";
    host.appendChild(el("div", { class: "ob-tw-state" }, [
      el("span", { class: "ob-tw-dot" }),
      el("span", { text: STATE }),
    ]));

    // coverage, three honest axes
    const bars = el("div", { class: "ob-cov" });
    [["Required", cov.req, "req"], ["Personalisation signals", cov.sig, "sig"],
     ["Optional context", cov.opt, "opt"]].forEach(([label, v, cls]) => {
      bars.appendChild(el("div", { class: "ob-cov-row" }, [
        el("span", { class: "ob-cov-l", text: label }),
        el("span", { class: "ob-cov-track" }, [
          el("i", { class: "ob-cov-fill " + cls, style: "width:" + v + "%" })]),
        el("span", { class: "ob-cov-v num", text: v + "%" }),
      ]));
    });
    host.appendChild(bars);

    // what's missing — clickable, jumps straight there
    const allMiss = missing();
    const miss = allMiss.slice(0, 4);
    if (miss.length) {
      const box = el("div", { class: "ob-missing", "data-missing": String(allMiss.length) }, [
        el("p", { class: "ob-missing-t",
          text: "Would benefit from · " + allMiss.length + " open" })]);
      miss.forEach((m) => {
        const b = X.el("button", { type: "button", class: "ob-missing-i" }, [
          el("span", { class: "ob-missing-dot" + (m.req ? " req" : "") }),
          el("span", { text: m.label }),
        ]);
        b.addEventListener("click", () => { step = m.step; X.rerender(); });
        box.appendChild(b);
      });
      if (allMiss.length > miss.length) {
        box.appendChild(el("p", { class: "ob-missing-t", style: "margin:.5rem 0 0;opacity:.7",
          text: "+" + (allMiss.length - miss.length) + " more" }));
      }
      host.appendChild(box);
    }
  }

  /* ============================================================ CONTROLS */
  function field(f, bucket) {
    const { el } = X;
    const val = () => (draft[bucket] || {})[f.k];
    const set = (v) => {
      draft[bucket] = draft[bucket] || {}; draft[bucket][f.k] = v;
      X.rerenderVis(); syncGate();
    };

    const head = el("div", { class: "fld-head" }, [
      el("label", { class: "fld-label", text: f.label, for: "f-" + f.k }),
      el("span", { class: "fld-meta" }, [
        el("span", { class: "fld-req" + (f.req ? " on" : ""), text: f.req ? "Required" : "Optional" }),
        el("span", { class: "fld-use " + USE_LABEL[f.use].c, text: USE_LABEL[f.use].t }),
      ]),
    ]);
    const wrap = el("div", { class: "fld" }, [head]);
    if (f.hint) wrap.appendChild(el("p", { class: "fld-hint", text: f.hint }));

    if (f.type === "text") {
      const i = el("input", { type: "text", id: "f-" + f.k, class: "inp",
        value: val() || "", placeholder: f.ph || "" });
      i.addEventListener("input", (e) => set(e.target.value));
      wrap.appendChild(i);
    }

    if (f.type === "textarea") {
      const t = el("textarea", { id: "f-" + f.k, class: "inp ta", rows: String(f.rows || 4),
        placeholder: f.ph || "" });
      t.value = val() || "";
      t.addEventListener("input", (e) => set(e.target.value));
      wrap.appendChild(t);
    }

    if (f.type === "segmented" || (f.type === "chips" && !f.multi)) {
      const row = el("div", { class: "seg" });
      f.opts.forEach((o) => {
        const b = el("button", { type: "button", class: "seg-b",
          "aria-pressed": String(val() === o), text: o });
        b.addEventListener("click", () => { set(val() === o ? "" : o); X.rerender(); });
        row.appendChild(b);
      });
      wrap.appendChild(row);
    }

    if (f.type === "chips" && f.multi) {
      const row = el("div", { class: "seg wrap" });
      const cur = () => val() || [];
      f.opts.forEach((o) => {
        const on = cur().includes(o);
        const b = el("button", { type: "button", class: "seg-b", "aria-pressed": String(on), text: o });
        b.addEventListener("click", () => {
          const c = cur().slice();
          const i = c.indexOf(o);
          if (i >= 0) c.splice(i, 1); else c.push(o);
          set(c); X.rerender();
        });
        row.appendChild(b);
      });
      wrap.appendChild(row);
    }

    if (f.type === "scale") {
      const row = el("div", { class: "scale" });
      f.labels.forEach((lab, i) => {
        const n = i + 1, on = val() === n;
        const b = el("button", { type: "button", class: "scale-b", "aria-pressed": String(on) }, [
          el("span", { class: "scale-n", text: String(n) }),
          el("span", { class: "scale-l", text: lab }),
        ]);
        b.addEventListener("click", () => { set(on ? null : n); X.rerender(); });
        row.appendChild(b);
      });
      wrap.appendChild(row);
    }

    if (f.type === "slider") {
      const cur = val() === undefined ? f.def : val();
      const out = el("span", { class: "sl-out num", text: cur + (f.unit || "") });
      const r = el("input", { type: "range", id: "f-" + f.k, min: String(f.min),
        max: String(f.max), step: String(f.step), value: String(cur), class: "sl" });
      r.addEventListener("input", (e) => { out.textContent = e.target.value + (f.unit || ""); });
      r.addEventListener("change", (e) => set(+e.target.value));
      head.querySelector(".fld-meta").insertBefore(out, head.querySelector(".fld-meta").firstChild);
      wrap.appendChild(r);
    }

    if (f.type === "course-pick") {
      const row = el("div", { class: "seg wrap" });
      if (!draft.courses.length) {
        row.appendChild(el("p", { class: "fld-hint", text: "Add courses first — step 02." }));
      }
      draft.courses.forEach((c) => {
        const on = val() === c.name;
        const b = el("button", { type: "button", class: "seg-b", "aria-pressed": String(on), text: c.name });
        b.addEventListener("click", () => { set(on ? "" : c.name); X.rerender(); });
        row.appendChild(b);
      });
      wrap.appendChild(row);
    }
    return wrap;
  }

  /* -------------------------------------------------------- courses -- */
  const SUGGEST = ["Machine Learning", "Databases", "Operating Systems", "Computer Networks",
    "Algorithms", "Statistics", "Linear Algebra", "Compilers", "Signals & Systems"];

  function coursesStep() {
    const { el } = X;
    const wrap = el("div", {});
    const list = el("div", { class: "crs-list" });

    const redraw = () => {
      list.innerHTML = "";
      if (!draft.courses.length) {
        list.appendChild(el("p", { class: "fld-hint", text: "No courses yet. Add at least one." }));
      }
      draft.courses.forEach((c, i) => {
        const row = el("div", { class: "crs" });
        const nm = el("input", { class: "inp crs-name", type: "text", value: c.name,
          "aria-label": "Course name" });
        nm.addEventListener("input", (e) => { c.name = e.target.value; X.rerenderVis(); syncGate(); });
        const code = el("input", { class: "inp crs-code", type: "text", value: c.code || "",
          placeholder: "Code", "aria-label": "Course code" });
        code.addEventListener("input", (e) => { c.code = e.target.value; });
        const imp = el("div", { class: "seg tiny" });
        ["Low", "Med", "High"].forEach((lv) => {
          const b = el("button", { type: "button", class: "seg-b",
            "aria-pressed": String((c.importance || "Med") === lv), text: lv });
          b.addEventListener("click", () => { c.importance = lv; redraw(); });
          imp.appendChild(b);
        });
        const del = el("button", { type: "button", class: "crs-x", "aria-label": "Remove " + c.name, text: "×" });
        del.addEventListener("click", () => { draft.courses.splice(i, 1); redraw(); X.rerenderVis(); syncGate(); });
        row.appendChild(nm); row.appendChild(code); row.appendChild(imp); row.appendChild(del);
        list.appendChild(row);
      });
    };
    redraw();
    wrap.appendChild(list);

    const add = el("div", { class: "crs-add" });
    const inp = el("input", { class: "inp", type: "text", placeholder: "Add a course and press Enter",
      "aria-label": "Add a course" });
    const commit = (v) => {
      const name = (v || "").trim();
      if (!name || draft.courses.length >= 10) return;
      draft.courses.push({ name: name, code: "", importance: "Med" });
      inp.value = ""; redraw(); X.rerenderVis(); syncGate();
    };
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(e.target.value); }
    });
    const btn = el("button", { type: "button", class: "btn btn-ghost", text: "Add" });
    btn.addEventListener("click", () => commit(inp.value));
    add.appendChild(inp); add.appendChild(btn);
    wrap.appendChild(add);

    const sug = el("div", { class: "seg wrap dim" });
    SUGGEST.forEach((sName) => {
      const b = el("button", { type: "button", class: "seg-b", text: "+ " + sName });
      b.addEventListener("click", () => commit(sName));
      sug.appendChild(b);
    });
    wrap.appendChild(sug);
    wrap.appendChild(el("div", { class: "note", style: "margin-top:1.25rem" }, [
      X.icon("info", 16),
      el("div", { html: "Courses become <b>contexts</b> — the unit the model conditions on. " +
        "Course names themselves are profile data; the model uses the context structure, " +
        "not the words." }),
    ]));
    return wrap;
  }

  /* ------------------------------------------------------- baseline -- */
  function baselineStep() {
    const { el } = X;
    const wrap = el("div", {});
    const B = [
      ["hours", "Typical study hours per week", 0, 45, 1, "h"],
      ["consistency", "Week-to-week consistency", 1, 5, 1, "/5"],
      ["workload", "How heavy the term feels", 1, 5, 1, "/5"],
      ["confidence", "Academic confidence", 1, 5, 1, "/5"],
      ["engagement", "Current engagement with the material", 1, 5, 1, "/5"],
    ];
    B.forEach(([k, label, min, max, st, unit]) => {
      const out = el("span", { class: "sl-out num", text: draft.baseline[k] + unit });
      const r = el("input", { type: "range", class: "sl", min: String(min), max: String(max),
        step: String(st), value: String(draft.baseline[k]), id: "b-" + k });
      r.addEventListener("input", (e) => { out.textContent = e.target.value + unit; });
      r.addEventListener("change", (e) => { draft.baseline[k] = +e.target.value; X.rerenderVis(); syncGate(); });
      wrap.appendChild(el("div", { class: "fld" }, [
        el("div", { class: "fld-head" }, [
          el("label", { class: "fld-label", text: label, for: "b-" + k }),
          el("span", { class: "fld-meta" }, [out,
            el("span", { class: "fld-use use-context", text: "Stored as context" })]),
        ]), r,
      ]));
    });
    wrap.appendChild(el("div", { class: "note", style: "margin-top:1.25rem" }, [
      X.icon("alert", 16),
      el("div", { html: "<b>Self-reported starting signals, not measurements.</b> The research " +
        "schema defines a <code>self_report</code> channel for exactly this and no adapter supplies " +
        "it yet, so these are stored with your profile and are <b>not consumed by the inference " +
        "model</b>. The model's own baseline is fitted from observed behaviour over time." }),
    ]));
    return wrap;
  }

  /* --------------------------------------------------------- review -- */
  function reviewStep() {
    const { el } = X;
    const wrap = el("div", {});
    const cov = coverage();

    const sec = (title, rows, stepId) => {
      const box = el("div", { class: "rv" });
      const h = el("div", { class: "rv-h" }, [el("h3", { text: title })]);
      const ed = el("button", { type: "button", class: "link-btn", text: "Edit" });
      ed.addEventListener("click", () => { step = idx(stepId); X.rerender(); });
      h.appendChild(ed);
      box.appendChild(h);
      const dl = el("dl", { class: "rv-dl" });
      rows.forEach(([k, v]) => {
        dl.appendChild(el("dt", { text: k }));
        dl.appendChild(el("dd", { text: v || "—", class: v ? "" : "muted" }));
      });
      box.appendChild(dl);
      return box;
    };

    const j = (v) => Array.isArray(v) ? (v.join(", ") || "") : (v === undefined ? "" : String(v));
    wrap.appendChild(sec("Identity", [
      ["Name", draft.identity.name], ["Year", draft.identity.year],
      ["Institution", draft.identity.institution], ["Programme", draft.identity.programme],
    ], "identity"));
    wrap.appendChild(sec("Courses", draft.courses.length
      ? draft.courses.map((c) => [c.name, (c.code ? c.code + " · " : "") + (c.importance || "Med")])
      : [["Courses", ""]], "courses"));
    wrap.appendChild(sec("Study patterns", [
      ["Hours / week", j(draft.patterns.hours)], ["Consistency", j(draft.patterns.consistency)],
      ["Usual times", j(draft.patterns.when)], ["Deadline habit", j(draft.patterns.deadlines)],
    ], "patterns"));
    wrap.appendChild(sec("Goals", [
      ["Goals", j(draft.goals.goals)], ["Success looks like", j(draft.goals.success)],
    ], "goals"));
    wrap.appendChild(sec("Baseline", [
      ["Study hours", draft.baseline.hours + "h"], ["Consistency", draft.baseline.consistency + "/5"],
      ["Workload", draft.baseline.workload + "/5"], ["Confidence", draft.baseline.confidence + "/5"],
      ["Engagement", draft.baseline.engagement + "/5"],
    ], "baseline"));
    if (draft.context.freeform) {
      wrap.appendChild(sec("Your own words", [["Context", draft.context.freeform]], "context"));
    }

    wrap.appendChild(el("div", { class: "knows", style: "margin-top:2rem" }, [
      el("div", { class: "knows-col yes" }, [
        el("h3", { text: "What your Twin knows" }),
        el("div", { class: "knows-list" }, [
          kn("Your academic context", draft.courses.length + " course contexts registered"),
          kn("A self-reported starting point", "Baseline signals stored with your profile"),
          kn("Your stated goals and constraints", "Held as context, retrievable, not inferred from"),
        ]),
      ]),
      el("div", { class: "knows-col no" }, [
        el("h3", { text: "What it does not know yet" }),
        el("div", { class: "knows-list" }, [
          kn("Your observed weekly behaviour", "The model's primary input. None collected.", true),
          kn("Your real personal baseline", "Fitted from behaviour, not from the sliders.", true),
          kn("Any trajectory or future", "Requires several weeks of observations.", true),
        ]),
      ]),
    ]));
    wrap.appendChild(el("div", { class: "note", style: "margin-top:1.5rem" }, [
      X.icon("alert", 16),
      el("div", { html: "<b>Twin coverage " + cov.overall + "%</b> measures how complete your " +
        "<em>profile</em> is. It is not a measure of how good the model's estimate is — that " +
        "depends on observations, and you have none yet." }),
    ]));
    return wrap;
  }
  function kn(t, sub, warn) {
    const { el, s } = X;
    const ic = s("svg", { viewBox: "0 0 24 24", width: 15, height: 15, fill: "none",
      stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" });
    ic.appendChild(s("path", { d: warn ? "M12 7v7M12 17.2h.01" : "M4 12.5l5 5L20 6.5" }));
    if (warn) ic.appendChild(s("circle", { cx: 12, cy: 12, r: 9 }));
    return el("div", { class: "knows-item" }, [ic,
      el("div", { html: t + "<span class='sub'>" + sub + "</span>" })]);
  }

  /* --------------------------------------------------------- privacy -- */
  function privacyStep() {
    const { el } = X;
    const wrap = el("div", {});
    [["What is stored", "Everything you entered: identity, courses, patterns, preferences, goals, " +
      "baseline answers and free text."],
     ["Where", "This browser's local storage. No server, no account, no network requests. " +
      "Clearing browser data deletes it."],
     ["What is shared", "Nothing. No analytics, no third parties."],
     ["What the model uses", "None of it, currently. The inference model learns from weekly " +
      "behavioural observations, which this prototype cannot yet collect."],
    ].forEach(([h, p]) => wrap.appendChild(
      el("div", { class: "consent" }, [el("h3", { text: h }), el("p", { text: p })])));
    wrap.appendChild(el("div", { class: "note" }, [X.icon("alert", 16),
      el("div", { html: "<b>Prototype.</b> Research prototype, not a deployed service. " +
        "Storage behaviour will change if a backend is ever connected." })]));
    const chk = el("input", { type: "checkbox", id: "ob-consent" });
    chk.checked = !!draft.consent;
    chk.addEventListener("change", (e) => { draft.consent = e.target.checked; X.rerenderVis(); syncGate(); });
    wrap.appendChild(el("label", { class: "consent-check", for: "ob-consent" }, [chk,
      el("span", { text: "I understand this is a prototype, my data stays on this device, and my " +
        "Twin will have very wide uncertainty until observations accumulate." })]));
    return wrap;
  }

  /* ============================================================= SHELL */
  function body() {
    const st = STEPS[step], { el } = X;
    if (st.kind === "intro") {
      const w = el("div", {});
      w.appendChild(el("div", { class: "note", style: "margin-bottom:1.5rem" }, [X.icon("info", 16),
        el("div", { html: "<b>What to expect.</b> About twelve short steps. Your Twin starts close " +
          "to a typical student with very wide uncertainty, and becomes genuinely personal only as " +
          "weekly observations accumulate. We show you exactly how far along it is at every point." })]));
      return w;
    }
    if (st.kind === "courses") return coursesStep();
    if (st.kind === "baseline") return baselineStep();
    if (st.kind === "privacy") return privacyStep();
    if (st.kind === "review") return reviewStep();
    const w = el("div", {});
    (st.fields || []).forEach((f) => w.appendChild(field(f, bucketOf(st.id))));
    return w;
  }

  function canAdvance() {
    const st = STEPS[step];
    if (st.id === "identity") return !!(draft.identity.name && draft.identity.year);
    if (st.kind === "courses") return draft.courses.length > 0;
    if (st.kind === "privacy") return !!draft.consent;
    return true;
  }

  function render(ctx) {
    X = ctx;
    if (!draft) draft = X.Store.read2() || blank();
    const { el } = X;
    const st = STEPS[step];

    const root = el("div", { class: "ob2" });

    /* rail */
    const rail = el("nav", { class: "ob2-rail", "aria-label": "Onboarding steps" });
    rail.appendChild(el("a", { class: "brand", href: "#", "data-go": "" },
      [X.icon("twin", 20), el("span", { text: "StudyTwin" })]));
    const list = el("ol", { class: "ob2-steps" });
    STEPS.forEach((s2, i) => {
      if (s2.kind === "intro") return;
      const b = el("button", { type: "button", class: "ob2-step",
        "aria-current": i === step ? "step" : "false" }, [
        el("span", { class: "ob2-num", text: String(i).padStart(2, "0") }),
        el("span", { class: "ob2-name", text: s2.nav || s2.title }),
      ]);
      b.addEventListener("click", () => { step = i; X.rerender(); });
      const li = el("li", {}); li.appendChild(b); list.appendChild(li);
    });
    rail.appendChild(list);
    root.appendChild(rail);

    /* question column */
    const main = el("div", { class: "ob2-main" });
    const card = el("div", { class: "ob2-card" });
    card.appendChild(el("p", { class: "eyebrow", text: st.eyebrow }));
    card.appendChild(el("h1", { class: "ob2-q", text: st.title }));
    if (st.lede) card.appendChild(el("p", { class: "lede", text: st.lede }));
    card.appendChild(body());

    const acts = el("div", { class: "ob-actions" });
    if (step > 0) {
      const b = el("button", { type: "button", class: "btn btn-ghost", text: "Back" });
      b.addEventListener("click", () => { step--; X.rerender(); });
      acts.appendChild(b);
    }
    acts.appendChild(el("span", { class: "spacer" }));
    if (step === 0) {
      acts.appendChild(el("a", { class: "link-btn", href: "#/app", "data-go": "app",
        text: "Explore a demo Twin instead" }));
    }
    const last = step === STEPS.length - 1;
    const next = el("button", { type: "button", class: "btn btn-primary" }, [
      el("span", { text: last ? "Create my Twin" : (step === 0 ? "Start" : "Continue") }),
      X.icon("arrow", 16)]);
    if (!canAdvance()) { next.disabled = true; next.classList.add("is-off"); }
    next.addEventListener("click", () => {
      if (!canAdvance()) return;
      X.Store.write2(draft);
      if (last) { draft.created = new Date().toISOString(); X.Store.write2(draft); X.go("twin/new"); }
      else { step++; X.rerender(); }
    });
    acts.appendChild(next);
    card.appendChild(acts);
    main.appendChild(card);
    root.appendChild(main);

    /* twin column */
    const aside = el("aside", { class: "ob2-aside", id: "ob2-aside" });
    twinVis(aside);
    root.appendChild(aside);
    return root;
  }

  /** Re-evaluate the Continue gate in place. Called after any mutation that
      could change it, so the button tracks the answers rather than the render. */
  function syncGate() {
    const b = document.querySelector(".ob-actions .btn-primary");
    if (!b) return;
    const ok = canAdvance();
    b.disabled = !ok;
    b.classList.toggle("is-off", !ok);
  }

  function refreshVis() {
    const a = document.getElementById("ob2-aside");
    if (!a) return;
    a.innerHTML = "";
    twinVis(a);
    syncGate();
  }

  window.ST_Onboarding = {
    render: render, refreshVis: refreshVis,
    reset: function () { draft = null; step = 0; },
    stepCount: STEPS.length,
  };
})();
