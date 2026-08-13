---
name: sklearn-baseline
description: Scaffold the standard load - split - scale - fit - evaluate pipeline for a scikit-learn model. Use when starting a new classifier or regressor, adding a baseline to compare against, or when asked to "set up the model" for an assignment.
---

# scikit-learn baseline

Match the house style of this repo: plain procedural cells, `np`/`pd` aliases,
no wrapper functions or classes unless the assignment asks for them.

## Classification

```python
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

model = DecisionTreeClassifier(random_state=42)   # swap in the assignment's model
model.fit(X_train, y_train)
y_pred = model.predict(X_test)

print("Accuracy:", accuracy_score(y_test, y_pred))
print(classification_report(y_test, y_pred))
```

## Regression

Same shape, minus `stratify`, with `LinearRegression` /  `RidgeCV` and
`mean_squared_error` + `r2_score`.

## Rules that actually matter

- **`random_state=42` everywhere** it is accepted — split, model, CV. Assignment
  results get compared across runs; unseeded output is not reproducible.
- **Fit the scaler on train only.** `fit_transform` on train, `transform` on
  test. Scaling before the split leaks test statistics and inflates the score.
- **`stratify=y` for classification**, especially on the small datasets used
  here — an unstratified split can drop a class from the test set entirely.
- **Scale for distance- and margin-based models** (KNN, SVC, PCA, logistic
  regression). Trees, random forests, and AdaBoost do not need it; adding a
  scaler there is harmless but noise.
- Prefer `Pipeline(StandardScaler(), model)` when the cell also runs
  `GridSearchCV` or `KFold` — otherwise the scaler leaks across CV folds.

## Comparing several models

Loop over a dict and print one row each, rather than copy-pasting the block:

```python
models = {
    "KNN": KNeighborsClassifier(),
    "SVC": SVC(random_state=42),
    "NB": GaussianNB(),
}
for name, m in models.items():
    m.fit(X_train, y_train)
    print(f"{name:6s} {accuracy_score(y_test, m.predict(X_test)):.4f}")
```
