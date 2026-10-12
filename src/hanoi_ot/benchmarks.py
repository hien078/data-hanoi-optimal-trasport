"""Small, dependency-light optimal transport benchmark solvers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

import numpy as np


@dataclass(frozen=True)
class BenchmarkResult:
    method: str
    status: str
    objective: float
    runtime: float
    iterations: int
    error: float


def _inputs(a: Any, b: Any, cost: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    cost = np.asarray(cost, dtype=float)
    if a.size == 0 or b.size == 0 or cost.shape != (a.size, b.size):
        raise ValueError("cost shape must match non-empty mass vectors")
    if not (np.isfinite(a).all() and np.isfinite(b).all() and np.isfinite(cost).all()):
        raise ValueError("masses and cost must be finite")
    if (a < 0).any() or (b < 0).any() or (cost < 0).any():
        raise ValueError("masses and cost must be nonnegative")
    if a.sum() <= 0 or b.sum() <= 0:
        raise ValueError("each mass vector must have positive total mass")
    return a / a.sum(), b / b.sum(), cost


def exact_lp(a: Any, b: Any, cost: Any) -> tuple[BenchmarkResult, np.ndarray]:
    """Solve balanced OT exactly with SciPy HiGHS."""
    from scipy.optimize import linprog

    a, b, cost = _inputs(a, b, cost)
    n, m = cost.shape
    rows = np.zeros((n + m, n * m))
    for i in range(n):
        rows[i, i * m:(i + 1) * m] = 1
    for j in range(m):
        rows[n + j, j::m] = 1
    started = perf_counter()
    solved = linprog(cost.ravel(), A_eq=rows, b_eq=np.r_[a, b], bounds=(0, None), method="highs")
    runtime = perf_counter() - started
    plan = solved.x.reshape(n, m) if solved.success else np.full((n, m), np.nan)
    error = _marginal_error(plan, a, b) if solved.success else float("inf")
    result = BenchmarkResult("exact_lp", "success" if solved.success else f"failed: {solved.message}",
                             float(solved.fun) if solved.success else float("nan"), runtime,
                             int(getattr(solved, "nit", 0)), error)
    return result, plan


def _marginal_error(plan: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    return float(max(np.max(np.abs(plan.sum(axis=1) - a)), np.max(np.abs(plan.sum(axis=0) - b))))


def sinkhorn(a: Any, b: Any, cost: Any, *, regularization: float = 0.05,
             max_iterations: int = 10_000, tolerance: float = 1e-9) -> tuple[BenchmarkResult, np.ndarray]:
    """Solve entropic OT using stabilized alternating NumPy scalings."""
    a, b, cost = _inputs(a, b, cost)
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError("regularization must be finite and positive")
    if max_iterations < 1 or tolerance <= 0:
        raise ValueError("max_iterations and tolerance must be positive")
    kernel = np.exp(-(cost - cost.min()) / regularization)
    kernel = np.maximum(kernel, np.finfo(float).tiny)
    u, v = np.ones_like(a), np.ones_like(b)
    started = perf_counter()
    error = float("inf")
    for iteration in range(1, max_iterations + 1):
        u = np.divide(a, kernel @ v, out=np.zeros_like(a), where=(kernel @ v) > 0)
        kt_u = kernel.T @ u
        v = np.divide(b, kt_u, out=np.zeros_like(b), where=kt_u > 0)
        if iteration == 1 or iteration % 10 == 0:
            plan = (u[:, None] * kernel) * v[None, :]
            error = _marginal_error(plan, a, b)
            if error <= tolerance:
                break
    plan = (u[:, None] * kernel) * v[None, :]
    error = _marginal_error(plan, a, b)
    runtime = perf_counter() - started
    status = "success" if error <= tolerance else "max_iterations"
    return BenchmarkResult("sinkhorn", status, float(np.sum(plan * cost)), runtime, iteration, error), plan


def pot_sinkhorn(a: Any, b: Any, cost: Any, *, regularization: float = 0.05,
                 max_iterations: int = 10_000, tolerance: float = 1e-9) -> tuple[BenchmarkResult, np.ndarray]:
    """Optional POT adapter; raises ImportError when POT is unavailable."""
    import ot

    a, b, cost = _inputs(a, b, cost)
    started = perf_counter()
    plan, log = ot.sinkhorn(a, b, cost, regularization, numItermax=max_iterations,
                            stopThr=tolerance, log=True)
    runtime = perf_counter() - started
    error = _marginal_error(plan, a, b)
    iterations = int(log.get("niter", len(log.get("err", []))))
    status = "success" if error <= tolerance else "max_iterations"
    return BenchmarkResult("pot_sinkhorn", status, float(np.sum(plan * cost)), runtime, iterations, error), plan


def result_dict(result: BenchmarkResult) -> dict[str, object]:
    return asdict(result)
