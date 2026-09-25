"""M5 EXP-001 chart rendering (`docs/experiments/EXP-001.md` r2 section 7): reliability_validation.png
plots the reliability.csv table for the validation period, one line per configuration."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_all(result, out_dir: Path) -> list[Path]:
    rel = result.reliability
    val = rel[rel["period"] == "validation"]
    paths: list[Path] = []
    if not val.empty:
        fig, ax = plt.subplots(figsize=(6, 6))
        for cfg, sub in val.groupby("config"):
            sub = sub.sort_values("p_mean")
            ax.plot(sub["p_mean"], sub["y_mean"], marker="o", label=cfg)
        lims = [0, max(1e-6, val["p_mean"].max(), val["y_mean"].max()) * 1.1]
        ax.plot(lims, lims, linestyle="--", color="grey", label="perfect calibration")
        ax.set_xlabel("mean predicted p")
        ax.set_ylabel("mean observed y")
        ax.set_title("Reliability - validation period (00981-01190)")
        ax.legend(fontsize="small")
        fig.tight_layout()
        path = out_dir / "reliability_validation.png"
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)
    return paths
