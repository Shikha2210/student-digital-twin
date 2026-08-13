# Data

**Nothing in `raw/` or `processed/` is committed.** See `.gitignore`.

## OULAD — required for any real result

The Open University Learning Analytics Dataset is **not present in this
repository** and must be downloaded separately.

- Source: <https://analyse.kmi.open.ac.uk/open-dataset>
- Paper: Kuzilek, J., Hlosta, M. & Zdrahal, Z. (2017). *Open University Learning
  Analytics dataset*. Scientific Data 4, 170171.
- Licence: CC-BY 4.0. Check the terms yourself before use or redistribution.

### Where to put it

Unzip so the CSVs sit directly in `data/raw/oulad/`:

```
data/raw/oulad/
├── assessments.csv
├── courses.csv
├── studentAssessment.csv
├── studentInfo.csv
├── studentRegistration.csv
├── studentVle.csv          (~430 MB, ~10.6M rows)
└── vle.csv
```

Then:

```bash
py -3.13 scripts/run_prototype.py --adapter oulad
```

The adapter checks for all seven files and raises `RawDataMissing` with these
instructions if any is absent. **It does not fall back to synthetic data** — a
silent fallback is how fabricated results happen.

### What OULAD contains

32,593 students · 7 modules · 22 course-presentations · ~10.6M daily click records.

Modules by discipline (verified against the dataset documentation):

| Discipline | Modules |
|---|---|
| Social science | AAA, BBB, GGG |
| STEM | CCC, DDD, EEE, FFF |

### What OULAD does NOT contain

- **No lifestyle data** — no sleep, exercise, hobbies, or screen time.
- **No self-reported state** — no stress, motivation, or perceived workload.
- **No per-question interactions** — clickstream is daily *aggregated counts* per
  activity type, so classical knowledge tracing is not supported.
- **No recorded interventions** — which is why intervention effects are assumed,
  never estimated. See [docs/assumptions.md A-08](../docs/assumptions.md#a-08).

Its context is also narrow in ways that matter: 100% distance learning, open
entry, mostly mature part-time students, UK, 2013–2014.

## Synthetic fixture — for tests only

`SyntheticAdapter` generates a deterministic cohort from a known latent process.
It needs no files and is used for pipeline tests and ground-truth recovery checks.

**It is not a substitute for OULAD.** Any number produced from it describes our
estimator, never students. Every artefact derived from it is stamped
`synthetic=True` and the provenance string says so.
