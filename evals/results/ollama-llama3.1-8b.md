### ollama-llama3.1:8b

| Metric | Value |
| --- | --- |
| Incidents | 60 |
| Scored (passed Gate A) | 60 |
| Blocked by Gate A | 0 |
| Exact severity accuracy | 66.7% |
| Within one level | 95.0% |
| **Under-classification rate** | **13.3%** |
| Over-classified | 12 |
| Escalation recall (Gate B) | 85.7% |
| Escalation precision (Gate B) | 88.2% |

Confusion matrix, rows are ground truth:

| truth \ predicted | SEV1 | SEV2 | SEV3 | SEV4 |
| --- | --- | --- | --- | --- |
| SEV1 | 15 | 3 | 2 | 0 |
| SEV2 | 2 | 5 | 2 | 0 |
| SEV3 | 0 | 4 | 15 | 1 |
| SEV4 | 1 | 0 | 5 | 5 |

Per-class:

| Severity | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| SEV1 | 20 | 0.83 | 0.75 | 0.79 |
| SEV2 | 9 | 0.42 | 0.56 | 0.48 |
| SEV3 | 20 | 0.62 | 0.75 | 0.68 |
| SEV4 | 11 | 0.83 | 0.45 | 0.59 |