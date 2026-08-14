### baseline-keyword-v2

| Metric | Value |
| --- | --- |
| Incidents | 60 |
| Scored (passed Gate A) | 60 |
| Blocked by Gate A | 0 |
| Exact severity accuracy | 58.3% |
| Within one level | 93.3% |
| **Under-classification rate** | **33.3%** |
| Over-classified | 5 |
| Escalation recall (Gate B) | 91.4% |
| Escalation precision (Gate B) | 59.3% |

Confusion matrix, rows are ground truth:

| truth \ predicted | SEV1 | SEV2 | SEV3 | SEV4 |
| --- | --- | --- | --- | --- |
| SEV1 | 9 | 7 | 4 | 0 |
| SEV2 | 0 | 5 | 4 | 0 |
| SEV3 | 0 | 1 | 14 | 5 |
| SEV4 | 0 | 0 | 4 | 7 |

Per-class:

| Severity | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| SEV1 | 20 | 1.00 | 0.45 | 0.62 |
| SEV2 | 9 | 0.38 | 0.56 | 0.45 |
| SEV3 | 20 | 0.54 | 0.70 | 0.61 |
| SEV4 | 11 | 0.58 | 0.64 | 0.61 |