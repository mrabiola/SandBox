"""Bloomberg-style terminal feed UI.

Renders a live-updating, color-coded news ticker in the terminal
using the Rich library. Finance tweets are blue, tech tweets are green,
high-score items are highlighted.
"""

from __future__ import annotations

import sys
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.filters.content_filter import ScoredTweet

# Color scheme (Bloomberg-inspired)
COLORS = {
    "finance": "bright_blue",
    "tech": "bright_green",
    "unknown": "white",
    "breaking": "bold bright_red",
    "header_bg": "on grey11",
    "ticker": "bold bright_yellow",
    "timestamp": "dim",
    "handle": "bold cyan",
    "score_high": "bold bright_yellow",
    "score_med": "bright_white",
    "score_low": "dim",
    "border": "bright_blue",
}

CATEGORY_LABELS = {
    "finance": "[FIN]",
    "tech": "[TECH]",
}


class TerminalFeed:
    """Renders the Bloomberg-style terminal feed."""

    def __init__(self, title: str = "TERMINAL FEED"):
        self.console = Console()
        self.title = title

    def _format_tweet_row(self, scored: ScoredTweet) -> tuple[Text, Text, Text, Text, Text]:
        """Format a single scored tweet as table columns."""
        tweet = scored.tweet
        score = scored.score

        # Timestamp
        ts = Text(tweet.age_str, style=COLORS["timestamp"])

        # Category tag
        cat_label = CATEGORY_LABELS.get(tweet.category, "[---]")
        cat_color = COLORS.get(tweet.category, COLORS["unknown"])
        cat = Text(cat_label, style=cat_color)

        # Handle
        handle = Text(f"@{tweet.handle}", style=COLORS["handle"])

        # Score indicator
        if score >= 5.0:
            score_style = COLORS["score_high"]
            score_icon = ">>>"
        elif score >= 2.0:
            score_style = COLORS["score_med"]
            score_icon = ">>"
        else:
            score_style = COLORS["score_low"]
            score_icon = ">"
        score_text = Text(score_icon, style=score_style)

        # Tweet text - highlight tickers and breaking keywords
        text = tweet.text
        if len(text) > 200:
            text = text[:197] + "..."

        styled_text = Text(text)

        # Highlight $TICKER patterns
        import re

        for match in re.finditer(r"\$[A-Z]{1,5}\b", text):
            styled_text.stylize(COLORS["ticker"], match.start(), match.end())

        # Highlight BREAKING patterns
        for match in re.finditer(
            r"\b(BREAKING|JUST IN|ALERT|URGENT)\b", text, re.IGNORECASE
        ):
            styled_text.stylize(COLORS["breaking"], match.start(), match.end())

        return ts, cat, handle, score_text, styled_text

    def build_feed_table(self, scored_tweets: list[ScoredTweet]) -> Table:
        """Build the main feed table."""
        table = Table(
            show_header=True,
            header_style="bold bright_white on grey11",
            border_style=COLORS["border"],
            expand=True,
            padding=(0, 1),
            show_lines=False,
        )

        table.add_column("AGE", width=4, no_wrap=True)
        table.add_column("CAT", width=6, no_wrap=True)
        table.add_column("SOURCE", width=18, no_wrap=True)
        table.add_column("SIG", width=3, no_wrap=True)
        table.add_column("CONTENT", ratio=1)

        for scored in scored_tweets:
            ts, cat, handle, score_text, text = self._format_tweet_row(scored)
            table.add_row(ts, cat, handle, score_text, text)

        return table

    def build_header(self, stats: dict) -> Panel:
        """Build the top header bar with stats."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        header_text = Text()
        header_text.append(f" {self.title} ", style="bold bright_white on blue")
        header_text.append("  ")
        header_text.append(now, style="bright_white")
        header_text.append("  |  ")
        header_text.append(f"FIN: {stats.get('finance', 0)}", style=COLORS["finance"])
        header_text.append("  ")
        header_text.append(f"TECH: {stats.get('tech', 0)}", style=COLORS["tech"])
        header_text.append("  ")
        header_text.append(f"TOTAL: {stats.get('total', 0)}", style="bright_white")
        header_text.append("  |  ")
        header_text.append(
            f"FILTERED: {stats.get('filtered', 0)} noise removed", style="dim"
        )

        return Panel(
            header_text,
            border_style=COLORS["border"],
            padding=(0, 0),
        )

    def build_status_bar(self, message: str = "") -> Panel:
        """Build the bottom status bar."""
        status = Text()
        status.append(" [q] Quit  ", style="dim")
        status.append("[r] Refresh  ", style="dim")
        status.append("[f] Finance only  ", style="dim")
        status.append("[t] Tech only  ", style="dim")
        status.append("[a] All  ", style="dim")
        if message:
            status.append(f"  |  {message}", style="bright_yellow")

        return Panel(status, border_style="grey30", padding=(0, 0))

    def render_static(
        self,
        scored_tweets: list[ScoredTweet],
        total_before_filter: int = 0,
        category_filter: str | None = None,
    ) -> None:
        """Render the feed once (non-live mode) to the terminal."""
        # Apply category filter if set
        if category_filter:
            display_tweets = [
                s for s in scored_tweets if s.tweet.category == category_filter
            ]
        else:
            display_tweets = scored_tweets

        # Compute stats
        stats = {
            "finance": sum(1 for s in scored_tweets if s.tweet.category == "finance"),
            "tech": sum(1 for s in scored_tweets if s.tweet.category == "tech"),
            "total": len(scored_tweets),
            "filtered": max(0, total_before_filter - len(scored_tweets)),
        }

        # Render
        self.console.clear()
        self.console.print(self.build_header(stats))
        self.console.print(self.build_feed_table(display_tweets))
        self.console.print(self.build_status_bar())

    def create_live_display(self) -> Live:
        """Create a Rich Live display for auto-refreshing."""
        return Live(
            console=self.console,
            refresh_per_second=1,
            screen=True,
        )

    def build_full_layout(
        self,
        scored_tweets: list[ScoredTweet],
        total_before_filter: int = 0,
        category_filter: str | None = None,
        status_message: str = "",
    ) -> Layout:
        """Build the full terminal layout for live mode."""
        if category_filter:
            display_tweets = [
                s for s in scored_tweets if s.tweet.category == category_filter
            ]
        else:
            display_tweets = scored_tweets

        stats = {
            "finance": sum(1 for s in scored_tweets if s.tweet.category == "finance"),
            "tech": sum(1 for s in scored_tweets if s.tweet.category == "tech"),
            "total": len(scored_tweets),
            "filtered": max(0, total_before_filter - len(scored_tweets)),
        }

        layout = Layout()
        layout.split_column(
            Layout(self.build_header(stats), size=3),
            Layout(self.build_feed_table(display_tweets)),
            Layout(self.build_status_bar(status_message), size=3),
        )
        return layout
