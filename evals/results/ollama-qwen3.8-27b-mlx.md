### ollama-qwen3.8:27b-mlx

| Metric | Value |
| --- | --- |
| Incidents | 60 |
| Scored (passed Gate A) | 0 |
| Blocked by Gate A | 60 |
| Exact severity accuracy | 0.0% |
| Within one level | 0.0% |
| **Under-classification rate** | **0.0%** |
| Over-classified | 0 |
| Escalation recall (Gate B) | 0.0% |
| Escalation precision (Gate B) | 0.0% |

Confusion matrix, rows are ground truth:

| truth \ predicted | SEV1 | SEV2 | SEV3 | SEV4 |
| --- | --- | --- | --- | --- |
| SEV1 | 0 | 0 | 0 | 0 |
| SEV2 | 0 | 0 | 0 | 0 |
| SEV3 | 0 | 0 | 0 | 0 |
| SEV4 | 0 | 0 | 0 | 0 |

Per-class:

| Severity | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| SEV1 | 20 | 0.00 | 0.00 | 0.00 |
| SEV2 | 9 | 0.00 | 0.00 | 0.00 |
| SEV3 | 20 | 0.00 | 0.00 | 0.00 |
| SEV4 | 11 | 0.00 | 0.00 | 0.00 |