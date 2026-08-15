/* ============================================================
   StudyTwin  ·  instrument graphics

   Hand-built SVG. There is no charting library here on purpose:
   every library we looked at treats uncertainty as an optional
   overlay you can switch off, and treats a simulated series as
   just another line. In this product uncertainty is geometry and
   simulation is visually unmistakable, so the marks are ours.

   Conventions honoured by every chart in this file:
     SOLID + ink        observed
     DASHED + hatched   model-generated
     DASHED amber       the student's own baseline, theta
     teal / coral       above / below theta  (direction, not verdict)
     thickness          the 95% credible interval
   ============================================================ */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const MONO = "Cascadia Mono, Consolas, ui-monospace, monospace";
  const s = (tag, a) => {
    const n = document.createElementNS(NS, tag);
    for (const k in (a || {})) n.setAttribute(k, a[k]);
    return n;
  };
  const txt = (a, t) => { const n = s("text", a); n.textContent = t; return n; };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const f2 = (v, d) => (v === null || v === undefined || Number.isNaN(v))
    ? "—" : v.toFixed(d === undefined ? 2 : d);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let UID = 0;
  const uid = (p) => p + "-" + (++UID);

  /** Diagonal hatch. Simulation must differ in TEXTURE, not only in hue,
      so the observed/simulated split survives greyscale printing and
      colour-vision differences alike. */
  function hatch(defs, id, color, op) {
    const p = s("pattern", { id: id, width: 6, height: 6,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    p.appendChild(s("rect", { width: 6, height: 6, fill: color, "fill-opacity": (op || .1) }));
    p.appendChild(s("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: color,
      "stroke-width": 1.6, "stroke-opacity": Math.min((op || .1) * 2.6, 1) }));
    defs.appendChild(p);
    return "url(#" + id + ")";
  }

  /* ============================================================
     1 - THE STATE RIBBON
     ------------------------------------------------------------
     The signature visualisation and the dominant object on Twin
     Home. Drawn against theta rather than zero, because the whole
     personalisation argument is "relative to their own normal".
     ============================================================ */
  function stateRibbon(o) {
    const mean = o.mean, sd = o.sd, theta = o.theta;
    const sim = o.sim || null;
    const n = mean.length;
    const nSim = sim ? sim.med.length : 0;
    const W = 1120, H = o.h || 430;
    const L = 58, R = 26, T = 30, B = 42;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;

    // Domain covers the observed band, theta, and any simulated envelope.
    let lo = Math.min(theta, ...mean.map((m, i) => m - 1.96 * sd[i]));
    let hi = Math.max(theta, ...mean.map((m, i) => m + 1.96 * sd[i]));
    if (sim) { lo = Math.min(lo, ...sim.lo); hi = Math.max(hi, ...sim.hi); }
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;

    const total = n + nSim;
    const X = (i) => x0 + (i / Math.max(total - 1, 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const cInk = css("--ink"), cInk3 = css("--ink-3"), cInk4 = css("--ink-4");
    const cLine = css("--line");
    const cTeal = css("--teal"), cTealB = css("--teal-b");
    const cCoral = css("--coral"), cCoralB = css("--coral-b");
    const cAmber = css("--amber"), cAmberB = css("--amber-b");
    const cIndigo = css("--indigo"), cIndigoB = css("--indigo-b");

    const host = document.createElement("div");
    host.className = "vz";
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "vz-svg",
      role: "img", "aria-label": o.label || "State ribbon" });
    const defs = s("defs", {}); g.appendChild(defs);
    const simFill = hatch(defs, uid("hx"), cIndigoB, .085);

    /* -- y grid: present, never heavy -------------------------- */
    const span = hi - lo;
    const step = span > 6 ? 2 : span > 3 ? 1 : span > 1.4 ? .5 : .25;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v),
        stroke: cLine, "stroke-width": 1 }));
      g.appendChild(txt({ x: x0 - 10, y: Y(v) + 3.5, fill: cInk4, "font-size": 10.5,
        "font-family": MONO, "text-anchor": "end" }, v.toFixed(step < 1 ? 2 : 0)));
    }

    /* -- simulated region: a different ground, plus a boundary -- */
    if (sim) {
      const bx = X(n - 1);
      g.appendChild(s("rect", { x: bx, y: y0, width: x1 - bx, height: y1 - y0,
        fill: cIndigoB, "fill-opacity": .022 }));
      g.appendChild(s("line", { x1: bx, x2: bx, y1: y0 - 8, y2: y1,
        stroke: cIndigo, "stroke-width": 1, "stroke-dasharray": "3 4" }));
      g.appendChild(txt({ x: bx - 8, y: y0 - 12, fill: cInk4, "font-size": 9.5,
        "font-family": MONO, "text-anchor": "end", "letter-spacing": "1.6" }, "OBSERVED"));
      g.appendChild(txt({ x: bx + 8, y: y0 - 12, fill: cIndigoB, "font-size": 9.5,
        "font-family": MONO, "letter-spacing": "1.6" }, "SIMULATED"));
    }

    /* -- 1. UNCERTAINTY as thickness --------------------------- */
    const gBand = s("g", { class: "vz-band" });
    for (let i = 0; i < n - 1; i++) {
      const a = mean[i], b = mean[i + 1];
      const sa = 1.96 * sd[i], sb = 1.96 * sd[i + 1];
      const bothUp = a >= theta && b >= theta, bothDown = a < theta && b < theta;
      const col = bothUp ? cTeal : bothDown ? cCoral : cInk3;
      gBand.appendChild(s("path", {
        d: "M " + X(i) + " " + Y(a + sa) + " L " + X(i + 1) + " " + Y(b + sb) +
           " L " + X(i + 1) + " " + Y(b - sb) + " L " + X(i) + " " + Y(a - sa) + " Z",
        fill: col, "fill-opacity": .19
      }));
    }
    g.appendChild(gBand);

    /* -- 2. THETA: a first-class mark ------------------------- */
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(theta), y2: Y(theta),
      stroke: cAmber, "stroke-width": 1.6, "stroke-dasharray": "6 5", "stroke-opacity": .95 }));
    if (H >= 320) {
      g.appendChild(s("rect", { x: x0 + 4, y: Y(theta) - 20, width: 122, height: 16,
        rx: 3, fill: css("--amber-d"), stroke: "#4A381E" }));
      g.appendChild(txt({ x: x0 + 11, y: Y(theta) - 8.5, fill: cAmberB, "font-size": 9.5,
        "font-family": MONO, "letter-spacing": ".8" }, "OWN BASELINE " + f2(theta)));
    } else {
      g.appendChild(txt({ x: x0 + 4, y: Y(theta) - 7, fill: cAmberB, "font-size": 13,
        "font-family": MONO, "letter-spacing": ".5" }, "θ " + f2(theta)));
    }

    /* -- 3. SIMULATED envelope + median ------------------------ */
    if (sim) {
      // Traverse the upper boundary left to right, then the LOWER boundary
      // right to left. Walking both in the same direction closes the polygon
      // through its own middle and paints a bowtie instead of an envelope.
      const sx = (j) => X(n - 1 + j);
      let up = "M " + X(n - 1) + " " + Y(mean[n - 1]);
      for (let j = 0; j < nSim; j++) up += " L " + sx(j + 1) + " " + Y(sim.hi[j]);
      let dn = "";
      for (let j = nSim - 1; j >= 0; j--) dn += " L " + sx(j + 1) + " " + Y(sim.lo[j]);
      dn += " L " + X(n - 1) + " " + Y(mean[n - 1]);
      g.appendChild(s("path", { d: up + dn + " Z", fill: simFill, stroke: cIndigo,
        "stroke-width": 1, "stroke-opacity": .5, "stroke-dasharray": "4 4" }));
      let mp = "M " + X(n - 1) + " " + Y(mean[n - 1]);
      for (let j = 0; j < nSim; j++) mp += " L " + sx(j + 1) + " " + Y(sim.med[j]);
      g.appendChild(s("path", { d: mp, fill: "none", stroke: cIndigoB, "stroke-width": 2,
        "stroke-dasharray": "7 5", "stroke-linecap": "round" }));
    }

    /* -- 4. OBSERVED trace: solid, bright, unmistakable -------- */
    let p = "";
    for (let i = 0; i < n; i++) p += (i ? " L " : "M ") + X(i) + " " + Y(mean[i]);
    const trace = s("path", { d: p, fill: "none", stroke: cInk, "stroke-width": 2.1,
      "stroke-linejoin": "round", "stroke-linecap": "round" });
    g.appendChild(trace);

    for (let i = 0; i < n; i++) {
      g.appendChild(s("circle", { cx: X(i), cy: Y(mean[i]), r: 2.4,
        fill: mean[i] >= theta ? cTealB : cCoralB, "fill-opacity": .9 }));
    }

    /* -- 5. current state marker ------------------------------- */
    const cx = X(n - 1), cy = Y(mean[n - 1]);
    const nowUp = mean[n - 1] >= theta;
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 9, fill: "none",
      stroke: nowUp ? cTealB : cCoralB, "stroke-width": 1, "stroke-opacity": .45 }));
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 4.4, fill: css("--bg"),
      stroke: nowUp ? cTealB : cCoralB, "stroke-width": 2.4 }));

    /* -- 6. x axis --------------------------------------------- */
    const ticks = [];
    const stride = Math.max(1, Math.round(total / 9));
    for (let i = 0; i < total; i += stride) ticks.push(i);
    if (ticks[ticks.length - 1] !== total - 1) ticks.push(total - 1);
    ticks.forEach((i) => {
      g.appendChild(txt({ x: X(i), y: y1 + 20, fill: i >= n ? cIndigo : cInk4,
        "font-size": 10, "font-family": MONO, "text-anchor": "middle" }, "w" + i));
    });

    /* -- 7. interaction: crosshair, pinned week, HTML readout --- */
    const pin = s("line", { y1: y0, y2: y1, x1: 0, x2: 0, stroke: cTealB, "stroke-width": 1,
      "stroke-dasharray": "2 3", opacity: 0 });
    g.appendChild(pin);

    const cross = s("g", { opacity: 0 });
    const cLineEl = s("line", { x1: 0, x2: 0, y1: y0, y2: y1, stroke: css("--line-3"),
      "stroke-width": 1 });
    const cDot = s("circle", { cx: 0, cy: 0, r: 5, fill: "none", stroke: cInk, "stroke-width": 2 });
    cross.appendChild(cLineEl); cross.appendChild(cDot);
    g.appendChild(cross);

    host.appendChild(g);
    const tip = document.createElement("div");
    tip.className = "vz-tip"; tip.hidden = true;
    host.appendChild(tip);

    function seriesAt(i) {
      if (i < n) return { obs: true, v: mean[i], sd: sd[i], w: i };
      const j = i - n;
      return { obs: false, v: sim.med[j], lo: sim.lo[j], hi: sim.hi[j], w: i };
    }
    function nearest(clientX) {
      const r = g.getBoundingClientRect();
      const sx = ((clientX - r.left) / r.width) * W;
      const i = Math.round(((sx - x0) / (x1 - x0)) * (total - 1));
      return clamp(i, 0, total - 1);
    }
    function showTip(i) {
      const d = seriesAt(i);
      const dev = d.v - theta;
      const rows = d.obs
        ? [["Engagement", f2(d.v)], ["Personal baseline", f2(theta)],
           ["Deviation", (dev >= 0 ? "+" : "") + f2(dev)],
           ["Uncertainty", "±" + f2(1.96 * d.sd)]]
        : [["Median", f2(d.v)], ["Personal baseline", f2(theta)],
           ["5th percentile", f2(d.lo)], ["95th percentile", f2(d.hi)]];
      tip.innerHTML =
        '<p class="vz-tip-h">WEEK ' + String(d.w).padStart(2, "0") +
        (d.obs ? "" : ' <span class="vz-tip-sim">SIMULATED</span>') + "</p>" +
        rows.map((r2) => '<div class="vz-tip-r"><span>' + r2[0] +
          '</span><span class="num">' + r2[1] + "</span></div>").join("") +
        (o.extra ? o.extra(i) : "");
      tip.hidden = false;
      const hr = host.getBoundingClientRect();
      const px = (X(i) / W) * hr.width;
      const py = (Y(d.v) / H) * hr.height;
      const flip = px > hr.width - 226;
      tip.style.left = (flip ? Math.max(px - 210, 4) : px + 18) + "px";
      tip.style.top = clamp(py - 24, 6, Math.max(hr.height - 160, 6)) + "px";
      cross.setAttribute("opacity", 1);
      cLineEl.setAttribute("x1", X(i)); cLineEl.setAttribute("x2", X(i));
      cDot.setAttribute("cx", X(i)); cDot.setAttribute("cy", Y(d.v));
      cDot.setAttribute("stroke", d.obs ? cInk : cIndigoB);
    }
    function hideTip() { tip.hidden = true; cross.setAttribute("opacity", 0); }

    g.addEventListener("pointermove", (e) => {
      const i = nearest(e.clientX);
      showTip(i);
      if (o.onHover) o.onHover(i < n ? i : null);
    });
    g.addEventListener("pointerleave", () => {
      hideTip();
      if (o.onHover) o.onHover(null);
    });
    if (o.onSelect) {
      g.style.cursor = "crosshair";
      g.addEventListener("click", (e) => {
        const i = nearest(e.clientX);
        if (i < n) o.onSelect(i);
      });
    }
    host.setWeek = function (i) {
      if (i === null || i === undefined) { pin.setAttribute("opacity", 0); return; }
      pin.setAttribute("x1", X(i)); pin.setAttribute("x2", X(i));
      pin.setAttribute("opacity", .85);
    };

    if (!reduced()) {
      requestAnimationFrame(function () {
        try {
          const len = trace.getTotalLength();
          if (!len) return;
          trace.style.strokeDasharray = len;
          trace.style.strokeDashoffset = len;
          trace.getBoundingClientRect();
          trace.style.transition = "stroke-dashoffset .95s cubic-bezier(.22,.61,.36,1)";
          trace.style.strokeDashoffset = "0";
        } catch (e) { /* getTotalLength unavailable in some headless paths */ }
      });
    }
    return host;
  }

  /* ============================================================
     2 - THE TWIN FIELD  (hero emblem)
     ------------------------------------------------------------
     A student's twenty weeks wrapped into a ring. Each tick runs
     from the baseline circle out to that week's state, so tick
     LENGTH is deviation from their own normal and tick DIRECTION
     is its sign. A student sitting exactly at their baseline
     produces a perfect circle and no ticks at all.

     It is a portrait of a model of a person, not a chart. The
     readable linear instrument lives on Twin Home.
     ============================================================ */
  function twinField(o) {
    const mean = o.mean, sd = o.sd, theta = o.theta;
    const sim = o.sim || null;
    const n = mean.length, nSim = sim ? sim.med.length : (o.simSteps || 8);
    const W = 640, H = 600, CX = 320, CY = 296;
    const rIn = 66, rOut = 244;

    let lo = Math.min(theta, ...mean.map((m, i) => m - 1.96 * sd[i]));
    let hi = Math.max(theta, ...mean.map((m, i) => m + 1.96 * sd[i]));
    if (sim) { lo = Math.min(lo, ...sim.lo); hi = Math.max(hi, ...sim.hi); }
    const pd = (hi - lo) * .06; lo -= pd; hi += pd;
    const Rr = (v) => rIn + ((clamp(v, lo, hi) - lo) / (hi - lo)) * (rOut - rIn);

    const total = n + nSim;
    const A0 = -145, SWEEP = 290;                    // degrees, clockwise from 12
    const Ang = (i) => (A0 + (i / (total - 1)) * SWEEP) * Math.PI / 180;
    const PX = (i, v) => CX + Rr(v) * Math.sin(Ang(i));
    const PY = (i, v) => CY - Rr(v) * Math.cos(Ang(i));

    const cTeal = css("--teal"), cTealB = css("--teal-b");
    const cCoral = css("--coral"), cCoralB = css("--coral-b");
    const cAmber = css("--amber"), cAmberB = css("--amber-b");
    const cIndigoB = css("--indigo-b"), cInk = css("--ink");
    const cInk4 = css("--ink-4"), cLine = css("--line-2");

    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "tf-svg",
      role: "img", "aria-label": o.label ||
        ("Twenty observed weeks of engagement wrapped into a ring around a personal " +
         "baseline of " + f2(theta) + ", with eight simulated future weeks") });

    /* ---- structural frame: the outer measuring ring ---------- */
    const frame = s("g", { class: "tf-layer", "data-layer": "frame" });
    for (let k = 0; k <= 116; k++) {
      const a = (A0 - 6 + (k / 116) * (SWEEP + 12)) * Math.PI / 180;
      const maj = k % 8 === 0;
      const r1 = rOut + 16, r2 = rOut + (maj ? 27 : 21);
      frame.appendChild(s("line", {
        x1: CX + r1 * Math.sin(a), y1: CY - r1 * Math.cos(a),
        x2: CX + r2 * Math.sin(a), y2: CY - r2 * Math.cos(a),
        stroke: maj ? cInk4 : cLine, "stroke-width": maj ? 1.4 : 1
      }));
    }
    g.appendChild(frame);

    /* ---- LAYER: uncertainty (the annulus) -------------------- */
    const unc = s("g", { class: "tf-layer", "data-layer": "uncertainty" });
    let uo = "", ui = "";
    for (let i = 0; i < n; i++) {
      uo += (i ? " L " : "M ") + PX(i, mean[i] + 1.96 * sd[i]) + " " + PY(i, mean[i] + 1.96 * sd[i]);
    }
    for (let i = n - 1; i >= 0; i--) {
      ui += " L " + PX(i, mean[i] - 1.96 * sd[i]) + " " + PY(i, mean[i] - 1.96 * sd[i]);
    }
    unc.appendChild(s("path", { d: uo + ui + " Z", fill: cTealB, "fill-opacity": .075,
      stroke: cTeal, "stroke-width": .8, "stroke-opacity": .16 }));
    g.appendChild(unc);

    /* ---- LAYER: personal baseline (the perfect circle) ------- */
    const base = s("g", { class: "tf-layer", "data-layer": "baseline" });
    base.appendChild(s("circle", { cx: CX, cy: CY, r: Rr(theta), fill: "none",
      stroke: cAmber, "stroke-width": 1.5, "stroke-dasharray": "6 6", "stroke-opacity": .95 }));
    const ta = (A0 + SWEEP + 15) * Math.PI / 180;
    base.appendChild(txt({ x: CX + (Rr(theta) + 10) * Math.sin(ta),
      y: CY - (Rr(theta) + 10) * Math.cos(ta), fill: cAmberB, "font-size": 11.5,
      "font-family": MONO, "letter-spacing": ".6" }, "θ " + f2(theta)));
    g.appendChild(base);

    /* ---- LAYER: observations -------------------------------- */
    const obs = s("g", { class: "tf-layer", "data-layer": "observations" });
    for (let i = 0; i < n; i++) {
      const up = mean[i] >= theta;
      const col = up ? cTealB : cCoralB;
      const tick = s("line", {
        x1: PX(i, theta), y1: PY(i, theta), x2: PX(i, mean[i]), y2: PY(i, mean[i]),
        stroke: col, "stroke-width": 3, "stroke-linecap": "round", "stroke-opacity": 1,
        class: "tf-tick"
      });
      tick.style.setProperty("--d", (i * 24) + "ms");
      obs.appendChild(tick);
      const dot = s("circle", { cx: PX(i, mean[i]), cy: PY(i, mean[i]), r: 3.1,
        fill: col, class: "tf-tick" });
      dot.style.setProperty("--d", (i * 24) + "ms");
      obs.appendChild(dot);
    }
    let op = "";
    for (let i = 0; i < n; i++) op += (i ? " L " : "M ") + PX(i, mean[i]) + " " + PY(i, mean[i]);
    obs.appendChild(s("path", { d: op, fill: "none", stroke: cInk, "stroke-width": 1.2,
      "stroke-opacity": .34, "stroke-linejoin": "round" }));
    g.appendChild(obs);

    /* ---- LAYER: futures -------------------------------------
       A wedge, not a bundle of spirals. Individual particle paths
       are honest but illegible once wrapped around a ring: they
       cross each other and read as noise. The readable fan of real
       paths lives on Future Lab, on a linear axis where it works.  */
    const fut = s("g", { class: "tf-layer", "data-layer": "futures" });
    if (sim) {
      let up = "M " + PX(n - 1, mean[n - 1]) + " " + PY(n - 1, mean[n - 1]);
      for (let j = 0; j < nSim; j++) up += " L " + PX(n + j, sim.hi[j]) + " " + PY(n + j, sim.hi[j]);
      let dn = "";
      for (let j = nSim - 1; j >= 0; j--) dn += " L " + PX(n + j, sim.lo[j]) + " " + PY(n + j, sim.lo[j]);
      dn += " L " + PX(n - 1, mean[n - 1]) + " " + PY(n - 1, mean[n - 1]);
      fut.appendChild(s("path", { d: up + dn + " Z", fill: cIndigoB, "fill-opacity": .06,
        stroke: cIndigoB, "stroke-width": 1, "stroke-opacity": .3, "stroke-dasharray": "4 4" }));
      let md = "M " + PX(n - 1, mean[n - 1]) + " " + PY(n - 1, mean[n - 1]);
      for (let j = 0; j < nSim; j++) md += " L " + PX(n + j, sim.med[j]) + " " + PY(n + j, sim.med[j]);
      fut.appendChild(s("path", { d: md, fill: "none", stroke: cIndigoB, "stroke-width": 1.8,
        "stroke-dasharray": "6 5", "stroke-linecap": "round", "stroke-opacity": .9 }));
      for (let j = 0; j < nSim; j++) {
        fut.appendChild(s("line", {
          x1: PX(n + j, sim.lo[j]), y1: PY(n + j, sim.lo[j]),
          x2: PX(n + j, sim.hi[j]), y2: PY(n + j, sim.hi[j]),
          stroke: cIndigoB, "stroke-width": 1, "stroke-opacity": .13 }));
      }
    }
    const fa = (A0 + SWEEP - 6) * Math.PI / 180;
    fut.appendChild(txt({ x: CX + (rOut + 42) * Math.sin(fa), y: CY - (rOut + 42) * Math.cos(fa),
      fill: cIndigoB, "font-size": 10, "font-family": MONO, "letter-spacing": "1.4",
      "text-anchor": "middle" }, "SIMULATED"));
    g.appendChild(fut);

    /* ---- LAYER: current state (the core) --------------------- */
    const core = s("g", { class: "tf-layer", "data-layer": "current" });
    const last = mean[n - 1], nowUp = last >= theta;
    core.appendChild(s("line", { x1: CX, y1: CY, x2: PX(n - 1, last), y2: PY(n - 1, last),
      stroke: nowUp ? cTealB : cCoralB, "stroke-width": 1, "stroke-opacity": .35,
      "stroke-dasharray": "2 4" }));
    core.appendChild(s("circle", { cx: CX, cy: CY, r: 58, fill: css("--bg"),
      stroke: css("--line-2"), "stroke-width": 1 }));
    core.appendChild(s("circle", { cx: CX, cy: CY, r: 58, fill: nowUp ? cTeal : cCoral,
      "fill-opacity": .07 }));
    core.appendChild(txt({ x: CX, y: CY - 13, fill: cInk4, "font-size": 8.5,
      "font-family": MONO, "text-anchor": "middle", "letter-spacing": "1.6" }, "CURRENT STATE"));
    core.appendChild(txt({ x: CX, y: CY + 15, fill: cInk, "font-size": 34,
      "text-anchor": "middle", "letter-spacing": "-1" }, f2(last)));
    core.appendChild(txt({ x: CX, y: CY + 32, fill: nowUp ? cTealB : cCoralB, "font-size": 10,
      "font-family": MONO, "text-anchor": "middle" },
      (last - theta >= 0 ? "+" : "") + f2(last - theta) + " vs own"));
    core.appendChild(s("circle", { cx: PX(n - 1, last), cy: PY(n - 1, last), r: 9,
      fill: "none", stroke: nowUp ? cTealB : cCoralB, "stroke-width": 1.2, "stroke-opacity": .5 }));
    g.appendChild(core);

    /* ---- week markers, quiet ------------------------------- */
    [0, Math.floor(n / 2), n - 1].forEach((i) => {
      const a = Ang(i), r = rOut + 40;
      g.appendChild(txt({ x: CX + r * Math.sin(a), y: CY - r * Math.cos(a) + 3,
        fill: cInk4, "font-size": 9.5, "font-family": MONO, "text-anchor": "middle" }, "w" + i));
    });

    /* ---- layer focus: motion that communicates state -------- */
    g.focusLayer = function (name) {
      ["observations", "baseline", "current", "futures", "uncertainty", "frame"].forEach((k) => {
        g.querySelectorAll('[data-layer="' + k + '"]').forEach((node) => {
          node.style.opacity = !name ? 1 : (k === name ? 1 : k === "frame" ? .3 : .16);
        });
      });
      const b = g.querySelector('[data-layer="baseline"] circle');
      if (b) b.setAttribute("stroke-width", name === "baseline" ? 2.8 : 1.5);
      const u = g.querySelector('[data-layer="uncertainty"] path');
      if (u) u.setAttribute("fill-opacity", name === "uncertainty" ? .26 : .075);
      g.querySelectorAll('[data-layer="futures"] path').forEach((p) =>
        p.setAttribute("stroke-opacity", name === "futures" ? .72 : .3));
    };
    return g;
  }

  /* ============================================================
     3 - FAN CHART  (Future Lab)
     Real simulated particle paths, not interpolation between two
     quantiles. A fan drawn from quantiles would be a picture of a
     band pretending to be a set of outcomes.
     ============================================================ */
  function fanChart(o) {
    const obs = o.obs, theta = o.theta, br = o.branches;
    const n = obs.length, nS = br[0].med.length;
    const W = 1120, H = o.h || 400;
    const L = 58, R = 92, T = 28, B = 40;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;

    let lo = Math.min(theta, ...obs), hi = Math.max(theta, ...obs);
    br.forEach((b) => { lo = Math.min(lo, ...b.lo); hi = Math.max(hi, ...b.hi); });
    (o.paths || []).forEach((p) => p.forEach((v) => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
    const pad = (hi - lo) * .1; lo -= pad; hi += pad;

    const total = n + nS;
    const X = (i) => x0 + (i / (total - 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const cInk = css("--ink"), cInk4 = css("--ink-4"), cLine = css("--line");
    const cAmber = css("--amber"), cAmberB = css("--amber-b"), cIndigo = css("--indigo");

    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "vz-svg",
      role: "img", "aria-label": o.label || "Observed engagement then simulated futures" });
    const defs = s("defs", {}); g.appendChild(defs);

    const span = hi - lo, step = span > 6 ? 2 : span > 3 ? 1 : .5;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: cLine, "stroke-width": 1 }));
      g.appendChild(txt({ x: x0 - 10, y: Y(v) + 3.5, fill: cInk4, "font-size": 10.5,
        "font-family": MONO, "text-anchor": "end" }, v.toFixed(step < 1 ? 1 : 0)));
    }

    const bx = X(n - 1);
    g.appendChild(s("rect", { x: bx, y: y0, width: x1 - bx, height: y1 - y0,
      fill: css("--indigo-b"), "fill-opacity": .022 }));
    g.appendChild(s("line", { x1: bx, x2: bx, y1: y0 - 8, y2: y1, stroke: cIndigo,
      "stroke-width": 1, "stroke-dasharray": "3 4" }));
    g.appendChild(txt({ x: bx - 8, y: y0 - 11, fill: cInk4, "font-size": 9.5,
      "font-family": MONO, "text-anchor": "end", "letter-spacing": "1.6" }, "OBSERVED"));
    g.appendChild(txt({ x: bx + 8, y: y0 - 11, fill: css("--indigo-b"), "font-size": 9.5,
      "font-family": MONO, "letter-spacing": "1.6" }, "MODEL-GENERATED"));

    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(theta), y2: Y(theta), stroke: cAmber,
      "stroke-width": 1.4, "stroke-dasharray": "6 5" }));
    g.appendChild(txt({ x: x0 + 8, y: Y(theta) - 8, fill: cAmberB, "font-size": 9.5,
      "font-family": MONO, "letter-spacing": ".6" }, "OWN BASELINE " + f2(theta)));

    (o.paths || []).forEach((p) => {
      let d = "M " + X(n - 1) + " " + Y(obs[n - 1]);
      for (let j = 0; j < Math.min(p.length, nS); j++) d += " L " + X(n + j) + " " + Y(p[j]);
      g.appendChild(s("path", { d: d, fill: "none", stroke: css("--indigo-b"),
        "stroke-width": .9, "stroke-opacity": .2, "stroke-linejoin": "round" }));
    });

    br.forEach((b) => {
      const fill = hatch(defs, uid("bh"), b.color, b.active ? .1 : .035);
      // Upper boundary forward, lower boundary BACKWARD - see stateRibbon.
      let up = "M " + X(n - 1) + " " + Y(obs[n - 1]), dn = "";
      for (let j = 0; j < nS; j++) up += " L " + X(n + j) + " " + Y(b.hi[j]);
      for (let j = nS - 1; j >= 0; j--) dn += " L " + X(n + j) + " " + Y(b.lo[j]);
      dn += " L " + X(n - 1) + " " + Y(obs[n - 1]);
      g.appendChild(s("path", { d: up + dn + " Z", fill: fill, stroke: b.color,
        "stroke-width": 1, "stroke-opacity": b.active ? .55 : .18, "stroke-dasharray": "4 4" }));
      let mp = "M " + X(n - 1) + " " + Y(obs[n - 1]);
      for (let j = 0; j < nS; j++) mp += " L " + X(n + j) + " " + Y(b.med[j]);
      g.appendChild(s("path", { d: mp, fill: "none", stroke: b.color,
        "stroke-width": b.active ? 2.4 : 1.4, "stroke-opacity": b.active ? 1 : .4,
        "stroke-dasharray": "7 5", "stroke-linecap": "round" }));
      const ey = Y(b.med[nS - 1]);
      g.appendChild(s("circle", { cx: X(total - 1), cy: ey, r: 3.4, fill: b.color,
        "fill-opacity": b.active ? 1 : .4 }));
      g.appendChild(txt({ x: X(total - 1) + 10, y: ey + 3.5, fill: b.color,
        "font-size": 10.5, "font-family": MONO, opacity: b.active ? 1 : .5 },
        f2(b.med[nS - 1])));
    });

    let p = "";
    for (let i = 0; i < n; i++) p += (i ? " L " : "M ") + X(i) + " " + Y(obs[i]);
    g.appendChild(s("path", { d: p, fill: "none", stroke: cInk, "stroke-width": 2.1,
      "stroke-linejoin": "round", "stroke-linecap": "round" }));
    g.appendChild(s("circle", { cx: X(n - 1), cy: Y(obs[n - 1]), r: 4.2, fill: css("--bg"),
      stroke: cInk, "stroke-width": 2.2 }));

    const fticks = [];
    for (let i = 0; i < total; i += 4) fticks.push(i);
    if (fticks[fticks.length - 1] !== total - 1) fticks.push(total - 1);
    fticks.forEach((i) => {
      g.appendChild(txt({ x: X(i), y: y1 + 19, fill: i >= n ? cIndigo : cInk4, "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" }, "w" + i));
    });
    return g;
  }

  /* ============================================================
     4 - ATTRIBUTION
     The residual is a bar like any other. Normalising it away is
     the commonest dishonesty in "explainable" dashboards.
     ============================================================ */
  function attribBars(rec, opts) {
    const o = opts || {};
    const wrap = document.createElement("div");
    wrap.className = "att";
    if (!rec) {
      wrap.innerHTML = '<p class="muted" style="font-size:.85rem;margin:0">' +
        "No decomposition for this week.</p>";
      return wrap;
    }
    const rows = Object.entries(rec.ch)
      .map(([k, v]) => [k.replace(/_/g, " "), v, false])
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    rows.push(["not attributable", rec.unexp, true]);
    const max = Math.max.apply(null, rows.map((r) => Math.abs(r[1])).concat([1e-6]));

    rows.forEach(function (row) {
      const name = row[0], v = row[1], resid = row[2];
      const d = document.createElement("div");
      d.className = "att-r" + (resid ? " resid" : "");
      const w = (Math.abs(v) / max) * 50;
      d.innerHTML =
        '<span class="att-n">' + name + "</span>" +
        '<span class="att-t">' +
          '<i class="att-b ' + (v < 0 ? "neg" : "pos") + '" style="' +
          (v < 0 ? "right:50%;" : "left:50%;") + "width:" + w.toFixed(2) + '%"></i>' +
          '<i class="att-z"></i>' +
        "</span>" +
        '<span class="att-v num">' + (v >= 0 ? "+" : "") + f2(v, 3) + "</span>";
      wrap.appendChild(d);
    });
    if (o.total !== false) {
      const t = document.createElement("div");
      t.className = "att-sum";
      t.innerHTML = "<span>Net shift in state, week " + rec.t + "</span>" +
        '<span class="num">' + (rec.shift >= 0 ? "+" : "") + f2(rec.shift, 3) + "</span>";
      wrap.appendChild(t);
    }
    return wrap;
  }

  /* ============================================================
     5 - PERSONAL DISTRIBUTION  (Deep Dive)
     What "normal" means for THIS student: their own histogram,
     their fitted set point, and where they stand now.
     ============================================================ */
  function distribution(o) {
    const vals = o.values, theta = o.theta, now = o.now;
    const W = 640, H = o.h || 250, L = 12, R = 12, T = 30, B = 36;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const lo = Math.min.apply(null, vals.concat([theta])) - .3;
    const hi = Math.max.apply(null, vals.concat([theta])) + .3;
    const bins = 14, wBin = (hi - lo) / bins;
    const counts = new Array(bins).fill(0);
    vals.forEach((v) => { counts[clamp(Math.floor((v - lo) / wBin), 0, bins - 1)]++; });
    const maxC = Math.max.apply(null, counts.concat([1]));
    const X = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
    const Yc = (c) => y1 - (c / maxC) * (y1 - y0);

    const cTeal = css("--teal"), cCoral = css("--coral"), cAmber = css("--amber");
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "vz-svg", role: "img",
      "aria-label": "Distribution of this student's own observed weekly states" });

    counts.forEach((c, i) => {
      const bx = X(lo + i * wBin), bw = ((x1 - x0) / bins) - 3;
      const mid = lo + (i + .5) * wBin;
      g.appendChild(s("rect", { x: bx + 1.5, y: Yc(c), width: Math.max(bw, 1),
        height: Math.max(y1 - Yc(c), 0), rx: 2,
        fill: mid >= theta ? cTeal : cCoral, "fill-opacity": c ? .38 : .07 }));
    });
    g.appendChild(s("line", { x1: x0, x2: x1, y1: y1, y2: y1, stroke: css("--line-2"),
      "stroke-width": 1 }));

    g.appendChild(s("line", { x1: X(theta), x2: X(theta), y1: y0 - 10, y2: y1, stroke: cAmber,
      "stroke-width": 1.6, "stroke-dasharray": "5 4" }));
    g.appendChild(txt({ x: X(theta), y: y0 - 15, fill: css("--amber-b"), "font-size": 10.5,
      "font-family": MONO, "text-anchor": "middle" }, "θ " + f2(theta)));

    if (now !== undefined && now !== null) {
      const up = now >= theta;
      const col = up ? css("--teal-b") : css("--coral-b");
      g.appendChild(s("line", { x1: X(now), x2: X(now), y1: y0, y2: y1,
        stroke: col, "stroke-width": 2 }));
      g.appendChild(s("circle", { cx: X(now), cy: y0 + 2, r: 3.6, fill: col }));
      g.appendChild(txt({ x: X(now), y: y1 + 22, fill: col, "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" }, "now " + f2(now)));
    }
    [lo + wBin, hi - wBin].forEach((v) => {
      g.appendChild(txt({ x: X(v), y: y1 + 22, fill: css("--ink-4"), "font-size": 10,
        "font-family": MONO, "text-anchor": "middle" }, f2(v, 1)));
    });
    return g;
  }

  /* ============================================================
     6 - OBSERVATION RAIL  (Timeline)
     The actual tier-1 features fed to the twin, week by week.
     Without them the rail would have to invent activity the
     model never saw.
     ============================================================ */
  function obsRail(o) {
    const rows = o.rows, cols = o.cols, sel = o.selected;
    const W = 1120, L = 176, R = 20, T = 26;
    const rowH = 24;
    const H = T + cols.length * rowH + 8;
    const n = rows.length;
    const cellW = (W - L - R) / n;
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "vz-svg", role: "img",
      "aria-label": "Weekly tier-1 features supplied to the twin" });

    cols.forEach((c, ci) => {
      const y = T + ci * rowH;
      g.appendChild(txt({ x: L - 14, y: y + 12.5, fill: css("--ink-3"), "font-size": 10.5,
        "font-family": MONO, "text-anchor": "end" }, c.replace(/_/g, " ")));
      const vs = rows.map((r) => r.v[ci]);
      const mx = Math.max.apply(null, vs.map(Math.abs).concat([1e-9]));
      rows.forEach((r, i) => {
        const v = r.v[ci], a = Math.abs(v) / mx;
        g.appendChild(s("rect", {
          x: L + i * cellW + 1, y: y + 2, width: Math.max(cellW - 2, 1), height: rowH - 6, rx: 2,
          fill: v >= 0 ? css("--teal") : css("--coral"),
          "fill-opacity": (.06 + a * .6).toFixed(3)
        }));
      });
    });
    for (let i = 0; i < n; i += 4) {
      g.appendChild(txt({ x: L + i * cellW + cellW / 2, y: 15, fill: css("--ink-4"),
        "font-size": 9.5, "font-family": MONO, "text-anchor": "middle" }, "w" + rows[i].t));
    }
    if (sel !== null && sel !== undefined) {
      g.appendChild(s("rect", { x: L + sel * cellW, y: T - 5, width: cellW,
        height: cols.length * rowH + 6, fill: "none", stroke: css("--teal-b"),
        "stroke-width": 1.4, rx: 2 }));
    }
    g.pick = function (clientX) {
      const r = g.getBoundingClientRect();
      const sx = ((clientX - r.left) / r.width) * W;
      return clamp(Math.floor((sx - L) / cellW), 0, n - 1);
    };
    return g;
  }

  /* ============================================================
     7 - SMALL PARTS
     ============================================================ */
  function spark(vals, color, opts) {
    const o = opts || {};
    const W = o.w || 92, H = o.h || 26, P = 3;
    const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    const span = (hi - lo) || 1;
    const X = (i) => P + (i / Math.max(vals.length - 1, 1)) * (W - 2 * P);
    const Y = (v) => H - P - ((v - lo) / span) * (H - 2 * P);
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "spark", "aria-hidden": "true" });
    let d = "", a = "M " + X(0) + " " + (H - P);
    vals.forEach((v, i) => {
      d += (i ? " L " : "M ") + X(i) + " " + Y(v);
      a += " L " + X(i) + " " + Y(v);
    });
    a += " L " + X(vals.length - 1) + " " + (H - P) + " Z";
    g.appendChild(s("path", { d: a, fill: color, "fill-opacity": .12 }));
    g.appendChild(s("path", { d: d, fill: "none", stroke: color, "stroke-width": 1.4,
      "stroke-linejoin": "round", "stroke-linecap": "round" }));
    g.appendChild(s("circle", { cx: X(vals.length - 1), cy: Y(vals[vals.length - 1]),
      r: 1.9, fill: color }));
    return g;
  }

  function coverageRing(pcts) {
    const W = 190, CX = 95, CY = 95;
    const g = s("svg", { viewBox: "0 0 " + W + " " + W, class: "cring", "aria-hidden": "true" });
    const R = [78, 64, 50];
    pcts.forEach((p, i) => {
      const c = 2 * Math.PI * R[i];
      g.appendChild(s("circle", { cx: CX, cy: CY, r: R[i], fill: "none",
        stroke: css("--line"), "stroke-width": 7 }));
      g.appendChild(s("circle", { cx: CX, cy: CY, r: R[i], fill: "none", stroke: p.color,
        "stroke-width": 7, "stroke-linecap": "round", class: "cring-arc",
        "stroke-dasharray": (c * p.v / 100).toFixed(1) + " " + c.toFixed(1),
        transform: "rotate(-90 " + CX + " " + CY + ")" }));
    });
    return g;
  }

  /* Cumulative simulated risk across the horizon. It only ever rises,
     which is what "cumulative" means and why it must be labelled as such. */
  function riskCurve(o) {
    const W = 560, H = o.h || 180, L = 46, R = 18, T = 20, B = 32;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const series = o.series;
    const hiV = Math.max.apply(null,
      series.map((sr) => Math.max.apply(null, sr.v))) * 1.15 || .1;
    const n = series[0].v.length;
    const X = (i) => x0 + (i / Math.max(n - 1, 1)) * (x1 - x0);
    const Y = (v) => y1 - (v / hiV) * (y1 - y0);
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "vz-svg", role: "img",
      "aria-label": "Cumulative simulated risk over the eight week horizon" });
    for (let k = 0; k <= 3; k++) {
      const v = (hiV / 3) * k;
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: css("--line"),
        "stroke-width": 1 }));
      g.appendChild(txt({ x: x0 - 8, y: Y(v) + 3.5, fill: css("--ink-4"), "font-size": 9.5,
        "font-family": MONO, "text-anchor": "end" }, (v * 100).toFixed(0) + "%"));
    }
    series.forEach((sr) => {
      let d = "";
      sr.v.forEach((v, i) => { d += (i ? " L " : "M ") + X(i) + " " + Y(v); });
      g.appendChild(s("path", { d: d, fill: "none", stroke: sr.color,
        "stroke-width": sr.active ? 2.2 : 1.3, "stroke-dasharray": "6 4",
        "stroke-opacity": sr.active ? 1 : .38, "stroke-linecap": "round" }));
      g.appendChild(s("circle", { cx: X(n - 1), cy: Y(sr.v[n - 1]), r: 3.2, fill: sr.color,
        "fill-opacity": sr.active ? 1 : .38 }));
    });
    for (let i = 0; i < n; i += 2) {
      g.appendChild(txt({ x: X(i), y: y1 + 18, fill: css("--ink-4"), "font-size": 9.5,
        "font-family": MONO, "text-anchor": "middle" }, "+" + (i + 1)));
    }
    return g;
  }

  window.ST_Charts = {
    stateRibbon: stateRibbon,
    twinField: twinField,
    fanChart: fanChart,
    attribBars: attribBars,
    distribution: distribution,
    obsRail: obsRail,
    riskCurve: riskCurve,
    spark: spark,
    coverageRing: coverageRing,
  };
})();
