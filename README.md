# Terminal Feed

Bloomberg-style terminal news feed that pulls from Twitter/X **without the paid API**.

Replaces logging into your two Twitter accounts multiple times a day. You add your high-signal follows once, and the feed handles the rest: pulls their tweets, filters out lifestyle/personal noise, and surfaces only finance and tech signal. It also discovers similar accounts you're not following yet.

## How it works

```
Your 2 Twitter accounts
        |
        v
  data/accounts.json   <-- single editable table of all accounts
        |
        v
  Nitter RSS scraper    <-- pulls tweets (free, no API key, no login)
        |
        v
  Keyword filter        <-- auto-categorizes finance/tech, kills noise
        |
        v
  Terminal UI           <-- Bloomberg-style color-coded feed
        |
        v
  Discovery engine      <-- finds new accounts from @mentions
        |
        v
  accounts.json         <-- suggestions added back to the table
```

## Quick start

```bash
pip install -e .

# See your accounts table
python -m src.main list

# Add an account
python -m src.main add zephyr_z9 -l "Zephyr" -cat semis

# Run live feed
python -m src.main watch

# One-time snapshot
python -m src.main snapshot

# Filter by category
python -m src.main watch --filter finance
python -m src.main watch --filter semis
```

## Account management

All accounts live in `data/accounts.json`. Manage via CLI:

```bash
# Add
python -m src.main add <handle> -l "Name" -cat <category> -s account1

# Edit
python -m src.main edit <handle> -cat tech -n "some notes"

# Remove
python -m src.main remove <handle>

# Show table
python -m src.main list          # active only
python -m src.main list --all    # include suggestions

# Discovery
python -m src.main discover      # run discovery manually
python -m src.main suggestions   # see pending suggestions
python -m src.main approve <handle>  # activate a suggestion
```

Categories: `finance`, `tech`, `semis`, `macro`, `crypto` (or anything custom).

## Config

Edit `config/feeds.yaml` to tune:
- Nitter instances (scraping endpoints)
- Refresh interval
- Finance/tech keyword lists
- Noise filter words
- Discovery settings
