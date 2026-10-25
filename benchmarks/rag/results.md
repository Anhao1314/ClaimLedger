# RAG status-filter benchmark

synthetic claims; lexical reference evidence index; no model calls. status filtering and evidence identity only, not semantic entailment or answer quality.

| Method | Evidence hits | Stale evidence hits | Stale query rate | Expected claim coverage | Current evidence ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Status-blind evidence | 8 | 2 | 40.00% | 100.00% | 75.00% |
| Status-aware context | 6 | 0 | 0.00% | 100.00% | 100.00% |

Queries: 5 · top-k: 5 · fixture: `5b58541b22645527…`

## Cases

| Query | Status-blind claim ids | Status-aware claim ids |
| --- | --- | --- |
| `use sqlite` | clm_4b81e2a7c9d30f56, clm_9f2a6c1d4e8b73a0 | clm_9f2a6c1d4e8b73a0 |
| `localStorage session tokens` | clm_c3f81a6d2b705e94, clm_e5d40b7a1c9f2836 | clm_c3f81a6d2b705e94 |
| `timeout retries` | clm_f62b9d0e1a4c8753, clm_07a1e4c8b93d62f5 | clm_f62b9d0e1a4c8753, clm_07a1e4c8b93d62f5 |
| `signing key` | clm_3a9e7f2c1b60d845 | clm_3a9e7f2c1b60d845 |
| `Friday feature flags` | clm_18d5b0c7f2a94e63 | clm_18d5b0c7f2a94e63 |

## Limits

- Synthetic claims and a lexical reference index; no embedding model.
- Expected-claim coverage is not semantic answer quality or entailment.
- A vector retriever may have different recall; re-run this benchmark with your adapter.
