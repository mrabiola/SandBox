"""Configuration loader for Terminal Feed."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class FeedConfig:
    """Parsed feed configuration."""

    nitter_instances: list[str] = field(default_factory=list)
    refresh_interval: int = 120
    max_feed_items: int = 200
    min_score: float = 1.0
    finance_keywords: list[str] = field(default_factory=list)
    tech_keywords: list[str] = field(default_factory=list)
    noise_keywords: list[str] = field(default_factory=list)
    discovery: dict | None = None


def load_config(config_path: str | Path = "config/feeds.yaml") -> FeedConfig:
    """Load and parse the YAML config file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config/feeds.yaml.example to config/feeds.yaml and edit it."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    return FeedConfig(
        nitter_instances=raw.get("nitter_instances", []),
        refresh_interval=raw.get("refresh_interval", 120),
        max_feed_items=raw.get("max_feed_items", 200),
        min_score=raw.get("min_score", 1.0),
        finance_keywords=raw.get("finance_keywords", []),
        tech_keywords=raw.get("tech_keywords", []),
        noise_keywords=raw.get("noise_keywords", []),
        discovery=raw.get("discovery"),
    )
