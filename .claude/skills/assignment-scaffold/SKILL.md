---
name: assignment-scaffold
description: Create a new Assignment-N.ipynb matching the structure of the existing notebooks. Use when starting a new ML assignment or asked to set up the next notebook.
---

# Scaffold a new assignment notebook

## Conventions in this repo

- Naming: `Assignment-N.ipynb` (hyphen). Only the first is `Assignment_1_ML.ipynb`
  — do not copy that older pattern.
- Kernel `python3`, Python 3.13 — the interpreter is `py -3.13`, not the 3.11 on
  PATH.
- **Code cells only**, no markdown cells, few cells overall — most notebooks here
  are 2 to 3 large cells. Keep that shape unless the assignment brief asks for
  written answers, in which case use markdown cells for them.
- Outputs are committed.

## Ask before generating

Get the assignment brief first — the task, the dataset, and the required model or
technique. Do not guess; a scaffold aimed at the wrong task is worse than none.

## Create it

Pick the next free number, then:

```bash
cd "C:/Users/ACER/gittry/Assignments-ML"
py -3.13 -c "
import nbformat as nbf
nb = nbf.v4.new_notebook()
nb.cells = [nbf.v4.new_code_cell(src) for src in [
    'import numpy as np\nimport pandas as pd\n'
    'from sklearn.model_selection import train_test_split\n'
    'from sklearn.preprocessing import StandardScaler\n',
    '# load data\n',
    '# fit + evaluate\n',
]]
nb.metadata = {
    'kernelspec': {'name': 'python3', 'display_name': 'Python 3'},
    'language_info': {'name': 'python', 'version': '3.13.5'},
}
nbf.write(nb, 'Assignment-9.ipynb')
"
```

Fill the cells using the `sklearn-baseline` skill for the modelling block and
`eval-report` for the results block, then run it once with `notebook-run` so the
committed outputs come from a clean top-to-bottom execution.
