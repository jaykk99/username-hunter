# username-hunter

Type in a username, get back every platform it's registered on. Checks **143 platforms** across social, dev, gaming, music, photo, video, finance, blogs and more — using public profile pages and public APIs. No API keys, no accounts, works on Termux and any Linux.

## Install

### Termux (Android)

```bash
pkg install -y python git
git clone https://github.com/jaykk99/username-hunter
cd username-hunter
pip install requests
```

### Linux (one-shot)

```bash
git clone https://github.com/jaykk99/username-hunter
cd username-hunter
chmod +x install.sh
./install.sh
```

## Usage

```bash
# basic scan
python3 username_hunter.py someuser

# faster (40 threads) and save results
python3 username_hunter.py someuser -t 40 -o hits.txt

# save as JSON or CSV
python3 username_hunter.py someuser --format json -o hits.json
python3 username_hunter.py someuser --format csv -o hits.csv

# scan only dev + gaming platforms
python3 username_hunter.py someuser --category dev,gaming

# only show hits, skip the misses
python3 username_hunter.py someuser --quiet

# list all categories
python3 username_hunter.py --list-categories
```

| Flag | What it does |
|---|---|
| `-t / --threads` | concurrent requests (default 25) |
| `--timeout` | seconds per request (default 10) |
| `--category` | comma-separated: social,dev,gaming,music,photo,video,finance,blog,misc |
| `-o / --output` | write hits to a file |
| `--format` | txt, json or csv |
| `--quiet` | only print found platforms |

## How it works

Each entry in `sites.json` defines a platform:

- `code` — found if the profile URL returns HTTP 200
- `api` — found if the platform's public API returns HTTP 200 (used for GitHub, Reddit, Bluesky, Lichess, Minecraft/PlayerDB, Speedrun, Keybase, DEV, Codeforces, Docker Hub, Bitbucket, Scratch, Kick...)
- `body` — found if HTTP 200 **and** the page doesn't contain a "not found" marker (used for X, Instagram, Steam, Hacker News...), optionally requiring a positive marker via `success_strings` (used for TikTok)
- `final_url_contains` — extra guard requiring the post-redirect URL to still contain the username (catches sites like Bandcamp that redirect missing profiles to a signup page)

Want more platforms? Just add entries to `sites.json` — no code changes needed.

## Notes

- Results are based on **public** data only. Some sites rate-limit or bot-block; re-run misses if you need to be sure.
- Always verify a hit manually before acting on it — same username ≠ same person.
- Be a decent netizen: default 25 threads is polite; don't crank it to 500.

MIT License.
