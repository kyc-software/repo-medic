# ML Metrics Refresher

## What Are ML Metrics?

ML metrics are numerical measures used to evaluate how well a machine-learning model performs. They compare predictions with known outcomes and turn model quality into values that can be tracked, compared, and optimized.

No single metric is best for every problem. Choose one based on the task, class balance, and real-world cost of each kind of mistake. Classification metrics evaluate predicted categories or probabilities; regression metrics evaluate predicted numbers.

## Classification

Start with the confusion matrix: true positives (TP), false positives (FP), true negatives (TN), and false negatives (FN).

| Metric | Formula | Use when |
| --- | --- | --- |
| Accuracy | `(TP + TN) / all` | Classes are balanced and error costs are similar. |
| Precision | `TP / (TP + FP)` | False positives are costly. |
| Recall (sensitivity) | `TP / (TP + FN)` | False negatives are costly. |
| Specificity | `TN / (TN + FP)` | Correct rejection of negatives matters. |
| F1 | `2 * precision * recall / (precision + recall)` | Need one score balancing precision and recall. |
| ROC-AUC | Area under TPR-vs-FPR curve | Compare ranking across thresholds; can look optimistic with rare positives. |
| PR-AUC | Area under precision-vs-recall curve | Positive class is rare or most important. |
| Log loss | Penalizes wrong probabilities | Probability calibration and confidence matter. Lower is better. |

## Regression

| Metric | Meaning | Use when |
| --- | --- | --- |
| MAE | Mean absolute error | Want interpretable, outlier-resistant error in target units. |
| MSE | Mean squared error | Large mistakes deserve extra penalty. |
| RMSE | Square root of MSE | Want large-error penalty in target units. |
| R² | Improvement over predicting the target mean | Want relative fit; can be negative on unseen data. Higher is better. |

## Interview Checks

- Choose metric from business error cost, class balance, and output type.
- Report validation/test performance, never training performance alone.
- Split before preprocessing; fit preprocessing only on training data.
- For imbalanced classification, inspect confusion matrix and PR-AUC, not accuracy alone.
- Tune classification threshold on validation data, then evaluate once on untouched test data.
- Compare against a simple baseline and include uncertainty when possible.

## RepoMedic metric contract

RepoMedic uses chronological 70/15/15 splits. TF-IDF fits inside each sklearn pipeline on training rows only. Required live report:

- Classification: macro-F1, per-class recall, calibrated confidence, and majority baseline.
- Close time: MAE and median absolute error in days, plus training-median MAE baseline.
- Retrieval: Hit@3 and MRR over 20 committed golden cases.
- Generation: citation presence, citation membership validity, and unsupported-step rate.

Offline fixture smoke on 48 balanced synthetic issues produced macro-F1 `1.0`, macro-recall `1.0`, close-time MAE `2.55` days, and median absolute error `2.34` days. These values prove training, artifact, and MLflow plumbing only. They are not portfolio quality claims. Replace them with live corpus metrics before interview.

Live 1,000-issue run on August 20, 2026 produced macro-F1 `0.746` against a `0.086` majority baseline. Sparse Ridge on raw close days failed its baseline because a few long-lived issues dominated training. Capping training targets at the training-period 60th percentile reduced chronological test MAE to `11.41` days against the `11.50`-day median baseline. Gain is small. Treat close time as a rough workload estimate, not a deadline.

## Three Efficient Learning Resources

Use these in order:

1. [Google: Accuracy, Precision, Recall, and Related Metrics](https://developers.google.com/machine-learning/crash-course/classification/accuracy-precision-recall) — Short guided lesson covering confusion-matrix terms, formulas, imbalanced-data traps, F1, and metric-selection exercises.
2. [Google: Classification Exercises](https://developers.google.com/machine-learning/crash-course/exercises#classification) — Interactive practice with thresholds, confusion matrices, precision/recall, ROC/AUC, and a final quiz.
3. [scikit-learn: Metrics and Scoring](https://scikit-learn.org/stable/modules/model_evaluation.html) — Practical Python reference covering classification, regression, clustering, scorer names, and model-selection APIs. Skim relevant sections instead of reading end to end.
