# Terminal Feed

Bloomberg-style terminal news feed that pulls from Twitter/X **without the paid API**.

Monitors accounts you follow across both your Twitter accounts, auto-filters lifestyle/personal noise, and surfaces only high-signal finance and tech content in a color-coded terminal UI.

## How it works

1. **Nitter RSS** - Fetches tweets via free Nitter instances (public Twitter mirrors with RSS feeds). No API key, no login needed.
2. **Keyword filter** - Auto-categorizes tweets as finance, tech, or noise. Noise gets filtered out.
3. **Terminal UI** - Rich-based Bloomberg-style display with color-coded categories, signal scoring, and live refresh.

## Quick start

```bash
pip install -e .

# Edit config to add your accounts
# (just add Twitter handles - no categorization needed)
nano config/feeds.yaml

# Run live feed
python -m src.main watch

# One-time snapshot
python -m src.main snapshot

# Filter by category
python -m src.main watch --filter finance
python -m src.main watch --filter tech
```

## Manage accounts

```bash
# Add an account
python -m src.main add elonmusk --label "Elon Musk"

# List all monitored accounts
python -m src.main list

# Remove an account
python -m src.main remove elonmusk
```

## Config

Edit `config/feeds.yaml` to:
- Add/remove accounts to monitor
- Tune finance and tech keywords
- Add noise words to filter out
- Adjust refresh interval and score threshold
