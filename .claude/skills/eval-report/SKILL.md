---
name: eval-report
description: Produce the standard evaluation block - metrics, confusion matrix, classification report, and the plot that goes with it. Use when asked to evaluate a model, report accuracy, show a confusion matrix, or interpret results.
---

# Evaluation block

## Classification

```python
from sklearn.metrics import (
    accuracy_score, confusion_matrix, classification_report,
    ConfusionMatrixDisplay,
)
import matplotlib.pyplot as plt

y_pred = model.predict(X_test)

print("Accuracy:", accuracy_score(y_test, y_pred))
print()
print(classification_report(y_test, y_pred))

ConfusionMatrixDisplay.from_estimator(model, X_test, y_test)
plt.title("Confusion matrix")
plt.tight_layout()
plt.show()
```

## Regression

```python
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

y_pred = model.predict(X_test)
print("MSE :", mean_squared_error(y_test, y_pred))
print("RMSE:", mean_squared_error(y_test, y_pred) ** 0.5)
print("MAE :", mean_absolute_error(y_test, y_pred))
print("R2  :", r2_score(y_test, y_pred))
```

## Cross-validated score, when a single split is too small

```python
from sklearn.model_selection import cross_val_score, KFold

cv = KFold(n_splits=5, shuffle=True, random_state=42)
scores = cross_val_score(pipeline, X, y, cv=cv, scoring="accuracy")
print(f"{scores.mean():.4f} +/- {scores.std():.4f}")
```

Pass the **pipeline**, not a pre-scaled `X` — scaling outside `cross_val_score`
leaks each fold's validation statistics into its training data.

## Reading the numbers

Say what the result means, not just what it is:

- **Accuracy alone is misleading on imbalanced classes.** Quote precision,
  recall, and F1 per class from the classification report; a 95% accuracy on a
  95/5 split is the majority-class baseline, not a working model.
- **Compare against a baseline.** `DummyClassifier(strategy="most_frequent")`
  or, for regression, predicting the mean. A model that does not beat it has
  learned nothing.
- **Name the confusion.** Read the off-diagonal cells and state which classes
  the model actually mixes up.
- **Train vs test gap.** Score both. A large gap is overfitting; both low is
  underfitting. Report it when it is present rather than only the test number.
