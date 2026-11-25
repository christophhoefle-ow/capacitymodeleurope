"""Gemeinsame Hilfen für alle Skripte: Pfade, Konfiguration, Logging."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "config.yml").read_text(encoding="utf-8"))


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


def path(cfg: dict, key: str) -> Path:
    return ROOT / cfg["paths"][key]
