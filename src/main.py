"""Terminal Feed - Bloomberg-style news feed from Twitter/X.

Main entry point. Orchestrates scraping, filtering, and terminal display.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import click

from src.config import load_config
from src.filters.content_filter import ContentFilter
from src.scrapers.nitter import NitterScraper
from src.ui.terminal_feed import TerminalFeed

logger = logging.getLogger("termfeed")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def fetch_and_filter(config, scraper, content_filter):
    """Fetch tweets from all accounts and filter them."""
    # Fetch from all configured accounts (no pre-categorization needed)
    all_tweets = scraper.fetch_all(config.accounts)
    total_raw = len(all_tweets)

    # Filter and score
    scored = content_filter.filter_tweets(
        all_tweets,
        min_score=config.min_score,
        max_items=config.max_feed_items,
    )

    return scored, total_raw


@click.group()
@click.option(
    "--config",
    "-c",
    default="config/feeds.yaml",
    help="Path to config file",
    type=click.Path(),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """Terminal Feed - Bloomberg-style news from Twitter/X."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.option(
    "--filter",
    "-f",
    "category",
    type=click.Choice(["all", "finance", "tech"]),
    default="all",
    help="Show only a specific category",
)
@click.pass_context
def watch(ctx, category):
    """Live-updating feed that auto-refreshes."""
    config = load_config(ctx.obj["config_path"])

    scraper = NitterScraper(instances=config.nitter_instances)
    content_filter = ContentFilter(
        finance_keywords=config.finance_keywords,
        tech_keywords=config.tech_keywords,
        noise_keywords=config.noise_keywords,
    )
    feed_ui = TerminalFeed()

    cat_filter = category if category != "all" else None
    status_msg = "Fetching initial data..."

    try:
        with feed_ui.create_live_display() as live:
            while True:
                try:
                    scored, total_raw = fetch_and_filter(
                        config, scraper, content_filter
                    )
                    status_msg = (
                        f"Last refresh: {time.strftime('%H:%M:%S')} | "
                        f"Next in {config.refresh_interval}s | "
                        f"Press Ctrl+C to quit"
                    )
                except Exception as e:
                    logger.error(f"Fetch error: {e}")
                    status_msg = f"Error: {e}"
                    scored, total_raw = [], 0

                layout = feed_ui.build_full_layout(
                    scored,
                    total_before_filter=total_raw,
                    category_filter=cat_filter,
                    status_message=status_msg,
                )
                live.update(layout)

                # Wait for refresh interval, checking every second
                for _ in range(config.refresh_interval):
                    time.sleep(1)

    except KeyboardInterrupt:
        click.echo("\nFeed stopped.")
    finally:
        scraper.close()


@cli.command()
@click.option(
    "--filter",
    "-f",
    "category",
    type=click.Choice(["all", "finance", "tech"]),
    default="all",
    help="Show only a specific category",
)
@click.pass_context
def snapshot(ctx, category):
    """Fetch and display a single snapshot of the feed (no auto-refresh)."""
    config = load_config(ctx.obj["config_path"])

    scraper = NitterScraper(instances=config.nitter_instances)
    content_filter = ContentFilter(
        finance_keywords=config.finance_keywords,
        tech_keywords=config.tech_keywords,
        noise_keywords=config.noise_keywords,
    )
    feed_ui = TerminalFeed()

    cat_filter = category if category != "all" else None

    click.echo("Fetching tweets...")
    try:
        scored, total_raw = fetch_and_filter(config, scraper, content_filter)
        feed_ui.render_static(
            scored,
            total_before_filter=total_raw,
            category_filter=cat_filter,
        )
        click.echo(f"\n{len(scored)} items displayed ({total_raw} fetched, "
                    f"{total_raw - len(scored)} filtered as noise)")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        scraper.close()


@cli.command()
@click.argument("handle")
@click.option("--label", "-l", default="", help="Display name for the account")
@click.pass_context
def add(ctx, handle, label):
    """Add a new account to monitor."""
    config_path = Path(ctx.obj["config_path"])
    config = load_config(config_path)

    # Check if already exists
    handle = handle.lstrip("@")
    for acc in config.accounts:
        if acc["handle"].lower() == handle.lower():
            click.echo(f"@{handle} is already in your feed config.")
            return

    # Append to YAML file
    import yaml

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    raw.setdefault("accounts", []).append(
        {"handle": handle, "label": label or handle}
    )

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

    click.echo(f"Added @{handle} ({label or handle}) to your feed.")


@cli.command(name="list")
@click.pass_context
def list_accounts(ctx):
    """List all monitored accounts."""
    config = load_config(ctx.obj["config_path"])

    if not config.accounts:
        click.echo("No accounts configured. Use 'termfeed add <handle>' to add one.")
        return

    click.echo(f"Monitoring {len(config.accounts)} accounts:\n")
    for acc in config.accounts:
        click.echo(f"  @{acc['handle']:20s}  {acc.get('label', '')}")


@cli.command()
@click.argument("handle")
@click.pass_context
def remove(ctx, handle):
    """Remove an account from monitoring."""
    import yaml

    config_path = Path(ctx.obj["config_path"])
    handle = handle.lstrip("@")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    accounts = raw.get("accounts", [])
    original_len = len(accounts)
    raw["accounts"] = [
        a for a in accounts if a["handle"].lower() != handle.lower()
    ]

    if len(raw["accounts"]) == original_len:
        click.echo(f"@{handle} not found in config.")
        return

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

    click.echo(f"Removed @{handle} from your feed.")


if __name__ == "__main__":
    cli()
