---
name: notebook-clean
description: Tidy a notebook before committing - fix execution order, remove dead cells, check it runs top-to-bottom. Use when asked to clean up, tidy, or prepare a notebook for submission or commit.
---

# Clean a notebook before committing

## Do not strip outputs by default

Every notebook in `Assignments-ML` is committed **with outputs**, and for graded
assignments that is usually deliberate — the outputs are the evidence the work
ran. Strip them only if the user explicitly asks.

## Check execution order first

Out-of-order or stale `execution_count` values mean the committed outputs do not
correspond to a clean top-to-bottom run:

```bash
cd "C:/Users/ACER/gittry/Assignments-ML"
py -3.13 -c "
import json, sys, glob
for f in sorted(glob.glob('*.ipynb')):
    nb = json.load(open(f, encoding='utf-8'))
    counts = [c.get('execution_count') for c in nb['cells'] if c['cell_type'] == 'code']
    ran = [c for c in counts if c is not None]
    flags = []
    if None in counts:            flags.append('unrun cells')
    if ran != sorted(ran):        flags.append('out of order')
    if ran and ran != list(range(1, len(ran) + 1)): flags.append('not a fresh run')
    print(f, counts, '<-- ' + ', '.join(flags) if flags else 'ok')
"
```

If anything is flagged, the fix is a clean re-run via the `notebook-run` skill,
not hand-editing counts.

## Then look for

- **Dead cells** — commented-out experiments, duplicated imports, cells whose
  output is a traceback. Remove them; keep anything the assignment asked for.
- **Imports scattered mid-notebook.** These notebooks have no markdown cells, so
  a reader's only structure is import-first. Hoist them into the top cell.
- **Absolute paths** like `C:/Users/ACER/...` — make them relative to the
  notebook so the file works on the grader's machine.
- **Secrets** in `requests` calls: API keys, tokens, cookies. Never commit
  these; flag to the user rather than silently rewriting.

## Stripping outputs, when asked

```bash
py -3.13 -m jupyter nbconvert --clear-output --inplace Assignment-5.ipynb
```

## Committing

The git repo is `Assignments-ML/`, **not** the parent `gittry/` folder — run git
from inside it. Commit only when the user asks, and show `git status` and the
notebook diff summary first: notebook diffs are large and mostly output noise,
so confirm the intended change is actually in there.
