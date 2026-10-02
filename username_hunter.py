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
import json
import os
import sys
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


def check(site, username, timeout, session):
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
        r = session.get(url, headers=HEADERS, timeout=timeout,
                        allow_redirects=True)
        result["status"] = r.status_code
        ctype = site.get("type", "code")

        if ctype == "code":
            result["found"] = r.status_code == 200
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
        else:
            result["found"] = r.status_code == 200
        if site.get("final_url_contains"):
            needle = site["final_url_contains"].format(username).lower()
            result["found"] = result["found"] and needle in r.url.lower()
    except Exception as exc:
        result["error"] = str(exc)[:90]
    return result


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
    ap.add_argument("--format", choices=["txt", "json", "csv"], default="txt",
                    help="output file format (default: txt)")
    ap.add_argument("--quiet", action="store_true",
                    help="only print found usernames, no misses")
    args = ap.parse_args()

    sites = load_sites()

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

    username = args.username.strip().lstrip("@")
    if not username:
        sys.exit("Empty username.")

    total = len(sites)
    print(f"{CYAN}[*]{RESET} Hunting {YELLOW}{username}{RESET} "
          f"across {total} platforms ({args.threads} threads)...\n")

    session = requests.Session()
    session.headers.update(HEADERS)
    found, done = [], 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = {pool.submit(check, s, username, args.timeout, session): s
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
        else:
            with open(args.output, "w", encoding="utf-8") as f:
                for r in found:
                    f.write(f"{r['name']}: {r['url']}\n")
        print(f"{CYAN}[*]{RESET} Saved {len(found)} hits to {args.output}")


if __name__ == "__main__":
    main()
