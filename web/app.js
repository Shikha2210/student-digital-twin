/* ============================================================
   StudyTwin frontend

   No framework, no build step, no runtime dependency. Charts live
   in charts.js and are hand-built SVG, so uncertainty can be
   encoded as geometry rather than as an overlay a charting library
   would let us switch off.

   Data contract: window.STUDYTWIN_DATA, written by
   scripts/export_web_data.py. Swapping in a real HTTP API means
   replacing one loader and nothing else.
   ============================================================ */
(function () {
  "use strict";

  /* The view model, resolved at boot by ST_Api from either the live API or
     the bundled offline snapshot. Both produce the identical shape, so nothing
     below this line knows which transport it got. */
  let D = null;
  let st = null, theta = 0, lastEng = 0, lastSd = 0, dev = 0, lastHz = 0, NW = 0;
  let currentWeek = 0;
  let BOOT = { mode: "loading", error: null, hint: null };
  const C = window.ST_Charts;
  const NS = "http://www.w3.org/2000/svg";
  const MONO = "Cascadia Mono, Consolas, ui-monospace, monospace";

  /* ---------------------------------------------- helpers ---- */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const el = (tag, attrs, kids) => {
    const n = document.createElement(tag);
    for (const k in (attrs || {})) {
      if (k === "class") n.className = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach((c) => c && n.appendChild(c));
    return n;
  };
  const s = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) n.setAttribute(k, attrs[k]);
    return n;
  };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v, d) => (v === null || v === undefined || Number.isNaN(v))
    ? "—" : v.toFixed(d === undefined ? 2 : d);
  const pct = (v, d) => fmt(v * 100, d === undefined ? 1 : d) + "%";
  const sign = (v, d) => (v >= 0 ? "+" : "") + fmt(v, d);

  /* ============================================================
     DATA CONTRACT
     ------------------------------------------------------------
     An early version read D.provenance while the generator emitted
     no such key. The read threw between two appendChild calls, so
     the sidebar mounted and the main region never did: a blank
     screen with no visible cause.

     Two rules prevent that class of bug recurring:
       1. the contract is declared, checked once at boot, and a
          violation produces a readable failure rather than silence
       2. every view renders inside a boundary, so one broken
          section degrades to an honest empty state
     ============================================================ */
  const CONTRACT = {
    "provenance.seed": "run seed",
    "provenance.note": "provenance statement",
    "student.id": "student identifier",
    "student.theta": "personal baseline",
    "state.eng": "engagement state series",
    "state.eng_sd": "engagement uncertainty series",
    "hazard": "weekly hazard series",
    "sim.base_risk": "baseline simulation",
  };
  const dig = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  function contractViolations() {
    if (!D) return Object.keys(CONTRACT);
    return Object.keys(CONTRACT).filter((p) => dig(D, p) === undefined);
  }

  /** Honest empty state. Used when data is genuinely absent - never to hide an error. */
  function emptyState(title, why, kind) {
    return el("div", { class: "empty " + (kind || "") }, [
      el("p", { class: "empty-title", text: title }),
      el("p", { class: "empty-why", html: why }),
    ]);
  }

  /** Render boundary: a thrown section reports itself instead of blanking the page. */
  function boundary(label, fn) {
    try {
      return fn();
    } catch (err) {
      console.error("[StudyTwin] " + label + " failed:", err);
      return emptyState(
        label + " could not be rendered",
        "<code>" + (err && err.message ? err.message : String(err)) + "</code><br>" +
        "This is a front-end fault, not a missing result. Regenerate the data with " +
        "<code>python scripts/export_web_data.py</code> and reload.",
        "err"
      );
    }
  }

  /* Lucide-geometry icons: 24px grid, 1.5 stroke, round caps.
     One family, drawn inline - no icon dependency, no mixing. */
  const ICON = {
    user:    "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
    refresh: "M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.7 3H21M21 3v5h-5M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.7-3H3M3 21v-5h5",
    branch:  "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 9a9 9 0 0 1-9 9",
    beaker:  "M9 3h6M10 3v6.5L5.2 17.4A2 2 0 0 0 6.9 20h10.2a2 2 0 0 0 1.7-2.6L14 9.5V3M7.5 14h9",
    home:    "M3 10.5 12 3l9 7.5M5 9.5V20h14V9.5",
    chart:   "M3 3v18h18M7 15l3.5-4 3 2.5L20 7",
    layers:  "M12 3 3 8l9 5 9-5-9-5M3 15l9 5 9-5M3 11.5l9 5 9-5",
    clock:   "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2",
    info:    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 11v5M12 7.5h.01",
    alert:   "M12 8v5M12 16.5h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0",
    arrow:   "M5 12h14M13 6l6 6-6 6",
    back:    "M19 12H5M11 18l-6-6 6-6",
    db:      "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    twin:    "M8.5 20a5 5 0 0 1-3.6-8.5A5 5 0 0 1 9 3.6M15.5 4a5 5 0 0 1 3.6 8.5A5 5 0 0 1 15 20.4M12 8v8",
    check:   "M4 12.5l5 5L20 6.5",
  };
  function icon(name, size) {
    const n = s("svg", { viewBox: "0 0 24 24", width: size || 20, height: size || 20,
      fill: "none", stroke: "currentColor", "stroke-width": 1.5,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    n.appendChild(s("path", { d: ICON[name] || ICON.info }));
    return n;
  }

  /* ---------------------------------------------- the subject ----
     Bound once per boot. `currentWeek` is shared across screens on purpose:
     switching views must not feel like switching applications, and the
     selected week is part of "where we are". */
  function bind(vm) {
    D = vm;
    st = D.state;
    theta = D.student.theta[0];
    lastEng = st.eng[st.eng.length - 1];
    lastSd = st.eng_sd[st.eng_sd.length - 1];
    dev = lastEng - theta;
    lastHz = D.hazard[D.hazard.length - 1];
    NW = st.t.length;
    currentWeek = NW - 1;
  }

  function keyd(text, color, dashed, band) {
    const sw = el("i", { class: "kd" + (band ? " band" : "") });
    if (band) sw.style.background = color; else sw.style.borderTopColor = color;
    if (dashed) sw.style.borderTopStyle = "dashed";
    return el("span", { class: "kdw" }, [sw, el("span", { text: text })]);
  }
  function ribbonKey() {
    return el("div", { class: "panel-key" }, [
      keyd("observed", css("--ink")),
      keyd("95% interval", css("--teal"), false, true),
      keyd("own baseline", css("--amber"), true),
      keyd("simulated", css("--indigo-b"), true),
    ]);
  }

  /* ============================================================
     TWIN HOME
     One question: where is this student, relative to their own
     normal? One dominant object, one dominant number.
     ============================================================ */
  function viewHome() {
    const v = el("div", { class: "view" });

    const chips = el("div", { class: "mstrip" });
    const chip = (lbl, val, sub, tone, sparkVals) => {
      const c = el("div", { class: "mchip " + (tone || "") }, [
        el("div", { class: "mchip-l" }, [
          el("span", { class: "mchip-lbl", text: lbl }),
          el("span", { class: "mchip-val num", text: val }),
          el("span", { class: "mchip-sub", text: sub }),
        ]),
      ]);
      if (sparkVals) {
        const sp = el("div", { class: "mchip-sp" });
        sp.appendChild(C.spark(sparkVals,
          tone === "down" ? css("--coral") : tone === "amber" ? css("--amber") : css("--teal")));
        c.appendChild(sp);
      }
      return c;
    };
    chips.appendChild(chip("Current state", fmt(lastEng), "±" + fmt(1.96 * lastSd) + " at 95%",
      dev < 0 ? "down" : "up", st.eng));
    chips.appendChild(chip("Own baseline θ", fmt(theta),
      "shrinkage k = " + fmt(D.shrinkage[0]), "amber"));
    chips.appendChild(chip("Deviation", sign(dev),
      dev < 0 ? "below own normal" : "above own normal", dev < 0 ? "down" : "up"));
    chips.appendChild(chip("Weekly hazard", pct(lastHz, 2),
      "from " + pct(D.hazard[0], 2) + " at w00", "", D.hazard));
    chips.appendChild(chip("Observations", String(NW), "weeks, synthetic cohort", ""));
    v.appendChild(chips);

    /* ---- the dominant object ---- */
    const panel = el("section", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Where is this student, relative to their own normal?" }),
        el("p", { class: "panel-s", text: NW + " observed weeks, then eight simulated. " +
          "The band's thickness is the 95% credible interval; hover any week to inspect it." }),
      ]),
      ribbonKey(),
    ]));

    const chartHost = el("div", { class: "panel-chart" });
    const readout = el("div", { class: "readout" });

    function paintReadout(i) {
      const k = (i === null || i === undefined) ? NW - 1 : i;
      const d0 = st.eng[k] - theta;
      readout.innerHTML = "";
      readout.appendChild(el("p", { class: "ro-w",
        text: (i === null || i === undefined) ? "CURRENT · WEEK " + String(st.t[k]).padStart(2, "0")
                                              : "WEEK " + String(st.t[k]).padStart(2, "0") }));
      readout.appendChild(el("p", { class: "ro-big num " + (d0 < 0 ? "down" : "up"),
        text: fmt(st.eng[k]) }));
      [["Own baseline", fmt(theta)],
       ["Deviation", sign(d0)],
       ["Uncertainty", "±" + fmt(1.96 * st.eng_sd[k])],
       ["Second dimension", fmt(st.cap[k])],
      ].forEach((row) => {
        readout.appendChild(el("div", { class: "ro-row" }, [
          el("span", { text: row[0] }), el("span", { class: "num", text: row[1] })]));
      });
      readout.appendChild(el("p", { class: "ro-status " + (d0 < 0 ? "down" : "up"),
        text: d0 < 0 ? "BELOW OWN BASELINE" : "AT OR ABOVE OWN BASELINE" }));

      const rec = D.attrib[k];
      if (rec) {
        const top = Object.entries(rec.ch)
          .filter((e) => Math.abs(e[1]) > 1e-3)
          .sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))[0];
        readout.appendChild(el("p", { class: "ro-why", html:
          "<b>What moved it</b>" +
          (top ? top[0].replace(/_/g, " ") + " contributed " + sign(top[1], 3)
               : "no single channel dominated") +
          (Math.abs(rec.unexp) > 0.02
            ? "<br><span class='muted'>residual " + sign(rec.unexp, 3) + " not attributable</span>"
            : "") }));
      }
      readout.appendChild(el("div", { class: "ro-sp" }));
    }

    const ribbon = C.stateRibbon({
      mean: st.eng, sd: st.eng_sd, theta: theta, h: 520,
      sim: { lo: D.sim.base_lo, med: D.sim.base_med, hi: D.sim.base_hi },
      onHover: paintReadout,
      onSelect: (i) => { currentWeek = i; ribbon.setWeek(i); paintReadout(i); },
      label: "Engagement for the demo student across " + NW +
        " observed weeks against a personal baseline of " + fmt(theta) +
        ", then eight simulated weeks",
    });
    chartHost.appendChild(ribbon);
    panel.appendChild(el("div", { class: "panel-body" }, [chartHost, readout]));
    paintReadout(null);
    panel.appendChild(el("div", { class: "note warn" }, [icon("alert", 16),
      el("div", { html: "<b>Known limitation.</b> Nominal 95% intervals cover about 81% of " +
        "true states in synthetic validation, so this band is narrower than it should be. " +
        "Parameter and transfer uncertainty are not estimated at all." })]));
    v.appendChild(panel);

    /* ---- why it moved, and what the model cannot say ---- */
    const two = el("div", { class: "two" });

    const why = el("section", { class: "panel" });
    why.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "What moved the estimate" }),
      el("p", { class: "panel-s",
        text: "First-order decomposition for week " + String(NW - 1).padStart(2, "0") +
          ". These are observations associated with the change, not causes of it." }),
    ])]));
    why.appendChild(C.attribBars(D.attrib[NW - 1]));
    why.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "The grey <b>not attributable</b> bar is the higher-order term the " +
        "decomposition cannot assign to any channel. Most tools normalise it away so the " +
        "contributions sum to 100%." })]));
    two.appendChild(why);

    const know = el("section", { class: "panel" });
    know.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "What this screen is not telling you" }),
      el("p", { class: "panel-s", text: "The same limits appear beside every chart, not once in a footer." }),
    ])]));
    const kl = el("div", { class: "knows-list" });
    [["The latent state is not measured knowledge or motivation",
      "The construct-validity test (T4) has not been written. The dimension names are conventions."],
     ["Nothing here describes a real student",
      "The cohort is synthetic, generated from a known process. OULAD has never been run."],
     ["Hazard is not a verdict",
      "A weekly hazard of " + pct(lastHz, 2) + " is a probability under this model, not a judgement."],
     ["The replay is retrospective",
      "Weekly, historical data. Nothing in this product is real-time."],
    ].forEach(([t, sub]) => {
      kl.appendChild(el("div", { class: "knows-item" }, [icon("alert", 15),
        el("div", { html: t + "<span class='sub'>" + sub + "</span>" })]));
    });
    know.appendChild(kl);
    two.appendChild(know);
    v.appendChild(two);
    return v;
  }

  /* ============================================================
     TIMELINE  —  time as a first-class interaction
     ============================================================ */
  function viewTimeline() {
    const v = el("div", { class: "view" });
    let ribbon = null;

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "Timeline" }),
        el("p", { class: "view-s", text: "Select a week. The state, the observations fed to " +
          "the model, and the decomposition all move together." }),
      ]),
      el("span", { class: "chip chip-observed" }, [
        el("i", { class: "chip-dot" }), el("span", { text: NW + " observed weeks" })]),
    ]));

    /* scrubber */
    const scrub = el("div", { class: "tl-scrub" });
    const badge = el("span", { class: "tl-badge num", text: "W" + String(currentWeek).padStart(2, "0") });
    const steps = el("div", { class: "tl-steps", role: "group", "aria-label": "Select week" });
    const stepBtns = [];
    for (let i = 0; i < NW; i++) {
      const b2 = el("button", { type: "button", class: "tl-step",
        "aria-pressed": String(i === currentWeek), "aria-label": "Week " + i,
        text: String(i).padStart(2, "0") });
      b2.addEventListener("click", () => setWeek(i));
      stepBtns.push(b2);
      steps.appendChild(b2);
    }
    scrub.appendChild(el("div", {}, [el("span", { class: "lbl", text: "Week" }), badge]));
    scrub.appendChild(steps);
    scrub.appendChild(el("span", { class: "tl-w", text: "of " + NW + " observed" }));
    v.appendChild(scrub);

    /* the ribbon, pinned to the selected week */
    const panel = el("section", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [el("h2", { class: "panel-t", text: "State across the presentation" })]),
      ribbonKey(),
    ]));
    const rHost = el("div", {});
    ribbon = C.stateRibbon({
      mean: st.eng, sd: st.eng_sd, theta: theta, h: 380,
      sim: { lo: D.sim.base_lo, med: D.sim.base_med, hi: D.sim.base_hi },
      onSelect: (i) => setWeek(i),
      label: "Engagement across " + NW + " weeks with the selected week marked",
    });
    rHost.appendChild(ribbon);
    panel.appendChild(rHost);
    v.appendChild(panel);

    /* observation rail: the real tier-1 features */
    const rail = el("section", { class: "panel" });
    const railHost = el("div", {});
    if (D.obs && D.obs.rows && D.obs.rows.length) {
      rail.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
        el("h2", { class: "panel-t", text: "What the twin actually saw" }),
        el("p", { class: "panel-s", text: "The tier-1 features supplied to the model each week. " +
          "Intensity is magnitude relative to this student's own range; teal is positive, coral negative." }),
      ])]));
      rail.appendChild(railHost);
    } else {
      rail.appendChild(emptyState("No feature rail in this data file",
        "The exporter did not write <code>obs</code>. Regenerate with " +
        "<code>python scripts/export_web_data.py</code>. Nothing is being hidden."));
    }
    v.appendChild(rail);

    /* decomposition for the selected week */
    const two = el("div", { class: "two" });
    const att = el("section", { class: "panel" });
    const attHead = el("div", { class: "panel-h" });
    att.appendChild(attHead);
    const attHost = el("div", {});
    att.appendChild(attHost);
    att.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "Association, not cause. The <b>not attributable</b> bar is left in." })]));
    two.appendChild(att);

    const story = el("section", { class: "panel" });
    const storyHost = el("div", {});
    story.appendChild(storyHost);
    two.appendChild(story);
    v.appendChild(two);

    function setWeek(i) {
      currentWeek = i;
      badge.textContent = "W" + String(i).padStart(2, "0");
      stepBtns.forEach((b2, k) => b2.setAttribute("aria-pressed", String(k === i)));
      if (ribbon) ribbon.setWeek(i);

      if (D.obs && D.obs.rows) {
        railHost.innerHTML = "";
        const r = C.obsRail({ rows: D.obs.rows, cols: D.obs.cols, selected: i });
        r.style.cursor = "pointer";
        r.addEventListener("click", (e) => setWeek(r.pick(e.clientX)));
        railHost.appendChild(r);
      }

      attHead.innerHTML = "";
      attHead.appendChild(el("div", {}, [
        el("h2", { class: "panel-t", text: "Why the state moved in week " + String(i).padStart(2, "0") }),
        el("p", { class: "panel-s", text: "First-order contributions to the shift, in state units." }),
      ]));
      attHost.innerHTML = "";
      attHost.appendChild(C.attribBars(D.attrib[i]));

      const d0 = st.eng[i] - theta;
      const prev = i > 0 ? st.eng[i - 1] - theta : null;
      let below = 0;
      for (let k = i; k >= 0 && st.eng[k] < theta; k--) below++;
      const nObs = (D.obs && D.obs.n && D.obs.n[i] !== undefined) ? D.obs.n[i] : null;
      storyHost.innerHTML = "";
      storyHost.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
        el("h2", { class: "panel-t", text: "Week " + String(i).padStart(2, "0") + " in words" })])]));
      const dl = el("div", { class: "dl" });
      [["State", fmt(st.eng[i]), d0 < 0 ? "down" : "up", "±" + fmt(1.96 * st.eng_sd[i])],
       ["Deviation from own baseline", sign(d0), d0 < 0 ? "down" : "up",
        prev === null ? "first week" : "was " + sign(prev)],
       ["Consecutive weeks below baseline", d0 < 0 ? String(below) : "0", "", "including this one"],
       ["Weekly hazard", pct(D.hazard[i], 2), "", "model readout"],
       ["Observation rows", nObs === null ? "—" : String(nObs), "", "fed to the filter"],
      ].forEach((row) => {
        dl.appendChild(el("div", { class: "dl-r" }, [
          el("span", { class: "dl-k", text: row[0] }),
          el("span", {}, [
            el("span", { class: "dl-v " + (row[2] || ""), text: row[1] }),
            el("span", { class: "sub", text: row[3] })]),
        ]));
      });
      storyHost.appendChild(dl);
      storyHost.appendChild(el("div", { class: "note" }, [icon("clock", 16),
        el("div", { html: "Week " + i + " of a <b>retrospective</b> weekly replay. " +
          "The twin updates once per week of historical data; nothing here is live." })]));
    }

    setWeek(currentWeek);
    return v;
  }

  /* ============================================================
     DEEP DIVE  —  the student's own history is the reference
     ============================================================ */
  function viewDeep() {
    const v = el("div", { class: "view" });
    const own = st.eng;
    const ownMean = own.reduce((a, b) => a + b, 0) / own.length;
    const ownSd = Math.sqrt(own.reduce((a, b) => a + (b - ownMean) * (b - ownMean), 0) / own.length);
    let belowNow = 0;
    for (let k = NW - 1; k >= 0 && own[k] < theta; k--) belowNow++;
    let longest = 0, run = 0;
    own.forEach((x) => { run = x < theta ? run + 1 : 0; longest = Math.max(longest, run); });
    const nBelow = own.filter((x) => x < theta).length;

    const thetas = (D.cohort_states || []).map((c) => c.theta).sort((a, b) => a - b);
    const rank = thetas.length ? thetas.filter((x) => x < theta).length / thetas.length : null;

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "What is this student's normal?" }),
        el("p", { class: "view-s", text: "Every judgement in this product is made against θ — a " +
          "set point fitted from this student's own history, shrunk toward their cohort by an " +
          "amount the data decides rather than a constant we choose." }),
      ]),
      el("span", { class: "chip chip-synthetic" }, [
        el("i", { class: "chip-dot" }), el("span", { text: "Synthetic" })]),
    ]));

    const two = el("div", { class: "two" });

    const dist = el("section", { class: "panel" });
    dist.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "This student's own distribution" }),
        el("p", { class: "panel-s", text: "All " + NW + " observed weekly states. The dashed line " +
          "is θ; the solid line is where they are now." }),
      ]),
    ]));
    dist.appendChild(C.distribution({ values: own, theta: theta, now: lastEng, h: 320 }));
    dist.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "<b>" + nBelow + " of " + NW + " weeks</b> sit below this student's own " +
        "baseline, and the current run is <b>" + belowNow + " week" + (belowNow === 1 ? "" : "s") +
        "</b> long. Against the cohort the same student is unremarkable — that is the whole point " +
        "of measuring against θ." })]));
    two.appendChild(dist);

    const facts = el("section", { class: "panel" });
    facts.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "The set point" })])]));
    const dl = el("div", { class: "dl" });
    [["Fitted set point θ", fmt(theta), "", "empirical Bayes"],
     ["Own observed mean", fmt(ownMean), "", NW + " weeks"],
     ["Own observed SD", fmt(ownSd), "", "within-student"],
     ["Current deviation", sign(dev), dev < 0 ? "down" : "up", "vs own baseline"],
     ["Weeks below baseline", nBelow + " / " + NW, "", "longest run " + longest],
     ["Shrinkage k", fmt(D.shrinkage[0]), "", "estimated, not fixed"],
     ["Position in cohort θ", rank === null ? "—" : pct(rank, 0), "",
      rank === null ? "" : (D.cohort_states || []).length + " students"],
    ].forEach((row) => {
      dl.appendChild(el("div", { class: "dl-r" }, [
        el("span", { class: "dl-k", text: row[0] }),
        el("span", {}, [
          el("span", { class: "dl-v " + (row[2] || ""), text: row[1] }),
          el("span", { class: "sub", text: row[3] })]),
      ]));
    });
    facts.appendChild(dl);
    facts.appendChild(el("div", { class: "note warn" }, [icon("alert", 16),
      el("div", { html: "<b>No interval on θ.</b> The two-stage estimator returns a point " +
        "estimate for the set point. Reporting a credible interval would mean inventing one, " +
        "so this row is absent rather than plausible." })]));
    two.appendChild(facts);
    v.appendChild(two);

    /* cohort context, from real per-student fitted set points */
    if (D.cohort_states && D.cohort_states.length) {
      const coh = el("section", { class: "panel" });
      coh.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
        el("h2", { class: "panel-t", text: "Where this baseline sits among the cohort's" }),
        el("p", { class: "panel-s", text: "Fitted set points for all " + D.cohort_states.length +
          " students in the run. Two students with the same observed activity can sit on opposite " +
          "sides of their own baselines." }),
      ])]));
      coh.appendChild(C.distribution({ values: thetas, theta: theta, now: null, h: 240 }));
      coh.appendChild(el("div", { class: "note" }, [icon("info", 16),
        el("div", { html: "The dashed marker is <b>this</b> student's θ inside the distribution of " +
          "everyone else's θ. It is a position, not a rank to be acted on." })]));
      v.appendChild(coh);
    }
    return v;
  }

  /* ============================================================
     FUTURE LAB  —  where might this student go?
     ============================================================ */
  function viewFutures() {
    const sim = D.sim;
    const v = el("div", { class: "view" });
    let active = 0;

    const SCEN = [
      { name: "Current dynamics", color: css("--indigo-b"),
        med: sim.base_med, lo: sim.base_lo, hi: sim.base_hi, risk: sim.base_risk,
        paths: sim.particles || [],
        note: "No intervention applied. The model's own transition dynamics, run forward." },
      { name: "Engagement support", color: css("--teal-b"),
        med: sim.alt_med, lo: sim.alt_lo, hi: sim.alt_hi, risk: sim.alt_risk,
        paths: sim.alt_particles || [],
        note: "A sustained engagement shift of one state unit, applied from now onward." },
    ];

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "Where might this student go?" }),
        el("p", { class: "view-s", text: "Eight weeks forward from the last observation. " +
          "600 particles drawn from the current posterior; the thin threads are real individual " +
          "simulated paths, not interpolation between quantiles." }),
      ]),
      el("span", { class: "chip chip-simulated" }, [
        el("i", { class: "chip-dot" }), el("span", { text: "Model-generated" })]),
    ]));

    const picker = el("div", { class: "scen" });
    const panel = el("section", { class: "panel" });
    const chartHost = el("div", {});
    const metrics = el("div", { class: "mstrip" });
    const riskHost = el("div", {});
    const expl = el("div", { class: "note sim" });

    function paint() {
      picker.innerHTML = "";
      SCEN.forEach((sc, i) => {
        const b = el("button", { type: "button", class: "scen-b",
          "aria-pressed": String(i === active) }, [
          el("span", { class: "scen-dot" }),
          el("span", { class: "scen-n", text: sc.name }),
          el("span", { class: "scen-r num", text: pct(sc.risk[sc.risk.length - 1]) }),
        ]);
        b.querySelector(".scen-dot").style.background = sc.color;
        b.addEventListener("click", () => { active = i; paint(); });
        picker.appendChild(b);
      });

      chartHost.innerHTML = "";
      chartHost.appendChild(C.fanChart({
        obs: st.eng, theta: theta, h: 400,
        paths: SCEN[active].paths,
        branches: SCEN.map((sc, i) => ({ color: sc.color, med: sc.med, lo: sc.lo, hi: sc.hi,
          active: i === active })),
        label: "Observed engagement then two simulated scenario branches",
      }));

      const sc = SCEN[active];
      metrics.innerHTML = "";
      [["Projected state", fmt(sc.med[sc.med.length - 1]), "median at week +8"],
       ["Cumulative risk", pct(sc.risk[sc.risk.length - 1]), "simulated, 8 weeks"],
       ["Spread", "±" + fmt((sc.hi[sc.hi.length - 1] - sc.lo[sc.lo.length - 1]) / 2),
        "5th to 95th percentile"],
       ["Particles", "600", "drawn from the posterior"],
      ].forEach((row) => {
        metrics.appendChild(el("div", { class: "mchip" }, [el("div", { class: "mchip-l" }, [
          el("span", { class: "mchip-lbl", text: row[0] }),
          el("span", { class: "mchip-val num", text: row[1] }),
          el("span", { class: "mchip-sub", text: row[2] })])]));
      });

      riskHost.innerHTML = "";
      riskHost.appendChild(el("h3", { class: "panel-t", style: "font-size:1.05rem",
        text: "Cumulative simulated risk" }));
      riskHost.appendChild(el("p", { class: "panel-s", style: "margin-bottom:1rem",
        text: "Probability of the modelled event occurring at some point within the horizon. " +
          "It rises by construction." }));
      riskHost.appendChild(C.riskCurve({
        series: SCEN.map((s2, i) => ({ v: s2.risk, color: s2.color, active: i === active })),
        h: 180,
      }));

      expl.innerHTML = "";
      expl.appendChild(icon("beaker", 16));
      expl.appendChild(el("div", { html: "<b>Model-generated scenario. Not a causal estimate.</b> " +
        sc.note + " The dataset records no interventions, so the sensitivity is <em>assumed</em>, " +
        "not fitted. Read this as what the model's assumed transition dynamics imply, never as " +
        "what an action would achieve for a real student." }));
    }
    paint();

    panel.appendChild(picker);
    panel.appendChild(chartHost);
    panel.appendChild(expl);
    v.appendChild(panel);
    v.appendChild(metrics);

    const risk = el("section", { class: "panel" });
    risk.appendChild(riskHost);
    v.appendChild(risk);
    return v;
  }

  /* ============================================================
     INTERVENTION LAB  —  hypothesis testing, honestly labelled
     Each slider stop is its own forward simulation exported by
     the pipeline. Interpolating between two of them would be a
     picture of a model we never ran.
     ============================================================ */
  function viewLab() {
    const v = el("div", { class: "view" });
    const sweep = D.sweep;

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "What if?" }),
        el("p", { class: "view-s", text: "Change one model input and re-run the eight-week " +
          "simulation. Both trajectories are drawn on the same axis so the difference is " +
          "the only thing that moves." }),
      ]),
      el("span", { class: "chip chip-simulated" }, [
        el("i", { class: "chip-dot" }), el("span", { text: "Not a causal estimate" })]),
    ]));

    if (!sweep || !sweep.length) {
      v.appendChild(emptyState("No intervention sweep in this data file",
        "The exporter did not write <code>sweep</code>. Regenerate with " +
        "<code>python scripts/export_web_data.py</code> and reload. Rather than interpolate " +
        "between the two scenarios we do have, this screen shows nothing."));
      return v;
    }

    let k = sweep.length - 3;   // start at delta = 0.75, mid-range and visibly different
    const base = sweep[0];

    const wi = el("div", { class: "whatif" });
    const out = el("div", { class: "wi-out" });
    const range = el("input", { type: "range", min: "0", max: String(sweep.length - 1),
      step: "1", value: String(k), "aria-label": "Engagement support magnitude" });
    const stops = el("div", { class: "wi-stops" });
    sweep.forEach((sw) => stops.appendChild(el("span", { text: fmt(sw.d, 2) })));
    wi.appendChild(el("div", {}, [
      el("h2", { class: "wi-q", text: "Sustained engagement support" }),
      el("p", { class: "wi-s", text: "Applied from now to the end of the horizon, in latent " +
        "state units. Every stop on this slider is a separate 600-particle simulation that the " +
        "pipeline actually ran." }),
      range, stops,
    ]));
    wi.appendChild(out);
    v.appendChild(wi);

    const panel = el("section", { class: "panel" });
    panel.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Current dynamics versus the hypothetical" }),
        el("p", { class: "panel-s", text: "Solid is observed history. Both branches past the " +
          "boundary are dashed and hatched because both are model output." }),
      ]),
      el("div", { class: "panel-key" }, [
        keyd("observed", css("--ink")),
        keyd("current dynamics", css("--ink-3"), true),
        keyd("hypothetical", css("--indigo-b"), true),
      ]),
    ]));
    const chartHost = el("div", {});
    panel.appendChild(chartHost);
    panel.appendChild(el("div", { class: "note sim" }, [icon("beaker", 16),
      el("div", { html: "<b>The sensitivity C is assumed, not fitted.</b> No intervention was " +
        "ever recorded in this dataset, so nothing here estimates what support would do. This is " +
        "the model's assumed transition dynamics under a changed input, and nothing more." })]));
    v.appendChild(panel);

    const cmp = el("div", { class: "cmp" });
    v.appendChild(cmp);

    const riskPanel = el("section", { class: "panel" });
    const riskHost = el("div", {});
    riskPanel.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "Cumulative simulated risk, both branches" }),
      el("p", { class: "panel-s", text: "Under the model's assumed dynamics." })])]));
    riskPanel.appendChild(riskHost);
    v.appendChild(riskPanel);

    function paint() {
      const alt = sweep[k];
      const last = (a) => a[a.length - 1];

      out.innerHTML = "";
      out.appendChild(el("span", { class: "lbl", text: "Support applied" }));
      out.appendChild(el("div", { class: "wi-d num", text: sign(alt.d, 2) }));
      out.appendChild(el("div", { class: "wi-u", text: "latent state units / week" }));

      chartHost.innerHTML = "";
      chartHost.appendChild(C.fanChart({
        obs: st.eng, theta: theta, h: 380,
        paths: alt.d === 0 ? (D.sim.particles || []) : [],
        branches: [
          { color: css("--ink-3"), med: base.med, lo: base.lo, hi: base.hi, active: alt.d === 0 },
          { color: css("--indigo-b"), med: alt.med, lo: alt.lo, hi: alt.hi, active: alt.d !== 0 },
        ],
        label: "Current dynamics compared with a hypothetical engagement support of " + alt.d,
      }));

      cmp.innerHTML = "";
      const col = (title, cls, sw, chipText) => {
        const c = el("div", { class: "cmp-c " + cls });
        c.appendChild(el("div", { class: "cmp-h" }, [
          el("span", { class: "lbl", text: title }),
          el("span", { class: "chip chip-simulated", text: chipText })]));
        c.appendChild(el("div", { class: "cmp-v num", text: fmt(last(sw.med)) }));
        c.appendChild(el("div", { class: "cmp-d", text: "median state at week +8" }));
        c.appendChild(el("div", { style: "margin-top:1rem" }, [
          el("div", { class: "cmp-row" }, [el("span", { text: "Cumulative risk" }),
            el("span", { class: "num", text: pct(last(sw.risk)) })]),
          el("div", { class: "cmp-row" }, [el("span", { text: "5th percentile" }),
            el("span", { class: "num", text: fmt(last(sw.lo)) })]),
          el("div", { class: "cmp-row" }, [el("span", { text: "95th percentile" }),
            el("span", { class: "num", text: fmt(last(sw.hi)) })]),
          el("div", { class: "cmp-row" }, [el("span", { text: "vs own baseline" }),
            el("span", { class: "num", text: sign(last(sw.med) - theta) })]),
        ]));
        return c;
      };
      cmp.appendChild(col("Current dynamics", "", base, "simulated"));
      cmp.appendChild(col("Hypothetical, " + sign(alt.d, 2), "alt", alt, "simulated"));

      riskHost.innerHTML = "";
      riskHost.appendChild(C.riskCurve({
        series: [
          { v: base.risk, color: css("--ink-3"), active: alt.d === 0 },
          { v: alt.risk, color: css("--indigo-b"), active: alt.d !== 0 },
        ], h: 180,
      }));
      const gap = last(alt.risk) - last(base.risk);
      riskHost.appendChild(el("div", { class: "note sim" }, [icon("alert", 16),
        el("div", { html: "Under this model the two branches differ by <b>" +
          fmt(Math.abs(gap) * 100, 1) + " percentage points</b> of cumulative simulated risk over " +
          "eight weeks. That difference is a property of the assumed dynamics. It is not " +
          "evidence that support changes outcomes, and it must never be reported as one." })]));
    }

    range.addEventListener("input", (e) => { k = +e.target.value; paint(); });
    paint();
    return v;
  }

  /* ============================================================
     MODEL & DATA  —  provenance, evaluation, controls
     ============================================================ */
  function viewModel() {
    const v = el("div", { class: "view" });

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: "Model and data" }),
        el("p", { class: "view-s", text: D.provenance.note }),
      ]),
      el("span", { class: "chip chip-synthetic" }, [
        el("i", { class: "chip-dot" }), el("span", { text: "Synthetic cohort" })]),
    ]));

    const manifest = el("div", { class: "manifest" });
    const co = D.cohort || {};
    [["Students", co.students == null ? "\u2014" : String(co.students), "trajectories fitted"],
     ["Person-period rows", co.rows == null ? "\u2014" : String(co.rows), "forward-chained"],
     ["Events", co.events == null ? "\u2014" : String(co.events),
      co.rate == null ? "positives in evaluation" : pct(co.rate, 1) + " of rows"],
     ["Run seed", String(D.provenance.seed), "derived per purpose"],
     ["Model version", D.provenance.model_version || "\u2014",
      D.provenance.code_revision ? "code " + D.provenance.code_revision : "revision unknown"],
     ["Inference", "Laplace", "approximate Gaussian filter"],
    ].forEach((row) => {
      manifest.appendChild(el("div", { class: "mf" }, [
        el("div", { class: "mf-k", text: row[0] }),
        el("div", { class: "mf-v", text: row[1] }),
        el("div", { class: "mf-d", text: row[2] }),
      ]));
    });
    v.appendChild(manifest);

    /* comparison table */
    const perf = el("section", { class: "panel" });
    perf.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "Against baselines it could lose to" }),
      el("p", { class: "panel-s", text: "Forward-chained splits, identical folds for every " +
        "model. The twin is compared against baselines chosen to be hard, including a gradient " +
        "boosting model on the same features." }),
    ])]));
    const tb = el("table");
    tb.appendChild(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Model" }), el("th", { text: "AUC" }),
      el("th", { text: "Brier" }), el("th", { text: "ECE" }), el("th", { text: "n" })])]));
    const tbody = el("tbody");
    (D.metrics || []).forEach((m) => {
      const tr = el("tr", m.model_name === "twin_state" ? { class: "hl" } : {});
      [m.model_name.replace(/_/g, " "), fmt(m.auc, 3), fmt(m.brier, 4), fmt(m.ece, 4),
       String(m.n)]
        .forEach((c) => tr.appendChild(el("td", { class: "num", text: c })));
      tbody.appendChild(tr);
    });
    tb.appendChild(tbody);
    perf.appendChild(el("div", { class: "tw" }, [tb]));
    perf.appendChild(el("div", { class: "note warn" }, [icon("alert", 16),
      el("div", { html: "<b>The twin does not win on calibration.</b> Its ECE is worse than " +
        "three of the four baselines. That is in the table because deleting it would be the " +
        "dishonest choice, and because a well-calibrated wrong answer is still wrong." })]));
    v.appendChild(perf);

    /* negative controls */
    const nc = el("section", { class: "panel" });
    nc.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "Negative controls" }),
      el("p", { class: "panel-s", text: "Each control states in advance what it expects to see. " +
        "A control that survives when it should collapse is a leak; one that collapses when it " +
        "should survive tells us the signal was never there." }),
    ])]));
    const ct = el("table");
    ct.appendChild(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Control" }), el("th", { text: "AUC" }), el("th", { text: "Verdict" })])]));
    const cbody = el("tbody");
    (D.controls || []).forEach((c) => {
      const tr = el("tr", {});
      tr.appendChild(el("td", { text: c.control.replace(/_/g, " ") }));
      tr.appendChild(el("td", { class: "num", text: fmt(c.auc, 3) }));
      const cls = c.verdict === "COLLAPSED" ? "ok" : c.verdict === "SURVIVED" ? "warn" : "";
      tr.appendChild(el("td", {}, [
        el("span", { class: "verdict " + cls, text: c.verdict })]));
      cbody.appendChild(tr);
    });
    ct.appendChild(cbody);
    nc.appendChild(el("div", { class: "tw" }, [ct]));
    nc.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "<b>permute_time survived.</b> Shuffling the weeks within a student " +
        "barely moves AUC, which means the readout is currently driven by the student's overall " +
        "<em>level</em> rather than by the shape of their trajectory. It is the most important " +
        "open weakness in the prototype and it is reported here rather than buried." })]));
    v.appendChild(nc);

    /* coverage */
    const cov = el("section", { class: "panel" });
    cov.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "Channel coverage" }),
      el("p", { class: "panel-s", text: "Every adapter must declare every canonical event type " +
        "as available or unavailable. Silence is not permitted by the schema." }),
    ])]));
    const cw = el("div", { class: "two" });
    const mk = (title, list, cls) => {
      const b = el("div", {});
      b.appendChild(el("p", { class: "lbl", style: "margin-bottom:.6rem", text: title }));
      const wrap = el("div", { style: "display:flex;flex-wrap:wrap;gap:.35rem" });
      list.forEach((x) => wrap.appendChild(el("span", { class: "chip " + cls, text: x.replace(/_/g, " ") })));
      b.appendChild(wrap);
      return b;
    };
    const covr = D.coverage || { available: [], unavailable: [] };
    cw.appendChild(mk("Available in this run", covr.available, "chip-observed"));
    cw.appendChild(mk("Declared unavailable", covr.unavailable, ""));
    cov.appendChild(cw);
    cov.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "Physiological and multimodal sensing appear in the schema as " +
        "<b>permanently unavailable</b>. They are declared so that no adapter can quietly " +
        "pretend to supply them, and they are out of scope for this project." })]));
    v.appendChild(cov);

    /* capability tests */
    const cap = el("section", { class: "panel" });
    cap.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "Twin capability tests" }),
      el("p", { class: "panel-s", text: "A digital twin is a claim with tests attached. " +
        "Two of the four have not been written, which is stated here rather than in a footnote." }),
    ])]));
    const caps = el("div", { class: "dl" });
    [["T1 · Persistence", "PASS", "ok", "recursive update equals full replay to 0.00e+00"],
     ["T2 · Generativity", "PASS", "ok", "90% band covers 89.6% of held-out observations"],
     ["T3 · Intervenability", "NOT IMPLEMENTED", "", "mechanism works; stability across refits untested"],
     ["T4 · Construct validity", "NOT IMPLEMENTED", "", "the dimension names remain conventions"],
    ].forEach((row) => {
      caps.appendChild(el("div", { class: "dl-r" }, [
        el("span", { class: "dl-k", text: row[0] }),
        el("span", {}, [
          el("span", { class: "verdict " + row[2], text: row[1] }),
          el("span", { class: "sub", text: row[3] })]),
      ]));
    });
    cap.appendChild(caps);
    v.appendChild(cap);
    return v;
  }

  /* ============================================================
     MY TWIN  —  a Twin with zero observations, and honest about it
     ============================================================ */
  function viewMyTwin() {
    const raw = Store.read2();
    const p = raw ? v2fold(raw) : Store.read();
    const v = el("div", { class: "view" });

    if (!p) {
      v.appendChild(emptyState("No Twin on this device",
        "Nothing has been created yet, and there is nothing to show. " +
        "<a class='link-btn' href='#/onboarding' data-go='onboarding'>Create your Twin</a>"));
      return v;
    }

    v.appendChild(el("div", { class: "view-head" }, [
      el("div", {}, [
        el("h1", { class: "view-t", text: (p.name || "Your") + "'s Twin" }),
        el("p", { class: "view-s", text: "Created from " +
          (p.courses.length || 0) + " course" + (p.courses.length === 1 ? "" : "s") +
          " and your own answers. It has not observed a single week yet." }),
      ]),
      el("span", { class: "chip" }, [el("i", { class: "chip-dot" }),
        el("span", { text: "0 observations" })]),
    ]));

    const strip = el("div", { class: "mstrip" });
    [["Observations", "0", "weeks collected"],
     ["State estimate", "prior", "cohort mean, maximum uncertainty"],
     ["Personal baseline θ", "not fitted", "needs your own history"],
     ["Simulation", "unavailable", "nothing to run forward"],
    ].forEach((row) => {
      strip.appendChild(el("div", { class: "mchip" }, [el("div", { class: "mchip-l" }, [
        el("span", { class: "mchip-lbl", text: row[0] }),
        el("span", { class: "mchip-val", text: row[1] }),
        el("span", { class: "mchip-sub", text: row[2] })])]));
    });
    v.appendChild(strip);

    const learn = el("section", { class: "learning" });
    learn.appendChild(el("h2", { class: "panel-t", text: "Your Twin has nothing to show yet, and that is correct" }));
    learn.appendChild(el("p", { style: "max-width:70ch",
      text: "A trajectory needs observations. Yours has none, so the filter has nothing to " +
        "update on and your state sits at the cohort prior with the widest uncertainty the " +
        "model can express. Drawing a line here would be fabrication, so there is no line." }));
    learn.appendChild(el("p", { style: "max-width:70ch",
      text: "The prototype cannot yet collect weekly behavioural observations — that requires a " +
        "connection to a learning platform, which does not exist. Everything you entered is " +
        "stored on this device as context; none of it is model input." }));
    const acts = el("div", { class: "hero-cta", style: "margin-top:1.5rem" });
    const b1 = el("button", { type: "button", class: "btn btn-primary" },
      [el("span", { text: "See a Twin with 20 weeks of data" }), icon("arrow", 16)]);
    b1.addEventListener("click", () => go("app/home"));
    acts.appendChild(b1);
    const b2 = el("button", { type: "button", class: "btn btn-ghost", text: "Edit my answers" });
    b2.addEventListener("click", () => { if (window.ST_Onboarding) window.ST_Onboarding.reset(); go("onboarding"); });
    acts.appendChild(b2);
    learn.appendChild(acts);
    v.appendChild(learn);

    /* what was stored, and how each part is used */
    const rec = el("section", { class: "panel" });
    rec.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "What is stored, and what it is used for" }),
      el("p", { class: "panel-s", text: "On this device only. No account, no server, no network request." }),
    ])]));
    const dl = el("div", { class: "dl" });
    const rows = [
      ["Name", p.name || "—", "Profile only"],
      ["Year of study", p.level || "—", "Stored as context"],
      ["Institution", p.institution || "—", "Profile only"],
      ["Courses", p.courses.length ? p.courses.join(", ") : "—", "Stored as context"],
      ["Self-reported study hours", p.baseline.study_hours === undefined ? "—" :
        String(p.baseline.study_hours), "Stored as context"],
      ["Consent given", p.consent ? "yes" : "no", "Profile only"],
    ];
    rows.forEach((row) => {
      dl.appendChild(el("div", { class: "dl-r" }, [
        el("span", { class: "dl-k", text: row[0] }),
        el("span", {}, [
          el("span", { class: "dl-v", style: "font-size:.9rem", text: row[1] }),
          el("span", { class: "sub", text: row[2] })]),
      ]));
    });
    rec.appendChild(dl);
    rec.appendChild(el("div", { class: "note warn" }, [icon("alert", 16),
      el("div", { html: "<b>None of this is model input.</b> The inference model learns from " +
        "weekly behavioural observations. Self-reported answers are kept as context for a " +
        "future version and are labelled that way throughout." })]));
    const del = el("button", { type: "button", class: "btn btn-ghost", style: "margin-top:1.25rem",
      text: "Delete my Twin from this device" });
    del.addEventListener("click", () => {
      Store.clear();
      if (window.ST_Onboarding) window.ST_Onboarding.reset();
      go("");
    });
    rec.appendChild(del);
    v.appendChild(rec);
    return v;
  }

  /* ============================================================
     SHELL
     ============================================================ */
  const VIEWS = {
    mytwin:   { label: "My Twin",   icon: "user",   render: viewMyTwin,  mode: "personal", group: "Subject" },
    home:     { label: "Twin Home", icon: "home",   render: viewHome,    mode: "demo", group: "Subject" },
    timeline: { label: "Timeline",  icon: "clock",  render: viewTimeline, mode: "demo", group: "Subject" },
    deep:     { label: "Deep Dive", icon: "layers", render: viewDeep,    mode: "demo", group: "Subject" },
    futures:  { label: "Future Lab", icon: "branch", render: viewFutures, mode: "demo", group: "Simulation" },
    lab:      { label: "Intervention Lab", icon: "beaker", render: viewLab, mode: "demo", group: "Simulation" },
    model:    { label: "Model & data", icon: "db",  render: viewModel,   mode: "demo", group: "Provenance" },
  };

  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "??";
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }

  function mountApp(route) {
    const app = $("#app");
    app.innerHTML = "";
    const mode = VIEWS[route].mode;
    const personal = mode === "personal";
    const prof = Store.read2();

    /* ---- sidebar: quiet, grouped, and it reports the Twin ---- */
    const side = el("aside", { class: "side" });
    const brand = el("button", { type: "button", class: "side-brand" },
      [icon("twin", 20), el("span", { text: "StudyTwin" })]);
    brand.addEventListener("click", () => go(""));
    side.appendChild(brand);

    const nav = el("nav", { class: "side-nav", "aria-label": "Application" });
    let lastGroup = null;
    Object.entries(VIEWS).filter(([, c]) => c.mode === mode).forEach(([k, cfg]) => {
      if (cfg.group !== lastGroup) {
        nav.appendChild(el("div", { class: "side-sec", text: cfg.group }));
        lastGroup = cfg.group;
      }
      const b = el("button", { type: "button" },
        [icon(cfg.icon, 17), el("span", { text: cfg.label })]);
      if (k === route) b.setAttribute("aria-current", "page");
      b.addEventListener("click", () => go(personal ? "twin" : "app/" + k));
      nav.appendChild(b);
    });
    if (personal) {
      nav.appendChild(el("div", { class: "side-sec", text: "Reference" }));
      const toDemo = el("button", { type: "button" },
        [icon("layers", 17), el("span", { text: "Explore the demo" })]);
      toDemo.addEventListener("click", () => go("app/home"));
      nav.appendChild(toDemo);
    }
    side.appendChild(nav);

    const obsN = personal ? 0 : NW;
    side.appendChild(el("div", { class: "side-status" }, [
      el("p", { class: "ss-h", text: "Twin status" }),
      el("div", { class: "ss-live" }, [
        el("span", { class: "ss-dot" }),
        el("span", { text: personal ? "Initialised" : "Active" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Observations" }),
        el("b", { text: obsN + " wks" })]),
      el("div", { class: "ss-bar" }, [
        el("i", { class: "ss-fill", style: "width:" + Math.min(100, obsN * 5) + "%" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Data" }),
        el("b", { text: personal ? "none" : "synthetic" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Inference" }),
        el("b", { text: "laplace" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Baseline θ" }),
        el("b", { text: personal ? "not fitted" : fmt(theta) })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Source" }),
        el("b", { text: BOOT.mode === "api" ? "live api" : "snapshot" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Run" }),
        el("b", { text: D.provenance.run_id
          ? D.provenance.run_id.slice(0, 8) : "bundled" })]),
    ]));

    side.appendChild(el("div", { class: "side-foot", html: personal
      ? "No observations collected.<br>Estimates are the cohort prior."
      : "Synthetic cohort.<br>Never run on real OULAD data." }));
    const back = el("button", { type: "button", class: "side-back" },
      [icon("back", 15), el("span", { text: "Back to site" })]);
    back.addEventListener("click", () => go(""));
    side.appendChild(back);
    app.appendChild(side);

    /* ---- main ---- */
    const main = el("div", { class: "main" });
    const top = el("header", { class: "topbar" });
    const name = personal ? ((prof && prof.identity && prof.identity.name) || "Your Twin")
                          : "Student " + D.student.id;
    top.appendChild(el("div", { class: "subject" }, [
      el("div", { class: "subject-av", text: personal ? initials(name) : "ST" }),
      el("div", {}, [
        el("div", { class: "sid", text: name }),
        el("div", { class: "smeta", text: personal
          ? ((prof && prof.courses && prof.courses.length
              ? prof.courses.length + " COURSES · " : "") + "0 OBSERVED WEEKS")
          : D.student.context + " · " + D.student.weeks + " OBSERVED WEEKS" }),
      ]),
    ]));
    const sp = el("div", { class: "topbar-sp" });
    top.appendChild(sp);
    if (!personal) {
      top.appendChild(el("div", { class: "topbar-wk" }, [
        el("span", { class: "v num", text: "W" + String(NW - 1).padStart(2, "0") }),
        el("span", { class: "of", text: "/ " + NW }),
      ]));
    }
    // Provenance describes THIS Twin. A Twin you created has no dataset and no
    // run seed, so borrowing the demo run's labels here would be a small lie.
    top.appendChild(el("div", { class: "prov" }, personal
      ? [el("span", { class: "chip", text: "No data source" }),
         el("span", { class: "chip", text: "Local to this device" })]
      : [el("span", { class: "chip chip-synthetic" }, [el("i", { class: "chip-dot" }),
          el("span", { text: D.provenance.synthetic ? "Synthetic data" : D.provenance.dataset })]),
         el("span", { class: "chip", text: "seed " + D.provenance.seed }),
         sourceChip()]));
    main.appendChild(top);

    // Say it at the top of every screen, not in a tooltip: a snapshot that
    // silently stands in for live data is the failure this layer exists to stop.
    if (BOOT.mode === "snapshot") {
      main.appendChild(el("div", { class: "src-banner" }, [
        icon("alert", 15),
        el("span", { html: "<b>Offline snapshot.</b> " +
          (D.fallback_reason || "The API did not respond.") +
          " These are real pipeline numbers from a bundled export, not live " +
          "results. <code>" + (D.fallback_hint || "") + "</code>" }),
      ]));
    }
    main.appendChild(el("div", { class: "mode-banner " + (personal ? "personal" : "demo") }, [
      icon(personal ? "user" : "info", 15),
      el("span", { html: personal
        ? "<b>Your Twin.</b> Zero observations collected. Every estimate here is the cohort prior."
        : "<b>Demo Twin.</b> One synthetic student. Nothing on these screens describes a real person." }),
    ]));

    const bad = contractViolations();
    if (bad.length) {
      main.appendChild(el("div", { class: "view" }, [
        emptyState(
          "The data file is missing " + bad.length + " required field" + (bad.length > 1 ? "s" : ""),
          "Absent: <code>" + bad.join("</code>, <code>") + "</code>.<br>" +
          "Regenerate with <code>python scripts/export_web_data.py</code>, then reload. " +
          "No result is being hidden — the file simply does not carry these fields.",
          "err"
        ),
      ]));
    } else {
      main.appendChild(boundary(VIEWS[route].label, VIEWS[route].render));
    }
    app.appendChild(main);
  }

  /* ---------------------------------------------- router ---- */
  function go(hash) {
    if (location.hash.replace(/^#\/?/, "") === hash) render();
    else location.hash = hash;
  }
  function render() {
    const h = location.hash.replace(/^#\/?/, "");
    const site = $("#site"), app = $("#app");

    if (h.startsWith("onboarding")) {
      site.hidden = true; app.hidden = false;
      app.className = ""; app.innerHTML = "";
      app.appendChild(boundary("Onboarding", () => {
        if (!window.ST_Onboarding) {
          return emptyState("The onboarding module did not load",
            "<code>onboarding.js</code> is missing or threw while parsing. " +
            "Reload the page; if it persists, check the browser console.", "err");
        }
        return window.ST_Onboarding.render(OB_CTX);
      }));
      window.scrollTo(0, 0);
      return;
    }
    if (h === "twin/new") {
      site.hidden = true; app.hidden = false;
      app.className = ""; app.innerHTML = "";
      app.appendChild(boundary("Initialisation", viewInit));
      window.scrollTo(0, 0);
      return;
    }
    if (h.startsWith("twin")) {
      site.hidden = true; app.hidden = false;
      app.className = "app";
      mountApp("mytwin");
      window.scrollTo(0, 0);
      return;
    }
    if (h.startsWith("app")) {
      const route = h.split("/")[1] || "home";
      site.hidden = true; app.hidden = false;
      app.className = "app";
      mountApp(VIEWS[route] && VIEWS[route].mode === "demo" ? route : "home");
      window.scrollTo(0, 0);
      return;
    }
    site.hidden = false; app.hidden = true;
    app.innerHTML = "";
    mountLanding();
  }

  /* ============================================================
     LANDING VISUALS
     Every one is built from real pipeline output; none exists to
     fill space.
     ============================================================ */

  /** The hero. A dial, not a chart - see charts.js for why. The legend
      doubles as the interaction: hovering a layer name focuses it. */
  function heroField(host) {
    const wrap = el("div", { class: "tf" });
    const stage = el("div", { class: "tf-stage" });
    const dial = C.twinField({
      mean: st.eng, sd: st.eng_sd, theta: theta,
      sim: { lo: D.sim.base_lo, med: D.sim.base_med, hi: D.sim.base_hi },
    });
    stage.appendChild(dial);
    wrap.appendChild(stage);

    const LAYERS = [
      { k: "observations", n: "Past observations", v: NW + " weeks",
        c: css("--teal-b"), cls: "" },
      { k: "baseline", n: "Personal baseline", v: "θ " + fmt(theta), c: css("--amber"), cls: "ring" },
      { k: "current", n: "Current state", v: fmt(lastEng), c: dev < 0 ? css("--coral-b") : css("--teal-b"), cls: "" },
      { k: "futures", n: "Possible futures", v: "8 weeks", c: css("--indigo-b"), cls: "" },
      { k: "uncertainty", n: "Uncertainty", v: "±" + fmt(1.96 * lastSd), c: css("--teal"), cls: "band" },
    ];
    const legend = el("div", { class: "tf-legend" });
    LAYERS.forEach((L) => {
      const b = el("button", { type: "button", class: "tf-item", "aria-current": "false" }, [
        el("i", { class: "tf-mark " + L.cls }),
        el("span", {}, [
          el("span", { class: "tf-n", text: L.n }),
          el("span", { class: "tf-v num", text: L.v })]),
      ]);
      const mark = b.querySelector(".tf-mark");
      if (L.cls === "ring") mark.style.borderColor = L.c;
      else if (L.cls === "band") { mark.style.background = L.c; mark.style.borderColor = L.c; }
      else mark.style.background = L.c;
      const on = () => {
        dial.focusLayer(L.k);
        legend.querySelectorAll(".tf-item").forEach((x) => x.setAttribute("aria-current", "false"));
        b.setAttribute("aria-current", "true");
      };
      const off = () => {
        dial.focusLayer(null);
        b.setAttribute("aria-current", "false");
      };
      b.addEventListener("pointerenter", on);
      b.addEventListener("focus", on);
      b.addEventListener("pointerleave", off);
      b.addEventListener("blur", off);
      legend.appendChild(b);
    });
    wrap.appendChild(legend);
    host.appendChild(wrap);
  }

  /* ============================================================
     FOUR MOVES  -  one interactive system diagram

     Not four cards. Selecting a stage changes what ONE diagram
     emphasises, because the claim is that these are four moves of a
     single object rather than four separate features.

     `Run the next week` advances the underlying week and walks the
     four stages in order, so the loop is watched rather than read.
     ============================================================ */
  const STAGES = [
    { n: "Observe",
      d: "New learning signals arrive for the week.",
      note: "Silence is a signal too. A week with no activity is evidence, not a gap - "
          + "which is why the submission channel is Bernoulli rather than a missing count." },
    { n: "Predict",
      d: "Push last week's state forward and widen the uncertainty.",
      note: "The state drifts toward the student's own baseline at a fitted rate, and the "
          + "interval widens because a week has passed and nothing has been seen yet." },
    { n: "Update",
      d: "Fold in what actually happened; the interval narrows.",
      note: "Evidence pulls the distribution toward what was observed. How far it moves "
          + "depends on how much the model trusts that channel." },
    { n: "State",
      d: "The posterior becomes next week's starting point.",
      note: "Verified: updating recursively equals replaying the whole history from "
          + "scratch, to 0.00e+00. That is test T1, and it is what makes the state a twin "
          + "rather than a rolling feature window." },
  ];

  function thinkSection(host) {
    let stage = 0;
    let week = Math.min(NW - 1, Math.max(1, NW - 3));
    let timer = null;

    const rail = el("div", { class: "stages", role: "tablist",
      "aria-label": "Model stages" });
    const body = el("div", { class: "loop-body" });
    const vis = el("div", { class: "loop-vis" });
    const note = el("p", { class: "stage-say" });
    const meta = el("div", { class: "loop-meta" });
    body.appendChild(vis);
    body.appendChild(el("div", { class: "loop-foot" }, [note, meta]));

    function frame() {
      const att = D.attrib[week] || {};
      const prevAtt = D.attrib[week - 1];
      const prev = {
        mean: prevAtt ? prevAtt.post : st.eng[Math.max(week - 1, 0)],
        sd: (prevAtt && prevAtt.post_sd) || st.eng_sd[Math.max(week - 1, 0)],
      };
      // A run ingested before prior_sd existed has no PREDICT interval. Rather
      // than invent one, fall back to the posterior SD and say so in the meta line.
      const havePrior = att.prior_sd !== undefined && att.prior_sd !== null;
      return {
        theta: theta, week: week, stage: stage, hazard: D.hazard[week],
        prev: prev,
        prior: {
          mean: att.prior !== undefined ? att.prior : st.eng[week],
          sd: havePrior ? att.prior_sd : st.eng_sd[week],
        },
        post: {
          mean: att.post !== undefined ? att.post : st.eng[week],
          sd: (att.post_sd !== undefined && att.post_sd !== null)
            ? att.post_sd : st.eng_sd[week],
        },
        obs: (D.obs && D.obs.rows && D.obs.rows[week])
          ? channelsAt(week) : {},
        havePrior: havePrior,
      };
    }

    function channelsAt(w) {
      // The decomposition names the channels that actually moved the state
      // this week, with their contributions. Those ARE the observations the
      // filter used, so no separate source is needed.
      const rec = D.attrib[w];
      return rec ? rec.ch : {};
    }

    function paint() {
      const f = frame();
      Array.prototype.forEach.call(rail.children, (c, k) => {
        c.setAttribute("aria-pressed", String(k === stage));
      });
      vis.innerHTML = "";
      vis.appendChild(C.modelLoop(f));
      note.textContent = STAGES[stage].note;

      meta.innerHTML = "";
      meta.appendChild(el("span", { class: "lbl",
        text: "Week " + String(week).padStart(2, "0") + " of " + NW }));
      meta.appendChild(el("span", { class: "loop-num", html:
        "predict <b class='num'>±" + fmt(1.96 * f.prior.sd) + "</b>" +
        "<i>→</i>update <b class='num'>±" + fmt(1.96 * f.post.sd) + "</b>" }));
      if (!f.havePrior) {
        meta.appendChild(el("span", { class: "loop-warn",
          text: "prediction interval not stored for this run" }));
      }
    }

    STAGES.forEach((stg, i) => {
      const b = el("button", { type: "button", class: "stage-btn",
        "aria-pressed": String(i === 0) }, [
        el("span", { class: "stage-n", text: String(i + 1).padStart(2, "0") }),
        el("span", { class: "stage-t", text: stg.n }),
        el("span", { class: "stage-d", text: stg.d }),
      ]);
      b.addEventListener("click", () => { stop(); stage = i; paint(); });
      b.addEventListener("focus", () => { stop(); stage = i; paint(); });
      rail.appendChild(b);
    });

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      runBtn.classList.remove("is-running");
      runBtn.querySelector("span").textContent = "Run the next week";
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const runBtn = el("button", { type: "button", class: "btn btn-ghost loop-run" },
      [el("span", { text: "Run the next week" }), icon("refresh", 16)]);
    runBtn.addEventListener("click", () => {
      if (timer) { stop(); return; }
      week = week + 1 >= NW ? 1 : week + 1;
      stage = 0;
      paint();
      if (reduced) { stage = 3; paint(); return; }
      runBtn.classList.add("is-running");
      runBtn.querySelector("span").textContent = "Running…";
      timer = setInterval(() => {
        if (stage >= 3) { stop(); return; }
        stage += 1;
        paint();
      }, 850);
    });

    host.appendChild(el("div", { class: "loop-head" }, [rail, runBtn]));
    host.appendChild(body);
    paint();
  }

  /* ============================================================
     THE TWIN REMEMBERS  -  scroll-driven, two columns

     Left: the six sentences of the loop, each one a scroll step.
     Right: the belief for one week, revealed step by step, plus a
     vertical week rail so time is directly selectable.

     Scroll drives the step because the argument IS sequential. It
     degrades to a static, fully-revealed diagram under
     prefers-reduced-motion.
     ============================================================ */
  const MEMORY_STEPS = [
    ["Last week's answer becomes this week's starting point.",
     "The twin does not re-read the term. It starts from the posterior it "
     + "finished with, which is the whole content of the word <em>remembers</em>."],
    ["It predicts.",
     "The state is pushed forward through the transition and drifts toward this "
     + "student's own baseline at a fitted rate."],
    ["Uncertainty widens.",
     "A week has passed and nothing has been observed yet, so the interval grows "
     + "by the process noise. This widening is the model's own, not an illustration."],
    ["An observation arrives.",
     "The week's canonical channels enter as evidence. A zero is a datum here, "
     + "not a gap."],
    ["It updates, and uncertainty narrows.",
     "The distribution contracts toward what was seen. How far depends on how "
     + "much the model trusts each channel."],
    ["This week's state.",
     "Which becomes next week's starting point, and the loop closes."],
  ];

  function memorySection(host) {
    let week = NW - 1;
    let step = 0;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const wrap = el("div", { class: "mem" });
    const left = el("ol", { class: "mem-steps" });
    const right = el("div", { class: "mem-vis" });
    const stage = el("div", { class: "mem-stage" });
    const railHost = el("div", { class: "mem-rail" });
    right.appendChild(el("div", { class: "mem-panel" }, [railHost, stage]));

    MEMORY_STEPS.forEach((sp, i) => {
      const li = el("li", { class: "mem-step", "data-step": String(i) }, [
        el("span", { class: "mem-n", text: String(i + 1).padStart(2, "0") }),
        el("div", {}, [
          el("p", { class: "mem-t", text: sp[0] }),
          el("p", { class: "mem-d", html: sp[1] }),
        ]),
      ]);
      // Clicking SCROLLS to the step rather than setting it directly. The step
      // is a function of scroll position, so a click that set it without moving
      // the page would be immediately overridden by the next observer callback -
      // the two controls would fight, and scroll would win.
      li.addEventListener("click", () => {
        if (reduced) { setStep(i); return; }
        li.scrollIntoView({ behavior: "smooth", block: "center" });
        setStep(i);
      });
      left.appendChild(li);
    });

    function frameFor(w) {
      const att = D.attrib[w] || {};
      const prevAtt = D.attrib[w - 1];
      return {
        theta: theta, week: w, step: reduced ? 5 : step,
        prev: {
          mean: prevAtt ? prevAtt.post : st.eng[Math.max(w - 1, 0)],
          sd: (prevAtt && prevAtt.post_sd) || st.eng_sd[Math.max(w - 1, 0)],
        },
        prior: {
          mean: att.prior !== undefined ? att.prior : st.eng[w],
          sd: (att.prior_sd !== undefined && att.prior_sd !== null)
            ? att.prior_sd : st.eng_sd[w],
        },
        post: {
          mean: att.post !== undefined ? att.post : st.eng[w],
          sd: (att.post_sd !== undefined && att.post_sd !== null)
            ? att.post_sd : st.eng_sd[w],
        },
      };
    }

    function paint() {
      stage.innerHTML = "";
      stage.appendChild(C.beliefEvolution(frameFor(week)));
      railHost.innerHTML = "";
      const rail = C.weekRail({
        n: NW, selected: week,
        above: st.eng.map((v) => v >= theta),
      });
      rail.style.cursor = "pointer";
      rail.addEventListener("click", (e) => { week = rail.pick(e.clientY); paint(); });
      railHost.appendChild(rail);
      Array.prototype.forEach.call(left.children, (li, i) => {
        li.setAttribute("aria-current", String(i === step));
      });
    }

    function setStep(i) {
      const next = Math.max(0, Math.min(MEMORY_STEPS.length - 1, i));
      if (next === step) return;
      step = next;
      paint();
    }

    wrap.appendChild(left);
    wrap.appendChild(right);
    host.appendChild(wrap);
    paint();

    if (!reduced && "IntersectionObserver" in window) {
      // Scroll progress selects the step. The observer is only a cheap trigger:
      // when anything crosses the band we recompute which step is NEAREST the
      // viewport centre. Taking whichever entry happened to fire last is
      // non-deterministic when two items are in the band at once, and it made
      // the active step disagree with what the reader is looking at.
      const pickNearest = () => {
        const mid = window.innerHeight / 2;
        let best = 0, bestD = Infinity;
        Array.prototype.forEach.call(left.children, (li, i) => {
          const r = li.getBoundingClientRect();
          const d = Math.abs((r.top + r.bottom) / 2 - mid);
          if (d < bestD) { bestD = d; best = i; }
        });
        setStep(best);
      };
      const io = new IntersectionObserver(pickNearest,
        { rootMargin: "-40% 0px -40% 0px", threshold: 0 });
      Array.prototype.forEach.call(left.children, (li) => io.observe(li));
    }
  }

  /** Same student, two questions. Real cohort values on both axes. */
  function cohortStrip(host) {
    const pts = D.cohort_states || [];
    if (!pts.length) { host.appendChild(emptyState("No cohort summary in this data file", "")); return; }
    const W = 1000, H = 300, L = 62, R = 30, T = 26, B = 46;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const xs = pts.map((p) => p.mean_state);
    const ys = pts.map((p) => p.last_state - p.theta);
    const xlo = Math.min.apply(null, xs) - .2, xhi = Math.max.apply(null, xs) + .2;
    const ylo = Math.min.apply(null, ys) - .2, yhi = Math.max.apply(null, ys) + .2;
    const X = (v) => x0 + ((v - xlo) / (xhi - xlo)) * (x1 - x0);
    const Y = (v) => y1 - ((v - ylo) / (yhi - ylo)) * (y1 - y0);
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, style: "width:100%;height:auto",
      role: "img", "aria-label": "Each student's average activity against their deviation " +
        "from their own baseline. The two are close to unrelated." });
    const cInk4 = css("--ink-4"), cLine = css("--line");
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(0), y2: Y(0), stroke: css("--amber"),
      "stroke-width": 1.2, "stroke-dasharray": "6 5" }));
    g.appendChild(s("line", { x1: x0, x2: x1, y1: y1, y2: y1, stroke: cLine }));
    g.appendChild(s("line", { x1: x0, x2: x0, y1: y0, y2: y1, stroke: cLine }));
    pts.forEach((p) => {
      const d0 = p.last_state - p.theta, isMe = p.student_id === D.student.id;
      g.appendChild(s("circle", { cx: X(p.mean_state), cy: Y(d0), r: isMe ? 6 : 2.6,
        fill: isMe ? css("--coral-b") : (d0 >= 0 ? css("--teal") : css("--coral")),
        "fill-opacity": isMe ? 1 : .4 }));
      if (isMe) g.appendChild(s("circle", { cx: X(p.mean_state), cy: Y(d0), r: 12,
        fill: "none", stroke: css("--coral-b"), "stroke-width": 1, "stroke-opacity": .55 }));
    });
    const lab = (x, y, t, col, anchor) => {
      const n = s("text", { x: x, y: y, fill: col, "font-size": 10.5, "font-family": MONO,
        "letter-spacing": "1.2", "text-anchor": anchor || "start" });
      n.textContent = t; g.appendChild(n);
    };
    lab(x0, H - 14, "AVERAGE ACTIVITY  →  how they compare to everyone", cInk4);
    lab(x0 - 8, y0 - 10, "DEVIATION FROM OWN BASELINE", cInk4);
    const mine = pts.find((p) => p.student_id === D.student.id);
    if (mine) {
      lab(X(mine.mean_state) + 18, Y(mine.last_state - mine.theta) + 4,
          "THIS STUDENT", css("--coral-b"));
    }
    host.appendChild(g);
  }

  /** Two real students whose baselines genuinely differ. */
  function contrastPair(host) {
    const pair = D.contrast;
    if (!pair || !pair.high || !pair.low) {
      host.appendChild(emptyState(
        "No contrast pair available",
        "Two students with genuinely different fitted set points could not be " +
        "found in this run. The comparison is omitted rather than assembled from " +
        "students who do not actually differ."));
      return;
    }
    [pair.high, pair.low].forEach((p) => {
      const box = el("div", { class: "strip-vis" });
      const d0 = p.mean[p.mean.length - 1] - p.theta;
      box.appendChild(el("p", { class: "sv-title", text: "Student " + p.student_id }));
      box.appendChild(el("p", { class: "sv-sub", text: "Own baseline θ = " + fmt(p.theta) +
        " · now " + fmt(p.mean[p.mean.length - 1]) + " (" + sign(d0) +
        " vs their own normal)" }));
      box.appendChild(C.stateRibbon({ mean: p.mean, sd: p.sd, theta: p.theta, h: 300,
        label: "Student " + p.student_id + " against their own baseline of " +
          fmt(p.theta) }));
      host.appendChild(box);
    });
  }

  /** Observed history, then a real fan of simulated futures. */
  function landingSim(host) {
    host.appendChild(C.fanChart({
      obs: st.eng, theta: theta, h: 360,
      paths: (D.sim && D.sim.particles) || [],
      branches: [{ color: css("--indigo-b"), med: D.sim.base_med, lo: D.sim.base_lo,
        hi: D.sim.base_hi, active: true }],
      label: "Twenty observed weeks then forty simulated particle paths across eight weeks",
    }));
  }

  function mountLanding() {
    [["#hero-vis", heroField],
     ["#vis-think", thinkSection],
     ["#vis-memory", memorySection],
     ["#vis-cohort", cohortStrip],
     ["#vis-contrast", contrastPair],
     ["#vis-sim", landingSim],
    ].forEach(([sel, fn]) => {
      const hostEl = $(sel);
      if (!hostEl || hostEl.dataset.done) return;
      const out = boundary(sel.replace("#vis-", "").replace("#", ""),
        () => { fn(hostEl); return null; });
      if (out) hostEl.appendChild(out);
      hostEl.dataset.done = "1";
    });
    document.querySelectorAll("[data-fig]").forEach((n) => {
      const k = n.getAttribute("data-fig");
      if (k === "weeks") n.textContent = String(NW);
      if (k === "students" && D.cohort && D.cohort.students != null) {
        n.textContent = String(D.cohort.students);
      }
      if (k === "theta") n.textContent = fmt(theta);
    });
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-go]");
    if (a) { e.preventDefault(); go(a.getAttribute("data-go")); }
  });
  /* `hashchange` is registered in boot(), after the view model is bound.
     Registering it here would let a hash change render an unbound app. */

  /* ============================================================
     PRODUCT LAYER — profile store, onboarding, first-run twin.

     A new user has ZERO observations. The filter has nothing to
     update on, so their state initialises at the context prior
     with maximum uncertainty — which is exactly what the model
     does at t=0. We show that honestly rather than rendering a
     trajectory that does not exist.
     ============================================================ */

  /** Fold the richer v2 onboarding profile into the shape the twin views expect,
      so the dashboard has one profile contract regardless of which flow created it. */
  function v2fold(v) {
    return {
      v: 2, created: v.created, observations: 0, consent: !!v.consent,
      name: (v.identity || {}).name || "",
      level: (v.identity || {}).year || "",
      institution: (v.identity || {}).institution || "",
      courses: (v.courses || []).map((c) => c.name),
      baseline: {
        study_hours: (v.baseline || {}).hours,
        consistency: (v.baseline || {}).consistency,
        workload: (v.baseline || {}).workload,
      },
      rich: v,
    };
  }

  /** Prototype persistence. Shaped to mirror a future POST /api/twin so the
      swap is one module, not a refactor. */
  const Store = {
    KEY: "studytwin.profile.v1",
    KEY2: "studytwin.profile.v2",
    read() {
      try { return JSON.parse(localStorage.getItem(this.KEY) || "null"); }
      catch (e) { return null; }
    },
    write(p) {
      try { localStorage.setItem(this.KEY, JSON.stringify(p)); return true; }
      catch (e) { console.warn("[StudyTwin] profile not persisted:", e); return false; }
    },
    read2() { try { return JSON.parse(localStorage.getItem(this.KEY2) || "null"); }
              catch (e) { return null; } },
    write2(p) { try { localStorage.setItem(this.KEY2, JSON.stringify(p)); return true; }
                catch (e) { console.warn("[StudyTwin] profile not persisted:", e); return false; } },
    clear() { try { localStorage.removeItem(this.KEY); localStorage.removeItem(this.KEY2); }
              catch (e) { } },
  };

  const OB_CTX = {
    el: el, s: s, icon: icon, css: css, fmt: fmt, Store: Store, go: go,
    rerender: () => render(),
    rerenderVis: () => { if (window.ST_Onboarding) window.ST_Onboarding.refreshVis(); },
  };

  /* ============================================================
     INITIALISATION — a short, truthful build sequence.
     Each row reports an actual completion state derived from the
     answers given. There is no fake progress bar and no wait that
     exists only to feel impressive.
     ============================================================ */
  function viewInit() {
    const raw = Store.read2();
    const p = raw || {};
    const wrap = el("div", { class: "init" });
    const inner = el("div", { class: "init-in" });
    inner.appendChild(el("p", { class: "eyebrow", text: "Building your Twin" }));
    inner.appendChild(el("h1", { class: "init-t", text: "Assembling the model" }));
    inner.appendChild(el("p", { class: "init-s",
      text: "Five components, each reporting what it actually has." }));

    const nCourses = (p.courses || []).length;
    const hasBase = !!(p.baseline && Object.keys(p.baseline).length);
    const STEPS = [
      ["Personal profile", (p.identity && p.identity.name) ? "COMPLETE" : "PARTIAL"],
      ["Study patterns", (p.patterns && Object.keys(p.patterns).length) ? "COMPLETE" : "PARTIAL"],
      ["Courses and context", nCourses ? "COMPLETE" : "PARTIAL"],
      ["Personal baseline θ", hasBase ? "SELF-REPORTED" : "NOT FITTED"],
      ["Observation history", "EMPTY"],
    ];
    const list = el("div", { class: "init-list" });
    STEPS.forEach((row, i) => {
      list.appendChild(el("div", { class: "init-i", "data-i": String(i) }, [
        el("span", { class: "init-n", text: String(i + 1).padStart(2, "0") }),
        el("span", { class: "init-l", text: row[0] }),
        el("span", { class: "init-st", text: "—" }),
      ]));
    });
    inner.appendChild(list);

    const done = el("div", { hidden: "" });
    const cta = el("button", { type: "button", class: "btn btn-primary" },
      [el("span", { text: "Open my Twin" }), icon("arrow", 16)]);
    cta.addEventListener("click", () => go("twin"));
    done.appendChild(el("p", { class: "note" }, [icon("info", 16),
      el("div", { html: "<b>Your Twin is ready, and it has observed nothing.</b> " +
        "The personal baseline is self-reported context, not a fitted set point. " +
        "It becomes a real estimate only once weekly observations exist." })]));
    done.appendChild(el("div", { style: "margin-top:1.25rem" }, [cta]));
    inner.appendChild(done);
    wrap.appendChild(inner);

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const rows = list.querySelectorAll(".init-i");
    let i = 0;
    function tick() {
      if (i > 0) {
        rows[i - 1].classList.remove("on");
        rows[i - 1].classList.add("done");
        rows[i - 1].querySelector(".init-st").textContent = STEPS[i - 1][1];
      }
      if (i >= rows.length) {
        done.hidden = false;
        done.classList.add("rise");
        return;
      }
      rows[i].classList.add("on");
      rows[i].querySelector(".init-st").textContent = "…";
      i++;
      setTimeout(tick, reduced ? 0 : 320);
    }
    setTimeout(tick, reduced ? 0 : 260);
    return wrap;
  }

  /* ============================================================
     BOOT

     Asynchronous, because the data now comes over HTTP. Three
     outcomes, all of them visible to the user:

       api       live backend
       snapshot  backend unreachable, bundled export used and SAID SO
       none      neither available - an error, never a blank page and
                 never a plausible-looking placeholder number
     ============================================================ */

  function skeleton() {
    const wrap = el("div", { class: "boot" });
    wrap.appendChild(el("div", { class: "boot-in" }, [
      el("div", { class: "boot-mark" }, [icon("twin", 26)]),
      el("p", { class: "boot-t", text: "Loading the Twin" }),
      el("p", { class: "boot-s", text: "Fetching one student's state, baseline, "
        + "attribution and simulated futures." }),
      el("div", { class: "boot-bar" }, [el("i", {})]),
      el("p", { class: "boot-src", text: (window.ST_Api ? window.ST_Api.base : "") ||
        location.origin }),
    ]));
    return wrap;
  }

  function bootFailure(err, hint) {
    const wrap = el("div", { class: "boot" });
    wrap.appendChild(el("div", { class: "boot-in" }, [
      emptyState(
        "StudyTwin could not load any data",
        "<code>" + (err || "unknown error") + "</code><br><br>" +
        (hint || "") + "<br><br>" +
        "No numbers are being shown because none are available. The application " +
        "will not display placeholder values in place of a result.",
        "err"),
    ]));
    return wrap;
  }

  /** Where the data came from. A snapshot that pretends to be live is the
      one failure mode this whole layer exists to prevent. */
  function sourceChip() {
    if (BOOT.mode === "api") {
      return el("span", { class: "chip chip-observed", title:
        "Live from the API. Run " + (D.provenance.run_id || "").slice(0, 8) }, [
        el("i", { class: "chip-dot" }), el("span", { text: "Live API" })]);
    }
    return el("span", { class: "chip chip-synthetic", title:
      (D.fallback_reason || "") + " " + (D.fallback_hint || "") },
      [el("i", { class: "chip-dot" }), el("span", { text: "Offline snapshot" })]);
  }

  async function boot() {
    const site = $("#site"), app = $("#app");
    site.hidden = true;
    app.hidden = false;
    app.className = "";
    app.innerHTML = "";
    app.appendChild(skeleton());

    const res = await window.ST_Api.boot({});
    if (!res.ok) {
      BOOT = { mode: "none", error: res.error, hint: res.hint };
      app.innerHTML = "";
      app.appendChild(bootFailure(res.error, res.hint));
      return;
    }

    bind(res.vm);
    BOOT = { mode: res.mode, error: null, hint: null };

    const violations = contractViolations();
    if (violations.length) {
      console.error("[StudyTwin] data contract violated. Missing:", violations);
    }
    if (res.mode === "snapshot") {
      console.warn("[StudyTwin] using the bundled offline snapshot: " +
        (res.vm.fallback_reason || "") + " " + (res.vm.fallback_hint || ""));
    }

    window.addEventListener("hashchange", render);
    render();
  }

  let booted = false;
  function bootOnce() {
    if (booted) return;
    booted = true;
    boot();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootOnce);
  } else {
    bootOnce();
  }
})();
