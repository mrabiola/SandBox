"""Accounts table - the single source of truth for all monitored accounts.

Stores accounts as a JSON file that can be:
- Edited directly by the user
- Modified via CLI commands (add/remove/edit)
- Written to by the discovery engine (status="suggested")
- Displayed as a pretty table in the terminal

Each account has:
  handle       - Twitter handle (no @)
  label        - Display name
  category     - "finance", "tech", "semis", "macro", or custom
  source       - Which of the user's Twitter accounts this came from
  added_by     - "manual" or "discovery"
  status       - "active" (monitoring) or "suggested" (pending approval)
  added_at     - ISO timestamp
  notes        - Optional free text
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table
from rich.text import Text

ACCOUNTS_FILE = Path("data/accounts.json")

# Category display colors
CATEGORY_COLORS = {
    "finance": "bright_blue",
    "tech": "bright_green",
    "semis": "bright_magenta",
    "macro": "bright_yellow",
    "crypto": "bright_cyan",
}


def _ensure_file() -> Path:
    """Ensure the accounts file and parent dir exist."""
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS_FILE.exists():
        ACCOUNTS_FILE.write_text("[]")
    return ACCOUNTS_FILE


def load_accounts() -> list[dict]:
    """Load all accounts from the JSON file."""
    path = _ensure_file()
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_accounts(accounts: list[dict]) -> None:
    """Save accounts to the JSON file."""
    path = _ensure_file()
    path.write_text(json.dumps(accounts, indent=2, default=str))


def get_active_accounts() -> list[dict]:
    """Get only active (non-suggested) accounts."""
    return [a for a in load_accounts() if a.get("status") == "active"]


def get_suggested_accounts() -> list[dict]:
    """Get only discovery-suggested accounts pending approval."""
    return [a for a in load_accounts() if a.get("status") == "suggested"]


def find_account(handle: str) -> dict | None:
    """Find an account by handle (case-insensitive)."""
    handle_lower = handle.lower().lstrip("@")
    for acc in load_accounts():
        if acc["handle"].lower() == handle_lower:
            return acc
    return None


def add_account(
    handle: str,
    label: str = "",
    category: str = "",
    source: str = "",
    added_by: Literal["manual", "discovery"] = "manual",
    status: Literal["active", "suggested"] = "active",
    notes: str = "",
) -> bool:
    """Add a new account. Returns False if already exists."""
    handle = handle.lower().lstrip("@")

    if find_account(handle):
        return False

    accounts = load_accounts()
    accounts.append({
        "handle": handle,
        "label": label or handle,
        "category": category,
        "source": source,
        "added_by": added_by,
        "status": status,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    })
    save_accounts(accounts)
    return True


def remove_account(handle: str) -> bool:
    """Remove an account by handle. Returns False if not found."""
    handle_lower = handle.lower().lstrip("@")
    accounts = load_accounts()
    original_len = len(accounts)
    accounts = [a for a in accounts if a["handle"].lower() != handle_lower]
    if len(accounts) == original_len:
        return False
    save_accounts(accounts)
    return True


def update_account(handle: str, **fields) -> bool:
    """Update fields on an existing account. Returns False if not found."""
    handle_lower = handle.lower().lstrip("@")
    accounts = load_accounts()
    for acc in accounts:
        if acc["handle"].lower() == handle_lower:
            acc.update(fields)
            save_accounts(accounts)
            return True
    return False


def approve_account(handle: str) -> bool:
    """Move a suggested account to active status."""
    return update_account(handle, status="active")


def add_discovered_accounts(discovered: list[dict]) -> int:
    """Bulk-add accounts from the discovery engine as 'suggested'.

    Args:
        discovered: List of dicts with at least 'handle' key.

    Returns:
        Number of new accounts added.
    """
    added = 0
    for d in discovered:
        success = add_account(
            handle=d["handle"],
            label=d.get("display_name", d["handle"]),
            category=d.get("category", ""),
            added_by="discovery",
            status="suggested",
            notes=d.get("reason", ""),
        )
        if success:
            added += 1
    return added


def print_accounts_table(
    accounts: list[dict] | None = None,
    show_suggested: bool = True,
) -> None:
    """Pretty-print the accounts table to the terminal."""
    console = Console()

    if accounts is None:
        accounts = load_accounts()

    if not show_suggested:
        accounts = [a for a in accounts if a.get("status") == "active"]

    if not accounts:
        console.print("[dim]No accounts configured. Use 'termfeed add' to add one.[/dim]")
        return

    table = Table(
        title="Monitored Accounts",
        title_style="bold bright_white",
        border_style="bright_blue",
        show_lines=False,
        expand=True,
        padding=(0, 1),
    )

    table.add_column("#", style="dim", width=3)
    table.add_column("Handle", style="bold cyan", min_width=18)
    table.add_column("Label", min_width=20)
    table.add_column("Category", width=10)
    table.add_column("Source", width=10, style="dim")
    table.add_column("Status", width=10)
    table.add_column("Added By", width=10, style="dim")
    table.add_column("Notes", ratio=1, style="dim")

    for i, acc in enumerate(accounts, 1):
        cat = acc.get("category", "")
        cat_color = CATEGORY_COLORS.get(cat, "white")
        cat_text = Text(cat or "-", style=cat_color)

        status = acc.get("status", "active")
        if status == "active":
            status_text = Text("ACTIVE", style="bold bright_green")
        else:
            status_text = Text("SUGGESTED", style="bold bright_yellow")

        added_by = acc.get("added_by", "manual")
        if added_by == "discovery":
            added_text = Text("auto", style="bright_yellow")
        else:
            added_text = Text("manual", style="dim")

        table.add_row(
            str(i),
            f"@{acc['handle']}",
            acc.get("label", ""),
            cat_text,
            acc.get("source", "-"),
            status_text,
            added_text,
            acc.get("notes", "")[:50],
        )

    console.print(table)

    # Summary
    active = sum(1 for a in accounts if a.get("status") == "active")
    suggested = sum(1 for a in accounts if a.get("status") == "suggested")
    console.print(
        f"\n [bold]{active}[/bold] active  "
        f"[bright_yellow]{suggested}[/bright_yellow] suggested"
    )
