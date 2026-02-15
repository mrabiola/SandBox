"""Account discovery engine.

Finds new high-signal accounts the user isn't following yet by:
1. Scraping who the user's existing high-signal accounts mention/interact with
2. Checking those discovered accounts for relevant finance/tech content
3. Scoring and recommending new accounts to follow

This runs passively alongside the main feed - surfacing new accounts
the user might want to add.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .models import Tweet
from .nitter import NitterScraper

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredAccount:
    """A potential new account to follow."""

    handle: str
    display_name: str
    reason: str  # Why we're recommending this account
    mentioned_by: list[str] = field(default_factory=list)
    mention_count: int = 0
    sample_tweets: list[Tweet] = field(default_factory=list)
    relevance_score: float = 0.0


class AccountDiscovery:
    """Discovers new accounts by analyzing interactions of existing follows."""

    # Pattern to find @mentions in tweet text
    _mention_pattern = re.compile(r"@([A-Za-z0-9_]{1,15})")

    def __init__(self, scraper: NitterScraper, known_handles: list[str]):
        self.scraper = scraper
        # Normalize known handles to lowercase for comparison
        self.known_handles = {h.lower() for h in known_handles}

    def _extract_mentions(self, tweets: list[Tweet]) -> Counter:
        """Extract @mentions from tweets, count frequency."""
        mentions: Counter = Counter()
        for tweet in tweets:
            found = self._mention_pattern.findall(tweet.text)
            for handle in found:
                handle_lower = handle.lower()
                # Skip self-mentions and already-known accounts
                if handle_lower not in self.known_handles:
                    mentions[handle_lower] += 1
        return mentions

    def _extract_quoted_accounts(self, tweets: list[Tweet]) -> Counter:
        """Find accounts that are being quote-tweeted or linked to."""
        quoted: Counter = Counter()
        # Look for x.com/handle or twitter.com/handle patterns in text
        url_pattern = re.compile(
            r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})"
        )
        for tweet in tweets:
            found = url_pattern.findall(tweet.text)
            for handle in found:
                handle_lower = handle.lower()
                if (
                    handle_lower not in self.known_handles
                    and handle_lower not in ("home", "search", "explore", "i", "settings")
                ):
                    quoted[handle_lower] += 1
        return quoted

    def discover_from_mentions(
        self,
        tweets: list[Tweet],
        min_mentions: int = 2,
        max_results: int = 20,
    ) -> list[DiscoveredAccount]:
        """Find frequently mentioned accounts that the user doesn't follow.

        Args:
            tweets: Tweets from the user's existing high-signal accounts.
            min_mentions: Minimum times an account must be mentioned.
            max_results: Maximum accounts to return.

        Returns:
            List of discovered accounts, sorted by mention frequency.
        """
        # Combine @mentions and quoted accounts
        mention_counts = self._extract_mentions(tweets)
        quoted_counts = self._extract_quoted_accounts(tweets)

        # Merge counts
        combined: Counter = Counter()
        combined.update(mention_counts)
        combined.update(quoted_counts)

        # Track who mentioned each discovered account
        mention_sources: dict[str, set[str]] = {}
        for tweet in tweets:
            found_handles = set()
            for m in self._mention_pattern.findall(tweet.text):
                found_handles.add(m.lower())
            for handle in found_handles:
                if handle not in self.known_handles:
                    mention_sources.setdefault(handle, set()).add(tweet.handle)

        # Filter by minimum mentions and build results
        discovered = []
        for handle, count in combined.most_common(max_results * 2):
            if count < min_mentions:
                break

            sources = list(mention_sources.get(handle, []))
            discovered.append(
                DiscoveredAccount(
                    handle=handle,
                    display_name=handle,
                    reason=f"Mentioned {count}x by accounts you follow",
                    mentioned_by=sources,
                    mention_count=count,
                    relevance_score=float(count),
                )
            )

            if len(discovered) >= max_results:
                break

        return discovered

    def validate_discovered(
        self,
        candidates: list[DiscoveredAccount],
        finance_keywords: list[str],
        tech_keywords: list[str],
        max_validate: int = 10,
    ) -> list[DiscoveredAccount]:
        """Validate discovered accounts by checking their actual content.

        Fetches a sample of tweets from each candidate and scores them
        against finance/tech keywords to confirm they're high-signal.

        Args:
            candidates: Discovered accounts to validate.
            finance_keywords: Finance keyword list.
            tech_keywords: Tech keyword list.
            max_validate: Max accounts to validate (each requires an HTTP request).

        Returns:
            Validated and re-scored candidates.
        """
        all_keywords = [k.lower() for k in finance_keywords + tech_keywords]

        validated = []
        for candidate in candidates[:max_validate]:
            tweets = self.scraper.fetch_user_tweets(
                candidate.handle, candidate.display_name
            )
            if not tweets:
                continue

            candidate.sample_tweets = tweets[:5]

            # Score: what % of their tweets match finance/tech keywords
            match_count = 0
            for tweet in tweets:
                text_lower = tweet.text.lower()
                if any(kw in text_lower for kw in all_keywords):
                    match_count += 1

            if tweets:
                relevance_ratio = match_count / len(tweets)
            else:
                relevance_ratio = 0.0

            # Combine mention frequency with content relevance
            candidate.relevance_score = (
                candidate.mention_count * 0.3 + relevance_ratio * 10.0
            )

            if relevance_ratio >= 0.3:  # At least 30% of tweets are relevant
                candidate.reason = (
                    f"Mentioned {candidate.mention_count}x | "
                    f"{int(relevance_ratio * 100)}% finance/tech content"
                )
                validated.append(candidate)

        validated.sort(key=lambda a: a.relevance_score, reverse=True)
        return validated

    def run_discovery(
        self,
        tweets: list[Tweet],
        finance_keywords: list[str],
        tech_keywords: list[str],
        min_mentions: int = 2,
        max_results: int = 10,
    ) -> list[DiscoveredAccount]:
        """Full discovery pipeline: find mentions -> validate content.

        Args:
            tweets: Tweets from the user's existing follows.
            finance_keywords: Finance keyword list for validation.
            tech_keywords: Tech keyword list for validation.
            min_mentions: Minimum mention threshold.
            max_results: Max accounts to return.

        Returns:
            Validated, scored list of recommended accounts.
        """
        logger.info("Running account discovery...")

        # Step 1: Find frequently mentioned unknown accounts
        candidates = self.discover_from_mentions(
            tweets, min_mentions=min_mentions, max_results=max_results * 2
        )
        logger.info(f"Found {len(candidates)} mention-based candidates")

        if not candidates:
            return []

        # Step 2: Validate by checking their actual content
        validated = self.validate_discovered(
            candidates,
            finance_keywords=finance_keywords,
            tech_keywords=tech_keywords,
            max_validate=max_results,
        )
        logger.info(f"Validated {len(validated)} high-signal accounts")

        return validated[:max_results]
