#!/usr/bin/env python3
"""
username_hunter - check a username across 100+ platforms.

Scans social, dev, gaming, music, photo, video, finance and other
platforms using their public profile pages and public APIs.

Works on Termux (Android) and any Linux. Needs Python 3.6+ and `requests`.

    python3 username_hunter.py someuser
    python3 username_hunter.py someuser -t 40 -o results.txt
    python3 username_hunter.py someuser --format json -o results.json
    python3 username_hunter.py someuser --category dev,gaming

Results are informational (public data only). Always verify hits manually.
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    sys.exit("The 'requests' module is missing. Install it with:\n  pip install requests")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
}

PROFILES_DIR = os.path.expanduser("~/.xname-hunter")
PROFILES_PATH = os.path.join(PROFILES_DIR, "profiles.json")

# Soft-404 guard: some sites answer HTTP 200 for a missing user but render a
# "not found" page. The <title> of a real profile almost never contains these,
# so a title hit flips a code-type 200 back to not-found.
SOFT404_TITLE_MARKERS = [
    "page not found",
    "user not found",
    "profile not found",
    "account not found",
    "404 not found",
    "this page doesn't exist",
    "doesn't exist",
]

# requests.Session is not thread-safe: a session shared across the worker
# pool corrupts responses (crossed connections, stale cookies) and drops
# real hits. Each thread gets its own session instead.
_tls = threading.local()


def _thread_session():
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        _tls.session = sess
    return sess


def load_sites():
    here = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
    path = os.path.join(here, "sites.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sites"]


def _resolve_json_key(data, dotted):
    node = data
    for key in dotted.split("."):
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and key.isdigit():
            node = node[int(key)] if int(key) < len(node) else None
        else:
            return None
    return node


def _page_title(html_text):
    m = re.search(r"<title[^>]*>(.*?)</title\s*>", html_text or "",
                  re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip().lower()


def _looks_like_soft404(body):
    title = _page_title(body)
    return any(marker in title for marker in SOFT404_TITLE_MARKERS)


def check(site, username, timeout, retries=2, retry_delay=1.0, delay=0.0):
    session = _thread_session()
    name = site["name"]
    profile_url = site["url"].format(username)
    result = {
        "name": name,
        "category": site.get("category", "misc"),
        "url": profile_url,
        "found": False,
        "status": None,
    }
    try:
        url = site["api"].format(username) if site.get("api") else profile_url
        r = None
        for attempt in range(max(retries, 0) + 1):
            if delay > 0:
                time.sleep(delay)
            try:
                r = session.get(url, headers=HEADERS, timeout=timeout,
                                allow_redirects=True)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= retries:
                    raise
                time.sleep(retry_delay * (2 ** attempt))
        result["status"] = r.status_code
        ctype = site.get("type", "code")

        if ctype == "code":
            result["found"] = r.status_code == 200
            # Soft-404 guard: 200 with a "not found" page title is a miss.
            if result["found"] and _looks_like_soft404(r.text[:4000]):
                result["found"] = False
                result["soft404"] = True
        elif ctype == "api":
            found = r.status_code == 200
            if found and site.get("json_key"):
                try:
                    found = bool(_resolve_json_key(r.json(), site["json_key"]))
                except Exception:
                    found = False
            result["found"] = found
        elif ctype == "body":
            body = r.text.lower()
            errs = [e.lower() for e in site.get("error_strings", [])]
            oks = [st.format(username).lower()
                   for st in site.get("success_strings", [])]
            found = r.status_code == 200 and not any(e in body for e in errs)
            if oks:
                found = found and any(o in body for o in oks)
            result["found"] = found
        else:
            result["found"] = r.status_code == 200
        if site.get("final_url_contains"):
            needle = site["final_url_contains"].format(username).lower()
            result["found"] = result["found"] and needle in r.url.lower()
    except Exception as exc:
        result["error"] = str(exc)[:90]
    return result


def load_profiles():
    try:
        with open(PROFILES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_profile(name, config):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    profiles = load_profiles()
    profiles[name] = config
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


def write_html_report(found, username, path, elapsed, total):
    """Self-contained HTML report of a scan: hits table + summary."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = "\n".join(
        "      <tr><td>{}</td><td>{}</td><td><a href=\"{}\">{}</a></td><td>{}</td></tr>".format(
            html.escape(r["name"]), html.escape(r["category"]),
            html.escape(r["url"]), html.escape(r["url"]),
            html.escape(str(r.get("status", ""))))
        for r in sorted(found, key=lambda r: r["name"].lower())
    )
    doc = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>username-hunter report: {user}</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
         margin: 0; padding: 24px; }}
  main {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ color: #fff; }}
  .meta {{ color: #94a3b8; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-weight: 600; }}
  a {{ color: #22d3ee; word-break: break-all; }}
  .none {{ color: #94a3b8; margin-top: 16px; }}
</style>
</head>
<body>
<main>
  <h1>username-hunter: {user}</h1>
  <p class="meta">{found} of {total} platforms matched &middot; scanned in {elapsed:.1f}s &middot; {now}</p>
  {table}
  <p class="meta">Public data only. Verify hits manually before acting on them.</p>
</main>
</body>
</html>""".format(
        user=html.escape(username), found=len(found), total=total,
        elapsed=elapsed, now=now,
        table=("<table><tr><th>Platform</th><th>Category</th><th>Profile URL</th>"
               "<th>Status</th></tr>\n" + rows + "\n    </table>")
        if found else '<p class="none">No matches found.</p>')
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    ap = argparse.ArgumentParser(
        description="Find which platforms a username is registered on.")
    ap.add_argument("username", nargs="?",
                    help="username to hunt for")
    ap.add_argument("-t", "--threads", type=int, default=25,
                    help="concurrent requests (default: 25)")
    ap.add_argument("--timeout", type=float, default=10,
                    help="per-request timeout in seconds (default: 10)")
    ap.add_argument("--category", default="",
                    help="comma-separated categories to scan "
                         "(social,dev,gaming,music,photo,video,finance,blog,misc)")
    ap.add_argument("--list-categories", action="store_true",
                    help="list available categories and exit")
    ap.add_argument("-o", "--output",
                    help="write found results to file")
    ap.add_argument("--format", choices=["txt", "json", "csv", "html"], default="txt",
                    help="output file format (default: txt)")
    ap.add_argument("--retries", type=int, default=2,
                    help="retries on connection errors/timeouts (default: 2)")
    ap.add_argument("--retry-delay", type=float, default=1.0,
                    help="base seconds between retries, doubled each time (default: 1.0)")
    ap.add_argument("--min-delay", type=float, default=0.0,
                    help="minimum seconds to wait before each request, per thread "
                         "(default: 0 — raise this if sites rate-limit you)")
    ap.add_argument("--save-profile", metavar="NAME",
                    help="save this scan's settings as a named profile and exit")
    ap.add_argument("--profile", metavar="NAME",
                    help="load scan settings from a saved profile")
    ap.add_argument("--list-profiles", action="store_true",
                    help="list saved scan profiles and exit")
    ap.add_argument("--quiet", action="store_true",
                    help="only print found usernames, no misses")
    # Parse once just to find --profile, then apply the profile as parser
    # defaults so explicit CLI flags still win over profile values.
    early = ap.parse_known_args()[0]
    if early.profile:
        profiles = load_profiles()
        cfg = profiles.get(early.profile)
        if not cfg:
            sys.exit(f"No profile named '{early.profile}'.")
        ap.set_defaults(**{k: v for k, v in cfg.items()})
        print(f"{CYAN}[*]{RESET} Loaded profile '{early.profile}'.")
    args = ap.parse_args()

    sites = load_sites()

    if args.list_profiles:
        profiles = load_profiles()
        if not profiles:
            print("No saved profiles.")
        else:
            for name, cfg in sorted(profiles.items()):
                print(f"{name}: {json.dumps(cfg)}")
        return

    if args.list_categories:
        cats = sorted({s.get("category", "misc") for s in sites})
        print("Categories: " + ", ".join(cats))
        return

    if not args.username:
        ap.error("username is required (unless using --list-categories)")

    if args.category:
        wanted = {c.strip().lower() for c in args.category.split(",")}
        sites = [s for s in sites if s.get("category", "misc") in wanted]
        if not sites:
            sys.exit("No sites match those categories.")

    if args.save_profile:
        save_profile(args.save_profile, {
            "threads": args.threads,
            "timeout": args.timeout,
            "category": args.category,
            "format": args.format,
            "retries": args.retries,
            "retry_delay": args.retry_delay,
            "min_delay": args.min_delay,
            "quiet": args.quiet,
        })
        print(f"{CYAN}[*]{RESET} Saved profile '{args.save_profile}'.")
        return

    username = args.username.strip().lstrip("@")
    if not username:
        sys.exit("Empty username.")

    total = len(sites)
    print(f"{CYAN}[*]{RESET} Hunting {YELLOW}{username}{RESET} "
          f"across {total} platforms ({args.threads} threads)...\n")

    found, done = [], 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = {pool.submit(check, s, username, args.timeout,
                              args.retries, args.retry_delay,
                              args.min_delay): s
                   for s in sites}
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            tag = f"[{done:>3}/{total}]"
            if res["found"]:
                found.append(res)
                print(f"{GREEN}[+]{RESET} {tag} {res['name']:<16} "
                      f"{DIM}{res['url']}{RESET}")
            elif not args.quiet:
                print(f"{DIM}[-]{RESET} {tag} {res['name']}")

    elapsed = time.time() - start
    print(f"\n{CYAN}[*]{RESET} Done in {elapsed:.1f}s — "
          f"{GREEN}{len(found)} found{RESET}, {total - len(found)} not found.")

    if args.output:
        if args.format == "json":
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(found, f, indent=2)
        elif args.format == "csv":
            with open(args.output, "w", encoding="utf-8") as f:
                f.write("platform,category,url,status\n")
                for r in found:
                    f.write(f"{r['name']},{r['category']},{r['url']},{r['status']}\n")
        elif args.format == "html":
            write_html_report(found, username, args.output, elapsed, total)
        else:
            with open(args.output, "w", encoding="utf-8") as f:
                for r in found:
                    f.write(f"{r['name']}: {r['url']}\n")
        print(f"{CYAN}[*]{RESET} Saved {len(found)} hits to {args.output}")


if __name__ == "__main__":
    main()
