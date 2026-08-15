/* ============================================================
   StudyTwin  ·  the two narrative instruments

   Both live here rather than in charts.js because they are not
   charts: they are diagrams of the model's own weekly procedure,
   and they are the only two graphics on the site whose subject is
   the algorithm rather than the student.

   Every quantity drawn is stored model output for one real week:

     prev    last week's posterior           (twin_states)
     prior   the PREDICT step, mean and SD   (attribution_steps)
     obs     the canonical channels observed (observations)
     post    the UPDATE step, mean and SD    (attribution_steps)

   Nothing is recomputed. The widening at PREDICT and the narrowing
   at UPDATE are the filter's own arithmetic, fetched over the API -
   re-deriving P_pred = F P F' + Q in the browser to illustrate
   P_pred = F P F' + Q would be the exact duplication this
   architecture exists to prevent.
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

  /** A Gaussian drawn sideways: value runs along Y, density along X.
      `dir` +1 opens rightward, -1 leftward. */
  function bell(x0, Y, mu, sd, amp, dir) {
    const d = dir === undefined ? 1 : dir;
    const sig = sd || 1e-6;
    let path = "";
    const lo = mu - 2.4 * sig, hi = mu + 2.4 * sig;
    for (let i = 0; i <= 48; i++) {
      const v = lo + (i / 48) * (hi - lo);
      const dens = Math.exp(-0.5 * Math.pow((v - mu) / sig, 2));
      path += (i ? " L " : "M ") + (x0 + d * amp * dens).toFixed(2) + " " +
        Y(v).toFixed(2);
    }
    return path;
  }

  /* ============================================================
     THE MODEL LOOP  -  landing section "Four moves"

     One diagram, four stages. Selecting a stage changes what this
     picture emphasises rather than swapping four cards, because the
     claim being made is that these are four moves of ONE object.
     ============================================================ */
  function modelLoop(o) {
    const W = 1180, H = 400, T = 46, B = 58;
    const y0 = T, y1 = H - B;
    const stations = [180, 452, 724, 996];
    const theta = o.theta;

    const sds = [o.prev.sd, o.prior.sd, o.post.sd].filter((x) => x > 0);
    const maxSd = Math.max.apply(null, sds.concat([0.05]));
    const vals = [o.prev.mean, o.prior.mean, o.post.mean, theta];
    const lo = Math.min.apply(null, vals) - 3.1 * maxSd;
    const hi = Math.max.apply(null, vals) + 3.1 * maxSd;
    const Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const cInk = css("--ink"), cInk3 = css("--ink-3"), cInk4 = css("--ink-4");
    const cLine = css("--line"), cLine3 = css("--line-3");
    const cTeal = css("--teal"), cTealB = css("--teal-b");
    const cAmber = css("--amber"), cAmberB = css("--amber-b");
    const cCoralB = css("--coral-b");

    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "loop-svg", role: "img",
      "aria-label": o.label ||
        ("Week " + o.week + " of one student: the observation, the prediction, "
         + "the update, and the resulting state") });

    for (let k = 0; k <= 4; k++) {
      const yy = y0 + (k / 4) * (y1 - y0);
      g.appendChild(s("line", { x1: 40, x2: W - 30, y1: yy, y2: yy,
        stroke: cLine, "stroke-width": 1, "stroke-opacity": .55 }));
    }

    /* theta: the reference every stage is measured against */
    const gTheta = s("g", {});
    gTheta.appendChild(s("line", { x1: 40, x2: W - 30, y1: Y(theta), y2: Y(theta),
      stroke: cAmber, "stroke-width": 1.5, "stroke-dasharray": "6 5" }));
    gTheta.appendChild(txt({ x: W - 34, y: Y(theta) - 8, fill: cAmberB, "font-size": 10,
      "font-family": MONO, "letter-spacing": ".6", "text-anchor": "end" },
      "θ " + f2(theta) + "  OWN BASELINE"));
    g.appendChild(gTheta);
    gTheta.style.opacity = o.stage === 1 ? 1 : 0.55;

    /* the belief thread linking the stations */
    const thread = "M " + stations[0] + " " + Y(o.prev.mean) +
      " C " + (stations[0] + 130) + " " + Y(o.prev.mean) + ", " +
      (stations[1] - 130) + " " + Y(o.prior.mean) + ", " +
      stations[1] + " " + Y(o.prior.mean) +
      " L " + stations[2] + " " + Y(o.prior.mean) +
      " C " + (stations[2] + 130) + " " + Y(o.prior.mean) + ", " +
      (stations[3] - 130) + " " + Y(o.post.mean) + ", " +
      stations[3] + " " + Y(o.post.mean);
    g.appendChild(s("path", { d: thread, fill: "none", stroke: cLine3,
      "stroke-width": 1.4, "stroke-dasharray": "5 5" }));

    /* ---- 01 OBSERVE ------------------------------------------- */
    const g1 = s("g", { "data-stage": "0" });
    g1.appendChild(s("rect", { x: 38, y: y0 - 2, width: 224, height: 136, rx: 6,
      fill: css("--bg"), stroke: cLine, "stroke-width": 1 }));
    g1.appendChild(txt({ x: 48, y: y0 + 12, fill: cInk4, "font-size": 9,
      "font-family": MONO, "letter-spacing": "1.4" }, "WEEK EVIDENCE"));
    const chans = Object.keys(o.obs || {})
      .filter((k) => o.obs[k] !== 0)
      .sort((a, b) => Math.abs(o.obs[b]) - Math.abs(o.obs[a]))
      .slice(0, 6);
    const maxV = Math.max.apply(null, chans.map((k) => Math.abs(o.obs[k])).concat([1]));
    chans.forEach((k, i) => {
      const yy = y0 + 22 + i * 18;
      const w = 6 + (Math.abs(o.obs[k]) / maxV) * 54;
      g1.appendChild(s("rect", { x: 48, y: yy, width: w, height: 9, rx: 2,
        fill: cTeal, "fill-opacity": .55 }));
      g1.appendChild(txt({ x: 48 + w + 7, y: yy + 8, fill: cInk3, "font-size": 9,
        "font-family": MONO }, k.replace(/_/g, " ") + " " + f2(o.obs[k], 0)));
    });
    g.appendChild(g1);

    /* ---- 02 PREDICT ------------------------------------------- */
    const g2 = s("g", { "data-stage": "1" });
    g2.appendChild(s("path", { d: bell(stations[0], Y, o.prev.mean, o.prev.sd, 52, 1),
      fill: cTealB, "fill-opacity": .13, stroke: cTealB, "stroke-width": 1.2 }));
    g2.appendChild(s("circle", { cx: stations[0], cy: Y(o.prev.mean), r: 3.4,
      fill: cTealB }));
    const midY = (Y(o.prev.mean) + Y(o.prior.mean)) / 2;
    g2.appendChild(s("path", {
      d: "M " + (stations[0] + 60) + " " + Y(o.prev.mean) + " Q " +
         ((stations[0] + stations[1]) / 2) + " " + midY + " " +
         (stations[1] - 62) + " " + Y(o.prior.mean),
      fill: "none", stroke: cAmberB, "stroke-width": 1.6, "stroke-dasharray": "4 4" }));
    g2.appendChild(txt({ x: (stations[0] + stations[1]) / 2, y: midY - 12, fill: cAmberB,
      "font-size": 9.5, "font-family": MONO, "text-anchor": "middle",
      "letter-spacing": ".8" }, "DRIFT TOWARD θ"));
    g2.appendChild(s("path", { d: bell(stations[1], Y, o.prior.mean, o.prior.sd, 60, -1),
      fill: cInk3, "fill-opacity": .1, stroke: cInk3, "stroke-width": 1.2,
      "stroke-dasharray": "4 3" }));
    g.appendChild(g2);

    /* ---- 03 UPDATE -------------------------------------------- */
    const g3 = s("g", { "data-stage": "2" });
    g3.appendChild(s("path", { d: bell(stations[2], Y, o.prior.mean, o.prior.sd, 60, -1),
      fill: cInk3, "fill-opacity": .07, stroke: cInk3, "stroke-width": 1,
      "stroke-dasharray": "4 3" }));
    g3.appendChild(s("line", { x1: stations[2] - 76, x2: stations[2] + 76,
      y1: Y(o.post.mean), y2: Y(o.post.mean), stroke: cInk, "stroke-width": 1.6 }));
    g3.appendChild(txt({ x: stations[2] + 82, y: Y(o.post.mean) + 3.5, fill: cInk,
      "font-size": 9.5, "font-family": MONO, "letter-spacing": ".6" }, "EVIDENCE"));
    g3.appendChild(s("path", { d: bell(stations[2], Y, o.post.mean, o.post.sd, 60, 1),
      fill: cTealB, "fill-opacity": .18, stroke: cTealB, "stroke-width": 1.4 }));
    g.appendChild(g3);

    /* ---- 04 STATE --------------------------------------------- */
    const g4 = s("g", { "data-stage": "3" });
    const up = o.post.mean >= theta;
    g4.appendChild(s("path", { d: bell(stations[3], Y, o.post.mean, o.post.sd, 62, -1),
      fill: up ? cTealB : cCoralB, "fill-opacity": .2,
      stroke: up ? cTealB : cCoralB, "stroke-width": 1.5 }));
    g4.appendChild(s("circle", { cx: stations[3], cy: Y(o.post.mean), r: 5,
      fill: css("--bg"), stroke: up ? cTealB : cCoralB, "stroke-width": 2.4 }));
    g4.appendChild(txt({ x: stations[3] + 16, y: Y(o.post.mean) - 5, fill: cInk,
      "font-size": 21, "letter-spacing": "-.6" }, f2(o.post.mean)));
    g4.appendChild(txt({ x: stations[3] + 16, y: Y(o.post.mean) + 12,
      fill: up ? cTealB : cCoralB, "font-size": 9.5, "font-family": MONO },
      (o.post.mean - theta >= 0 ? "+" : "") + f2(o.post.mean - theta) + " vs own"));
    if (o.hazard !== undefined && o.hazard !== null) {
      g4.appendChild(txt({ x: stations[3] + 16, y: Y(o.post.mean) + 28, fill: cInk4,
        "font-size": 9.5, "font-family": MONO },
        "hazard " + (o.hazard * 100).toFixed(2) + "%"));
    }
    g.appendChild(g4);

    /* ---- station labels, and the SD readout that makes the point */
    const NAMES = ["OBSERVE", "PREDICT", "UPDATE", "STATE"];
    const SUB = [
      Object.keys(o.obs || {}).length + " channels",
      "±" + f2(1.96 * o.prior.sd) + " widened",
      "±" + f2(1.96 * o.post.sd) + " narrowed",
      "carried forward",
    ];
    stations.forEach((x, i) => {
      const on = i === o.stage;
      g.appendChild(s("line", { x1: x, x2: x, y1: y1 + 6, y2: y1 + 15,
        stroke: on ? cTealB : cLine3, "stroke-width": on ? 1.8 : 1.2 }));
      g.appendChild(txt({ x: x, y: y1 + 31, fill: on ? cInk : cInk4,
        "font-size": 10.5, "font-family": MONO, "text-anchor": "middle",
        "letter-spacing": "1.4" }, String(i + 1).padStart(2, "0") + "  " + NAMES[i]));
      g.appendChild(txt({ x: x, y: y1 + 45, fill: on ? cTealB : cInk4,
        "font-size": 9.5, "font-family": MONO, "text-anchor": "middle" }, SUB[i]));
    });

    /* Dim what is not being discussed. Never hide it: the argument is that
       these are stages of one object, and hiding three of them denies that. */
    for (let i = 0; i < 4; i++) {
      const node = g.querySelector('[data-stage="' + i + '"]');
      if (node) node.style.opacity = i === o.stage ? 1 : 0.2;
    }
    return g;
  }

  /* ============================================================
     BELIEF EVOLUTION  -  landing section "The twin remembers"

     The same week read vertically as a sequence. The geometry does
     the arguing: the PREDICT band is visibly wider than the
     posterior it came from, and the UPDATE band is narrower again.
     ============================================================ */
  function beliefEvolution(o) {
    const W = 560, H = 470, L = 122, R = 92, T = 34, B = 34;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const theta = o.theta;

    const rows = [
      { k: "prev", label: "LAST WEEK", mu: o.prev.mean, sd: o.prev.sd, step: 0 },
      { k: "predict", label: "PREDICT", mu: o.prior.mean, sd: o.prior.sd, step: 1 },
      { k: "widen", label: "UNCERTAINTY", mu: o.prior.mean, sd: o.prior.sd, step: 2 },
      { k: "obs", label: "OBSERVATION", mu: o.post.mean, sd: null, step: 3 },
      { k: "update", label: "UPDATE", mu: o.post.mean, sd: o.post.sd, step: 4 },
      { k: "state", label: "THIS WEEK", mu: o.post.mean, sd: o.post.sd, step: 5 },
    ];
    const maxHalf = 1.96 * Math.max(o.prev.sd, o.prior.sd, o.post.sd);
    const mus = [o.prev.mean, o.prior.mean, o.post.mean];
    const lo = Math.min(Math.min.apply(null, mus) - maxHalf * 1.15, theta - 0.3);
    const hi = Math.max(Math.max.apply(null, mus) + maxHalf * 1.15, theta + 0.3);
    const X = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);

    const cInk = css("--ink"), cInk3 = css("--ink-3"), cInk4 = css("--ink-4");
    const cLine = css("--line"), cTealB = css("--teal-b"), cAmber = css("--amber");
    const cAmberB = css("--amber-b"), cCoralB = css("--coral-b");

    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "be-svg", role: "img",
      "aria-label": o.label ||
        ("One week of belief for week " + o.week + ": last week's state, the "
         + "prediction, the observation, and the updated state") });

    g.appendChild(s("line", { x1: X(theta), x2: X(theta), y1: y0 - 10, y2: y1 + 6,
      stroke: cAmber, "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
    g.appendChild(txt({ x: X(theta), y: y0 - 15, fill: cAmberB, "font-size": 10,
      "font-family": MONO, "text-anchor": "middle" }, "θ " + f2(theta)));

    const rowH = (y1 - y0) / rows.length;
    rows.forEach((r, i) => {
      const yc = y0 + rowH * (i + 0.5);
      const reached = o.step >= r.step;
      const on = o.step === r.step;
      const gr = s("g", { class: "be-row" });
      gr.style.opacity = reached ? 1 : 0.15;

      gr.appendChild(txt({ x: L - 16, y: yc + 3.5, fill: on ? cInk : cInk4,
        "font-size": 10, "font-family": MONO, "text-anchor": "end",
        "letter-spacing": "1.2" }, r.label));

      if (r.sd === null) {
        // The observation is a datum, not a distribution: a tick, not a band.
        gr.appendChild(s("line", { x1: X(r.mu), x2: X(r.mu), y1: yc - 13, y2: yc + 13,
          stroke: cInk, "stroke-width": 2.2 }));
        gr.appendChild(s("circle", { cx: X(r.mu), cy: yc, r: 3.4, fill: cInk }));
        gr.appendChild(txt({ x: X(r.mu) + 12, y: yc + 3.5, fill: on ? cInk : cInk4,
          "font-size": 9.5, "font-family": MONO }, "evidence arrives"));
      } else {
        const half = 1.96 * r.sd;
        const predicting = r.k === "predict" || r.k === "widen";
        const col = predicting ? cInk3 : (r.mu >= theta ? cTealB : cCoralB);
        gr.appendChild(s("rect", {
          x: X(r.mu - half), y: yc - 9,
          width: Math.max(X(r.mu + half) - X(r.mu - half), 2),
          height: 18, rx: 3, fill: col, "fill-opacity": on ? .32 : .16,
          stroke: col, "stroke-width": on ? 1.4 : 1,
          "stroke-dasharray": predicting ? "4 3" : "none",
        }));
        gr.appendChild(s("line", { x1: X(r.mu), x2: X(r.mu), y1: yc - 13, y2: yc + 13,
          stroke: col, "stroke-width": 1.8 }));
        gr.appendChild(txt({ x: x1 + 10, y: yc + 3.5, fill: on ? cInk : cInk4,
          "font-size": 9.5, "font-family": MONO }, "±" + f2(half)));
      }
      g.appendChild(gr);

      if (i < rows.length - 1) {
        g.appendChild(s("path", {
          d: "M " + (L - 54) + " " + (yc + 9) + " L " + (L - 54) + " " + (yc + rowH - 9),
          stroke: o.step > r.step ? cInk4 : cLine, "stroke-width": 1 }));
      }
    });

    g.appendChild(txt({ x: x0, y: y1 + 22, fill: cInk4, "font-size": 9.5,
      "font-family": MONO, "letter-spacing": "1.2" }, "STATE VALUE →"));
    g.appendChild(txt({ x: x1, y: y1 + 22, fill: cInk4, "font-size": 9.5,
      "font-family": MONO, "letter-spacing": "1.2", "text-anchor": "end" },
      "WEEK " + String(o.week).padStart(2, "0")));
    return g;
  }

  /* ============================================================
     WEEK RAIL  -  a vertical temporal index for the Time section
     ============================================================ */
  function weekRail(o) {
    const n = o.n, sel = o.selected;
    const W = 74, H = 470, T = 22, B = 22;
    const y0 = T, y1 = H - B;
    const Y = (i) => y0 + (i / Math.max(n - 1, 1)) * (y1 - y0);
    const cInk4 = css("--ink-4"), cLine = css("--line-2");
    const cTealB = css("--teal-b"), cCoralB = css("--coral-b");
    const g = s("svg", { viewBox: "0 0 " + W + " " + H, class: "wr-svg",
      role: "img", "aria-label": "Week selector, week 0 to week " + (n - 1) });

    g.appendChild(s("line", { x1: 30, x2: 30, y1: y0, y2: y1, stroke: cLine,
      "stroke-width": 1 }));
    for (let i = 0; i < n; i++) {
      const on = i === sel;
      const above = o.above && o.above[i];
      g.appendChild(s("circle", { cx: 30, cy: Y(i), r: on ? 5 : 2.6,
        fill: on ? (above ? cTealB : cCoralB) : cInk4,
        "fill-opacity": on ? 1 : .55 }));
      if (on) {
        g.appendChild(s("circle", { cx: 30, cy: Y(i), r: 10, fill: "none",
          stroke: above ? cTealB : cCoralB, "stroke-width": 1, "stroke-opacity": .5 }));
      }
      if (i % 4 === 0 || on) {
        g.appendChild(txt({ x: 46, y: Y(i) + 3.5, fill: on ? css("--ink") : cInk4,
          "font-size": 9.5, "font-family": MONO },
          "W" + String(i).padStart(2, "0")));
      }
    }
    g.pick = function (clientY) {
      const r = g.getBoundingClientRect();
      const sy = ((clientY - r.top) / r.height) * H;
      const i = Math.round(((sy - y0) / (y1 - y0)) * (n - 1));
      return Math.max(0, Math.min(n - 1, i));
    };
    return g;
  }

  window.ST_Charts.modelLoop = modelLoop;
  window.ST_Charts.beliefEvolution = beliefEvolution;
  window.ST_Charts.weekRail = weekRail;
})();
