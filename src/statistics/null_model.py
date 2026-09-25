"""Uniform null model: 6-of-55 draws without replacement + 1 special from the remaining 49.

Pure functions only (M3 spec section 3.2). No I/O.
"""
from __future__ import annotations

import numpy as np

N_NUMBERS = 55
K_MAIN = 6
P_NUMBER = K_MAIN / N_NUMBERS
Q_PAIR = 1 / 99  # C(53,4)/C(55,6)
EDA_SEED = 20260924


def rng_for(stream_id: int, seed: int = EDA_SEED) -> np.random.Generator:
    """A reproducible generator for a given logical stream."""
    return np.random.default_rng(np.random.SeedSequence([seed, stream_id]))


def simulate_draws(
    n_draws: int,
    rng: np.random.Generator,
    N: int = N_NUMBERS,
    k: int = K_MAIN,
    chunk_size: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate `n_draws` uniform k-subsets of 1..N plus 1 special from the remaining N-k.

    Returns (main[int16, n_draws x k] ascending, special[int16, n_draws]).
    Generated in chunks of whole draws (default: one chunk); the output does not depend on
    chunk_size because the underlying RNG stream is consumed sequentially regardless of the
    shape requested per call.
    """
    if n_draws < 0:
        raise ValueError("n_draws must be >= 0")
    if chunk_size is None or chunk_size <= 0:
        chunk_size = n_draws if n_draws > 0 else 1

    mains: list[np.ndarray] = []
    specials: list[np.ndarray] = []
    remaining = n_draws
    while remaining > 0:
        c = min(chunk_size, remaining)
        u = rng.random((c, N))
        perm = np.argsort(u, axis=1, kind="stable")[:, : k + 1] + 1
        main = np.sort(perm[:, :k], axis=1)
        special = perm[:, k]
        mains.append(main)
        specials.append(special)
        remaining -= c

    if not mains:
        return np.empty((0, k), dtype=np.int16), np.empty((0,), dtype=np.int16)
    return (
        np.concatenate(mains, axis=0).astype(np.int16),
        np.concatenate(specials, axis=0).astype(np.int16),
    )
