from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tweet:
    """A single tweet/post scraped from Twitter/X."""

    id: str
    handle: str
    display_name: str
    text: str
    timestamp: datetime
    url: str
    category: str = ""  # "finance", "tech", or ""
    retweet: bool = False
    media_urls: list[str] = field(default_factory=list)

    @property
    def age_str(self) -> str:
        """Human-readable age string like '2m', '1h', '3d'."""
        delta = datetime.utcnow() - self.timestamp
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
