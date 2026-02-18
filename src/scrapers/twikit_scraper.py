"""Twitter scraper using twikit (Twitter's internal API).

Logs in with your actual Twitter credentials, saves session cookies
for reuse. No paid API key needed. This is what your browser does
when you scroll Twitter - we just do it programmatically.

Flow:
  1. First run: `termfeed login` - enter your creds, saves cookies
  2. Every run after: loads cookies automatically, no re-login needed
  3. Cookies expire eventually → re-run `termfeed login`
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import Tweet

logger = logging.getLogger(__name__)

COOKIES_FILE = Path("data/.twitter_cookies.json")


class TwikitScraper:
    """Scrapes Twitter via twikit (internal API, your login)."""

    def __init__(self, cookies_file: str | None = None):
        self.cookies_file = str(cookies_file or COOKIES_FILE)
        self._client = None
        self._user_id_cache: dict[str, str] = {}
        self._logged_in = False

    async def _ensure_client(self):
        """Lazy-init the twikit client."""
        if self._client is not None:
            return

        try:
            from twikit import Client
        except ImportError:
            raise ImportError(
                "twikit is required: pip install twikit\n"
                "Then run: termfeed login"
            )

        self._client = Client("en-US")

        # Try loading saved cookies
        cookies_path = Path(self.cookies_file)
        if cookies_path.exists():
            try:
                self._client.load_cookies(self.cookies_file)
                self._logged_in = True
                logger.info("Loaded saved Twitter session")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")
                self._logged_in = False

    async def login(
        self,
        username: str,
        email: str | None = None,
        password: str = "",
    ) -> bool:
        """Log into Twitter and save session cookies.

        Args:
            username: Your Twitter handle or phone number.
            email: Your email (helps avoid verification prompts).
            password: Your password.

        Returns:
            True if login succeeded.
        """
        await self._ensure_client()

        # Ensure parent dir exists
        Path(self.cookies_file).parent.mkdir(parents=True, exist_ok=True)

        try:
            await self._client.login(
                auth_info_1=username,
                auth_info_2=email,
                password=password,
                cookies_file=self.cookies_file,
            )
            self._logged_in = True
            logger.info("Twitter login successful, cookies saved")
            return True
        except Exception as e:
            logger.error(f"Twitter login failed: {e}")
            return False

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    async def _get_user_id(self, handle: str) -> str | None:
        """Look up a user's internal ID from their handle."""
        handle = handle.lower().lstrip("@")

        if handle in self._user_id_cache:
            return self._user_id_cache[handle]

        try:
            user = await self._client.get_user_by_screen_name(handle)
            self._user_id_cache[handle] = user.id
            return user.id
        except Exception as e:
            logger.warning(f"Failed to look up @{handle}: {e}")
            return None

    async def _fetch_user_tweets_async(
        self,
        handle: str,
        display_name: str = "",
        count: int = 20,
    ) -> list[Tweet]:
        """Fetch recent tweets for a single user (async)."""
        await self._ensure_client()

        if not self._logged_in:
            logger.warning("Not logged in. Run 'termfeed login' first.")
            return []

        handle = handle.lower().lstrip("@")
        display_name = display_name or handle

        user_id = await self._get_user_id(handle)
        if not user_id:
            return []

        try:
            # twikit max is 40 per request
            raw_tweets = await self._client.get_user_tweets(
                user_id, "Tweets", count=min(count, 40)
            )
        except Exception as e:
            logger.warning(f"Failed to fetch tweets for @{handle}: {e}")
            # Could be expired session
            if "401" in str(e) or "403" in str(e) or "unauthorized" in str(e).lower():
                self._logged_in = False
                logger.error("Session expired. Run 'termfeed login' to re-authenticate.")
            return []

        tweets = []
        for t in raw_tweets:
            try:
                text = t.text or ""
                tweet_id = t.id or ""

                # Parse timestamp
                if hasattr(t, "created_at") and t.created_at:
                    try:
                        timestamp = datetime.strptime(
                            t.created_at, "%a %b %d %H:%M:%S %z %Y"
                        )
                    except (ValueError, TypeError):
                        timestamp = datetime.now(timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)

                # Check if retweet
                is_rt = text.startswith("RT @")

                # Media
                media_urls = []
                if hasattr(t, "media") and t.media:
                    for m in t.media:
                        if hasattr(m, "media_url_https"):
                            media_urls.append(m.media_url_https)

                tweets.append(Tweet(
                    id=str(tweet_id),
                    handle=handle,
                    display_name=display_name,
                    text=text,
                    timestamp=timestamp,
                    url=f"https://x.com/{handle}/status/{tweet_id}",
                    retweet=is_rt,
                    media_urls=media_urls,
                ))
            except Exception as e:
                logger.debug(f"Failed to parse tweet from @{handle}: {e}")
                continue

        logger.info(f"Fetched {len(tweets)} tweets from @{handle}")
        return tweets

    def fetch_user_tweets(
        self,
        handle: str,
        display_name: str = "",
        count: int = 20,
    ) -> list[Tweet]:
        """Fetch recent tweets for a single user (sync wrapper)."""
        loop = _get_or_create_event_loop()
        return loop.run_until_complete(
            self._fetch_user_tweets_async(handle, display_name, count)
        )

    def fetch_all(self, accounts: list[dict[str, str]]) -> list[Tweet]:
        """Fetch tweets from multiple accounts.

        Args:
            accounts: List of dicts with 'handle' and optional 'label' keys.
        """
        loop = _get_or_create_event_loop()
        return loop.run_until_complete(self._fetch_all_async(accounts))

    async def _fetch_all_async(self, accounts: list[dict[str, str]]) -> list[Tweet]:
        """Fetch tweets from multiple accounts (async)."""
        await self._ensure_client()

        if not self._logged_in:
            logger.warning("Not logged in. Run 'termfeed login' first.")
            return []

        all_tweets: list[Tweet] = []
        for account in accounts:
            handle = account["handle"]
            label = account.get("label", handle)
            tweets = await self._fetch_user_tweets_async(handle, label)
            all_tweets.extend(tweets)

        all_tweets.sort(key=lambda t: t.timestamp, reverse=True)
        return all_tweets

    def close(self):
        """Nothing to clean up for twikit."""
        pass


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get the running event loop or create a new one."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop
