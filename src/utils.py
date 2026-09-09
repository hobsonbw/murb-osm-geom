"""Small helpers shared across pipeline modules."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml


LOGGER_NAME = "necb_geom"


def project_root() -> Path:
    """Return the repository root (parent of the `src/` directory)."""
    return Path(__file__).resolve().parent.parent


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    """Load the YAML settings file."""
    if path is None:
        path = project_root() / "config" / "settings.yaml"
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_path(rel: str) -> Path:
    """Resolve a path from settings against the project root."""
    p = Path(rel)
    if p.is_absolute():
        return p
    return project_root() / p


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def slugify_city(city: str) -> str:
    """Turn a place name like 'Ottawa, Ontario, Canada' into 'ottawa'.

    Keeps only the first comma-separated segment, lower-cased, with any
    non-alphanumeric character collapsed to underscore. Used to derive a
    default output basename so multi-city runs don't overwrite each other.
    """
    head = city.split(",", 1)[0].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", head).strip("_")
    return slug or "study_area"


def get_logger(name: str = LOGGER_NAME, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger
