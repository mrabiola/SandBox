"""Content filtering engine for tweets.

Automatically categorizes tweets as finance, tech, or noise based on
keyword matching. Filters out lifestyle/personal content so only
high-signal finance and tech tweets surface in the feed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.scrapers.models import Tweet


@dataclass
class ScoredTweet:
    """A tweet with a relevance score."""

    tweet: Tweet
    score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)


class ContentFilter:
    """Filters and scores tweets based on keyword relevance."""

    def __init__(
        self,
        finance_keywords: list[str] | None = None,
        tech_keywords: list[str] | None = None,
        noise_keywords: list[str] | None = None,
    ):
        self.finance_keywords = [k.lower() for k in (finance_keywords or [])]
        self.tech_keywords = [k.lower() for k in (tech_keywords or [])]
        self.noise_keywords = [k.lower() for k in (noise_keywords or [])]

        # High-value patterns that get bonus scoring
        self._ticker_pattern = re.compile(r"\$[A-Z]{1,5}\b")
        self._breaking_pattern = re.compile(
            r"\b(BREAKING|JUST IN|ALERT|URGENT)\b", re.IGNORECASE
        )
        self._numbers_pattern = re.compile(r"\b\d+\.?\d*[%BMK]\b")

    def _keyword_score(self, text: str, keywords: list[str]) -> tuple[float, list[str]]:
        """Score text against a keyword list. Returns (score, matched_keywords)."""
        text_lower = text.lower()
        matched = []
        score = 0.0

        for kw in keywords:
            if kw in text_lower:
                matched.append(kw)
                # Longer keywords are more specific = higher signal
                score += 1.0 + (len(kw) / 20.0)

        return score, matched

    def _noise_score(self, text: str) -> float:
        """Calculate noise penalty. Higher = more noise."""
        text_lower = text.lower()
        penalty = 0.0
        for kw in self.noise_keywords:
            if kw in text_lower:
                penalty += 2.0
        return penalty

    def _bonus_score(self, text: str) -> float:
        """Extra score for high-signal patterns."""
        bonus = 0.0

        # Ticker symbols ($AAPL, $NVDA, etc.)
        tickers = self._ticker_pattern.findall(text)
        bonus += len(tickers) * 2.0

        # Breaking news patterns
        if self._breaking_pattern.search(text):
            bonus += 5.0

        # Numbers with units (likely data/stats)
        numbers = self._numbers_pattern.findall(text)
        bonus += len(numbers) * 1.5

        return bonus

    def score_tweet(self, tweet: Tweet) -> ScoredTweet:
        """Score a single tweet for relevance."""
        text = tweet.text

        # Score against both keyword lists
        fin_score, fin_matched = self._keyword_score(text, self.finance_keywords)
        tech_score, tech_matched = self._keyword_score(text, self.tech_keywords)

        all_matched = fin_matched + tech_matched
        base_score = fin_score + tech_score

        # Auto-categorize based on dominant keyword matches
        if fin_score > tech_score:
            tweet.category = "finance"
        elif tech_score > fin_score:
            tweet.category = "tech"
        elif fin_score > 0:
            tweet.category = "finance"  # tie goes to finance
        elif tech_score > 0:
            tweet.category = "tech"
        # else: no category (noise)

        # Bonus scoring for high-signal patterns
        bonus = self._bonus_score(text)

        # Noise penalty
        noise = self._noise_score(text)

        # Penalize retweets slightly (original content is higher signal)
        rt_penalty = 0.7 if tweet.retweet else 1.0

        total_score = max(0.0, (base_score + bonus - noise) * rt_penalty)

        return ScoredTweet(
            tweet=tweet,
            score=total_score,
            matched_keywords=all_matched,
        )

    def filter_tweets(
        self,
        tweets: list[Tweet],
        min_score: float = 0.0,
        max_items: int = 200,
    ) -> list[ScoredTweet]:
        """Filter and rank tweets by relevance.

        Args:
            tweets: Raw tweets to filter.
            min_score: Minimum score to include (0 = include all).
            max_items: Maximum items to return.

        Returns:
            Scored tweets sorted by timestamp (newest first), filtered by score.
        """
        scored = [self.score_tweet(t) for t in tweets]

        if min_score > 0:
            scored = [s for s in scored if s.score >= min_score]

        # Sort by timestamp (newest first), use score as tiebreaker
        scored.sort(
            key=lambda s: (s.tweet.timestamp, s.score),
            reverse=True,
        )

        return scored[:max_items]
