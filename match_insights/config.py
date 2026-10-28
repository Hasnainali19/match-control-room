"""Runtime configuration, read from environment variables (12-factor)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _f(name, default):
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MCR_DATA_DIR", ROOT / "data")))
    log_level: str = field(default_factory=lambda: os.getenv("MCR_LOG_LEVEL", "INFO"))
    log_json: bool = field(default_factory=lambda: os.getenv("MCR_LOG_FORMAT", "json") == "json")
    default_seed: int = field(default_factory=lambda: int(os.getenv("MCR_DEFAULT_SEED", "11")))
    subgroup_s: float = field(default_factory=lambda: _f("MCR_SUBGROUP_SECONDS", 90))
    llm_timeout_s: float = field(default_factory=lambda: _f("MCR_LLM_TIMEOUT", 8))
    max_stream_gap_s: float = field(default_factory=lambda: _f("MCR_MAX_STREAM_GAP", 1.5))
    airtime_gap_s: float = field(default_factory=lambda: _f("MCR_AIRTIME_GAP", 40))


def get_settings() -> Settings:
    return Settings()
