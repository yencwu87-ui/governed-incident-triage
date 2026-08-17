### gbdt-tfidf-n3000

| Metric | Value |
| --- | --- |
| Incidents | 60 |
| Scored (passed Gate A) | 58 |
| Blocked by Gate A | 2 |
| Exact severity accuracy | 36.2% |
| Within one level | 67.2% |
| **Under-classification rate** | **25.0%** |
| Over-classified | 22 |
| Escalation recall (Gate B) | 97.1% |
| Escalation precision (Gate B) | 64.2% |

Confusion matrix, rows are ground truth:

| truth \ predicted | SEV1 | SEV2 | SEV3 | SEV4 |
| --- | --- | --- | --- | --- |
| SEV1 | 9 | 3 | 6 | 2 |
| SEV2 | 2 | 5 | 2 | 0 |
| SEV3 | 5 | 5 | 6 | 2 |
| SEV4 | 4 | 2 | 4 | 1 |

Per-class:

| Severity | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| SEV1 | 20 | 0.45 | 0.45 | 0.45 |
| SEV2 | 9 | 0.33 | 0.56 | 0.42 |
| SEV3 | 20 | 0.33 | 0.30 | 0.32 |
| SEV4 | 11 | 0.20 | 0.09 | 0.13 |