"""Shared retrieval metrics for the synthetic and LongMemEval benchmarks.

One definition, two datasets. Recall@k is expected-ID coverage; MRR is the
reciprocal rank of the first relevant ID, truncated at 5; stale-hit@k and
disputed-hit@k are the fraction of queries exposing at least one such ID in the
top k. Hit rates measure exposure, not correctness.
"""

STATUS_STALE = "已过期"
STATUS_DISPUTED = "有争议"


def metrics(runs, statuses=None, *, stale_ids=None, disputed_ids=None, k_values=(1, 3, 5)):
    """Compute the shared metric block.

    ``runs`` items need ``ids`` (ranked result IDs) and ``expected`` (relevant IDs).
    Labels come either from a ``statuses`` mapping (synthetic benchmark) or from
    explicit ``stale_ids`` / ``disputed_ids`` sets (session-level benchmark).
    """
    if not runs:
        raise ValueError("metrics requires at least one run")
    if statuses is not None:
        stale_ids = {key for key, value in statuses.items() if value == STATUS_STALE}
        disputed_ids = {key for key, value in statuses.items() if value == STATUS_DISPUTED}
    else:
        stale_ids = set(stale_ids or ())
        disputed_ids = set(disputed_ids or ())

    n = len(runs)
    result = {}
    for k in k_values:
        recall = 0.0
        stale_hit = 0
        disputed_hit = 0
        for run in runs:
            expected = set(run["expected"])
            if not expected:
                raise ValueError("metrics requires non-empty expected IDs")
            top = run["ids"][:k]
            recall += len(set(top) & expected) / len(expected)
            stale_hit += any(identifier in stale_ids for identifier in top)
            disputed_hit += any(identifier in disputed_ids for identifier in top)
        result["Recall@%d" % k] = recall / n
        result["stale-hit@%d" % k] = stale_hit / n
        result["controversial-hit@%d" % k] = disputed_hit / n
    result["MRR"] = sum(
        next((1 / (index + 1) for index, identifier in enumerate(run["ids"])
              if identifier in set(run["expected"])), 0)
        for run in runs
    ) / n
    return {key: round(value, 6) for key, value in result.items()}
