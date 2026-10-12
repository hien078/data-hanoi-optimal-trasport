"""Configuration loading: YAML config + logging setup.

All file paths come from config/config.yaml (relative to repo root).
No absolute local paths anywhere.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"

_config: dict[str, Any] | None = None


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or malformed."""


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load and cache the YAML configuration.

    Args:
        path: Optional explicit config path; defaults to ``config/config.yaml``
            at the repository root.

    Returns:
        Parsed configuration dictionary.

    Raises:
        ConfigError: If the file is missing or not valid YAML.
    """
    global _config
    if _config is not None and path is None:
        return _config
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(cfg).__name__}: {p}")
    _config = cfg
    return cfg


def data_dir(kind: str) -> Path:
    """Return an absolute data directory (``raw`` | ``interim`` | ``processed``).

    Args:
        kind: Data stage directory name.

    Returns:
        Absolute path to the directory, created if missing.
    """
    cfg = load_config()
    rel = Path(cfg["paths"][kind])
    p = rel if rel.is_absolute() else REPO_ROOT / rel
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_path(key: str) -> Path:
    """Return absolute path for a processed output file (e.g. ``population``).

    Args:
        key: Key under ``paths.outputs`` in config (``boundaries``,
            ``population``, ``facilities``, ``distance_matrix``, ``metadata``).

    Returns:
        Absolute output file path; parent directory created if missing.
    """
    cfg = load_config()
    p = data_dir("processed") / cfg["paths"]["outputs"][key]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the package logger (stderr, concise format).

    Args:
        level: Log level name.

    Returns:
        Configured ``hanoi_ot`` logger.
    """
    logger = logging.getLogger("hanoi_ot")
    if logger.handlers:  # already configured
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the configured ``hanoi_ot`` logger."""
    setup_logging()
    return logging.getLogger(f"hanoi_ot.{name}")
