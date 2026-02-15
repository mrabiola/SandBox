"""Nitter RSS feed scraper.

Nitter is a free, open-source alternative Twitter frontend that exposes
RSS feeds for any public account. This module fetches tweets via Nitter
RSS without needing any Twitter API keys or credentials.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from html import unescape

import feedparser
import httpx
from bs4 import BeautifulSoup

from .models import Tweet

logger = logging.getLogger(__name__)


class NitterScraper:
    """Scrapes tweets from Nitter RSS feeds."""

    def __init__(self, instances: list[str], timeout: float = 15.0):
        self.instances = instances
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "TerminalFeed/0.1"},
        )
        # Cache which instance is currently working
        self._active_instance: str | None = None

    def _find_working_instance(self) -> str | None:
        """Try each Nitter instance and return the first one that responds."""
        for instance in self.instances:
            try:
                resp = self._client.get(instance, timeout=5.0)
                if resp.status_code < 500:
                    self._active_instance = instance
                    logger.info(f"Using Nitter instance: {instance}")
                    return instance
            except (httpx.RequestError, httpx.TimeoutException):
                logger.debug(f"Nitter instance unreachable: {instance}")
                continue
        logger.warning("No working Nitter instances found")
        return None

    def _get_instance(self) -> str | None:
        """Get the current working instance, or find a new one."""
        if self._active_instance:
            return self._active_instance
        return self._find_working_instance()

    def _parse_entry(self, entry: dict, handle: str, display_name: str) -> Tweet | None:
        """Parse a single RSS feed entry into a Tweet."""
        try:
            # Extract text content - strip HTML tags
            raw_html = entry.get("summary", entry.get("title", ""))
            soup = BeautifulSoup(raw_html, "html.parser")
            text = unescape(soup.get_text(separator=" ").strip())

            # Clean up whitespace
            text = re.sub(r"\s+", " ", text).strip()

            if not text:
                return None

            # Parse timestamp
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                timestamp = datetime(*published[:6])
            else:
                timestamp = datetime.utcnow()

            # Extract link
            url = entry.get("link", "")

            # Generate stable ID from URL or content hash
            tweet_id = hashlib.md5(
                (url or f"{handle}:{text[:100]}").encode()
            ).hexdigest()[:16]

            # Check if retweet
            is_rt = text.startswith("RT ") or text.startswith("RT @")

            # Extract media URLs from content
            media_urls = []
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if src and "emoji" not in src:
                    media_urls.append(src)

            return Tweet(
                id=tweet_id,
                handle=handle,
                display_name=display_name,
                text=text,
                timestamp=timestamp,
                url=url,
                retweet=is_rt,
                media_urls=media_urls,
            )
        except Exception as e:
            logger.debug(f"Failed to parse entry for @{handle}: {e}")
            return None

    def fetch_user_tweets(self, handle: str, display_name: str = "") -> list[Tweet]:
        """Fetch recent tweets for a single user via Nitter RSS."""
        instance = self._get_instance()
        if not instance:
            return []

        display_name = display_name or handle
        rss_url = f"{instance}/{handle}/rss"

        try:
            resp = self._client.get(rss_url)
            if resp.status_code != 200:
                # Instance might be down, try finding a new one
                logger.debug(f"RSS fetch failed ({resp.status_code}): {rss_url}")
                self._active_instance = None
                instance = self._find_working_instance()
                if not instance:
                    return []
                rss_url = f"{instance}/{handle}/rss"
                resp = self._client.get(rss_url)
                if resp.status_code != 200:
                    return []

            feed = feedparser.parse(resp.text)
            tweets = []
            for entry in feed.entries:
                tweet = self._parse_entry(entry, handle, display_name)
                if tweet:
                    tweets.append(tweet)

            logger.info(f"Fetched {len(tweets)} tweets from @{handle}")
            return tweets

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.debug(f"Request failed for @{handle}: {e}")
            self._active_instance = None
            return []

    def fetch_all(
        self, accounts: list[dict[str, str]], category: str = ""
    ) -> list[Tweet]:
        """Fetch tweets from multiple accounts.

        Args:
            accounts: List of dicts with 'handle' and optional 'label' keys.
            category: Category to assign to all fetched tweets.
        """
        all_tweets: list[Tweet] = []
        for account in accounts:
            handle = account["handle"]
            label = account.get("label", handle)
            tweets = self.fetch_user_tweets(handle, label)
            for tweet in tweets:
                tweet.category = category
            all_tweets.extend(tweets)

        # Sort by timestamp, newest first
        all_tweets.sort(key=lambda t: t.timestamp, reverse=True)
        return all_tweets

    def close(self):
        self._client.close()
