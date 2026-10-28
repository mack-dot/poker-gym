"""Regenerate pokergym/data/preflop_equity.json.

    python scripts/gen_preflop_equity.py --samples 50000 --seed 2026 --workers 8

Monte Carlo equity of each of the 169 hand classes against 1..7 random
hands, plus heads-up equity against top-X% ranges. Deterministic for a given
(samples, seed). About 4 minutes on 8 cores.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokergym.equity import _DATA_PATH, generate_table  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", default=_DATA_PATH)
    a = ap.parse_args()
    t0 = time.perf_counter()
    d = generate_table(a.samples, a.seed, a.workers)
    d["command"] = " ".join(sys.argv)
    d["wall_s"] = round(time.perf_counter() - t0, 1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(d, f, separators=(",", ":"))
    print(f"wrote {a.out} in {d['wall_s']} s")


if __name__ == "__main__":
    main()
