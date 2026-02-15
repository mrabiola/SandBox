"""Browser-based Twitter scraper using httpx session cookies.

This scraper optionally logs into Twitter/X using basic credentials
to pull home timeline data. It's rate-limited to a configurable number
of logins per day to avoid detection.

NOTE: This is a secondary data source. The primary source is Nitter RSS
which requires no authentication.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .models import Tweet

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".termfeed" / "browser_state.json"


class BrowserScraper:
    """Scrapes Twitter via authenticated session (optional, rate-limited)."""

    def __init__(
        self,
        max_logins_per_day: int = 3,
        cookie_file: str | None = None,
    ):
        self.max_logins_per_day = max_logins_per_day
        self.cookie_file = cookie_file
        self._login_count = 0
        self._last_reset = datetime.utcnow().date()
        self._load_state()

    def _load_state(self):
        """Load login count state from disk."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                last_date = datetime.fromisoformat(data.get("last_reset", "")).date()
                if last_date == datetime.utcnow().date():
                    self._login_count = data.get("login_count", 0)
                else:
                    self._login_count = 0
            except (json.JSONDecodeError, ValueError):
                self._login_count = 0

    def _save_state(self):
        """Persist login count state to disk."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(
                {
                    "login_count": self._login_count,
                    "last_reset": datetime.utcnow().date().isoformat(),
                }
            )
        )

    @property
    def can_login(self) -> bool:
        """Check if we're under the daily login limit."""
        today = datetime.utcnow().date()
        if today != self._last_reset:
            self._login_count = 0
            self._last_reset = today
        return self._login_count < self.max_logins_per_day

    @property
    def logins_remaining(self) -> int:
        today = datetime.utcnow().date()
        if today != self._last_reset:
            return self.max_logins_per_day
        return max(0, self.max_logins_per_day - self._login_count)

    def fetch_with_cookies(self, cookie_str: str) -> list[Tweet]:
        """Fetch home timeline using pre-existing browser cookies.

        This is the safest approach: export your cookies from your browser
        using a cookie export extension, then paste them here.
        No actual login request is made.

        Args:
            cookie_str: Cookie header string from your browser session.

        Returns:
            List of tweets from the home timeline.
        """
        if not cookie_str:
            logger.warning("No cookies provided for browser scraper")
            return []

        self._login_count += 1
        self._save_state()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Cookie": cookie_str,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            client = httpx.Client(
                headers=headers,
                follow_redirects=True,
                timeout=20.0,
            )
            # Attempt to get the home timeline page
            resp = client.get("https://x.com/home")

            if resp.status_code != 200:
                logger.warning(
                    f"Twitter home fetch failed: {resp.status_code}"
                )
                return []

            # Parse whatever we can from the response
            # Twitter's modern pages are heavily JS-rendered, so this
            # will mainly work with the initial server-rendered content
            return self._parse_timeline_html(resp.text)

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.warning(f"Browser scrape failed: {e}")
            return []

    def _parse_timeline_html(self, html: str) -> list[Tweet]:
        """Best-effort parse of Twitter timeline HTML.

        Modern Twitter is a React SPA, so server-rendered content is limited.
        This extracts what it can from the initial HTML payload.
        """
        tweets: list[Tweet] = []
        soup = BeautifulSoup(html, "html.parser")

        # Look for tweet-like content in script tags (JSON payloads)
        for script in soup.find_all("script"):
            text = script.string or ""
            if '"full_text"' not in text and '"text"' not in text:
                continue

            # Try to extract JSON data
            try:
                # Twitter embeds data in various script formats
                json_match = re.search(r'\{.*"full_text".*\}', text)
                if json_match:
                    data = json.loads(json_match.group())
                    # Try to extract tweets from the data structure
                    tweets.extend(self._extract_tweets_from_json(data))
            except (json.JSONDecodeError, KeyError):
                continue

        logger.info(f"Browser scraper extracted {len(tweets)} tweets")
        return tweets

    def _extract_tweets_from_json(self, data: dict) -> list[Tweet]:
        """Extract tweets from Twitter's JSON data payloads."""
        tweets = []

        def _walk(obj):
            if isinstance(obj, dict):
                if "full_text" in obj or "text" in obj:
                    try:
                        text = obj.get("full_text", obj.get("text", ""))
                        user = obj.get("user", obj.get("core", {}))
                        handle = ""
                        display = ""
                        if isinstance(user, dict):
                            handle = user.get(
                                "screen_name",
                                user.get("username", ""),
                            )
                            display = user.get("name", handle)

                        if text and handle:
                            tweet = Tweet(
                                id=str(obj.get("id_str", obj.get("id", ""))),
                                handle=handle,
                                display_name=display or handle,
                                text=text,
                                timestamp=datetime.utcnow(),
                                url=f"https://x.com/{handle}",
                            )
                            tweets.append(tweet)
                    except (KeyError, TypeError):
                        pass

                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(data)
        return tweets
