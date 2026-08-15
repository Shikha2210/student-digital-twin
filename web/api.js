/* ============================================================
   StudyTwin  ·  data layer

   The frontend has ONE internal shape - the view model - and two
   producers for it:

     fromApi(...)       live data from the FastAPI backend
     fromSnapshot(...)  the bundled offline export, web/data.js

   Both produce identical structures, so no screen knows or cares
   which one it got. That is the whole point: there is no second
   implementation of anything, and the fallback is a transport
   fallback rather than a different product.

   No number is computed here that the model could have computed.
   The two exceptions are arithmetic over already-inferred values -
   deriving a deviation by subtracting theta from a state, and
   sorting scenarios by their own stored magnitude - and both are
   labelled where they are used.
   ============================================================ */
(function () {
  "use strict";

  /** Where the API lives. Same origin when FastAPI serves the page; an
      explicit host when the static server on :8777 does. */
  const API_BASE = (function () {
    const override = new URLSearchParams(location.search).get("api");
    if (override) return override.replace(/\/$/, "");
    if (location.port === "8777") return "http://127.0.0.1:8000";
    return "";
  })();

  const TIMEOUT_MS = 6000;

  async function getJSON(path) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(API_BASE + path, {
        signal: ctrl.signal, headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const err = new Error("HTTP " + res.status + " on " + path);
        err.status = res.status;
        err.body = body;
        throw err;
      }
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /* ------------------------------------------------------------------
     API -> view model
     ------------------------------------------------------------------ */

  /** Magnitude of the engagement-support intervention on a scenario, in
      latent state units. Read off the stored intervention record - not
      parsed out of the label, which would break the moment someone
      renames one. */
  function magnitudeOf(scenario) {
    const iv = (scenario.interventions || [])
      .filter((i) => i.name === "engagement_support");
    return iv.length ? Number(iv[0].magnitude) : 0;
  }

  function seriesFor(twin, dimName) {
    return twin.state.find((s) => s.dim_name === dimName) || null;
  }

  function quantilesFor(scenario, dimName) {
    return scenario.quantiles.find((q) => q.dim_name === dimName) || null;
  }

  function fromApi(twin, extras) {
    const dims = twin.dim_names;
    const primary = dims[0];
    const second = dims[1] || dims[0];
    const s0 = seriesFor(twin, primary);
    const s1 = seriesFor(twin, second);
    const theta = twin.baseline.map((b) => b.theta);

    // Scenarios, ordered by their own magnitude so the Intervention Lab
    // slider walks a monotone axis. Every stop is a stored simulation.
    const scen = twin.scenarios
      .map((s) => ({ s: s, d: magnitudeOf(s) }))
      .sort((a, b) => a.d - b.d);
    const base = (scen.find((x) => x.d === 0) || scen[0] || {}).s || null;
    const alt = (scen.filter((x) => x.d > 0).slice(-1)[0] || {}).s || base;
    const bq = base ? quantilesFor(base, primary) : null;
    const aq = alt ? quantilesFor(alt, primary) : null;

    const attrib = twin.attribution.map((a) => {
      const ch = {};
      a.components.forEach((c) => { ch[c.channel] = c.contribution; });
      return {
        t: a.t, shift: a.shift, unexp: a.residual, ch: ch,
        // PREDICT and UPDATE, as the filter actually computed them. Carried
        // through so the landing page can show the loop without a single
        // model equation being re-implemented in the browser.
        prior: a.prior_mean, prior_sd: a.prior_sd,
        post: a.posterior_mean, post_sd: a.posterior_sd,
      };
    });

    const featNames = Object.keys(
      (twin.observations.find((o) => Object.keys(o.features).length) || {}).features || {});
    const obs = featNames.length ? {
      cols: featNames,
      rows: twin.observations.map((o) => ({
        t: o.t, v: featNames.map((f) => (o.features[f] === undefined ? 0 : o.features[f])),
      })),
      n: twin.observations.map((o) => Object.keys(o.channels).length),
    } : null;

    const ownPrimary = twin.own_distribution.find((d) => d.dim_name === primary) || {};

    return {
      source: "api",
      provenance: {
        dataset: twin.provenance.dataset,
        synthetic: twin.provenance.synthetic,
        seed: twin.provenance.seed,
        inference: twin.provenance.inference_method,
        note: twin.provenance.note,
        run_id: twin.provenance.run_id,
        model_version: twin.provenance.model_version,
        code_revision: twin.provenance.code_revision,
        created_at: twin.provenance.created_at,
      },
      dim_names: dims,
      student: {
        id: twin.student.student_id,
        context: twin.student.context_id,
        weeks: twin.student.n_weeks,
        theta: theta,
      },
      state: {
        t: s0 ? s0.t : [],
        eng: s0 ? s0.mean : [],
        eng_sd: s0 ? s0.sd : [],
        cap: s1 ? s1.mean : [],
        cap_sd: s1 ? s1.sd : [],
        method: s0 ? s0.method : "unknown",
      },
      hazard: twin.hazard.map((h) => h.hazard),
      cum_risk: twin.hazard.map((h) => h.cum_risk),
      sim: base ? {
        weeks: bq ? bq.t : [],
        base_med: bq ? bq.q50 : [], base_lo: bq ? bq.q05 : [], base_hi: bq ? bq.q95 : [],
        alt_med: aq ? aq.q50 : [], alt_lo: aq ? aq.q05 : [], alt_hi: aq ? aq.q95 : [],
        base_risk: base.cum_risk, alt_risk: alt ? alt.cum_risk : base.cum_risk,
        particles: base.paths, alt_particles: alt ? alt.paths : [],
        horizon: base.horizon, n_particles: base.n_particles,
        disclaimer: base.disclaimer,
      } : null,
      sweep: scen.map((x) => {
        const q = quantilesFor(x.s, primary);
        return {
          d: x.d, label: x.s.label,
          med: q ? q.q50 : [], lo: q ? q.q05 : [], hi: q ? q.q95 : [],
          risk: x.s.cum_risk,
        };
      }),
      attrib: attrib,
      obs: obs,
      own: ownPrimary,
      shrinkage: twin.baseline.map((b) => b.shrinkage_k),
      cohort_theta: twin.cohort_theta,
      // filled by the extras fetch; absent rather than faked if it failed
      metrics: extras.metrics || null,
      controls: extras.controls || null,
      capability: extras.capability || null,
      not_implemented: extras.not_implemented || [],
      coverage: extras.coverage || null,
      cohort: extras.cohort || null,
      cohort_states: extras.cohort_states || null,
      contrast: extras.contrast || null,
      run: extras.run || null,
    };
  }

  /* ------------------------------------------------------------------
     Bundled snapshot -> view model

     web/data.js is a frozen export of one run. It exists so the product
     still demonstrates itself with no backend running, and it is
     labelled OFFLINE SNAPSHOT wherever it is used.
     ------------------------------------------------------------------ */
  function fromSnapshot(D) {
    if (!D) return null;
    const sweep = (D.sweep || []).map((s) => ({
      d: s.d, label: s.d ? "Support +" + s.d.toFixed(2) : "Current dynamics",
      med: s.med, lo: s.lo, hi: s.hi, risk: s.risk,
    }));
    const own = (function () {
      const v = D.state.eng, th = D.student.theta[0];
      if (!v || !v.length) return {};
      const n = v.length, mu = v.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) * (b - mu), 0) / n);
      const below = v.map((x) => x < th);
      let longest = 0, run = 0, cur = 0;
      below.forEach((b) => { run = b ? run + 1 : 0; longest = Math.max(longest, run); });
      for (let i = below.length - 1; i >= 0 && below[i]; i--) cur++;
      return {
        dim_name: "engagement", mean: mu, sd: sd, n: n,
        weeks_below_theta: below.filter(Boolean).length,
        longest_run_below: longest, current_run_below: cur,
      };
    })();

    return {
      source: "snapshot",
      provenance: {
        dataset: D.provenance.dataset, synthetic: D.provenance.synthetic,
        seed: D.provenance.seed, inference: D.provenance.inference,
        note: D.provenance.note, run_id: null, model_version: null,
        code_revision: null, created_at: null,
      },
      dim_names: ["engagement", "capability"],
      student: D.student,
      state: Object.assign({ method: D.provenance.inference }, D.state),
      hazard: D.hazard,
      cum_risk: null,
      sim: D.sim,
      sweep: sweep,
      attrib: D.attrib,
      obs: D.obs || null,
      own: own,
      shrinkage: D.shrinkage,
      cohort_theta: (D.cohort_states || []).map((c) => c.th),
      metrics: (D.metrics || []).map((m) => ({
        model_name: m.name, auc: m.auc, brier: m.brier, ece: m.ece,
        n: m.n, positives: m.pos,
      })),
      controls: (D.controls || []).map((c) => ({
        control: c.c, verdict: c.v, auc: c.auc, is_leakage_test: c.leak,
      })),
      capability: null,
      not_implemented: [
        "T3 (intervention stability) - NOT IMPLEMENTED.",
        "T4 (identifiability / construct validity) - NOT IMPLEMENTED.",
      ],
      coverage: D.cohort ? {
        available: D.cohort.coverage_avail, unavailable: D.cohort.coverage_missing,
      } : null,
      cohort: D.cohort,
      run: null,
      cohort_states: (D.cohort_states || []).map((c) => ({
        student_id: c.id, mean_state: c.m, theta: c.th, last_state: c.last,
      })),
      contrast: (D.contrast && D.contrast.length >= 2) ? {
        high: { student_id: D.contrast[0].id, theta: D.contrast[0].theta,
                mean: D.contrast[0].eng, sd: D.contrast[0].eng_sd },
        low: { student_id: D.contrast[1].id, theta: D.contrast[1].theta,
               mean: D.contrast[1].eng, sd: D.contrast[1].eng_sd },
      } : null,
    };
  }

  /* ------------------------------------------------------------------
     Boot
     ------------------------------------------------------------------ */

  async function loadFromApi(studentId) {
    const health = await getJSON("/api/health");
    if (!health.runs) {
      const e = new Error("The API is running but the database contains no model run.");
      e.hint = "Run: python scripts/ingest_run.py --students 250 --weeks 20";
      e.kind = "empty";
      throw e;
    }
    const sid = studentId || (await getJSON("/api/students/demo")).student_id;
    const twin = await getJSON("/api/students/" + encodeURIComponent(sid) + "/twin");

    // Secondary payloads. A failure here degrades one panel, not the app,
    // so each one resolves to null rather than rejecting the boot.
    const soft = (p) => p.catch(() => null);
    const [evalP, cohort, contrast, run] = await Promise.all([
      soft(getJSON("/api/evaluation")),
      soft(getJSON("/api/cohort?limit=400")),
      soft(getJSON("/api/contrast")),
      soft(getJSON("/api/runs/" + encodeURIComponent(health.latest_run_id))),
    ]);

    return fromApi(twin, {
      metrics: evalP ? evalP.metrics : null,
      controls: evalP ? evalP.negative_controls : null,
      capability: evalP ? evalP.capability_tests : null,
      not_implemented: evalP ? evalP.not_implemented : [],
      coverage: evalP ? evalP.coverage : null,
      cohort_states: cohort,
      cohort: run ? {
        students: run.n_students, rows: run.n_person_periods, events: run.n_events,
        rate: run.n_person_periods ? run.n_events / run.n_person_periods : null,
        contexts: null,
      } : (cohort ? { students: cohort.length } : null),
      run: run,
      contrast: contrast,
    });
  }

  /** Resolve the view model. Tries the API, falls back to the snapshot.
      Never invents data: if both fail, it reports which and why. */
  async function boot(opts) {
    const o = opts || {};
    const started = performance.now();
    try {
      const vm = await loadFromApi(o.studentId);
      vm.latency_ms = Math.round(performance.now() - started);
      return { ok: true, vm: vm, mode: "api" };
    } catch (err) {
      const snap = fromSnapshot(window.STUDYTWIN_DATA);
      if (snap) {
        snap.fallback_reason = err.kind === "empty"
          ? "The API has no model run stored."
          : "The API at " + (API_BASE || location.origin) + " did not respond.";
        snap.fallback_hint = err.hint ||
          "Start it with: uvicorn student_twin.api.app:app --port 8000";
        return { ok: true, vm: snap, mode: "snapshot" };
      }
      return {
        ok: false, vm: null, mode: "none",
        error: err.message || String(err),
        hint: err.hint || "No API and no bundled snapshot. Nothing can be shown.",
      };
    }
  }

  window.ST_Api = {
    base: API_BASE,
    boot: boot,
    getJSON: getJSON,
    fromApi: fromApi,
    fromSnapshot: fromSnapshot,
    createProfile: function (body) {
      return fetch(API_BASE + "/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))));
    },
  };
})();
