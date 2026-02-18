"""Twitter API v2 scraper.

Uses your Twitter API bearer token to pull user timelines directly.
No browser automation, no Nitter middleman. Clean REST calls.

Rate limit aware - backs off when hitting limits and tracks monthly
tweet consumption to avoid burning through your quota.

Tiers:
  Free:  ~1,500 reads/month (barely usable)
  Basic: 10,000 reads/month ($100/mo) - workable for ~10 accounts
  Pro:   1M reads/month ($5,000/mo) - overkill for private use
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .models import Tweet

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/.twitter_api_state.json")
BASE_URL = "https://api.x.com/2"


class TwitterAPI:
    """Twitter API v2 client for pulling user timelines."""

    def __init__(self, bearer_token: str, monthly_limit: int = 10_000):
        self.bearer_token = bearer_token
        self.monthly_limit = monthly_limit
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "User-Agent": "TerminalFeed/0.1",
            },
            timeout=15.0,
        )
        # Track usage
        self._state = self._load_state()
        # Cache user ID lookups (handle -> id)
        self._user_id_cache: dict[str, str] = self._state.get("user_ids", {})

    # ── State management ─────────────────────────

    def _load_state(self) -> dict:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                # Reset monthly count if new month
                saved_month = state.get("month", "")
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                if saved_month != current_month:
                    state["tweets_read"] = 0
                    state["month"] = current_month
                return state
            except (json.JSONDecodeError, KeyError):
                pass
        return {
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "tweets_read": 0,
            "user_ids": {},
        }

    def _save_state(self):
        self._state["user_ids"] = self._user_id_cache
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self._state, indent=2))

    @property
    def tweets_remaining(self) -> int:
        return max(0, self.monthly_limit - self._state.get("tweets_read", 0))

    @property
    def is_quota_exhausted(self) -> bool:
        return self.tweets_remaining <= 0

    # ── API calls ────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response | None:
        """Make an API request with rate limit handling."""
        try:
            resp = self._client.request(method, path, **kwargs)

            if resp.status_code == 429:
                # Rate limited - check reset time
                reset = resp.headers.get("x-rate-limit-reset")
                if reset:
                    wait_seconds = int(reset) - int(time.time())
                    if 0 < wait_seconds <= 900:  # wait up to 15 min
                        logger.info(f"Rate limited, waiting {wait_seconds}s")
                        time.sleep(wait_seconds + 1)
                        return self._request(method, path, **kwargs)
                logger.warning("Rate limited, no reset header")
                return None

            if resp.status_code == 401:
                logger.error("Twitter API auth failed - check your bearer token")
                return None

            if resp.status_code == 403:
                logger.error("Twitter API forbidden - your tier may not support this endpoint")
                return None

            if resp.status_code != 200:
                logger.warning(f"Twitter API {resp.status_code}: {resp.text[:200]}")
                return None

            return resp

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.warning(f"Twitter API request failed: {e}")
            return None

    def _get_user_id(self, handle: str) -> str | None:
        """Look up a user's numeric ID from their handle."""
        handle = handle.lower().lstrip("@")

        if handle in self._user_id_cache:
            return self._user_id_cache[handle]

        resp = self._request("GET", f"/users/by/username/{handle}")
        if not resp:
            return None

        data = resp.json().get("data", {})
        user_id = data.get("id")
        if user_id:
            self._user_id_cache[handle] = user_id
            self._save_state()
        return user_id

    def fetch_user_tweets(
        self,
        handle: str,
        display_name: str = "",
        max_results: int = 10,
    ) -> list[Tweet]:
        """Fetch recent tweets for a single user.

        Args:
            handle: Twitter handle (no @).
            display_name: Label to show in the feed.
            max_results: Number of tweets to fetch (5-100).
        """
        if self.is_quota_exhausted:
            logger.warning(f"Monthly tweet quota exhausted ({self.monthly_limit})")
            return []

        handle = handle.lower().lstrip("@")
        display_name = display_name or handle

        user_id = self._get_user_id(handle)
        if not user_id:
            return []

        # Clamp to remaining quota
        max_results = min(max_results, self.tweets_remaining, 100)
        max_results = max(max_results, 5)

        resp = self._request(
            "GET",
            f"/users/{user_id}/tweets",
            params={
                "max_results": max_results,
                "exclude": "replies",
                "tweet.fields": "created_at,public_metrics,referenced_tweets",
                "expansions": "author_id",
                "user.fields": "name,username",
            },
        )

        if not resp:
            return []

        body = resp.json()
        raw_tweets = body.get("data", [])

        # Track consumption
        self._state["tweets_read"] = self._state.get("tweets_read", 0) + len(raw_tweets)
        self._save_state()

        tweets = []
        for t in raw_tweets:
            text = t.get("text", "")
            tweet_id = t.get("id", "")
            created_at = t.get("created_at", "")

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)

            # Check if retweet
            is_rt = False
            refs = t.get("referenced_tweets", [])
            if refs:
                is_rt = any(r.get("type") == "retweeted" for r in refs)

            # Metrics
            metrics = t.get("public_metrics", {})

            tweets.append(Tweet(
                id=tweet_id,
                handle=handle,
                display_name=display_name,
                text=text,
                timestamp=timestamp,
                url=f"https://x.com/{handle}/status/{tweet_id}",
                retweet=is_rt,
            ))

        logger.info(
            f"Fetched {len(tweets)} tweets from @{handle} "
            f"({self.tweets_remaining} remaining this month)"
        )
        return tweets

    def fetch_all(self, accounts: list[dict[str, str]]) -> list[Tweet]:
        """Fetch tweets from multiple accounts.

        Args:
            accounts: List of dicts with 'handle' and optional 'label' keys.
        """
        all_tweets: list[Tweet] = []
        for account in accounts:
            if self.is_quota_exhausted:
                logger.warning("Monthly quota exhausted, stopping fetch")
                break
            handle = account["handle"]
            label = account.get("label", handle)
            tweets = self.fetch_user_tweets(handle, label)
            all_tweets.extend(tweets)

        all_tweets.sort(key=lambda t: t.timestamp, reverse=True)
        return all_tweets

    def close(self):
        self._client.close()

    def status(self) -> dict:
        """Return current API usage status."""
        return {
            "month": self._state.get("month", ""),
            "tweets_read": self._state.get("tweets_read", 0),
            "monthly_limit": self.monthly_limit,
            "remaining": self.tweets_remaining,
            "cached_users": len(self._user_id_cache),
        }
