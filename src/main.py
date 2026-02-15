"""Terminal Feed - Bloomberg-style news feed from Twitter/X.

Main entry point. Orchestrates scraping, filtering, and terminal display.
All account management goes through data/accounts.json (the accounts table).
"""

from __future__ import annotations

import logging
import sys
import time

import click

from src.accounts import (
    add_account,
    add_discovered_accounts,
    approve_account,
    find_account,
    get_active_accounts,
    get_suggested_accounts,
    load_accounts,
    print_accounts_table,
    remove_account,
    update_account,
)
from src.config import load_config
from src.filters.content_filter import ContentFilter
from src.scrapers.discovery import AccountDiscovery
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


def fetch_and_filter(config, scraper, content_filter, accounts):
    """Fetch tweets from all active accounts and filter them."""
    account_dicts = [{"handle": a["handle"], "label": a.get("label", "")} for a in accounts]
    all_tweets = scraper.fetch_all(account_dicts)
    total_raw = len(all_tweets)

    scored = content_filter.filter_tweets(
        all_tweets,
        min_score=config.min_score,
        max_items=config.max_feed_items,
    )
    return scored, total_raw


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────

@click.group()
@click.option("--config", "-c", default="config/feeds.yaml", help="Path to config file", type=click.Path())
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """Terminal Feed - Bloomberg-style news from Twitter/X."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


# ──────────────────────────────────────────────
#  FEED COMMANDS
# ──────────────────────────────────────────────

@cli.command()
@click.option("--filter", "-f", "category", type=click.Choice(["all", "finance", "tech", "semis", "macro"]), default="all")
@click.pass_context
def watch(ctx, category):
    """Live-updating feed that auto-refreshes."""
    config = load_config(ctx.obj["config_path"])
    accounts = get_active_accounts()

    if not accounts:
        click.echo("No active accounts. Use 'python -m src.main add <handle>' first.")
        return

    scraper = NitterScraper(instances=config.nitter_instances)
    content_filter = ContentFilter(
        finance_keywords=config.finance_keywords,
        tech_keywords=config.tech_keywords,
        noise_keywords=config.noise_keywords,
    )
    feed_ui = TerminalFeed()
    cat_filter = category if category != "all" else None

    # Discovery settings
    disc_cfg = config.discovery
    disc_enabled = disc_cfg.get("enabled", False) if disc_cfg else False
    disc_every = disc_cfg.get("run_every", 3) if disc_cfg else 3
    refresh_count = 0

    try:
        with feed_ui.create_live_display() as live:
            while True:
                try:
                    scored, total_raw = fetch_and_filter(config, scraper, content_filter, accounts)
                    status_msg = (
                        f"Last refresh: {time.strftime('%H:%M:%S')} | "
                        f"{len(accounts)} accounts | "
                        f"Next in {config.refresh_interval}s | "
                        f"Ctrl+C to quit"
                    )

                    # Run discovery periodically
                    refresh_count += 1
                    if disc_enabled and refresh_count % disc_every == 0:
                        all_tweets = [s.tweet for s in scored]
                        known = [a["handle"] for a in accounts]
                        discovery = AccountDiscovery(scraper, known)
                        discovered = discovery.run_discovery(
                            all_tweets,
                            finance_keywords=config.finance_keywords,
                            tech_keywords=config.tech_keywords,
                            min_mentions=disc_cfg.get("min_mentions", 2),
                            max_results=disc_cfg.get("max_suggestions", 10),
                        )
                        if discovered:
                            new_count = add_discovered_accounts([
                                {"handle": d.handle, "display_name": d.display_name, "reason": d.reason}
                                for d in discovered
                            ])
                            if new_count:
                                status_msg += f" | {new_count} new account suggestions!"

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

                for _ in range(config.refresh_interval):
                    time.sleep(1)

    except KeyboardInterrupt:
        click.echo("\nFeed stopped.")
    finally:
        scraper.close()


@cli.command()
@click.option("--filter", "-f", "category", type=click.Choice(["all", "finance", "tech", "semis", "macro"]), default="all")
@click.pass_context
def snapshot(ctx, category):
    """Fetch and display a one-time snapshot of the feed."""
    config = load_config(ctx.obj["config_path"])
    accounts = get_active_accounts()

    if not accounts:
        click.echo("No active accounts. Use 'python -m src.main add <handle>' first.")
        return

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
        scored, total_raw = fetch_and_filter(config, scraper, content_filter, accounts)
        feed_ui.render_static(scored, total_before_filter=total_raw, category_filter=cat_filter)
        click.echo(f"\n{len(scored)} items ({total_raw} fetched, {total_raw - len(scored)} filtered)")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        scraper.close()


# ──────────────────────────────────────────────
#  ACCOUNT MANAGEMENT COMMANDS
# ──────────────────────────────────────────────

@cli.command()
@click.argument("handle")
@click.option("--label", "-l", default="", help="Display name")
@click.option("--category", "-cat", default="", help="Category: finance, tech, semis, macro, crypto")
@click.option("--source", "-s", default="", help="Which Twitter account (account1, account2)")
@click.option("--notes", "-n", default="", help="Optional notes")
def add(handle, label, category, source, notes):
    """Add a new account to monitor.

    Example: python -m src.main add zephyr_z9 -l "Zephyr" -cat semis
    """
    success = add_account(
        handle=handle,
        label=label,
        category=category,
        source=source,
        notes=notes,
    )
    if success:
        click.echo(f"Added @{handle.lstrip('@')} [{category or 'uncategorized'}]")
    else:
        click.echo(f"@{handle.lstrip('@')} already exists in the table.")


@cli.command()
@click.argument("handle")
def remove(handle):
    """Remove an account from monitoring."""
    if remove_account(handle):
        click.echo(f"Removed @{handle.lstrip('@')}")
    else:
        click.echo(f"@{handle.lstrip('@')} not found.")


@cli.command(name="list")
@click.option("--all", "-a", "show_all", is_flag=True, help="Include suggested accounts")
def list_cmd(show_all):
    """Show the accounts table."""
    print_accounts_table(show_suggested=show_all)


@cli.command()
@click.argument("handle")
@click.option("--label", "-l", default=None)
@click.option("--category", "-cat", default=None)
@click.option("--source", "-s", default=None)
@click.option("--notes", "-n", default=None)
def edit(handle, label, category, source, notes):
    """Edit an existing account's fields."""
    fields = {}
    if label is not None:
        fields["label"] = label
    if category is not None:
        fields["category"] = category
    if source is not None:
        fields["source"] = source
    if notes is not None:
        fields["notes"] = notes

    if not fields:
        click.echo("Nothing to update. Use --label, --category, --source, or --notes.")
        return

    if update_account(handle, **fields):
        click.echo(f"Updated @{handle.lstrip('@')}")
    else:
        click.echo(f"@{handle.lstrip('@')} not found.")


@cli.command()
@click.argument("handle")
def approve(handle):
    """Approve a discovery-suggested account (moves to active)."""
    if approve_account(handle):
        click.echo(f"Approved @{handle.lstrip('@')} - now active in your feed.")
    else:
        click.echo(f"@{handle.lstrip('@')} not found.")


@cli.command()
def suggestions():
    """Show discovery-suggested accounts pending your approval."""
    suggested = get_suggested_accounts()
    if not suggested:
        click.echo("No pending suggestions. Discovery runs automatically during 'watch'.")
        return
    print_accounts_table(accounts=suggested)
    click.echo("\nUse 'python -m src.main approve <handle>' to activate.")


@cli.command()
@click.pass_context
def discover(ctx):
    """Run account discovery once and show results."""
    config = load_config(ctx.obj["config_path"])
    accounts = get_active_accounts()

    if not accounts:
        click.echo("No active accounts to discover from.")
        return

    scraper = NitterScraper(instances=config.nitter_instances)
    known = [a["handle"] for a in accounts]

    click.echo("Fetching tweets from your accounts...")
    account_dicts = [{"handle": a["handle"], "label": a.get("label", "")} for a in accounts]
    all_tweets = scraper.fetch_all(account_dicts)

    if not all_tweets:
        click.echo("No tweets fetched. Nitter instances may be down.")
        scraper.close()
        return

    click.echo(f"Analyzing {len(all_tweets)} tweets for new accounts...")
    discovery = AccountDiscovery(scraper, known)
    discovered = discovery.run_discovery(
        all_tweets,
        finance_keywords=config.finance_keywords,
        tech_keywords=config.tech_keywords,
    )
    scraper.close()

    if not discovered:
        click.echo("No new accounts discovered this time.")
        return

    new_count = add_discovered_accounts([
        {"handle": d.handle, "display_name": d.display_name, "reason": d.reason}
        for d in discovered
    ])
    click.echo(f"\nFound {len(discovered)} accounts, {new_count} new:")
    for d in discovered:
        click.echo(f"  @{d.handle:20s} {d.reason}")
    click.echo("\nUse 'python -m src.main suggestions' to review, 'approve <handle>' to activate.")


if __name__ == "__main__":
    cli()
