/* ============================================================
   StudyTwin chart language
   ------------------------------------------------------------
   Bespoke SVG. The rules, in order of importance:

   1. ONE bold stroke carries the data. Everything else recedes.
   2. Almost no chart junk: three faint horizontal guides, no
      vertical grid, small quiet axis labels.
   3. The present moment is a real object - a filled node with a
      ring around it - not just where the line stops.
   4. Uncertainty is a gradient band, not a grey polygon.
   5. Hover produces a dark tooltip pill on a vertical guide,
      never a browser title attribute.

   Colour is semantic and fixed:
     near-black  observed history
     amber       the student's own baseline
     teal        current state, above baseline
     coral       below baseline
     indigo      simulated futures
   ============================================================ */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const MONO = "Cascadia Mono, Consolas, ui-monospace, monospace";
  const s = (t, a) => { const n = document.createElementNS(NS, t);
    for (const k in (a || {})) n.setAttribute(k, a[k]); return n; };
  const el = (t, a, kids) => { const n = document.createElement(t);
    for (const k in (a || {})) {
      if (k === "class") n.className = a[k];
      else if (k === "html") n.innerHTML = a[k];
      else if (k === "text") n.textContent = a[k];
      else n.setAttribute(k, a[k]);
    }
    (kids || []).forEach((c) => n.appendChild(c)); return n; };
  const cssv = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v, d) => (v === null || v === undefined || Number.isNaN(v))
    ? "—" : v.toFixed(d === undefined ? 2 : d);

  let uid = 0;
  const nextId = () => "st-" + (++uid);

  /* ============================================================
     twinChart — the primary visualisation.
     Observed history, the personal baseline, the current state,
     and optionally the simulated futures, in one frame.
     ============================================================ */
  function twinChart(opts) {
    const mean = opts.mean, sd = opts.sd, theta = opts.theta;
    const sim = opts.sim || null;                 // {weeks, lo, med, hi} or null
    const W = 1000, H = opts.h || 400;
    const L = 54, R = 30, T = 34, B = 44;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;

    const nObs = mean.length;
    const nFut = sim ? sim.med.length : 0;
    const total = nObs + nFut;

    const lows = mean.map((m, i) => m - 1.96 * sd[i]);
    const highs = mean.map((m, i) => m + 1.96 * sd[i]);
    let lo = Math.min(theta, ...lows, ...(sim ? sim.lo : [])) - .3;
    let hi = Math.max(theta, ...highs, ...(sim ? sim.hi : [])) + .3;

    const X = (i) => x0 + (i / Math.max(total - 1, 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const INK = cssv("--ink") || "#0D1418";
    const TEAL = cssv("--teal") || "#07786B";
    const TEAL2 = cssv("--teal-2") || "#0A9C8A";
    const CORAL = cssv("--coral") || "#C9524C";
    const AMBER = cssv("--amber") || "#C8830E";
    const INDIGO = cssv("--indigo") || "#4A42D4";
    const LINE = cssv("--line") || "#D6D1C4";
    const MUT = cssv("--ink-3") || "#63727A";
    const SURF = cssv("--surface") || "#fff";

    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "tc2", role: "img",
      "aria-label": opts.label || "Twin state over time" });

    /* gradients: uncertainty reads as a field, not a polygon */
    const defs = s("defs");
    const gid = nextId(), gid2 = nextId();
    const lg = s("linearGradient", { id: gid, x1: "0", y1: "0", x2: "0", y2: "1" });
    lg.appendChild(s("stop", { offset: "0%", "stop-color": TEAL2, "stop-opacity": ".22" }));
    lg.appendChild(s("stop", { offset: "50%", "stop-color": TEAL2, "stop-opacity": ".10" }));
    lg.appendChild(s("stop", { offset: "100%", "stop-color": TEAL2, "stop-opacity": ".22" }));
    defs.appendChild(lg);
    const lg2 = s("linearGradient", { id: gid2, x1: "0", y1: "0", x2: "1", y2: "0" });
    lg2.appendChild(s("stop", { offset: "0%", "stop-color": INDIGO, "stop-opacity": ".34" }));
    lg2.appendChild(s("stop", { offset: "100%", "stop-color": INDIGO, "stop-opacity": ".12" }));
    defs.appendChild(lg2);
    g.appendChild(defs);

    /* three faint guides. No vertical grid - it adds nothing here. */
    const step = (hi - lo) > 3.5 ? 1 : .5;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v),
        stroke: LINE, "stroke-width": 1, "stroke-opacity": .55 }));
      const t = s("text", { x: x0 - 12, y: Y(v) + 4, fill: MUT, "font-size": 11,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = v.toFixed(step < 1 ? 1 : 0);
      g.appendChild(t);
    }

    /* simulated region gets its own ground so it can never read as observed */
    if (sim) {
      g.appendChild(s("rect", { x: X(nObs - 1), y: y0, width: x1 - X(nObs - 1),
        height: y1 - y0, fill: INDIGO, "fill-opacity": .05 }));
    }

    /* uncertainty band on the observed history */
    let band = "";
    highs.forEach((v, i) => { band += (i ? " L " : "M ") + X(i) + " " + Y(v); });
    for (let i = nObs - 1; i >= 0; i--) band += " L " + X(i) + " " + Y(lows[i]);
    band += " Z";
    g.appendChild(s("path", { d: band, fill: `url(#${gid})` }));

    /* deviation fill: the area between the line and the student's own normal */
    let dev = `M ${X(0)} ${Y(theta)}`;
    mean.forEach((m, i) => { dev += ` L ${X(i)} ${Y(m)}`; });
    dev += ` L ${X(nObs - 1)} ${Y(theta)} Z`;
    const below = mean[nObs - 1] < theta;
    g.appendChild(s("path", { d: dev, fill: below ? CORAL : TEAL,
      "fill-opacity": .07 }));

    /* the personal baseline: amber, dashed, labelled at the left */
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(theta), y2: Y(theta),
      stroke: AMBER, "stroke-width": 1.8, "stroke-dasharray": "7 6" }));
    const bl = s("text", { x: x0 + 4, y: Y(theta) - 10, fill: AMBER, "font-size": 10.5,
      "font-family": MONO, "letter-spacing": ".12em" });
    bl.textContent = "PERSONAL BASELINE  " + fmt(theta);
    g.appendChild(bl);

    /* simulated futures */
    if (sim) {
      let fb = `M ${X(nObs - 1)} ${Y(mean[nObs - 1])}`;
      sim.hi.forEach((v, i) => { fb += ` L ${X(nObs + i)} ${Y(v)}`; });
      for (let i = sim.lo.length - 1; i >= 0; i--) fb += ` L ${X(nObs + i)} ${Y(sim.lo[i])}`;
      fb += " Z";
      g.appendChild(s("path", { d: fb, fill: `url(#${gid2})` }));

      let fm = `M ${X(nObs - 1)} ${Y(mean[nObs - 1])}`;
      sim.med.forEach((v, i) => { fm += ` L ${X(nObs + i)} ${Y(v)}`; });
      g.appendChild(s("path", { d: fm, fill: "none", stroke: INDIGO, "stroke-width": 2.4,
        "stroke-dasharray": "8 5", "stroke-linecap": "round", "stroke-linejoin": "round" }));

      g.appendChild(s("line", { x1: X(nObs - 1), x2: X(nObs - 1), y1: y0, y2: y1,
        stroke: MUT, "stroke-width": 1, "stroke-dasharray": "3 4", "stroke-opacity": .6 }));
      const nl = s("text", { x: X(nObs - 1) + 8, y: y0 + 12, fill: INDIGO, "font-size": 10,
        "font-family": MONO, "letter-spacing": ".14em" });
      nl.textContent = "SIMULATED";
      g.appendChild(nl);
    }

    /* ONE bold stroke. This is the data. */
    let p = "";
    mean.forEach((m, i) => { p += (i ? " L " : "M ") + X(i) + " " + Y(m); });
    g.appendChild(s("path", { d: p, fill: "none", stroke: INK, "stroke-width": 2.6,
      "stroke-linejoin": "round", "stroke-linecap": "round" }));

    /* the present moment, as an object */
    const cx = X(nObs - 1), cy = Y(mean[nObs - 1]);
    const stateCol = below ? CORAL : TEAL;
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 15, fill: stateCol, "fill-opacity": .14 }));
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 8.5, fill: SURF }));
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 6, fill: stateCol }));

    /* quiet axis */
    const ticks = [];
    for (let i = 0; i < total; i += Math.max(1, Math.round(total / 7))) ticks.push(i);
    if (ticks[ticks.length - 1] !== total - 1) ticks.push(total - 1);
    ticks.forEach((i) => {
      const t = s("text", { x: X(i), y: y1 + 22, fill: MUT, "font-size": 11,
        "font-family": MONO, "text-anchor": "middle" });
      t.textContent = "w" + i;
      g.appendChild(t);
    });

    /* ---- hover: guide + dark tooltip pill ---- */
    const guide = s("line", { y1: y0, y2: y1, stroke: INK, "stroke-width": 1,
      "stroke-dasharray": "3 3", opacity: 0 });
    const hoverDot = s("circle", { r: 5, fill: INK, opacity: 0 });
    g.appendChild(guide); g.appendChild(hoverDot);

    const tipG = s("g", { opacity: 0, class: "tc2-tip" });
    const tipBg = s("rect", { rx: 8, fill: INK, width: 168, height: 86 });
    tipG.appendChild(tipBg);
    const lines = [];
    for (let i = 0; i < 4; i++) {
      const t = s("text", { "font-size": 11, "font-family": MONO, fill: "#fff" });
      tipG.appendChild(t); lines.push(t);
    }
    g.appendChild(tipG);

    const hit = s("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, fill: "transparent" });
    g.appendChild(hit);

    function showAt(i) {
      if (i < 0 || i >= nObs) return;
      const px = X(i), py = Y(mean[i]);
      guide.setAttribute("x1", px); guide.setAttribute("x2", px);
      guide.setAttribute("opacity", .35);
      hoverDot.setAttribute("cx", px); hoverDot.setAttribute("cy", py);
      hoverDot.setAttribute("opacity", 1);
      const d0 = mean[i] - theta;
      const rows = [
        "WEEK " + i,
        "state      " + fmt(mean[i]),
        "baseline   " + fmt(theta),
        "deviation  " + (d0 >= 0 ? "+" : "") + fmt(d0) + "   ±" + fmt(1.96 * sd[i]),
      ];
      const tw = 176;
      let tx = px + 16;
      if (tx + tw > x1) tx = px - tw - 16;
      const ty = Math.max(y0 + 4, Math.min(py - 46, y1 - 92));
      tipBg.setAttribute("x", tx); tipBg.setAttribute("y", ty);
      tipBg.setAttribute("width", tw);
      rows.forEach((r, k) => {
        lines[k].setAttribute("x", tx + 12);
        lines[k].setAttribute("y", ty + 22 + k * 18);
        lines[k].textContent = r;
        lines[k].setAttribute("fill", k === 0 ? "#8FA3A8" : "#fff");
        lines[k].setAttribute("letter-spacing", k === 0 ? ".14em" : "0");
      });
      tipG.setAttribute("opacity", 1);
      if (opts.onHover) opts.onHover(i);
    }
    function hide() {
      guide.setAttribute("opacity", 0);
      hoverDot.setAttribute("opacity", 0);
      tipG.setAttribute("opacity", 0);
      if (opts.onHover) opts.onHover(null);
    }
    hit.addEventListener("pointermove", (e) => {
      const r = g.getBoundingClientRect();
      const vx = ((e.clientX - r.left) / r.width) * W;
      showAt(Math.round(((vx - x0) / (x1 - x0)) * (total - 1)));
    });
    hit.addEventListener("pointerleave", hide);
    return g;
  }

  /* ============================================================
     coverageRing — Ref-2's radial tick scale, doing real work.
     Ticks are weeks observed; the arc is coverage.
     ============================================================ */
  function coverageRing(opts) {
    const pctv = Math.max(0, Math.min(100, opts.pct || 0));
    const W = 260, H = 260, C = 130, R = 96;
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "cring", role: "img",
      "aria-label": (opts.label || "Coverage") + " " + pctv + " percent" });
    const TEAL = opts.onDeep ? "#22D3B8" : (cssv("--teal") || "#07786B");
    const MUT = opts.onDeep ? "rgba(232,237,236,.22)" : (cssv("--line") || "#D6D1C4");
    const INK = opts.onDeep ? "#E8EDEC" : (cssv("--ink") || "#0D1418");
    const SUB = opts.onDeep ? "#9DB0B4" : (cssv("--ink-3") || "#63727A");

    /* tick scale: one tick per unit, lit up to the value */
    const N = 60;
    for (let i = 0; i < N; i++) {
      const a = (-90 + (i / N) * 360) * Math.PI / 180;
      const on = (i / N) * 100 <= pctv;
      const r1 = R + 10, r2 = R + (on ? 22 : 16);
      g.appendChild(s("line", {
        x1: C + Math.cos(a) * r1, y1: C + Math.sin(a) * r1,
        x2: C + Math.cos(a) * r2, y2: C + Math.sin(a) * r2,
        stroke: on ? TEAL : MUT, "stroke-width": on ? 2 : 1,
        "stroke-opacity": on ? .85 : .5, "stroke-linecap": "round",
      }));
    }
    const circ = 2 * Math.PI * R;
    g.appendChild(s("circle", { cx: C, cy: C, r: R, fill: "none", stroke: MUT,
      "stroke-width": 2, "stroke-opacity": .5 }));
    g.appendChild(s("circle", { cx: C, cy: C, r: R, fill: "none", stroke: TEAL,
      "stroke-width": 3, "stroke-linecap": "round",
      "stroke-dasharray": `${circ * pctv / 100} ${circ}`,
      transform: `rotate(-90 ${C} ${C})`, class: "cring-arc" }));

    const big = s("text", { x: C, y: C + 6, "text-anchor": "middle", fill: INK,
      "font-size": 52, "font-family": MONO, "letter-spacing": "-.03em" });
    big.textContent = pctv;
    g.appendChild(big);
    const pc = s("text", { x: C + 44, y: C + 6, "text-anchor": "start", fill: SUB,
      "font-size": 18, "font-family": MONO });
    pc.textContent = "%";
    g.appendChild(pc);
    const lab = s("text", { x: C, y: C + 30, "text-anchor": "middle", fill: SUB,
      "font-size": 10, "font-family": MONO, "letter-spacing": ".16em" });
    lab.textContent = (opts.label || "COVERAGE").toUpperCase();
    g.appendChild(lab);
    return g;
  }

  /* ============================================================
     branchChart — Future Lab. Scenarios as visibly separate
     branches from one shared present.
     ============================================================ */
  function branchChart(opts) {
    const obs = opts.obs, theta = opts.theta, branches = opts.branches;
    const W = 1000, H = 380, L = 54, R = 190, T = 30, B = 40;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const nObs = obs.length, nFut = branches[0].med.length, total = nObs + nFut;
    const all = obs.concat(...branches.map((b) => b.lo.concat(b.hi)));
    const lo = Math.min(theta, ...all) - .3, hi = Math.max(theta, ...all) + .3;
    const X = (i) => x0 + (i / (total - 1)) * (x1 - x0);
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const INK = cssv("--ink"), AMBER = cssv("--amber"), MUT = cssv("--ink-3"),
          LINE = cssv("--line"), SURF = cssv("--surface");
    const g = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "tc2", role: "img",
      "aria-label": opts.label || "Scenario branches" });

    for (let v = Math.ceil(lo); v <= hi; v++) {
      g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), stroke: LINE,
        "stroke-opacity": .55 }));
      const t = s("text", { x: x0 - 12, y: Y(v) + 4, fill: MUT, "font-size": 11,
        "font-family": MONO, "text-anchor": "end" });
      t.textContent = v; g.appendChild(t);
    }
    g.appendChild(s("line", { x1: x0, x2: x1, y1: Y(theta), y2: Y(theta), stroke: AMBER,
      "stroke-width": 1.8, "stroke-dasharray": "7 6" }));

    branches.forEach((b) => {
      let band = `M ${X(nObs - 1)} ${Y(obs[nObs - 1])}`;
      b.hi.forEach((v, i) => { band += ` L ${X(nObs + i)} ${Y(v)}`; });
      for (let i = b.lo.length - 1; i >= 0; i--) band += ` L ${X(nObs + i)} ${Y(b.lo[i])}`;
      band += " Z";
      g.appendChild(s("path", { d: band, fill: b.color,
        "fill-opacity": b.active ? .16 : .05, class: "br-band" }));
    });

    let p = "";
    obs.forEach((v, i) => { p += (i ? " L " : "M ") + X(i) + " " + Y(v); });
    g.appendChild(s("path", { d: p, fill: "none", stroke: INK, "stroke-width": 2.6,
      "stroke-linejoin": "round" }));

    branches.forEach((b) => {
      let m = `M ${X(nObs - 1)} ${Y(obs[nObs - 1])}`;
      b.med.forEach((v, i) => { m += ` L ${X(nObs + i)} ${Y(v)}`; });
      g.appendChild(s("path", { d: m, fill: "none", stroke: b.color,
        "stroke-width": b.active ? 3 : 1.8, "stroke-dasharray": "8 5",
        "stroke-opacity": b.active ? 1 : .4, "stroke-linecap": "round",
        "stroke-linejoin": "round", class: "br-line" }));
      const ey = Y(b.med[b.med.length - 1]);
      g.appendChild(s("circle", { cx: X(total - 1), cy: ey, r: b.active ? 6 : 4,
        fill: b.color, "fill-opacity": b.active ? 1 : .45 }));
      const t = s("text", { x: X(total - 1) + 14, y: ey + 4, fill: b.color,
        "font-size": 12, "font-family": MONO, "fill-opacity": b.active ? 1 : .5 });
      t.textContent = b.name;
      g.appendChild(t);
    });

    g.appendChild(s("line", { x1: X(nObs - 1), x2: X(nObs - 1), y1: y0, y2: y1,
      stroke: MUT, "stroke-width": 1, "stroke-dasharray": "3 4", "stroke-opacity": .6 }));
    const cx = X(nObs - 1), cy = Y(obs[nObs - 1]);
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 13, fill: INK, "fill-opacity": .1 }));
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 7.5, fill: SURF }));
    g.appendChild(s("circle", { cx: cx, cy: cy, r: 5, fill: INK }));
    const nl = s("text", { x: cx, y: y1 + 22, fill: MUT, "font-size": 10,
      "font-family": MONO, "text-anchor": "middle", "letter-spacing": ".12em" });
    nl.textContent = "NOW";
    g.appendChild(nl);
    return g;
  }

  /* ---- small sparkline for metric chips ---- */
  function spark(vals, color, w, h) {
    w = w || 92; h = h || 28;
    const lo = Math.min(...vals), hi = Math.max(...vals), r = (hi - lo) || 1;
    const g = s("svg", { viewBox: `0 0 ${w} ${h}`, class: "spark", "aria-hidden": "true" });
    let p = "";
    vals.forEach((v, i) => {
      p += (i ? " L " : "M ") + (i / (vals.length - 1)) * w + " " +
        (h - ((v - lo) / r) * (h - 6) - 3);
    });
    g.appendChild(s("path", { d: p, fill: "none", stroke: color, "stroke-width": 1.8,
      "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const lx = w, ly = h - ((vals[vals.length - 1] - lo) / r) * (h - 6) - 3;
    g.appendChild(s("circle", { cx: lx - 2, cy: ly, r: 2.6, fill: color }));
    return g;
  }

  window.ST_Charts = {
    twinChart: twinChart, coverageRing: coverageRing,
    branchChart: branchChart, spark: spark, el: el, s: s,
  };
})();
