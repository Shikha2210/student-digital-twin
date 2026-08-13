---
name: notebook-run
description: Execute an assignment notebook end-to-end and report which cell failed and why. Use when asked to run, execute, check, or verify a .ipynb, or to confirm a notebook still works after edits.
---

# Run a notebook end-to-end

## Interpreter

Use `py -3.13`. The bare `python` on PATH is 3.11 and has **no sklearn** — it will
produce a misleading `ModuleNotFoundError` on the first import cell.

## Execute

Run in-place so outputs land in the notebook (this repo commits outputs):

```bash
cd "C:/Users/ACER/gittry/Assignments-ML"
py -3.13 -m jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=600 Assignment-5.ipynb
```

To check *without* touching the file, drop `--inplace` and send it to a temp path
under the session scratchpad instead.

If `jupyter` is missing, fall back to nbclient directly:

```bash
py -3.13 -c "
import nbformat
from nbclient import NotebookClient
nb = nbformat.read('Assignment-5.ipynb', as_version=4)
NotebookClient(nb, timeout=600, kernel_name='python3').execute()
nbformat.write(nb, 'Assignment-5.ipynb')
"
```

## Report the failure, don't just dump the traceback

`nbconvert` prints the whole notebook on error. Report instead:

1. **Which cell** — the 1-indexed code-cell number and its first line of source.
2. **The exception** — type and message only.
3. **The likely cause**, checked against the usual suspects in this repo:
   - missing dataset file or a dead `requests` URL,
   - a cell that depends on a variable defined in a cell below it (these
     notebooks have no markdown cells and cell order drifts easily),
   - sklearn 1.8 API drift, e.g. renamed/removed keyword arguments,
   - `nltk` corpora not downloaded (`nltk.download('punkt')` etc.).

Fix the cause, re-run, and state the final result plainly: which notebook,
how many cells, pass or fail.
