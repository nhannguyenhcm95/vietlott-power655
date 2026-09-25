"""Monte Carlo derived null references (M3 spec section 3.3). Pure function, no I/O."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.statistics import null_model

# Dedicated stream ids for mc_reference, distinct from other null_model consumers (stream 1 is
# reserved for "replicate datasets" per the spec's module docstring convention).
_STREAM_MAIN = 1
_STREAM_SPECIAL = 2

_ROW_CHUNK_CAP = 200_000


def _pair_counts_vector(main_slice: np.ndarray, N: int = 55) -> np.ndarray:
    """1,485-length vector of pair co-occurrence counts, in the deterministic i<j (row-major)
    order given by `np.triu_indices(N, k=1)`."""
    mat = np.zeros((N + 1, N + 1), dtype=np.int64)
    idx_i, idx_j = np.triu_indices(main_slice.shape[1], k=1)
    pi = main_slice[:, idx_i]
    pj = main_slice[:, idx_j]
    np.add.at(mat, (pi.ravel(), pj.ravel()), 1)
    sub = mat[1 : N + 1, 1 : N + 1]
    iu = np.triu_indices(N, k=1)
    return sub[iu]


def _number_counts_vector(main_slice: np.ndarray, N: int = 55) -> np.ndarray:
    counts = np.bincount(main_slice.ravel(), minlength=N + 1)
    return counts[1 : N + 1]


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    x = x.astype(float)
    y = y.astype(float)
    xm = x - x.mean()
    ym = y - y.mean()
    denom = np.sqrt((xm**2).sum() * (ym**2).sum())
    if denom == 0:
        return float("nan")
    return float((xm * ym).sum() / denom)


def _quantile(values: list[float], q: float, method: str = "linear") -> float:
    clean = [v for v in values if not (isinstance(v, float) and np.isnan(v))]
    return float(np.quantile(np.asarray(clean, dtype=float), q, method=method))


def replicate_references(
    n: int,
    windows: list[int],
    n_blocks: int,
    reps: int,
    seed: int,
    n_special: int | None = None,
    replicate_chunk_size: int | None = None,
) -> pd.DataFrame:
    """Simulate `reps` replicate datasets of `n` draws under the uniform null and summarize the
    quantities needed for MC-derived references (section 3.3). Long form:
    statistic, param, quantile, value, reps, seed.

    Streamed in chunks of replicates (`replicate_chunk_size`, default = reps, i.e. one chunk);
    the output is invariant to the chunk size because the underlying RNG streams
    (`null_model.rng_for(_STREAM_MAIN, seed)` for the main numbers and
    `null_model.rng_for(_STREAM_SPECIAL, seed)` for the special, each simulated over `n_special`
    draws paired 1:1 by replicate index) are each consumed once, continuously, regardless of how
    the replicate loop is batched: `null_model.simulate_draws` is itself chunk-size invariant for
    a fixed, continuing RNG (see T5).
    """
    if n_special is None:
        n_special = n
    if replicate_chunk_size is None or replicate_chunk_size <= 0:
        replicate_chunk_size = reps

    p = null_model.P_NUMBER

    rng_main = null_model.rng_for(stream_id=_STREAM_MAIN, seed=seed)
    rng_special = null_model.rng_for(stream_id=_STREAM_SPECIAL, seed=seed)

    block_ranges = np.array_split(np.arange(n), n_blocks)
    block_pairs = [(a, b) for a in range(n_blocks) for b in range(a + 1, n_blocks)]

    freq_min: list[int] = []
    freq_max: list[int] = []
    special_min: list[int] = []
    special_max: list[int] = []
    pair_min: list[int] = []
    pair_max: list[int] = []
    rolling: dict[int, dict[str, list[float]]] = {w: {"max_z": [], "min_z": []} for w in windows}
    r_number: dict[tuple[int, int], list[float]] = {bp: [] for bp in block_pairs}
    r_pair: dict[tuple[int, int], list[float]] = {bp: [] for bp in block_pairs}

    # Pass 1: main-number statistics (frequency min/max, pairs, rolling envelope, block stability).
    remaining = reps
    while remaining > 0:
        c = min(replicate_chunk_size, remaining)
        row_chunk = min(c * n, _ROW_CHUNK_CAP)
        main_flat, _ = null_model.simulate_draws(c * n, rng_main, chunk_size=row_chunk)
        main_batch = main_flat.reshape(c, n, 6)

        for r in range(c):
            main_r = main_batch[r]

            counts = _number_counts_vector(main_r)
            freq_min.append(int(counts.min()))
            freq_max.append(int(counts.max()))

            pair_vec = _pair_counts_vector(main_r)
            pair_min.append(int(pair_vec.min()))
            pair_max.append(int(pair_vec.max()))

            for w in windows:
                if w > n:
                    continue
                sub_counts = _number_counts_vector(main_r[:w])
                expected = w * p
                sd = np.sqrt(w * p * (1 - p))
                z = (sub_counts - expected) / sd
                rolling[w]["max_z"].append(float(z.max()))
                rolling[w]["min_z"].append(float(z.min()))

            block_number_vecs = [_number_counts_vector(main_r[idx]) for idx in block_ranges]
            block_pair_vecs = [_pair_counts_vector(main_r[idx]) for idx in block_ranges]
            for a, b in block_pairs:
                r_number[(a, b)].append(_pearson_r(block_number_vecs[a], block_number_vecs[b]))
                r_pair[(a, b)].append(_pearson_r(block_pair_vecs[a], block_pair_vecs[b]))

        remaining -= c

    # Pass 2: special-number statistics, over n_special draws, paired 1:1 by replicate index.
    remaining = reps
    while remaining > 0:
        c = min(replicate_chunk_size, remaining)
        row_chunk_s = min(c * n_special, _ROW_CHUNK_CAP)
        _, special_flat = null_model.simulate_draws(c * n_special, rng_special, chunk_size=row_chunk_s)
        special_batch = special_flat.reshape(c, n_special)
        for r in range(c):
            s_counts = np.bincount(special_batch[r], minlength=56)[1:56]
            special_min.append(int(s_counts.min()))
            special_max.append(int(s_counts.max()))
        remaining -= c

    # nit-3: these are counts (integers); use "lower"/"higher" (not linear interpolation) so the
    # simultaneous-band quantiles are themselves integers, widening conservatively outward.
    rows = []
    rows.append({"statistic": "number_frequency_min", "param": "", "quantile": 0.025, "value": _quantile(freq_min, 0.025, method="lower")})
    rows.append({"statistic": "number_frequency_max", "param": "", "quantile": 0.975, "value": _quantile(freq_max, 0.975, method="higher")})
    rows.append({"statistic": "special_frequency_min", "param": "", "quantile": 0.025, "value": _quantile(special_min, 0.025, method="lower")})
    rows.append({"statistic": "special_frequency_max", "param": "", "quantile": 0.975, "value": _quantile(special_max, 0.975, method="higher")})
    rows.append({"statistic": "pair_count_min", "param": "", "quantile": 0.025, "value": _quantile(pair_min, 0.025, method="lower")})
    rows.append({"statistic": "pair_count_max", "param": "", "quantile": 0.975, "value": _quantile(pair_max, 0.975, method="higher")})

    for w in windows:
        if not rolling[w]["max_z"]:
            continue
        rows.append({"statistic": "rolling_max_z", "param": str(w), "quantile": 0.975, "value": _quantile(rolling[w]["max_z"], 0.975)})
        rows.append({"statistic": "rolling_min_z", "param": str(w), "quantile": 0.025, "value": _quantile(rolling[w]["min_z"], 0.025)})

    for a, b in block_pairs:
        param = f"{a}-{b}"
        rows.append({"statistic": "stability_number", "param": param, "quantile": "mean", "value": float(np.nanmean(r_number[(a, b)]))})
        rows.append({"statistic": "stability_number", "param": param, "quantile": 0.025, "value": _quantile(r_number[(a, b)], 0.025)})
        rows.append({"statistic": "stability_number", "param": param, "quantile": 0.975, "value": _quantile(r_number[(a, b)], 0.975)})
        rows.append({"statistic": "stability_pair", "param": param, "quantile": "mean", "value": float(np.nanmean(r_pair[(a, b)]))})
        rows.append({"statistic": "stability_pair", "param": param, "quantile": 0.025, "value": _quantile(r_pair[(a, b)], 0.025)})
        rows.append({"statistic": "stability_pair", "param": param, "quantile": 0.975, "value": _quantile(r_pair[(a, b)], 0.975)})

    out = pd.DataFrame(rows, columns=["statistic", "param", "quantile", "value"])
    out["reps"] = reps
    out["seed"] = seed
    return out.sort_values(["statistic", "param", "quantile"], key=lambda s: s.astype(str)).reset_index(drop=True)
