/* ============================================================
   StudyTwin frontend
   ------------------------------------------------------------
   No framework, no build step, no runtime dependency. Charts are
   hand-built SVG so uncertainty can be encoded as geometry rather
   than as an optional overlay a charting library would let us
   switch off.

   Data contract: window.STUDYTWIN_DATA, written by
   scripts/export_web_data.py. Swapping in a real HTTP API means
   replacing loadData() and nothing else.
   ============================================================ */
(function () {
  "use strict";

  const D = window.STUDYTWIN_DATA;
  const NS = "http://www.w3.org/2000/svg";
  // SVG presentation attributes do not resolve CSS var(); use a literal stack.
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
    (kids || []).forEach((c) => n.appendChild(c));
    return n;
  };
  const s = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) n.setAttribute(k, attrs[k]);
    return n;
  };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v, d) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : v.toFixed(d === undefined ? 2 : d);
  const pct = (v, d) => fmt(v * 100, d === undefined ? 1 : d) + "%";

  /* ============================================================
     DATA CONTRACT
     ------------------------------------------------------------
     The first version of this app read D.provenance while the
     generator emitted no such key. The read threw between two
     appendChild calls, so the sidebar mounted and the main region
     never did: a blank screen with no visible cause.

     Two rules now prevent that class of bug from recurring:
       1. the contract is declared, checked once at boot, and a
          violation produces a readable failure rather than silence
       2. every view renders inside a boundary, so one broken
          section degrades to an honest empty state instead of
          taking the page down
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
    "metrics": "evaluation metrics",
    "cohort.students": "cohort size",
  };
  const dig = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  function contractViolations() {
    if (!D) return Object.keys(CONTRACT);
    return Object.keys(CONTRACT).filter((p) => dig(D, p) === undefined);
  }
  const has = (p) => dig(D, p) !== undefined;

  /** Honest empty state. Used when data is genuinely absent — never to hide an error. */
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
     One family, drawn inline — no icon dependency, no mixing. */
  const ICON = {
    user:    "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
    refresh: "M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.7 3H21M21 3v5h-5M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.7-3H3M3 21v-5h5",
    branch:  "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 9a9 9 0 0 1-9 9",
    beaker:  "M9 3h6M10 3v6.5L5.2 17.4A2 2 0 0 0 6.9 20h10.2a2 2 0 0 0 1.7-2.6L14 9.5V3M7.5 14h9",
    home:    "M3 10.5 12 3l9 7.5M5 9.5V20h14V9.5",
    chart:   "M3 3v18h18M7 15l3.5-4 3 2.5L20 7",
    layers:  "M12 3 3 8l9 5 9-5-9-5M3 15l9 5 9-5M3 11.5l9 5 9-5",
    shield:  "M12 3 4 6v6c0 4.5 3.2 8 8 9 4.8-1 8-4.5 8-9V6l-8-3M9.5 12.5l2 2 3.5-4",
    info:    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 11v5M12 7.5h.01",
    alert:   "M12 8v5M12 16.5h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0",
    arrow:   "M5 12h14M13 6l6 6-6 6",
    db:      "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    twin:    "M8.5 20a5 5 0 0 1-3.6-8.5A5 5 0 0 1 9 3.6M15.5 4a5 5 0 0 1 3.6 8.5A5 5 0 0 1 15 20.4M12 8v8",
  };
  function icon(name, size) {
    const n = s("svg", { viewBox: "0 0 24 24", width: size || 20, height: size || 20,
      fill: "none", stroke: "currentColor", "stroke-width": 1.5,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    n.appendChild(s("path", { d: ICON[name] || ICON.info }));
    return n;
  }

  /* ============================================================
     THE STATE RIBBON — the signature visualisation.

     Encodes five quantities in one mark:
       vertical position  state mean
       THICKNESS          95% credible interval  (uncertainty cannot be hidden)
       fill colour        side of the student's OWN baseline
       dashed rule        the personal set point theta
       terminal dots      20-quantile posterior of the current state

     Drawn against theta rather than zero. That is the whole
     personalisation argument made visible: this student sits
     ABOVE their cohort while being BELOW their own normal.
     ============================================================ */
  function ribbon(opts) {
    const mean = opts.mean, sd = opts.sd, theta = opts.theta;
    const W = opts.w || 880, H = opts.h || 300;
    const L = 46, R = opts.dots ? 116 : 34, T = 18, B = 30;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    let lo = Math.min(theta, ...mean.map((m, i) => m - 2 * sd[i])) - .25;
    let hi = Math.max(theta, ...mean.map((m, i) => m + 2 * sd[i])) + .25;
    const X = (i) => x0 + (i / Math.max(mean.length - 1, 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);
    const above = (v) => v >= theta;

    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%",
      role: "img", "aria-label": opts.label || "State ribbon" });

    const cTeal = css("--teal-2"), cRose = css("--coral"), cAmber = css("--amber"),
          cInk = css("--ink"), cInk3 = css("--ink-3"), cLine = css("--line");

    // y gridlines
    const step = (hi - lo) > 3 ? 1 : .5;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: cLine, "stroke-width": 1 }));
      const t = s("text", { x: x0 - 8, y: Y(v) + 3.5, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = v.toFixed(step < 1 ? 1 : 0);
      g.appendChild(t);
    }

    // area between state and personal baseline: the integral of deviation
    let gap = `M ${X(0)} ${Y(theta)}`;
    mean.forEach((m, i) => { gap += ` L ${X(i)} ${Y(m)}`; });
    gap += ` L ${X(mean.length - 1)} ${Y(theta)} Z`;
    g.appendChild(s("path", { d: gap, fill: cTeal, "fill-opacity": .07 }));

    // the ribbon itself — thickness IS the credible interval
    for (let i = 0; i < mean.length - 1; i++) {
      const a = mean[i], b = mean[i + 1], sa = 1.96 * sd[i], sb = 1.96 * sd[i + 1];
      const col = (above(a) && above(b)) ? cTeal : (!above(a) && !above(b)) ? cRose : cInk3;
      g.appendChild(s("path", {
        d: `M ${X(i)} ${Y(a + sa)} L ${X(i + 1)} ${Y(b + sb)} L ${X(i + 1)} ${Y(b - sb)} L ${X(i)} ${Y(a - sa)} Z`,
        fill: col, "fill-opacity": .24, class: "fade"
      }));
    }

    // personal baseline: a first-class mark, not a gridline
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(theta), y2: Y(theta),
      stroke: cAmber, "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    const tl = s("text", {
      x: opts.dots ? x1 - 6 : x1 + 6, y: Y(theta) - 6,
      fill: cAmber, "font-size": 10, "font-family": MONO,
      "text-anchor": opts.dots ? "end" : "start" });
    tl.textContent = "θ " + fmt(theta);
    g.appendChild(tl);

    // mean trace, drawn on load
    let p = "";
    mean.forEach((m, i) => { p += (i ? " L " : "M ") + X(i) + " " + Y(m); });
    const trace = s("path", { d: p, fill: "none", stroke: cInk, "stroke-width": 1.9,
      "stroke-linejoin": "round", "stroke-linecap": "round", class: "draw" });
    g.appendChild(trace);
    requestAnimationFrame(() => {
      try { const len = trace.getTotalLength(); trace.style.setProperty("--len", len); } catch (e) { }
    });

    mean.forEach((m, i) => {
      g.appendChild(s("circle", { cx: X(i), cy: Y(m), r: 2.1,
        fill: above(m) ? cTeal : cRose, class: "fade" }));
    });

    // week axis
    const ticks = mean.length > 12 ? [0, 4, 8, 12, 16, mean.length - 1] : mean.map((_, i) => i);
    ticks.forEach((i) => {
      const t = s("text", { x: X(i), y: y1 + 18, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" });
      t.textContent = "w" + i;
      g.appendChild(t);
    });

    // terminal quantile dotplot — frequency framing at the decision point
    if (opts.dots) {
      const m = mean[mean.length - 1], sdv = sd[sd.length - 1], dx = x1 + 52;
      const lab = s("text", { x: dx, y: y0 + 2, fill: cInk3, "font-size": 9,
        "font-family": MONO, "text-anchor": "middle" });
      lab.textContent = "20 OUTCOMES";
      g.appendChild(lab);
      for (let i = 1; i <= 20; i++) {
        const v = m + sdv * probit((i - .5) / 20);
        g.appendChild(s("circle", { cx: dx + (((i - 1) % 4) - 1.5) * 9.5, cy: Y(v), r: 3.1,
          fill: above(v) ? cTeal : cRose, "fill-opacity": .85, class: "fade" }));
      }
    }
    return g;
  }

  /* Acklam rational approximation to the normal quantile function.
     Used for the quantile dotplot; accurate to ~1e-9, no dependency. */
  function probit(p) {
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425; let q, r;
    if (p < pl) { q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
    if (p > 1 - pl) { q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
    q = p - .5; r = q * q;
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
  }

  /* ---- observed-then-simulated chart. Solid = observed, dashed = model. ---- */
  function futureChart(opts) {
    const W = 860, H = 300, L = 46, R = 26, T = 18, B = 34;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const obs = opts.obs, simW = opts.simWeeks;
    const nObs = obs.length, total = nObs + simW.length;
    const series = opts.series;
    let lo = Math.min(opts.theta, ...obs, ...series.flatMap((q) => q.lo)) - .3;
    let hi = Math.max(opts.theta, ...obs, ...series.flatMap((q) => q.hi)) + .3;
    const X = (i) => x0 + (i / (total - 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img",
      "aria-label": opts.label });
    const cInk = css("--ink"), cInk3 = css("--ink-3"), cLine = css("--line"),
          cAmber = css("--amber"), cTeal = css("--teal-2");

    for (let v = Math.ceil(lo); v <= hi; v++) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: cLine }));
      const t = s("text", { x: x0 - 8, y: Y(v) + 3.5, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = v; g.appendChild(t);
    }

    // simulated region gets a tinted ground so it can never be mistaken for observation
    g.appendChild(s("rect", { x: X(nObs - 1), y: y0, width: x1 - X(nObs - 1), height: y1 - y0,
      fill: css("--surface-2"), "fill-opacity": .75 }));

    series.forEach((q) => {
      let band = `M ${X(nObs - 1)} ${Y(obs[nObs - 1])}`;
      q.hi.forEach((v, i) => { band += ` L ${X(nObs + i)} ${Y(v)}`; });
      for (let i = q.lo.length - 1; i >= 0; i--) band += ` L ${X(nObs + i)} ${Y(q.lo[i])}`;
      band += " Z";
      g.appendChild(s("path", { d: band, fill: q.color, "fill-opacity": .16 }));
    });

    // personal baseline
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(opts.theta), y2: Y(opts.theta),
      stroke: cAmber, "stroke-width": 1.4, "stroke-dasharray": "5 4" }));

    // observed
    let p = "";
    obs.forEach((v, i) => { p += (i ? " L " : "M ") + X(i) + " " + Y(v); });
    g.appendChild(s("path", { d: p, fill: "none", stroke: cInk, "stroke-width": 1.9, "stroke-linejoin": "round" }));

    // simulated medians — dashed, always
    series.forEach((q) => {
      let sp = `M ${X(nObs - 1)} ${Y(obs[nObs - 1])}`;
      q.med.forEach((v, i) => { sp += ` L ${X(nObs + i)} ${Y(v)}`; });
      g.appendChild(s("path", { d: sp, fill: "none", stroke: q.color, "stroke-width": 2,
        "stroke-dasharray": "6 4", "stroke-linejoin": "round" }));
    });

    // "now" boundary
    g.appendChild(s("line", { x1: X(nObs - 1), x2: X(nObs - 1), y1: y0, y2: y1,
      stroke: cInk3, "stroke-width": 1, "stroke-dasharray": "2 3" }));
    const nl = s("text", { x: X(nObs - 1) + 6, y: y0 + 11, fill: cInk3, "font-size": 9.5,
      "font-family": MONO, "letter-spacing": ".08em" });
    nl.textContent = "LAST OBSERVATION";
    g.appendChild(nl);

    [0, 5, 10, 15, nObs - 1, total - 1].forEach((i) => {
      if (i >= total) return;
      const t = s("text", { x: X(i), y: y1 + 18, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" });
      t.textContent = "w" + i; g.appendChild(t);
    });
    return g;
  }

  /* ---- cumulative risk, baseline vs scenario ---- */
  function riskChart(weeks, a, b) {
    const W = 860, H = 190, L = 46, R = 26, T = 16, B = 30;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const hi = Math.max(...a, ...b) * 1.25;
    const X = (i) => x0 + (i / (weeks.length - 1)) * (x1 - x0);
    const Y = (v) => y1 - (v / hi) * (y1 - y0);
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img",
      "aria-label": "Cumulative simulated risk, baseline versus scenario" });
    const cInk3 = css("--ink-3"), cLine = css("--line");
    [0, hi / 2, hi].forEach((v) => {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: cLine }));
      const t = s("text", { x: x0 - 8, y: Y(v) + 3.5, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = (v * 100).toFixed(0) + "%"; g.appendChild(t);
    });
    [[a, css("--ink"), "baseline"], [b, css("--indigo"), "scenario"]].forEach(([ser, col]) => {
      let p = "";
      ser.forEach((v, i) => { p += (i ? " L " : "M ") + X(i) + " " + Y(v); });
      g.appendChild(s("path", { d: p, fill: "none", stroke: col, "stroke-width": 2,
        "stroke-dasharray": "6 4", "stroke-linejoin": "round" }));
      ser.forEach((v, i) => g.appendChild(s("circle", { cx: X(i), cy: Y(v), r: 2.4, fill: col })));
    });
    weeks.forEach((w, i) => {
      if (i % 2) return;
      const t = s("text", { x: X(i), y: y1 + 17, fill: cInk3, "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" });
      t.textContent = "w" + w; g.appendChild(t);
    });
    return g;
  }

  /* ---- attribution: signed contributions INCLUDING the residual ---- */
  function attribBar(rec) {
    const rows = Object.entries(rec.ch)
      .filter(([, v]) => Math.abs(v) > 1e-4)
      .sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))
      .slice(0, 5);
    rows.push(["not attributable", rec.unexp]);
    const W = 560, rowH = 26, H = rows.length * rowH + 34;
    const LBL = 168, mid = LBL + (W - LBL - 70) * .62;
    const maxV = Math.max(...rows.map((r) => Math.abs(r[1])), .001);
    const scale = (v) => (v / maxV) * (W - LBL - 110) * .5;
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img",
      "aria-label": "Observations associated with the state change this week" });
    const cInk2 = css("--ink-2"), cInk3 = css("--ink-3"), cTeal = css("--teal-2"),
          cRose = css("--coral"), cLine = css("--line");
    g.appendChild(s("line", { x1: mid, x2: mid, y1: 4, y2: rows.length * rowH + 4, stroke: cLine }));
    rows.forEach(([name, v], i) => {
      const y = 6 + i * rowH, res = name === "not attributable";
      const w = Math.abs(scale(v));
      const t = s("text", { x: LBL - 12, y: y + 13, fill: res ? cInk3 : cInk2, "font-size": 11.5,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = name.replace(/_/g, " "); g.appendChild(t);
      g.appendChild(s("rect", { x: v < 0 ? mid - w : mid, y: y + 2, width: Math.max(w, .8), height: 14,
        rx: 1.5, fill: res ? cInk3 : (v < 0 ? cRose : cTeal), "fill-opacity": res ? .4 : .82 }));
      const val = s("text", { x: mid + (W - LBL) * .32, y: y + 13,
        fill: res ? cInk3 : (v < 0 ? cRose : cTeal), "font-size": 11.5, "font-family": MONO });
      val.textContent = (v >= 0 ? "+" : "") + v.toFixed(3); g.appendChild(val);
    });
    const yT = rows.length * rowH + 20;
    g.appendChild(s("line", { x1: LBL - 100, x2: W - 40, y1: yT - 9, y2: yT - 9, stroke: cLine }));
    const lt = s("text", { x: LBL - 12, y: yT + 5, fill: css("--ink"), "font-size": 11.5,
      "font-family": MONO, "text-anchor": "end" });
    lt.textContent = "total state shift"; g.appendChild(lt);
    const vt = s("text", { x: mid + (W - LBL) * .32, y: yT + 5, fill: css("--ink"),
      "font-size": 11.5, "font-family": MONO });
    vt.textContent = (rec.shift >= 0 ? "+" : "") + rec.shift.toFixed(3); g.appendChild(vt);
    return g;
  }

  /* ============================================================
     Views
     ============================================================ */
  const st = D.state, theta = D.student.theta[0];
  const lastEng = st.eng[st.eng.length - 1], lastSd = st.eng_sd[st.eng_sd.length - 1];
  const dev = lastEng - theta;
  const lastHz = D.hazard[D.hazard.length - 1];

  let currentWeek = st.t.length - 1;
  let scenarioOn = true;

  function modeBanner(mode) {
    if (mode === "personal") {
      return el("div", { class: "mode-banner" }, [
        icon("user", 15),
        el("span", { html: "<b>Your Twin.</b> Stored on this device. No observations collected yet." }),
        el("span", { class: "spacer" }),
        el("a", { class: "link-btn", href: "#/app", "data-go": "app", text: "Open the demo twin" }),
      ]);
    }
    return el("div", { class: "mode-banner" }, [
      icon("alert", 15),
      el("span", { html: "<b>Demonstration only — not a real student.</b> A synthetic cohort with known " +
        "ground truth. Every figure is real pipeline output; none of it describes a person." }),
      el("span", { class: "spacer" }),
      el("a", { class: "link-btn", href: "#/onboarding", "data-go": "onboarding", text: "Create your own Twin" }),
    ]);
  }

  function provenanceChips() {
    const p = (D && D.provenance) || {};
    const kids = [
      el("span", { class: "chip chip-synthetic",
        text: p.synthetic === false ? String(p.dataset || "dataset") : "Synthetic cohort" }),
      el("span", { class: "chip chip-uncert", text: p.inference || "laplace approximate" }),
    ];
    if (p.seed !== undefined) kids.push(el("span", { class: "chip chip-uncert", text: "seed " + p.seed }));
    return el("div", { class: "topbar-right" }, kids);
  }

  function viewOverview() {
    const C = window.ST_Charts;
    const v = el("div", { class: "view" });

    // Metric strip: chips with a sparkline, not five giant white cards.
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
        sp.appendChild(C.spark(sparkVals, tone === "down" ? css("--coral") : css("--teal-2")));
        c.appendChild(sp);
      }
      return c;
    };
    chips.appendChild(chip("Current state", fmt(lastEng),
      "+/- " + fmt(lastSd) + " (95% CI)", dev < 0 ? "down" : "up", st.eng));
    chips.appendChild(chip("Personal baseline", fmt(theta),
      "shrinkage k = " + fmt(D.shrinkage[0]), "amber"));
    chips.appendChild(chip("Deviation", (dev >= 0 ? "+" : "") + fmt(dev),
      dev < 0 ? "below own normal" : "above own normal", dev < 0 ? "down" : "up"));
    chips.appendChild(chip("Weekly hazard", pct(lastHz, 2),
      "from " + pct(D.hazard[0], 2) + " at w0", "", D.hazard));
    chips.appendChild(chip("Observations", String(st.t.length),
      "weeks, synthetic cohort", ""));
    v.appendChild(chips);

    // Primary visualisation, full width, with a live interpretation panel.
    const main = el("section", { class: "panel" });
    main.appendChild(el("div", { class: "panel-h" }, [
      el("div", {}, [
        el("h2", { class: "panel-t", text: "Where is this student, relative to their own normal?" }),
        el("p", { class: "panel-s", text: "Engagement across " + st.t.length +
          " observed weeks, then eight simulated. Hover to inspect any week." }),
      ]),
      el("div", { class: "panel-key" }, [
        keyd("observed", css("--ink")), keyd("baseline", css("--amber"), true),
        keyd("simulated", css("--indigo"), true),
      ]),
    ]));

    const chartHost = el("div", { class: "panel-chart" });
    const readout = el("div", { class: "readout" });
    function paintReadout(i) {
      const k = (i === null || i === undefined) ? st.eng.length - 1 : i;
      const d0 = st.eng[k] - theta;
      readout.innerHTML = "";
      readout.appendChild(el("p", { class: "ro-w",
        text: (i === null || i === undefined ? "CURRENT / WEEK " : "WEEK ") + st.t[k] }));
      readout.appendChild(el("p", { class: "ro-big num " + (d0 < 0 ? "down" : "up"),
        text: fmt(st.eng[k]) }));
      [["Personal baseline", fmt(theta)],
       ["Deviation", (d0 >= 0 ? "+" : "") + fmt(d0)],
       ["Uncertainty", "+/- " + fmt(1.96 * st.eng_sd[k])],
       ["Capability", fmt(st.cap[k])]
      ].forEach(function (row) {
        readout.appendChild(el("div", { class: "ro-row" }, [
          el("span", { text: row[0] }), el("span", { class: "num", text: row[1] })]));
      });
      readout.appendChild(el("p", { class: "ro-status " + (d0 < 0 ? "down" : "up"),
        text: d0 < 0 ? "Below personal baseline" : "At or above personal baseline" }));
      const rec = D.attrib[k];
      if (rec) {
        const top = Object.entries(rec.ch).filter(function (e) { return Math.abs(e[1]) > 1e-3; })
          .sort(function (x, y) { return Math.abs(y[1]) - Math.abs(x[1]); })[0];
        readout.appendChild(el("p", { class: "ro-why", html: "<b>What moved it</b><br>" +
          (top ? top[0].replace(/_/g, " ") + " contributed " + (top[1] >= 0 ? "+" : "") +
            fmt(top[1], 3) : "no single channel dominated") +
          (Math.abs(rec.unexp) > 0.02 ? "<br><span class='muted'>residual / unexplained " +
            fmt(rec.unexp, 3) + "</span>" : "") }));
      }
    }
    chartHost.appendChild(C.twinChart({
      mean: st.eng, sd: st.eng_sd, theta: theta, h: 400,
      sim: { weeks: D.sim.weeks, lo: D.sim.base_lo, med: D.sim.base_med, hi: D.sim.base_hi },
      onHover: paintReadout,
      label: "Engagement for the demo student across 20 observed weeks against a personal baseline",
    }));
    main.appendChild(el("div", { class: "panel-body" }, [chartHost, readout]));
    paintReadout(null);
    main.appendChild(el("div", { class: "note" }, [icon("alert", 16),
      el("div", { html: "<b>Known limitation.</b> Nominal 95% intervals cover about 81% of " +
        "true states in validation, so the band is narrower than it should be. Parameter and " +
        "transfer uncertainty are not yet estimated." })]));
    v.appendChild(main);

    // Drivers, with the residual shown rather than normalised away.
    const why = el("section", { class: "panel" });
    let wk = st.t.length - 1;
    why.appendChild(el("div", { class: "panel-h" }, [el("div", {}, [
      el("h2", { class: "panel-t", text: "What moved the estimate" }),
      el("p", { class: "panel-s", text: "Observations associated with the change, not causes of it." }),
    ])]));
    const holder = el("div", {});
    const redrawWhy = function () { holder.innerHTML = ""; holder.appendChild(attribBar(D.attrib[wk])); };
    redrawWhy();
    why.appendChild(holder);
    const scrub = el("div", { class: "wk-inspect" }, [
      el("label", { class: "muted", style: "font-size:.8rem", for: "wk", text: "Inspect week" })]);
    const range = el("input", { type: "range", id: "wk", min: "0",
      max: String(st.t.length - 1), value: String(wk) });
    const out = el("span", { class: "num", text: "w" + wk });
    range.addEventListener("input", function (e) {
      wk = +e.target.value; redrawWhy(); out.textContent = "w" + wk; paintReadout(wk);
    });
    scrub.appendChild(range); scrub.appendChild(out);
    why.appendChild(scrub);
    why.appendChild(el("div", { class: "note" }, [icon("info", 16),
      el("div", { html: "The grey <b>not attributable</b> bar is the higher-order term the " +
        "first-order decomposition cannot assign. Most tools normalise it away." })]));
    v.appendChild(why);
    return v;
  }

  function keyd(text, color, dashed) {
    const sw = el("i", { class: "kd" });
    sw.style.borderTopColor = color;
    if (dashed) sw.style.borderTopStyle = "dashed";
    return el("span", { class: "kdw" }, [sw, el("span", { text: text })]);
  }

  function viewFutures() {
    const C = window.ST_Charts, sim = D.sim;
    const v = el("div", { class: "view" });
    let active = 1;

    const SCEN = [
      { name: "Current dynamics", color: css("--ink-3"),
        med: sim.base_med, lo: sim.base_lo, hi: sim.base_hi, risk: sim.base_risk,
        note: "No intervention applied. The model's own dynamics, run forward." },
      { name: "Engagement support", color: css("--indigo"),
        med: sim.alt_med, lo: sim.alt_lo, hi: sim.alt_hi, risk: sim.alt_risk,
        note: "A sustained engagement shift of one state unit, applied from now." }
    ];

    v.appendChild(el("section", { class: "lab-head" }, [
      el("div", {}, [
        el("h1", { class: "lab-t", text: "Explore possible futures" }),
        el("p", { class: "panel-s", text: "Eight weeks forward from the last observation. " +
          "600 particles drawn from the current posterior." }),
      ]),
      el("span", { class: "chip chip-simulated", text: "Model-generated" }),
    ]));

    const picker = el("div", { class: "scen" });
    const chartHost = el("div", {});
    const metrics = el("div", { class: "mstrip" });
    const expl = el("div", { class: "note sim" });

    function paint() {
      picker.innerHTML = "";
      SCEN.forEach(function (sc, i) {
        const b = el("button", { type: "button", class: "scen-b",
          "aria-pressed": String(i === active) }, [
          el("span", { class: "scen-dot" }),
          el("span", { class: "scen-n", text: sc.name }),
          el("span", { class: "scen-r num", text: pct(sc.risk[sc.risk.length - 1]) }),
        ]);
        b.querySelector(".scen-dot").style.background = sc.color;
        b.addEventListener("click", function () { active = i; paint(); });
        picker.appendChild(b);
      });

      chartHost.innerHTML = "";
      chartHost.appendChild(C.branchChart({
        obs: st.eng, theta: theta,
        branches: SCEN.map(function (sc, i) {
          return { name: sc.name, color: sc.color, med: sc.med, lo: sc.lo, hi: sc.hi,
                   active: i === active };
        }),
        label: "Observed engagement then two simulated scenario branches",
      }));

      const sc = SCEN[active];
      metrics.innerHTML = "";
      [["Projected state", fmt(sc.med[sc.med.length - 1]), "median at week +8"],
       ["Cumulative risk", pct(sc.risk[sc.risk.length - 1]), "simulated, 8 weeks"],
       ["Uncertainty", "+/- " + fmt((sc.hi[sc.hi.length - 1] - sc.lo[sc.lo.length - 1]) / 2),
        "5th to 95th percentile"],
       ["Horizon", "8 weeks", "600 particles"]
      ].forEach(function (row) {
        metrics.appendChild(el("div", { class: "mchip" }, [el("div", { class: "mchip-l" }, [
          el("span", { class: "mchip-lbl", text: row[0] }),
          el("span", { class: "mchip-val num", text: row[1] }),
          el("span", { class: "mchip-sub", text: row[2] })])]));
      });

      expl.innerHTML = "";
      expl.appendChild(icon("beaker", 16));
      expl.appendChild(el("div", { html: "<b>Model-generated scenario, not a causal estimate.</b> " +
        sc.note + " The dataset records no interventions, so the sensitivity is <em>assumed</em>, " +
        "not fitted. Read this as what the model's dynamics imply, never as what an action " +
        "would achieve for a real student." }));
    }
    paint();

    const panel = el("section", { class: "panel" });
    panel.appendChild(picker);
    panel.appendChild(chartHost);
    panel.appendChild(metrics);
    panel.appendChild(expl);
    v.appendChild(panel);
    return v;
  }

  function viewResearch() {
    const v = el("div", { class: "view" });

    const tests = el("section", { class: "card" });
    tests.appendChild(el("div", { class: "card-head" }, [
      el("div", {}, [
        el("p", { class: "card-title", text: "Digital twin capability tests" }),
        el("p", { class: "card-sub", text: "Falsification tests. An unimplemented test is never shown as passing." }),
      ]),
    ]));
    const tt = el("table", { class: "data" });
    tt.innerHTML =
      "<thead><tr><th>Test</th><th>Asks</th><th>Status</th><th>Result</th></tr></thead><tbody>" +
      "<tr><td>T1 sufficiency</td><td>Does recursive updating equal full history replay?</td><td><span class='status pass'>PASS</span></td><td class='n'>max diff 0.00e+00</td></tr>" +
      "<tr><td>T2 generativity</td><td>Are simulated futures distributionally plausible?</td><td><span class='status pass'>PASS</span></td><td class='n'>coverage 0.896</td></tr>" +
      "<tr><td>T3 intervention stability</td><td>Are simulated effects stable across refits?</td><td><span class='status notimp'>NOT IMPLEMENTED</span></td><td class='n'>—</td></tr>" +
      "<tr><td>T4 identifiability</td><td>Do the dimensions keep their meaning across refits?</td><td><span class='status notimp'>NOT IMPLEMENTED</span></td><td class='n'>—</td></tr>" +
      "</tbody>";
    tests.appendChild(tt);
    tests.appendChild(el("div", { class: "note", style: "margin-top:1rem" }, [
      icon("alert", 16),
      el("div", { html: "Because T4 has not run, <b>“engagement” and “capability” are labels of convenience, not validated constructs.</b> The product uses those words; the research does not yet earn them." }),
    ]));
    v.appendChild(tests);

    const g2 = el("div", { class: "grid-2" });

    const perf = el("section", { class: "card" });
    perf.appendChild(el("div", { class: "card-head" }, [
      el("div", {}, [
        el("p", { class: "card-title", text: "The twin against every baseline" }),
        el("p", { class: "card-sub", text: "Forward-chained split. Calibration error (ECE) matters more than AUC for a human decision." }),
      ]),
    ]));
    const mt = el("table", { class: "data" });
    let rows = "";
    D.metrics.slice().sort((a, b) => b.auc - a.auc).forEach((m) => {
      rows += `<tr class="${m.name === "twin_state" ? "hl" : ""}"><td>${m.name.replace(/_/g, " ")}</td>` +
        `<td class="n">${m.auc.toFixed(3)}</td><td class="n">${m.brier.toFixed(4)}</td><td class="n">${m.ece.toFixed(4)}</td></tr>`;
    });
    mt.innerHTML = "<thead><tr><th>Model</th><th>AUC</th><th>Brier</th><th>ECE</th></tr></thead><tbody>" + rows + "</tbody>";
    perf.appendChild(mt);
    perf.appendChild(el("p", { class: "card-sub", style: "margin-top:.8rem",
      html: "Near-parity on discrimination is the <em>predicted</em> outcome, not a disappointment. Reported without confidence intervals on " + D.cohort.events + " events — a known evaluation gap." }));
    g2.appendChild(perf);

    const ctrl = el("section", { class: "card" });
    ctrl.appendChild(el("div", { class: "card-head" }, [
      el("div", {}, [
        el("p", { class: "card-title", text: "Leakage controls" }),
        el("p", { class: "card-sub", text: "Destroy a structure, see what survives." }),
      ]),
    ]));
    const ct = el("table", { class: "data" });
    let crows = "";
    D.controls.forEach((c) => {
      crows += `<tr><td>${c.c.replace(/_/g, " ")}</td><td class="n">${c.auc.toFixed(3)}</td>` +
        `<td><span class="status ${c.v === "COLLAPSED" ? "pass" : "warnv"}">${c.v}</span></td>` +
        `<td>${c.leak ? "leakage test" : "diagnostic"}</td></tr>`;
    });
    ct.innerHTML = "<thead><tr><th>Control</th><th>AUC</th><th>Verdict</th><th>Role</th></tr></thead><tbody>" + crows + "</tbody>";
    ctrl.appendChild(ct);
    ctrl.appendChild(el("p", { class: "card-sub", style: "margin-top:.8rem",
      html: "Only <b>permute student identity</b> tests leakage. Surviving a within-student time shuffle is expected for a level-driven model and is not evidence of a leak." }));
    g2.appendChild(ctrl);
    v.appendChild(g2);

    // — data quality —
    const dq = el("section", { class: "card" });
    dq.appendChild(el("div", { class: "card-head" }, [
      el("div", {}, [
        el("p", { class: "card-title", text: "Data provenance and coverage" }),
        el("p", { class: "card-sub", text: D.provenance.note }),
      ]),
      el("span", { class: "chip chip-synthetic", text: "Synthetic" }),
    ]));
    dq.appendChild(el("div", { class: "stat-row", style: "margin-bottom:1rem" }, [
      stat("Students", String(D.cohort.students), "in this run", ""),
      stat("Student-weeks", String(D.cohort.rows), "at-risk rows only", ""),
      stat("Events", String(D.cohort.events), pct(D.cohort.rate, 2) + " weekly rate", ""),
      stat("Contexts", String(D.cohort.contexts), "course-presentations", ""),
    ]));
    const cov = el("div", { class: "scroll-x" });
    const cvt = el("table", { class: "data" });
    cvt.innerHTML = "<thead><tr><th>Channel</th><th>Status</th></tr></thead><tbody>" +
      D.cohort.coverage_avail.map((c) => `<tr><td>${c.replace(/_/g, " ")}</td><td><span class="status pass">AVAILABLE</span></td></tr>`).join("") +
      D.cohort.coverage_missing.map((c) => `<tr><td>${c.replace(/_/g, " ")}</td><td><span class="status notimp">NOT SUPPLIED</span></td></tr>`).join("") +
      "</tbody>";
    cov.appendChild(cvt); dq.appendChild(cov);
    dq.appendChild(el("div", { class: "note", style: "margin-top:1rem" }, [
      icon("db", 16),
      el("div", { html: "<b>Lifestyle and self-report channels exist in the schema and are supplied by no adapter.</b> They are declared unavailable rather than silently omitted, so a later survey instrument is an adapter rather than a migration." }),
    ]));
    v.appendChild(dq);
    return v;
  }

  /* ---------------------------------------------- chrome ---- */
  function stat(lbl, val, sub, cls) {
    return el("div", { class: "stat" }, [
      el("span", { class: "lbl", text: lbl }),
      el("span", { class: "val " + (cls || ""), text: val }),
      el("span", { class: "sub", text: sub }),
    ]);
  }
  function legend(text, color, dashed) {
    const sw = el("i", { class: "sw" });
    sw.style.borderTopColor = color;
    if (dashed) sw.style.borderTopStyle = "dashed";
    return el("span", {}, [sw, el("span", { text: text })]);
  }

  /* Two distinct experiences, never mixed. `mode` decides which routes appear
     in the sidebar and which banner sits above the content. */
  const VIEWS = {
    mytwin:   { label: "My Twin",        icon: "user",   render: viewTwinNew,  mode: "personal" },
    overview: { label: "Overview",       icon: "home",   render: viewOverview, mode: "demo" },
    futures:  { label: "Future Lab",     icon: "beaker", render: viewFutures,  mode: "demo" },
    research: { label: "Research & data", icon: "chart", render: viewResearch, mode: "demo" },
  };

  function mountApp(route) {
    const app = $("#app");
    app.innerHTML = "";
    const side = el("aside", { class: "side" });
    const brand = el("div", { class: "side-brand" }, [icon("twin", 20), el("span", { text: "StudyTwin" })]);
    side.appendChild(brand);
    const nav = el("nav", { class: "side-nav", "aria-label": "Application" });
    const mode = VIEWS[route].mode;
    Object.entries(VIEWS).filter(([, c]) => c.mode === mode).forEach(([k, cfg]) => {
      const b = el("button", { type: "button" }, [icon(cfg.icon, 17), el("span", { text: cfg.label })]);
      if (k === route) b.setAttribute("aria-current", "page");
      b.addEventListener("click", () => go(mode === "personal" ? "twin" : "app/" + k));
      nav.appendChild(b);
    });
    if (mode === "personal") {
      const toDemo = el("button", { type: "button" }, [icon("layers", 17),
        el("span", { text: "Explore the demo" })]);
      toDemo.addEventListener("click", () => go("app/overview"));
      nav.appendChild(toDemo);
    }
    side.appendChild(nav);
    // Twin status: what this Twin actually is, not just where you can navigate.
    const cov = mode === "personal" ? 0 : 100;
    const obsN = mode === "personal" ? 0 : st.t.length;
    const status = el("div", { class: "side-status" }, [
      el("p", { class: "ss-h", text: "Twin status" }),
      el("div", { class: "ss-live" }, [
        el("span", { class: "ss-dot" }),
        el("span", { text: mode === "personal" ? "Initialised" : "Active" }),
      ]),
      el("div", { class: "ss-row" }, [el("span", { text: "Observations" }),
        el("b", { text: obsN + " wks" })]),
      el("div", { class: "ss-bar" }, [
        el("i", { class: "ss-fill", style: "width:" + Math.min(100, obsN * 5) + "%" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Data" }),
        el("b", { text: mode === "personal" ? "none" : "synthetic" })]),
      el("div", { class: "ss-row" }, [el("span", { text: "Inference" }),
        el("b", { text: "laplace" })]),
    ]);
    side.appendChild(status);
    side.appendChild(el("div", { class: "side-foot", html: mode === "personal"
      ? "No observations collected.<br>Estimates are the cohort prior."
      : "Synthetic cohort.<br>Never run on real OULAD data." }));
    const back = el("button", { type: "button", class: "side-foot", style: "text-align:left;width:100%", text: "← Back to site" });
    back.addEventListener("click", () => go(""));
    side.appendChild(back);
    app.appendChild(side);

    const main = el("div", { class: "main" });
    const top = el("header", { class: "topbar" });
    const prof = Store.read();
    const personal = VIEWS[route].mode === "personal";
    top.appendChild(el("div", { class: "subject" }, [
      icon("user", 18),
      el("div", {}, [
        el("div", { class: "sid", text: personal
          ? ((prof && prof.name) || "Your Twin")
          : "Synthetic Student SYN-" + D.student.id }),
        el("div", { class: "meta", text: personal
          ? ((prof && prof.courses.length ? prof.courses.length + " courses · " : "") + "0 observed weeks")
          : D.student.context + " · " + D.student.weeks + " observed weeks" }),
      ]),
    ]));
    top.appendChild(provenanceChips());
    main.appendChild(top);
    main.appendChild(modeBanner(mode));

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
    location.hash = hash;
    render();
  }
  function render() {
    const h = location.hash.replace(/^#\/?/, "");
    const site = $("#site"), app = $("#app");

    // onboarding and the first-run twin live outside the demo shell
    if (h.startsWith("onboarding")) {
      site.hidden = true; app.hidden = false;
      app.className = ""; app.innerHTML = "";
      app.appendChild(boundary("Onboarding", () =>
        window.ST_Onboarding ? window.ST_Onboarding.render(OB_CTX) : viewOnboarding()));
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
      app.className = "app";
      const route = h.split("/")[1] || "overview";
      site.hidden = true; app.hidden = false;
      mountApp(VIEWS[route] ? route : "overview");
      window.scrollTo(0, 0);
    } else {
      site.hidden = false; app.hidden = true;
      app.innerHTML = "";
      mountLanding();
    }
  }

  /* ============================================================
     Landing-page visuals. Every one is built from real pipeline
     output; none exists to fill space.
     ============================================================ */

  /** Hero ribbon with hover-to-inspect. The readout is the point of the
      interaction — hover reveals precision, never new meaning. */
  function heroRibbon(host) {
    const wrap = el("div", { class: "hero-ribbon" });
    const read = el("div", { class: "hero-read" }, [
      el("span", { class: "hr-week", text: "week 19" }),
      el("span", { class: "hr-val", text: fmt(lastEng) }),
      el("span", { class: "hr-dev", text: fmt(dev, 2) + " vs own baseline" }),
    ]);
    const svgHost = el("div", {});
    svgHost.appendChild(ribbon({
      mean: st.eng, sd: st.eng_sd, theta: theta, dots: true, h: 300,
      label: "Engagement state across 20 weeks against this student's own baseline of " + fmt(theta),
    }));
    wrap.appendChild(read);
    wrap.appendChild(svgHost);

    const svg = svgHost.querySelector("svg");
    const marker = s("line", { y1: 18, y2: 270, stroke: css("--ink-3"),
      "stroke-width": 1, "stroke-dasharray": "2 3", opacity: 0 });
    svg.appendChild(marker);
    const L = 46, R = 116, W = 880;
    svg.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const vx = ((e.clientX - r.left) / r.width) * W;
      const i = Math.round(((vx - L) / (W - R - L)) * (st.eng.length - 1));
      if (i < 0 || i >= st.eng.length) return;
      const x = L + (i / (st.eng.length - 1)) * (W - R - L);
      marker.setAttribute("x1", x); marker.setAttribute("x2", x);
      marker.setAttribute("opacity", .55);
      const d0 = st.eng[i] - theta;
      read.querySelector(".hr-week").textContent = "week " + st.t[i];
      read.querySelector(".hr-val").textContent = fmt(st.eng[i]);
      read.querySelector(".hr-dev").textContent =
        (d0 >= 0 ? "+" : "") + fmt(d0) + " vs own baseline";
      read.querySelector(".hr-val").className = "hr-val " + (d0 < 0 ? "below" : "above");
    });
    svg.addEventListener("pointerleave", () => marker.setAttribute("opacity", 0));
    host.appendChild(wrap);
  }

  /** The contrast that carries the site: cohort-relative vs self-relative. */
  function cohortStrip(host) {
    const pts = D.cohort_states || [];
    if (!pts.length) {
      host.appendChild(emptyState("Cohort summary not available",
        "The data file carries no <code>cohort_states</code> block.")); return;
    }
    const W = 720, H = 92, L = 20, R = 20;
    const vals = pts.map((p) => p.last);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const me = pts.find((p) => p.id === D.student.id) || pts[0];

    function strip(title, sub, valueOf, centre, label) {
      const g = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img", "aria-label": label });
      const X = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
      g.appendChild(s("line", { x1: L, x2: W - R, y1: 54, y2: 54, stroke: css("--line"), "stroke-width": 1 }));
      pts.forEach((p) => {
        g.appendChild(s("circle", { cx: X(valueOf(p)), cy: 54, r: 2.6,
          fill: css("--ink-3"), "fill-opacity": .28 }));
      });
      const mv = valueOf(me);
      g.appendChild(s("line", { x1: X(mv), x2: X(mv), y1: 30, y2: 70,
        stroke: centre ? css("--coral") : css("--teal-2"), "stroke-width": 2 }));
      const t = s("text", { x: X(mv), y: 24, "text-anchor": "middle",
        fill: centre ? css("--coral") : css("--teal-2"), "font-size": 11, "font-family": MONO });
      t.textContent = (mv >= 0 ? "+" : "") + fmt(mv);
      g.appendChild(t);
      if (centre) {
        g.appendChild(s("line", { x1: X(0), x2: X(0), y1: 40, y2: 68,
          stroke: css("--amber"), "stroke-width": 1.4, "stroke-dasharray": "4 3" }));
        const z = s("text", { x: X(0), y: 84, "text-anchor": "middle", fill: css("--amber"),
          "font-size": 10, "font-family": MONO });
        z.textContent = "their own normal"; g.appendChild(z);
      }
      return el("div", { class: "strip-vis" }, [
        el("p", { class: "sv-title", text: title }),
        el("p", { class: "sv-sub", text: sub }),
        g,
      ]);
    }

    host.appendChild(strip(
      "Compared with everyone else",
      pts.length + " students, current engagement state. This student is unremarkable.",
      (p) => p.last, false,
      "Distribution of current engagement across the cohort with this student marked."
    ));
    host.appendChild(strip(
      "Compared with themselves",
      "The same students, each measured against their own baseline. This student is among the furthest below.",
      (p) => p.last - p.th, true,
      "Distribution of deviation from personal baseline with this student marked."
    ));
  }

  /** Two real students: the same absolute state means opposite things. */
  function contrastPair(host) {
    const c = D.contrast || [];
    if (c.length < 2) {
      host.appendChild(emptyState("Contrast pair not available",
        "The data file carries no <code>contrast</code> block.")); return;
    }
    c.forEach((stu) => {
      const last = stu.eng[stu.eng.length - 1], dv = last - stu.theta;
      const card = el("div", { class: "contrast-card" }, [
        el("div", { class: "cc-head" }, [
          el("span", { class: "num cc-id", text: stu.id }),
          el("span", { class: "chip " + (dv < -.5 ? "chip-synthetic" : "chip-observed"),
            text: dv < -.5 ? "far below own normal" : "at own normal" }),
        ]),
        el("div", { class: "cc-stats" }, [
          stat("Their normal θ", (stu.theta >= 0 ? "+" : "") + fmt(stu.theta), "fitted baseline", ""),
          stat("Now", (last >= 0 ? "+" : "") + fmt(last), "engagement state", ""),
          stat("Deviation", (dv >= 0 ? "+" : "") + fmt(dv), dv < 0 ? "below own normal" : "above own normal",
            dv < -.5 ? "below" : ""),
        ]),
      ]);
      const vis = el("div", {});
      vis.appendChild(ribbon({ mean: stu.eng, sd: stu.eng_sd, theta: stu.theta, h: 190, w: 620,
        label: "Engagement for " + stu.id + " against a personal baseline of " + fmt(stu.theta) }));
      card.appendChild(vis);
      host.appendChild(card);
    });
  }

  /** Observed history, then simulated futures, with a scenario the visitor controls. */
  function landingSim(host) {
    if (!has("sim.base_med")) {
      host.appendChild(emptyState("Simulation not available",
        "The data file carries no simulation block.")); return;
    }
    const sim = D.sim;
    let on = false;
    const controls = el("div", { class: "scenarios" });
    const b1 = el("button", { type: "button", "aria-pressed": "true", text: "Model dynamics only" });
    const b2 = el("button", { type: "button", "aria-pressed": "false", text: "With engagement support" });
    controls.appendChild(b1); controls.appendChild(b2);
    const chart = el("div", {});
    const caption = el("p", { class: "sv-sub", style: "margin-top:.7rem" });

    function draw() {
      const series = [{ med: sim.base_med, lo: sim.base_lo, hi: sim.base_hi, color: css("--ink-3") }];
      if (on) series.push({ med: sim.alt_med, lo: sim.alt_lo, hi: sim.alt_hi, color: css("--indigo") });
      chart.innerHTML = "";
      chart.appendChild(futureChart({ obs: st.eng, simWeeks: sim.weeks, theta: theta, series: series,
        label: "Observed engagement, then simulated futures." }));
      b1.setAttribute("aria-pressed", String(!on));
      b2.setAttribute("aria-pressed", String(on));
      const bR = sim.base_risk[sim.base_risk.length - 1], aR = sim.alt_risk[sim.alt_risk.length - 1];
      caption.innerHTML = on
        ? "Simulated 8-week cumulative risk: <b>" + pct(bR) + "</b> under model dynamics alone, <b>" +
          pct(aR) + "</b> with the hypothesis applied. This is what the model implies, <b>not</b> an estimated effect of doing anything."
        : "Eight weeks forward from the last observation, 600 particles drawn from the current posterior. Simulated 8-week cumulative risk: <b>" + pct(bR) + "</b>.";
    }
    b1.addEventListener("click", () => { on = false; draw(); });
    b2.addEventListener("click", () => { on = true; draw(); });
    host.appendChild(controls); host.appendChild(chart); host.appendChild(caption);
    draw();
  }

  function mountLanding() {
    const mounts = [
      ["#hero-vis", twinModel],
      ["#vis-think", thinkSection],
      ["#vis-cohort", cohortStrip],
      ["#vis-contrast", contrastPair],
      ["#vis-sim", landingSim],
    ];
    mounts.forEach(([sel, fn]) => {
      const host = $(sel);
      if (!host || host.dataset.done) return;
      const out = boundary(sel.replace("#vis-", "").replace("#", ""), () => { fn(host); return null; });
      if (out) host.appendChild(out);
      host.dataset.done = "1";
    });
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-go]");
    if (a) { e.preventDefault(); go(a.getAttribute("data-go")); }
  });
  window.addEventListener("hashchange", render);

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
    read() {
      try { return JSON.parse(localStorage.getItem(this.KEY) || "null"); }
      catch (e) { return null; }
    },
    write(p) {
      try { localStorage.setItem(this.KEY, JSON.stringify(p)); return true; }
      catch (e) { console.warn("[StudyTwin] profile not persisted:", e); return false; }
    },
    clear() { try { localStorage.removeItem(this.KEY); localStorage.removeItem(this.KEY2); } catch (e) { } },
    KEY2: "studytwin.profile.v2",
    read2() { try { return JSON.parse(localStorage.getItem(this.KEY2) || "null"); } catch (e) { return null; } },
    write2(p) { try { localStorage.setItem(this.KEY2, JSON.stringify(p)); return true; }
                catch (e) { console.warn("[StudyTwin] profile not persisted:", e); return false; } },
    blank() {
      return {
        v: 1, created: null, name: "", level: "", institution: "",
        courses: [], baseline: { study_hours: 12, consistency: 3, workload: 3 },
        consent: false, observations: 0,
      };
    },
  };

  /* ---------------------------------------------- hero diagram ---- */
  /** The concept, not a chart: the twin shadows the student, then runs ahead.
      Real trajectory, real simulated particles, zero chart furniture. */
  function heroDiagram(host) {
    const sim = D.sim, paths = (sim && sim.particles) || [];
    const W = 760, H = 340, PAD = 16;
    const nObs = st.eng.length, nFut = paths.length ? paths[0].length : 0;
    const total = nObs + nFut;
    const all = st.eng.concat(...paths.map((p) => p));
    const lo = Math.min(theta, ...all) - .5, hi = Math.max(theta, ...all) + .5;
    const X = (i) => PAD + (i / (total - 1)) * (W - PAD * 2);
    const Y = (v) => H - PAD - ((v - lo) / (hi - lo)) * (H - PAD * 2);

    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": "Diagram: a student's observed trajectory, the twin's belief tracking it with uncertainty, and a fan of simulated possible futures diverging from the present moment." });

    const cTeal = css("--teal-2"), cInk = css("--ink"), cAmber = css("--amber"),
          cIndigo = css("--indigo"), cInk3 = css("--ink-3");

    // personal baseline — the only horizontal reference in the diagram
    g.appendChild(s("line", { x1: PAD, x2: W - PAD, y1: Y(theta), y2: Y(theta),
      stroke: cAmber, "stroke-width": 1.2, "stroke-dasharray": "6 5", opacity: .75 }));

    // the twin's belief: an uncertainty envelope hugging the observed path
    let band = "";
    st.eng.forEach((m, i) => { band += (i ? " L " : "M ") + X(i) + " " + Y(m + 1.96 * st.eng_sd[i]); });
    for (let i = nObs - 1; i >= 0; i--) band += " L " + X(i) + " " + Y(st.eng[i] - 1.96 * st.eng_sd[i]);
    band += " Z";
    g.appendChild(s("path", { d: band, fill: cTeal, "fill-opacity": .16 }));

    // fan of real simulated futures
    paths.forEach((p, k) => {
      let d2 = "M " + X(nObs - 1) + " " + Y(st.eng[nObs - 1]);
      p.forEach((v, i) => { d2 += " L " + X(nObs + i) + " " + Y(v); });
      const path = s("path", { d: d2, fill: "none", stroke: cIndigo,
        "stroke-width": 1, "stroke-opacity": .22, "stroke-linejoin": "round", class: "draw" });
      g.appendChild(path);
      requestAnimationFrame(() => {
        try {
          const L2 = path.getTotalLength();
          path.style.setProperty("--len", L2);
          path.style.animationDelay = (420 + k * 26) + "ms";
        } catch (e) { }
      });
    });

    // the observed student: solid, ending at the present
    let obs = "";
    st.eng.forEach((m, i) => { obs += (i ? " L " : "M ") + X(i) + " " + Y(m); });
    const trace = s("path", { d: obs, fill: "none", stroke: cInk, "stroke-width": 2.1,
      "stroke-linejoin": "round", "stroke-linecap": "round", class: "draw" });
    g.appendChild(trace);
    requestAnimationFrame(() => {
      try { trace.style.setProperty("--len", trace.getTotalLength()); } catch (e) { }
    });

    // sparse observation marks — evidence, not a scatter plot
    st.eng.forEach((m, i) => {
      if (i % 3) return;
      g.appendChild(s("circle", { cx: X(i), cy: Y(m), r: 2.2, fill: cInk,
        "fill-opacity": .5, class: "fade" }));
    });

    // the present moment
    const nx = X(nObs - 1), ny = Y(st.eng[nObs - 1]);
    g.appendChild(s("line", { x1: nx, x2: nx, y1: PAD, y2: H - PAD,
      stroke: cInk3, "stroke-width": 1, "stroke-dasharray": "2 4", opacity: .45 }));
    g.appendChild(s("circle", { cx: nx, cy: ny, r: 9, fill: cTeal, "fill-opacity": .16, class: "fade" }));
    g.appendChild(s("circle", { cx: nx, cy: ny, r: 4, fill: cTeal, class: "fade" }));

    const lbl = (x, y, txt, col, anchor) => {
      const t = s("text", { x: x, y: y, fill: col, "font-size": 10.5, "font-family": MONO,
        "letter-spacing": ".1em", "text-anchor": anchor || "start", class: "fade" });
      t.textContent = txt; g.appendChild(t);
    };
    lbl(PAD, Y(theta) - 8, "THEIR OWN NORMAL", cAmber);
    lbl(nx - 10, PAD + 10, "NOW", cInk3, "end");
    lbl(nx + 12, PAD + 10, "POSSIBLE FUTURES", cIndigo);
    lbl(PAD, H - PAD + 2, "OBSERVED", cInk3);

    host.appendChild(g);
    host.appendChild(el("div", { class: "hf-caption" }, [
      keyItem("observed history", cInk, false),
      keyItem("the twin's belief, with uncertainty", cTeal, false, true),
      keyItem("their own baseline", cAmber, true),
      keyItem("24 simulated futures", cIndigo, false, true),
    ]));
  }
  function keyItem(text, color, dashed, band) {
    const i = el("i", { class: "hf-key" + (dashed ? " dash" : "") + (band ? " fan" : "") });
    if (band) i.style.background = color; else i.style.borderTopColor = color;
    return el("span", {}, [i, el("span", { text: text })]);
  }

  /* ============================================================
     THE TWIN CORE — the landing hero.

     Not a chart. The form is the argument: many observations
     CONVERGE into one state, which then DIVERGES into many
     futures. A lens, not a plot. That shape is literally what
     the model does, so the composition carries the concept
     before a single word is read.

     Proportions are grounded in real pipeline output (observation
     count, posterior spread, real particle endpoints) so nothing
     here is arbitrary decoration — but it carries no axes and
     makes no quantitative claim.
     ============================================================ */
  function twinCore(host) {
    const W = 820, H = 430, CX = 400, CY = 215;
    const sim = D.sim, particles = (sim && sim.particles) || [];
    const nObs = st.eng.length;

    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "twin-core",
      role: "img", "aria-label":
      "A diagram of the digital twin: learning observations on the left converge into a single " +
      "estimated state at the centre, ringed by its uncertainty and crossed by the student's " +
      "personal baseline, which then diverges into many possible futures on the right." });

    const cTeal = css("--teal"), cTeal2 = css("--teal-2"), cAmber = css("--amber"),
          cIndigo = css("--indigo"), cInk = css("--ink"), cInk3 = css("--ink-3");

    const layer = (name) => s("g", { class: "tc-layer", "data-layer": name });
    const gObs = layer("observations"), gBase = layer("baseline"),
          gCore = layer("state"), gFut = layer("futures");

    /* ---- personal baseline: one horizontal rule through everything ---- */
    gBase.appendChild(s("line", { x1: 24, x2: W - 24, y1: CY, y2: CY,
      stroke: cAmber, "stroke-width": 1.3, "stroke-dasharray": "7 6", opacity: .85 }));
    const bl = s("text", { x: 24, y: CY - 11, fill: cAmber, "font-size": 10.5,
      "font-family": MONO, "letter-spacing": ".14em" });
    bl.textContent = "PERSONAL BASELINE";
    gBase.appendChild(bl);

    /* ---- left: observations converging ---- */
    const engRange = Math.max(...st.eng) - Math.min(...st.eng) || 1;
    const engMin = Math.min(...st.eng);
    for (let i = 0; i < nObs; i++) {
      const f = i / (nObs - 1);
      const x = 30 + f * 268;
      const spread = (1 - f) * 128 + 12;
      const even = ((i % 2 ? 1 : -1) * (0.35 + 0.65 * ((i * 7) % 5) / 4));
      const wob = ((st.eng[i] - engMin) / engRange - .5) * .5;
      const y = CY + (even * 0.72 + wob) * spread;
      const o = .3 + f * .55;
      gObs.appendChild(s("line", { x1: x, y1: y, x2: CX - 86, y2: CY,
        stroke: cTeal2, "stroke-width": .9, "stroke-opacity": o * .38 }));
      const dot = s("circle", { cx: x, cy: y, r: 3 + f * 2.4, fill: cInk,
        "fill-opacity": o, class: "tc-in" });
      dot.style.animationDelay = (i * 34) + "ms";
      gObs.appendChild(dot);
    }
    const ol = s("text", { x: 30, y: 22, fill: cInk3, "font-size": 10.5,
      "font-family": MONO, "letter-spacing": ".14em" });
    ol.textContent = "LEARNING OBSERVATIONS";
    gObs.appendChild(ol);

    /* ---- centre: the state and its uncertainty ---- */
    [104, 76, 50].forEach((r, i) => {
      const ring = s("circle", { cx: CX, cy: CY, r: r, fill: "none", stroke: cTeal2,
        "stroke-width": 1, "stroke-opacity": .2 + i * .13, class: "tc-ring" });
      ring.style.animationDelay = (620 + i * 110) + "ms";
      gCore.appendChild(ring);
    });
    gCore.appendChild(s("circle", { cx: CX, cy: CY, r: 50, fill: cTeal2,
      "fill-opacity": .09, class: "tc-ring" }));
    const core = s("circle", { cx: CX, cy: CY, r: 11, fill: cTeal, class: "tc-core" });
    gCore.appendChild(core);
    const cl = s("text", { x: CX, y: CY + 118, fill: cTeal, "font-size": 10.5,
      "font-family": MONO, "letter-spacing": ".14em", "text-anchor": "middle" });
    cl.textContent = "ESTIMATED STATE";
    gCore.appendChild(cl);
    const ul = s("text", { x: CX, y: CY - 104, fill: cTeal2, "font-size": 10,
      "font-family": MONO, "letter-spacing": ".12em", "text-anchor": "middle", opacity: .8 });
    ul.textContent = "UNCERTAINTY";
    gCore.appendChild(ul);

    /* ---- right: futures diverging (real particle endpoints) ---- */
    const ends = particles.length
      ? particles.map((p) => p[p.length - 1])
      : st.eng.slice(-12);
    const eMin = Math.min(...ends), eMax = Math.max(...ends), eR = (eMax - eMin) || 1;
    ends.forEach((v, k) => {
      const norm = (v - eMin) / eR - .5;
      const x2 = W - 34, y2 = CY + norm * 200;
      const cx1 = CX + 104, cy1 = CY, cx2 = x2 - 120, cy2 = y2;
      const path = s("path", {
        d: `M ${CX + 12} ${CY} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`,
        fill: "none", stroke: cIndigo, "stroke-width": 1.1,
        "stroke-opacity": .34, class: "tc-fut" });
      path.style.animationDelay = (900 + k * 22) + "ms";
      gFut.appendChild(path);
      // no endpoint markers: a vertical column of dots at the canvas edge read
      // as an artefact rather than as outcomes
    });
    const fl = s("text", { x: W - 30, y: 22, fill: cIndigo, "font-size": 10.5,
      "font-family": MONO, "letter-spacing": ".14em", "text-anchor": "end" });
    fl.textContent = "POSSIBLE FUTURES";
    gFut.appendChild(fl);

    [gBase, gObs, gFut, gCore].forEach((n) => g.appendChild(n));

    /* ---- hover zones: reveal what each layer is ---- */
    const ZONES = [
      { name: "observations", x: 0, w: 318, title: "Learning observations",
        body: "Weekly activity, submissions and scores. Evidence arriving over time." },
      { name: "state", x: 318, w: 186, title: "The estimated state",
        body: "One belief about where this student is now — with its uncertainty around it." },
      { name: "futures", x: 504, w: 316, title: "Possible futures",
        body: "The state run forward many times. A distribution, not a prediction." },
    ];
    const tip = el("div", { class: "tc-tip" }, [
      el("p", { class: "tc-tip-t", text: "A living model of one student" }),
      el("p", { class: "tc-tip-b", text: "Hover the diagram to see how it works." }),
    ]);
    ZONES.forEach((z) => {
      const r = s("rect", { x: z.x, y: 0, width: z.w, height: H, fill: "transparent",
        class: "tc-zone", tabindex: "0", role: "button",
        "aria-label": z.title + ". " + z.body });
      const enter = () => {
        g.setAttribute("data-focus", z.name);
        tip.querySelector(".tc-tip-t").textContent = z.title;
        tip.querySelector(".tc-tip-b").textContent = z.body;
      };
      const leave = () => {
        g.removeAttribute("data-focus");
        tip.querySelector(".tc-tip-t").textContent = "A living model of one student";
        tip.querySelector(".tc-tip-b").textContent = "Hover the diagram to see how it works.";
      };
      r.addEventListener("pointerenter", enter);
      r.addEventListener("focus", enter);
      r.addEventListener("pointerleave", leave);
      r.addEventListener("blur", leave);
      g.appendChild(r);
    });

    host.appendChild(g);
    host.appendChild(tip);
  }

  /* ============================================================
     THE TWIN MODEL — hero visual, on the deep plane.

     Replaces the earlier converge/diverge funnel, which read as a
     diagram rather than as a model of something. This is built as
     an instrument: a state at the centre, the student's own
     baseline as a ring around it, the signal channels that feed
     it orbiting outside, and futures branching to the right.

     Every element maps to something the model actually has.
     Nothing is here to fill space.
     ============================================================ */
  function twinModel(host) {
    const W = 760, H = 470, CX = 296, CY = 232;
    const sim = D.sim, particles = (sim && sim.particles) || [];

    const wrap = el("div", { class: "tm-wrap" });
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "tm-svg", role: "img",
      "aria-label":
      "A model of one student: signal channels feeding a central estimated state, " +
      "ringed by that student's own baseline and its uncertainty, branching into " +
      "possible futures." });

    const TEAL = "#22D3B8", TEAL_D = "#0A9C8A", AMB = "#F0A93C",
          IND = "#7B72FF", ON = "#E8EDEC", MUT = "#6E858C";

    const mk = (n) => s("g", { class: "tm-layer", "data-layer": n });
    const gLink = mk("channels"), gRing = mk("baseline"),
          gCore = mk("state"), gFut = mk("futures"), gNode = mk("channels");

    /* ---- uncertainty: the widest thing on screen, as it should be ---- */
    [124, 100, 76].forEach((r, i) => {
      const c = s("circle", { cx: CX, cy: CY, r: r, fill: "none", stroke: TEAL,
        "stroke-opacity": .07 + i * .05, "stroke-width": 1, class: "tm-ring" });
      c.style.animationDelay = (240 + i * 120) + "ms";
      gCore.appendChild(c);
    });
    gCore.appendChild(s("circle", { cx: CX, cy: CY, r: 76, fill: TEAL,
      "fill-opacity": .05, class: "tm-ring" }));

    /* ---- the student's own baseline: a ring, not a line.
           A ring says "your normal is a place you orbit", which is
           what the mean-reverting transition actually encodes. ---- */
    const ring = s("circle", { cx: CX, cy: CY, r: 56, fill: "none", stroke: AMB,
      "stroke-width": 1.6, "stroke-dasharray": "6 7", "stroke-opacity": .9, class: "tm-ring" });
    ring.style.animationDelay = "520ms";
    gRing.appendChild(ring);
    const rl = s("text", { x: CX, y: CY - 66, fill: AMB, "font-size": 10,
      "font-family": MONO, "letter-spacing": ".16em", "text-anchor": "middle", class: "tm-fade" });
    rl.textContent = "YOUR OWN BASELINE";
    gRing.appendChild(rl);

    /* ---- the estimated state: offset from the baseline ring, because
           this student is currently below their own normal ---- */
    const SX = CX - 22, SY = CY + 27;
    gCore.appendChild(s("circle", { cx: SX, cy: SY, r: 26, fill: TEAL,
      "fill-opacity": .16, class: "tm-pulse" }));
    const core = s("circle", { cx: SX, cy: SY, r: 11, fill: TEAL, class: "tm-core" });
    gCore.appendChild(core);
    const sl = s("text", { x: SX, y: SY + 46, fill: TEAL, "font-size": 10,
      "font-family": MONO, "letter-spacing": ".16em", "text-anchor": "middle", class: "tm-fade" });
    sl.textContent = "ESTIMATED STATE";
    gCore.appendChild(sl);
    // the deviation, drawn as the thing it is: a gap
    gCore.appendChild(s("line", { x1: CX, y1: CY, x2: SX, y2: SY, stroke: TEAL,
      "stroke-width": 1, "stroke-opacity": .5, "stroke-dasharray": "2 3", class: "tm-fade" }));

    /* ---- signal channels: what the twin actually reads ---- */
    const CHANNELS = [
      { n: "Content views",     a: -158, r: 210 },
      { n: "Forum activity",    a: -104, r: 186 },
      { n: "Quiz attempts",     a:  -70, r: 168 },
      { n: "Submissions",       a:  152, r: 206 },
      { n: "Assessment scores", a:  118, r: 186 },
    ];
    CHANNELS.forEach((ch, i) => {
      const rad = (ch.a * Math.PI) / 180;
      const x = CX + Math.cos(rad) * ch.r, y = CY + Math.sin(rad) * ch.r * .62;
      const path = s("path", {
        d: `M ${x} ${y} Q ${(x + CX) / 2} ${(y + CY) / 2 - 18} ${CX} ${CY}`,
        fill: "none", stroke: TEAL_D, "stroke-width": 1, "stroke-opacity": .34,
        class: "tm-draw" });
      path.style.animationDelay = (700 + i * 90) + "ms";
      gLink.appendChild(path);

      const node = s("circle", { cx: x, cy: y, r: 5.5, fill: TEAL_D,
        "fill-opacity": .9, class: "tm-fade" });
      node.style.animationDelay = (760 + i * 90) + "ms";
      gNode.appendChild(node);

      const anchor = x < CX ? "end" : "start";
      const t = s("text", { x: x + (x < CX ? -12 : 12), y: y + 4, fill: MUT,
        "font-size": 11, "font-family": MONO, "letter-spacing": ".04em",
        "text-anchor": anchor, class: "tm-fade" });
      t.textContent = ch.n;
      t.style.animationDelay = (800 + i * 90) + "ms";
      gNode.appendChild(t);
    });

    /* ---- futures: real particle endpoints, branching right ---- */
    gFut.appendChild(s("circle", { cx: SX, cy: SY, r: 16, fill: IND,
      "fill-opacity": .16, class: "tm-fade" }));
    const ends = particles.length ? particles.map((p) => p[p.length - 1]) : [];
    const eMin = Math.min(...ends), eMax = Math.max(...ends), eR = (eMax - eMin) || 1;
    ends.slice(0, 18).forEach((v, k) => {
      const norm = (v - eMin) / eR - .5;
      const x2 = W - 46, y2 = CY + norm * 330;
      const p2 = s("path", {
        d: `M ${SX + 10} ${SY} C ${SX + 130} ${SY}, ${x2 - 190} ${y2}, ${x2} ${y2}`,
        fill: "none", stroke: IND, "stroke-width": 1.2, "stroke-opacity": .34,
        class: "tm-draw" });
      p2.style.animationDelay = (1080 + k * 26) + "ms";
      gFut.appendChild(p2);
    });
    const fl = s("text", { x: W - 46, y: CY - 96, fill: IND, "font-size": 10,
      "font-family": MONO, "letter-spacing": ".16em", "text-anchor": "end", class: "tm-fade" });
    fl.textContent = "POSSIBLE FUTURES";
    gFut.appendChild(fl);

    [gCore, gRing, gLink, gFut, gNode].forEach((n) => g.appendChild(n));

    /* ---- interaction: each zone explains itself ---- */
    const ZONES = [
      { name: "channels", x: 0, y: 0, w: 176, h: H, t: "Learning signals",
        b: "Weekly activity, submissions and scores. Silence counts as evidence too." },
      { name: "baseline", x: 176, y: 0, w: 104, h: H, t: "Your own baseline",
        b: "A fitted parameter, not the cohort average. Your normal, learned from you." },
      { name: "state", x: 280, y: 120, w: 140, h: 230, t: "The estimated state",
        b: "Where the model believes you are now — and how far that sits from your normal." },
      { name: "futures", x: 420, y: 0, w: 340, h: H, t: "Possible futures",
        b: "The state run forward 600 times. A distribution, never a prediction." },
    ];
    const panel = el("div", { class: "tm-panel" }, [
      el("p", { class: "tm-panel-t", text: "A living model of one student" }),
      el("p", { class: "tm-panel-b", text: "Hover any part of the model to see what it is." }),
    ]);
    ZONES.forEach((z) => {
      const r = s("rect", { x: z.x, y: z.y, width: z.w, height: z.h, fill: "transparent",
        class: "tm-zone", tabindex: "0", role: "button", "aria-label": z.t + ". " + z.b });
      const on = () => {
        g.setAttribute("data-focus", z.name);
        panel.querySelector(".tm-panel-t").textContent = z.t;
        panel.querySelector(".tm-panel-b").textContent = z.b;
      };
      const off = () => {
        g.removeAttribute("data-focus");
        panel.querySelector(".tm-panel-t").textContent = "A living model of one student";
        panel.querySelector(".tm-panel-b").textContent = "Hover any part of the model to see what it is.";
      };
      r.addEventListener("pointerenter", on); r.addEventListener("focus", on);
      r.addEventListener("pointerleave", off); r.addEventListener("blur", off);
      g.appendChild(r);
    });

    wrap.appendChild(el("div", { class: "tm-chrome" }, [
      el("span", { class: "tm-dot" }),
      el("span", { class: "tm-chrome-t", text: "TWIN MODEL" }),
      el("span", { class: "tm-chrome-s", text: "synthetic · 20 weeks observed" }),
    ]));
    wrap.appendChild(g);
    wrap.appendChild(panel);
    host.appendChild(wrap);
  }

  /* ============================================================
     HOW THE TWIN THINKS — four stages, one shared diagram.
     Selecting a stage changes what the diagram emphasises, so the
     pipeline is understood by watching one object change rather
     than by reading four cards.
     ============================================================ */
  const STAGES = [
    { k: "observe", n: "Observe", d: "New learning signals arrive — activity, submissions, scores.",
      note: "Silence is a signal too. A week with no activity is evidence, not a gap." },
    { k: "understand", n: "Understand", d: "The Twin estimates where the student is now, and how sure it is.",
      note: "The estimate is a distribution. Certainty is part of the answer, not a footnote." },
    { k: "update", n: "Update", d: "Last week's belief becomes this week's starting point.",
      note: "Verified: recursive updating equals replaying the full history, to 0.00e+00." },
    { k: "explore", n: "Explore", d: "The state is generative, so it can be run forward.",
      note: "Many futures, with honest spread. Not a prediction, and never a guarantee." },
  ];

  function thinkSection(host) {
    let active = 0;
    const rail = el("div", { class: "stage-rail" });
    const stageVis = el("div", { class: "stage-vis" });
    const note = el("p", { class: "stage-note" });

    function drawStage(i) {
      const W = 640, H = 260, CX = 320, CY = 130;
      const g = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
        "aria-label": STAGES[i].n + ": " + STAGES[i].d });
      const cTeal = css("--teal"), cTeal2 = css("--teal-2"), cAmber = css("--amber"),
            cIndigo = css("--indigo"), cInk = css("--ink"), cInk3 = css("--ink-3"),
            cLine = css("--line");

      g.appendChild(s("line", { x1: 30, x2: W - 30, y1: CY, y2: CY, stroke: cAmber,
        "stroke-width": 1.1, "stroke-dasharray": "6 5", opacity: i === 1 ? .9 : .3 }));

      // incoming evidence
      for (let k = 0; k < 9; k++) {
        const x = 46 + k * 22, on = i === 0;
        g.appendChild(s("circle", { cx: x, cy: CY + Math.sin(k * 1.1) * 26, r: on ? 3.4 : 2.2,
          fill: cInk, "fill-opacity": on ? .75 : .18 }));
      }
      // the state
      const rings = i === 1 ? [50, 34] : [34];
      rings.forEach((r, j) => g.appendChild(s("circle", { cx: CX, cy: CY, r: r, fill: "none",
        stroke: cTeal2, "stroke-width": 1, "stroke-opacity": i === 1 ? .5 - j * .18 : .22 })));
      g.appendChild(s("circle", { cx: CX, cy: CY, r: i >= 1 ? 8 : 5, fill: cTeal,
        "fill-opacity": i >= 1 ? 1 : .35 }));

      // the update arc: last week's belief moving to this week's
      if (i === 2) {
        g.appendChild(s("path", { d: `M ${CX - 92} ${CY} Q ${CX - 46} ${CY - 54} ${CX - 8} ${CY}`,
          fill: "none", stroke: cTeal, "stroke-width": 1.6, "stroke-dasharray": "5 4" }));
        g.appendChild(s("circle", { cx: CX - 92, cy: CY, r: 5, fill: cTeal, "fill-opacity": .3 }));
      }
      // futures
      for (let k = 0; k < 11; k++) {
        const on = i === 3, sp = (k / 10 - .5) * (on ? 190 : 40);
        g.appendChild(s("path", {
          d: `M ${CX + 10} ${CY} C ${CX + 90} ${CY}, ${W - 130} ${CY + sp}, ${W - 42} ${CY + sp}`,
          fill: "none", stroke: cIndigo, "stroke-width": 1,
          "stroke-opacity": on ? .38 : .1 }));
      }
      return g;
    }

    function select(i) {
      active = i;
      [...rail.children].forEach((c, k) => c.setAttribute("aria-selected", String(k === i)));
      stageVis.innerHTML = "";
      stageVis.appendChild(drawStage(i));
      note.textContent = STAGES[i].note;
    }

    STAGES.forEach((stg, i) => {
      const b = el("button", { type: "button", class: "stage-btn", role: "tab",
        "aria-selected": String(i === 0) }, [
        el("span", { class: "stage-n", text: String(i + 1).padStart(2, "0") }),
        el("span", { class: "stage-name", text: stg.n }),
        el("span", { class: "stage-d", text: stg.d }),
      ]);
      b.addEventListener("click", () => select(i));
      b.addEventListener("pointerenter", () => select(i));
      b.addEventListener("focus", () => select(i));
      rail.appendChild(b);
    });
    rail.setAttribute("role", "tablist");

    host.appendChild(el("div", { class: "stage-wrap" }, [rail,
      el("div", {}, [stageVis, note])]));
    select(0);
  }

  /* ============================================================
     Onboarding twin: the same core, gaining layers as answers
     arrive. The point is that you are building something, not
     filling in a form.
     ============================================================ */
  function onboardTwin(host, step, profile) {
    const W = 320, H = 320, CX = 160, CY = 160;
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", class: "ob-twin" });
    const cTeal = css("--teal"), cTeal2 = css("--teal-2"), cAmber = css("--amber"),
          cInk3 = css("--ink-3"), cIndigo = css("--indigo");

    // uncertainty halo — always widest at the start, because it is
    g.appendChild(s("circle", { cx: CX, cy: CY, r: 118, fill: "none", stroke: cTeal2,
      "stroke-width": 1, "stroke-opacity": .16 }));
    g.appendChild(s("circle", { cx: CX, cy: CY, r: 92, fill: cTeal2, "fill-opacity": .05 }));

    // step 1+: identity core appears
    if (step >= 1) {
      g.appendChild(s("circle", { cx: CX, cy: CY, r: 9, fill: cTeal, class: "tc-core" }));
    } else {
      g.appendChild(s("circle", { cx: CX, cy: CY, r: 9, fill: "none", stroke: cInk3,
        "stroke-width": 1.2, "stroke-dasharray": "3 3" }));
    }

    // step 2+: one node per course, orbiting
    if (step >= 2 && profile.courses.length) {
      profile.courses.forEach((c, i) => {
        const a = (i / Math.max(profile.courses.length, 1)) * Math.PI * 2 - Math.PI / 2;
        const x = CX + Math.cos(a) * 66, y = CY + Math.sin(a) * 66;
        g.appendChild(s("line", { x1: CX, y1: CY, x2: x, y2: y, stroke: cTeal2,
          "stroke-width": .8, "stroke-opacity": .3 }));
        const n = s("circle", { cx: x, cy: y, r: 5, fill: cTeal2, "fill-opacity": .7, class: "tc-in" });
        n.style.animationDelay = (i * 70) + "ms";
        g.appendChild(n);
      });
    }

    // step 3+: the personal baseline becomes a real mark
    if (step >= 3) {
      g.appendChild(s("line", { x1: 22, x2: W - 22, y1: CY, y2: CY, stroke: cAmber,
        "stroke-width": 1.2, "stroke-dasharray": "6 5", class: "tc-in" }));
    }

    // step 4: futures remain latent — there are no observations to run forward
    if (step >= 4) {
      for (let k = 0; k < 7; k++) {
        const sp = (k / 6 - .5) * 90;
        g.appendChild(s("path", {
          d: `M ${CX + 10} ${CY} C ${CX + 60} ${CY}, ${W - 70} ${CY + sp}, ${W - 26} ${CY + sp}`,
          fill: "none", stroke: cIndigo, "stroke-width": 1, "stroke-opacity": .13,
          "stroke-dasharray": "3 4" }));
      }
    }
    host.appendChild(g);

    const CAPS = [
      "Nothing known yet.",
      "Identity set. The state is still the cohort prior.",
      profile.courses.length + " context" + (profile.courses.length === 1 ? "" : "s") + " attached.",
      "A starting baseline — to be replaced by observed behaviour.",
      "Futures stay dashed: there are no observations to run forward.",
    ];
    host.appendChild(el("p", { class: "ob-twin-cap", text: CAPS[Math.min(step, 4)] }));
  }

  /* ================================================= onboarding ---- */
  const STEPS = ["Welcome", "You", "Courses", "Your normal", "Privacy"];
  let draft = null, obStep = 0;

  const SUGGESTED = ["Machine Learning", "Databases", "Operating Systems",
    "Computer Networks", "Algorithms", "Statistics", "Linear Algebra", "Compilers"];

  function stepper(n) {
    const wrap = el("div", { class: "stepper" });
    STEPS.forEach((_, i) => wrap.appendChild(
      el("i", { class: i === n ? "on" : (i < n ? "done" : "") })));
    wrap.appendChild(el("span", { class: "stepper-txt",
      text: "Step " + (n + 1) + " of " + STEPS.length }));
    return wrap;
  }

  function obShell(inner) {
    const root = el("div", { class: "ob" });
    root.appendChild(el("div", { class: "ob-top" }, [
      el("div", { class: "page ob-top-in" }, [
        el("a", { class: "brand", href: "#", "data-go": "" }, [icon("twin", 20),
          el("span", { text: "StudyTwin" })]),
        stepper(obStep),
      ]),
    ]));
    // The twin is visible throughout and gains a layer per answer, so the
    // flow reads as building something rather than completing a form.
    const aside = el("aside", { class: "ob-aside", id: "ob-aside" });
    onboardTwin(aside, obStep, draft || Store.blank());
    root.appendChild(el("div", { class: "ob-body" }, [
      el("div", { class: "ob-split" }, [aside, el("div", {}, [inner])]),
    ]));
    return root;
  }

  /** Redraw the onboarding twin in place, so an answer visibly adds a layer. */
  const OB_CTX = {
    el: el, s: s, icon: icon, css: css, fmt: fmt, pct: pct, Store: Store,
    go: (h) => go(h),
    rerender: () => render(),
    rerenderVis: () => { if (window.ST_Onboarding) window.ST_Onboarding.refreshVis(); },
  };

  function refreshTwinAside() {
    const aside = $("#ob-aside");
    if (!aside) return;
    aside.innerHTML = "";
    onboardTwin(aside, obStep, draft || Store.blank());
  }

  function actions(nextLabel, onNext, opts) {
    const o = opts || {};
    const row = el("div", { class: "ob-actions" });
    if (obStep > 0) {
      const back = el("button", { type: "button", class: "btn btn-ghost", text: "Back" });
      back.addEventListener("click", () => { obStep--; render(); });
      row.appendChild(back);
    }
    row.appendChild(el("span", { class: "spacer" }));
    if (o.secondary) {
      const sec = el("a", { class: "link-btn", href: "#/app", "data-go": "app",
        text: "Explore a demo twin instead" });
      row.appendChild(sec);
    }
    const next = el("button", { type: "button", class: "btn btn-primary" }, [
      el("span", { text: nextLabel }), icon("arrow", 16)]);
    if (o.disabled) { next.disabled = true; next.style.opacity = .45; next.style.cursor = "not-allowed"; }
    next.addEventListener("click", onNext);
    row.appendChild(next);
    return row;
  }

  function viewOnboarding() {
    if (!draft) draft = Store.read() || Store.blank();

    if (obStep === 0) {
      return obShell(el("div", {}, [
        el("p", { class: "ob-step-label", text: "Welcome" }),
        el("h1", { text: "Let's build your Twin." }),
        el("p", { class: "lede", html:
          "StudyTwin learns what <em>your</em> normal looks like, tracks how that picture changes " +
          "week to week, and lets you explore how the coming weeks could unfold." }),
        el("div", { class: "note", style: "margin-bottom:1.5rem" }, [icon("info", 16),
          el("div", { html: "<b>What to expect.</b> Your Twin starts with almost no information about " +
            "you, so its first estimate is close to a typical student with wide uncertainty. It becomes " +
            "genuinely personal only as weekly observations accumulate — we will show you exactly how " +
            "far along it is." })]),
        actions("Start", () => { obStep = 1; render(); }, { secondary: true }),
      ]));
    }

    if (obStep === 1) {
      const wrap = el("div", {}, [
        el("p", { class: "ob-step-label", text: "About you" }),
        el("h1", { text: "Who is the Twin for?" }),
        el("p", { class: "lede", text: "Only what is useful. Nothing here is required to be your real name." }),
      ]);
      const f1 = el("div", { class: "field" }, [
        el("label", { for: "ob-name", text: "Preferred name" }),
        el("p", { class: "hint", text: "Shown in your dashboard. A nickname is fine." }),
      ]);
      const nameIn = el("input", { type: "text", id: "ob-name", value: draft.name,
        placeholder: "e.g. Sid", autocomplete: "off" });
      nameIn.addEventListener("input", (e) => { draft.name = e.target.value; });
      f1.appendChild(nameIn);
      wrap.appendChild(f1);

      const row = el("div", { class: "field-row" });
      const f2 = el("div", { class: "field" }, [el("label", { for: "ob-level", text: "Year of study" })]);
      const sel = el("select", { id: "ob-level" });
      ["", "1st year", "2nd year", "3rd year", "4th year", "Postgraduate"].forEach((v) => {
        const o = el("option", { value: v, text: v || "Select…" });
        if (v === draft.level) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener("change", (e) => { draft.level = e.target.value; });
      f2.appendChild(sel); row.appendChild(f2);

      const f3 = el("div", { class: "field" }, [el("label", { for: "ob-inst", text: "Institution" })]);
      const inst = el("input", { type: "text", id: "ob-inst", value: draft.institution,
        placeholder: "Optional", autocomplete: "off" });
      inst.addEventListener("input", (e) => { draft.institution = e.target.value; });
      f3.appendChild(inst); row.appendChild(f3);
      wrap.appendChild(row);

      wrap.appendChild(el("div", { class: "note" }, [icon("info", 16),
        el("div", { html: "Stored on this device only. <b>None of these fields is used by the " +
          "inference model</b> — the twin infers from behaviour over time, not from demographics." })]));
      wrap.appendChild(actions("Continue", () => { obStep = 2; render(); }));
      return obShell(wrap);
    }

    if (obStep === 2) {
      const wrap = el("div", {}, [
        el("p", { class: "ob-step-label", text: "Academic context" }),
        el("h1", { text: "What are you studying this term?" }),
        el("p", { class: "lede", text: "Each course becomes a context the Twin can track separately." }),
      ]);
      const chips = el("div", { class: "chips" });
      const redraw = () => {
        chips.innerHTML = "";
        draft.courses.forEach((c, i) => {
          const x = el("button", { type: "button", "aria-label": "Remove " + c, text: "×" });
          x.addEventListener("click", () => { draft.courses.splice(i, 1); redraw(); refreshTwinAside(); });
          chips.appendChild(el("span", { class: "chip-in" }, [el("span", { text: c }), x]));
        });
        if (!draft.courses.length) chips.appendChild(el("span", { class: "hint",
          text: "No courses added yet." }));
      };
      redraw();
      const f = el("div", { class: "field" }, [
        el("label", { for: "ob-course", text: "Add a course" }),
      ]);
      const inp = el("input", { type: "text", id: "ob-course", placeholder: "Type and press Enter", autocomplete: "off" });
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target.value.trim()) {
          e.preventDefault();
          if (draft.courses.length < 8) draft.courses.push(e.target.value.trim());
          e.target.value = ""; redraw(); refreshTwinAside();
        }
      });
      f.appendChild(inp);
      const sug = el("div", { class: "chip-suggest" });
      SUGGESTED.forEach((cName) => {
        const b = el("button", { type: "button", text: "+ " + cName });
        b.addEventListener("click", () => {
          if (!draft.courses.includes(cName) && draft.courses.length < 8) {
            draft.courses.push(cName); redraw(); refreshTwinAside();
          }
        });
        sug.appendChild(b);
      });
      f.appendChild(sug);
      wrap.appendChild(chips); wrap.appendChild(f);
      wrap.appendChild(actions("Continue", () => { obStep = 3; render(); }));
      return obShell(wrap);
    }

    if (obStep === 3) {
      const wrap = el("div", {}, [
        el("p", { class: "ob-step-label", text: "Personal baseline" }),
        el("h1", { text: "Your normal is not everyone's normal." }),
        el("p", { class: "lede", html:
          "Twelve hours a week is an ordinary week for one student and a collapse for another. " +
          "These answers give the Twin a starting point — they are <em>not</em> treated as truth." }),
      ]);
      const sliders = [
        ["study_hours", "Typical study hours per week", 0, 40, 1, (v) => v + " h"],
        ["consistency", "How consistent is your week-to-week study?", 1, 5, 1,
          (v) => ["Very irregular", "Irregular", "Mixed", "Fairly steady", "Very steady"][v - 1]],
        ["workload", "How heavy does this term feel right now?", 1, 5, 1,
          (v) => ["Very light", "Light", "Manageable", "Heavy", "Very heavy"][v - 1]],
      ];
      sliders.forEach(([key, label, min, max, stepv, fmtv]) => {
        const out = el("span", { class: "out", text: fmtv(draft.baseline[key]) });
        const r = el("input", { type: "range", min: min, max: max, step: stepv,
          value: draft.baseline[key], id: "sl-" + key });
        r.addEventListener("input", (e) => {
          draft.baseline[key] = +e.target.value;
          out.textContent = fmtv(+e.target.value);
        });
        r.addEventListener("change", refreshTwinAside);
        wrap.appendChild(el("div", { class: "slider-row" }, [
          el("div", { class: "slider-head" }, [el("label", { for: "sl-" + key, text: label }), out]),
          r,
        ]));
      });
      wrap.appendChild(el("div", { class: "note" }, [icon("alert", 16),
        el("div", { html: "<b>Where these actually go.</b> These are self-reported signals. The research " +
          "schema defines a <code>self_report</code> channel for exactly this, and <b>no adapter supplies " +
          "it yet</b> — so your answers are saved to your profile and are <b>not currently used by the " +
          "inference model</b>. We would rather tell you that than imply a slider is steering a filter." })]));
      wrap.appendChild(actions("Continue", () => { obStep = 4; render(); }));
      return obShell(wrap);
    }

    // step 4 — privacy sits next to the commit action, not buried mid-flow
    const wrap = el("div", {}, [
      el("p", { class: "ob-step-label", text: "Privacy" }),
      el("h1", { text: "What happens to this." }),
      el("p", { class: "lede", text: "Short version: it stays in this browser." }),
    ]);
    [
      ["What is stored", "Your name, year, institution, course list and the three baseline answers."],
      ["Where it is stored", "In this browser's local storage. There is no server and no account. " +
        "Clearing your browser data deletes it."],
      ["What is shared", "Nothing. No analytics, no third parties, no network requests."],
      ["What the model uses", "None of it, currently. The inference model learns from weekly " +
        "behavioural observations, which this prototype cannot yet collect."],
    ].forEach(([h, p]) => wrap.appendChild(
      el("div", { class: "consent" }, [el("h3", { text: h }), el("p", { text: p })])));

    wrap.appendChild(el("div", { class: "note" }, [icon("alert", 16),
      el("div", { html: "<b>Prototype.</b> This is a research prototype, not a deployed service. " +
        "Storage behaviour will change if it is ever connected to a backend." })]));

    const chk = el("input", { type: "checkbox", id: "ob-consent" });
    const next = actions("Create my Twin", () => {
      draft.consent = true;
      draft.created = new Date().toISOString();
      draft.observations = 0;
      Store.write(draft);
      go("twin/new");
    }, { disabled: true });
    const btn = next.querySelector(".btn-primary");
    if (draft.consent) { chk.checked = true; btn.disabled = false; btn.style.opacity = 1; btn.style.cursor = ""; }
    chk.addEventListener("change", (e) => {
      btn.disabled = !e.target.checked;
      btn.style.opacity = e.target.checked ? 1 : .45;
      btn.style.cursor = e.target.checked ? "" : "not-allowed";
    });
    wrap.appendChild(el("label", { class: "consent-check", for: "ob-consent" }, [chk,
      el("span", { text: "I understand this is a prototype, my data stays on this device, and my Twin " +
        "will have very wide uncertainty until observations accumulate." })]));
    wrap.appendChild(next);
    return obShell(wrap);
  }

  /* ------------------------------------------- initialisation ---- */
  function viewInit() {
    const v2 = Store.read2();
    const p = v2 ? v2fold(v2) : (Store.read() || Store.blank());
    const root = el("div", { class: "ob" });
    root.appendChild(el("div", { class: "ob-top" }, [el("div", { class: "page ob-top-in" }, [
      el("span", { class: "brand" }, [icon("twin", 20), el("span", { text: "StudyTwin" })]),
    ])]));
    const card = el("div", {}, [
      el("p", { class: "ob-step-label", text: "Initialising" }),
      el("h1", { text: "Building your Twin." }),
    ]);
    const list = el("div", { class: "init-list" });
    const rows = [
      ["Profile stored", p.name ? "on this device" : "no name given", false],
      ["Courses registered", p.courses.length + " course" + (p.courses.length === 1 ? "" : "s"), false],
      ["Baseline answers saved", "not used by inference yet", true],
      ["State initialised at the cohort prior", "no observations yet", false],
      ["Uncertainty set to maximum", "nothing observed to narrow it", true],
    ];
    rows.forEach(([label, note, warn]) => {
      list.appendChild(el("div", { class: "init-row" }, [
        el("span", { class: "mark" }, [icon("shield", 16)]),
        el("span", { text: label }),
        el("span", { class: "st" + (warn ? " warn" : ""), text: note }),
      ]));
    });
    card.appendChild(list);
    const done = el("div", { style: "opacity:0;transition:opacity .4s ease" }, [
      el("p", { class: "lede", style: "margin-bottom:1.5rem", html:
        "<b>Your Twin has a starting point — not a history.</b> It currently knows what a typical " +
        "student looks like and almost nothing about you specifically." }),
    ]);
    const cta = el("a", { class: "btn btn-primary", href: "#/twin", "data-go": "twin" }, [
      el("span", { text: "Meet your Twin" }), icon("arrow", 16)]);
    done.appendChild(cta);
    card.appendChild(done);
    root.appendChild(el("div", { class: "ob-body" }, [el("div", { class: "ob-card" }, [card])]));

    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const items = list.querySelectorAll(".init-row");
    if (reduce) {
      items.forEach((n) => n.classList.add("on"));
      done.style.opacity = 1;
    } else {
      items.forEach((n, i) => setTimeout(() => n.classList.add("on"), 180 + i * 260));
      setTimeout(() => { done.style.opacity = 1; }, 180 + items.length * 260 + 220);
    }
    return root;
  }

  /* ------------------------------------------ the new user's twin ---- */
  function viewTwinNew() {
    const v2 = Store.read2();
    const p = v2 ? v2fold(v2) : Store.read();
    const v = el("div", { class: "view" });
    if (!p) {
      v.appendChild(emptyState("No Twin on this device",
        "Nothing has been created here yet. <a href='#/onboarding' data-go='onboarding'>Create your Twin</a> " +
        "or <a href='#/app' data-go='app'>explore the demo</a>."));
      return v;
    }

    const learning = el("section", { class: "learning" }, [
      el("h3", { text: (p.name ? p.name + ", your" : "Your") + " Twin is still learning." }),
      el("p", { class: "why", html:
        "It has <b>0 weekly observations</b>. Until behaviour accumulates, the state estimate is the " +
        "cohort prior with maximum uncertainty — so there is no trajectory to plot, no deviation from " +
        "your baseline to report, and no future worth simulating." }),
    ]);
    const pctDone = 0;
    learning.appendChild(el("div", { class: "gauge" }, [
      el("div", { class: "gauge-track" }, [
        el("div", { class: "gauge-fill", style: "width:" + pctDone + "%" })]),
      el("span", { class: "gauge-txt", text: "0 of 4 weeks before estimates stabilise" }),
    ]));
    const needs = el("div", { class: "need-list" });
    [
      ["Weekly activity observations — the model's primary input", "not yet collected"],
      ["At least one assessment score, to identify the capability dimension", "not yet collected"],
      ["About four weeks, before the personal baseline separates from the cohort", "not yet reached"],
    ].forEach(([t, st2]) => needs.appendChild(el("div", { class: "need" }, [
      icon("info", 15), el("div", { html: t + " — <span class='muted'>" + st2 + "</span>" })])));
    learning.appendChild(needs);
    learning.appendChild(el("div", { class: "note", style: "margin-top:1.5rem" }, [icon("alert", 16),
      el("div", { html: "<b>This prototype has no observation pipeline.</b> There is no integration with " +
        "an LMS, so no observations will arrive. Rather than fabricate them, the Twin stays honest about " +
        "being empty. To see a fully-populated Twin, " +
        "<a href='#/app' data-go='app'>open the demo</a>." })]));
    v.appendChild(learning);

    const prof = el("section", { class: "card" });
    prof.appendChild(el("div", { class: "card-head" }, [el("div", {}, [
      el("p", { class: "card-title", text: "What your Twin knows" }),
      el("p", { class: "card-sub", text: "Stored on this device. Nothing here reaches the inference model yet." }),
    ])]));
    const tbl = el("table", { class: "data" });
    const rows = [
      ["Name", p.name || "—", "profile only"],
      ["Year", p.level || "—", "profile only"],
      ["Institution", p.institution || "—", "profile only"],
      ["Courses", p.courses.length ? p.courses.join(", ") : "—", "would become contexts"],
      ["Typical study hours", p.baseline.study_hours + " h/week", "self_report — unused"],
      ["Consistency", String(p.baseline.consistency) + " / 5", "self_report — unused"],
      ["Perceived workload", String(p.baseline.workload) + " / 5", "self_report — unused"],
      ["Observations", "0", "required for inference"],
    ];
    tbl.innerHTML = "<thead><tr><th>Field</th><th>Value</th><th>Model use</th></tr></thead><tbody>" +
      rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td class="muted">${r[2]}</td></tr>`).join("") +
      "</tbody>";
    prof.appendChild(tbl);
    const reset = el("button", { type: "button", class: "link-btn",
      style: "margin-top:1rem;display:inline-block", text: "Delete this Twin from my device" });
    reset.addEventListener("click", () => {
      Store.clear(); draft = null; obStep = 0; go("");
    });
    prof.appendChild(reset);
    v.appendChild(prof);
    return v;
  }

  // fill live figures into the marketing copy so it can never drift from the data
  document.querySelectorAll("[data-fig]").forEach((n) => {
    const map = {
      theta: fmt(theta), eng: fmt(lastEng), dev: (dev >= 0 ? "+" : "") + fmt(dev),
      weeks: String(st.t.length), students: String(D.cohort.students),
      auc: D.metrics.find((m) => m.name === "twin_state").auc.toFixed(3),
      ece: D.metrics.find((m) => m.name === "twin_state").ece.toFixed(4),
    };
    n.textContent = map[n.getAttribute("data-fig")] || n.textContent;
  });

  render();
})();
