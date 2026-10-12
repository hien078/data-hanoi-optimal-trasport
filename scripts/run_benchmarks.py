#!/usr/bin/env python3
"""Run OT benchmarks against pipeline CSV outputs."""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from hanoi_ot.benchmarks import exact_lp, pot_sinkhorn, result_dict, sinkhorn


def _numeric_mass(frame: pd.DataFrame, preferred: tuple[str, ...]) -> np.ndarray:
    for name in preferred:
        if name in frame:
            return pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
    numeric = frame.select_dtypes(include="number")
    if numeric.empty:
        raise ValueError(f"no numeric mass column; expected one of {preferred}")
    return numeric.iloc[:, -1].to_numpy(float)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("population_csv", nargs="?", default="data/processed/case1/population.csv")
    parser.add_argument("facilities_csv", nargs="?", default="data/processed/case1/facilities.csv")
    parser.add_argument("distance_csv", nargs="?", default="data/processed/case1/distance_matrix.csv")
    parser.add_argument("--synthetic-uniform-capacity", action="store_true")
    parser.add_argument("--regularization", type=float, default=0.05)
    parser.add_argument("--methods", nargs="+", choices=("lp", "sinkhorn", "pot"), default=("lp", "sinkhorn"))
    args = parser.parse_args()

    population = pd.read_csv(args.population_csv)
    facilities = pd.read_csv(args.facilities_csv)
    distance = pd.read_csv(args.distance_csv, index_col=0).apply(pd.to_numeric, errors="coerce").to_numpy(float)
    a = _numeric_mass(population, ("population", "children_under_5", "mass", "demand"))
    capacity = pd.to_numeric(facilities.get("capacity"), errors="coerce").to_numpy(float) if "capacity" in facilities else None
    valid = capacity is not None and capacity.size and np.isfinite(capacity).all() and (capacity >= 0).all() and capacity.sum() > 0
    if not valid:
        if not args.synthetic_uniform_capacity:
            parser.error("facility capacity missing/invalid; pass --synthetic-uniform-capacity explicitly")
        capacity = np.ones(len(facilities))
    solvers = {"lp": exact_lp, "sinkhorn": lambda x, y, c: sinkhorn(x, y, c, regularization=args.regularization),
               "pot": lambda x, y, c: pot_sinkhorn(x, y, c, regularization=args.regularization)}
    for method in args.methods:
        try:
            result, _ = solvers[method](a, capacity, distance)
            print(json.dumps(result_dict(result), allow_nan=False))
        except ImportError as exc:
            print(json.dumps({"method": method, "status": f"unavailable: {exc}"}))


if __name__ == "__main__":
    main()
