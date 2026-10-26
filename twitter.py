#!/usr/bin/env python3
"""
Unified Twitter/X bookmarks CLI.

Subcommands:
  videos    list (and optionally download) every video in your bookmarks
  download  download videos from specific tweet URL(s)
  clear     remove every bookmark from your account

Auth: pass -t/--token, set TWITTER_AUTH_TOKEN, or let it auto-extract the
auth_token from a logged-in browser (Chrome, Safari, Firefox, Zen, Edge,
Brave, ...). If none of those work it falls back to cookies.txt /
accounts.txt. Use --browser NAME to pick one, or --no-browser to disable.

Examples:
  twitter.py videos                       # write bookmark_videos.txt + urls
  twitter.py videos --download            # + download all of them
  twitter.py download <tweet_url> ...     # download specific tweets
  twitter.py download -f links.txt        # download from a file of URLs
  twitter.py clear                        # dry run
  twitter.py clear --yes                  # actually clear bookmarks
  twitter.py videos --browser zen         # force a specific browser
  twitter.py videos --no-browser          # only use cookies.txt/accounts.txt
"""

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import aiohttp
from gallery_dl import util
from gallery_dl.extractor import twitter
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

HERE = Path(__file__).resolve().parent
BOOKMARKS_URL = "https://x.com/i/bookmarks"
VIDEO_TYPES = ("video", "animated_gif")

# X GraphQL constants (verified against the live web bundle).
DELETE_BOOKMARK_QUERY_ID = "Wlmlj2-xzyS1GN3a6cj-mQ"
BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
# Tried in order when no explicit token is available.
BROWSER_ORDER = (
    "chrome", "safari", "firefox", "zen", "librewolf", "floorp",
    "edge", "brave", "chromium", "vivaldi", "opera", "orion",
)


def _is_x_domain(domain):
    domain = (domain or "").lstrip(".").lower()
    return domain == "x.com" or domain.endswith(".x.com") \
        or domain == "twitter.com" or domain.endswith(".twitter.com")


def token_from_browser(browser=None):
    """Return (auth_token, browser_name) from a logged-in browser, or None."""
    try:
        from gallery_dl import cookies as gdcookies
    except Exception:
        return None, None

    for name in ((browser,) if browser else BROWSER_ORDER):
        try:
            jar = gdcookies.load_cookies((name,))
        except Exception:
            # Browser not installed / locked DB / no permission — skip it.
            continue
        for cookie in jar:
            if cookie.name == "auth_token" and _is_x_domain(cookie.domain):
                return cookie.value, name
    return None, None


def resolve_token(cli_token, browser=None, use_browser=True):
    """Resolve a token, returning (value, source)."""
    if cli_token:
        return cli_token, "argument"
    if os.environ.get("TWITTER_AUTH_TOKEN"):
        return os.environ["TWITTER_AUTH_TOKEN"], "environment"

    # Prefer a live browser session over a possibly stale stored token.
    if use_browser:
        value, source = token_from_browser(browser)
        if value:
            return value, f"{source} browser"

    for name in ("cookies.txt", "accounts.txt"):
        path = HERE / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if name == "cookies.txt":
                parts = line.split("\t")
                if "auth_token" in parts:
                    return parts[parts.index("auth_token") + 1], name
            else:
                return line, name

    return None, None


def require_token(args):
    token, source = resolve_token(
        args.token,
        getattr(args, "browser", None),
        not getattr(args, "no_browser", False),
    )
    if not token:
        sys.exit(
            "Error: no auth token. Use -t/--token, set TWITTER_AUTH_TOKEN, "
            "add it to cookies.txt, or log in to x.com in a supported browser."
        )
    if source not in ("argument", "environment", "cookies.txt", "accounts.txt"):
        print(f"Using auth_token from {source}.", file=sys.stderr)
    return token


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def _init_extractor(extractor, token):
    cfg = {"cookies": {"auth_token": token}}
    extractor.config = lambda key, default=None: cfg.get(key, default)
    extractor.initialize()
    return extractor


def extract_bookmark_videos(token):
    """Yield a dict per video found in the bookmarks."""
    extractor = _init_extractor(
        twitter.TwitterBookmarkExtractor.from_url(BOOKMARKS_URL), token
    )
    seen = set()
    for item in extractor:
        if not (isinstance(item, tuple) and len(item) >= 3):
            continue
        media_url, meta = item[1], item[2]
        if not media_url or not isinstance(meta, dict):
            continue
        if meta.get("type") not in VIDEO_TYPES:
            continue
        video = _video_from_meta(meta, media_url)
        key = (video["permalink"], video["url"])
        if key in seen:
            continue
        seen.add(key)
        yield video


def extract_tweet_videos(url, token):
    """Yield a dict per video found in a single tweet URL."""
    extractor = _init_extractor(
        twitter.TwitterTweetExtractor.from_url(url), token
    )
    for item in extractor:
        if not (isinstance(item, tuple) and len(item) >= 3):
            continue
        media_url, meta = item[1], item[2]
        if not media_url or not isinstance(meta, dict):
            continue
        if meta.get("type") not in VIDEO_TYPES:
            continue
        yield _video_from_meta(meta, media_url)


def _video_from_meta(meta, media_url):
    tweet_id = meta.get("tweet_id")
    author = (meta.get("author") or {}).get("name") or "unknown"
    return {
        "permalink": f"https://x.com/{author}/status/{tweet_id}",
        "url": media_url,
        "tweet_id": tweet_id,
        "author": author,
        "num": meta.get("num", 1),
    }


def list_all_bookmarks(token):
    """Return [(tweet_id, author)] for every bookmarked post, videos or not."""
    extractor = twitter.TwitterBookmarkExtractor.from_url(BOOKMARKS_URL)
    cfg = {"cookies": {"auth_token": token}, "text-tweets": True}
    extractor.config = lambda key, default=None: cfg.get(key, default)
    extractor.initialize()

    seen = set()
    posts = []
    for item in extractor:
        if not (isinstance(item, tuple) and len(item) >= 3):
            continue
        meta = item[2]
        if not isinstance(meta, dict):
            continue
        tweet_id = meta.get("tweet_id")
        if not tweet_id or tweet_id in seen:
            continue
        seen.add(tweet_id)
        posts.append((tweet_id, (meta.get("author") or {}).get("name")))
    return posts


# --------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------
def _filename(video):
    author = re.sub(r"[^\w.-]", "_", str(video["author"]))
    return f"{author}_{video['tweet_id']}_{int(video['num']):02d}.mp4"


async def download_video(url, filepath, session):
    async with session.get(url) as response:
        if response.status != 200:
            print(f"✗ HTTP {response.status}")
            return False
        total = int(response.headers.get("content-length", 0)) or None
        with Progress(
            TextColumn("[bold cyan]{task.fields[filename]}", justify="right"),
            BarColumn(bar_width=None),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                "download", filename=os.path.basename(filepath), total=total
            )
            with open(filepath, "wb") as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))
    print("✓ Download complete!")
    return True


async def _download_all(videos, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = skipped = failed = 0
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, video in enumerate(videos, 1):
            filepath = out_dir / video.get("filename", _filename(video))
            print(f"\n[{i}/{len(videos)}] {video['permalink']}")
            if filepath.exists() and filepath.stat().st_size > 0:
                print(f"  ↷ already downloaded, skipping ({filepath.name})")
                skipped += 1
                continue
            try:
                success = await download_video(video["url"], str(filepath), session)
            except Exception as exc:
                print(f"✗ Download error: {exc}")
                success = False
            ok += success
            failed += not success
    print(f"\n✓ {ok} downloaded, {skipped} skipped, {failed} failed.")
    print(f"  Saved to: {out_dir}")


# --------------------------------------------------------------------------
# clear bookmarks
# --------------------------------------------------------------------------
def _make_session(token):
    ct0 = util.generate_token()
    import requests

    session = requests.Session()
    session.headers.update({
        "authorization": f"Bearer {BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "accept": "*/*",
        "referer": "https://x.com/",
        "origin": "https://x.com",
        "user-agent": USER_AGENT,
    })
    session.cookies.set("auth_token", token, domain=".x.com")
    session.cookies.set("ct0", ct0, domain=".x.com")
    return session


def _delete_bookmark(session, tweet_id):
    # X rotates the ct0 cookie; the header must always match it.
    ct0 = session.cookies.get("ct0", domain=".x.com")
    if ct0:
        session.headers["x-csrf-token"] = ct0
    url = (f"https://x.com/i/api/graphql/"
           f"{DELETE_BOOKMARK_QUERY_ID}/DeleteBookmark")
    body = {"variables": {"tweet_id": str(tweet_id)},
            "queryId": DELETE_BOOKMARK_QUERY_ID}
    resp = session.post(url, json=body, timeout=30)
    if resp.status_code == 200 and not resp.json().get("errors"):
        return True, None
    if resp.status_code == 200:
        return False, str(resp.json()["errors"])
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"


def _merge_lines(path, lines):
    merged = list(lines)
    seen = set(merged)
    if path.exists():
        for line in path.read_text().splitlines():
            if line and line not in seen:
                merged.append(line)
                seen.add(line)
    path.write_text("\n".join(merged) + "\n")
    return len(merged)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_videos(args):
    token = require_token(args)
    print("Fetching bookmarks... (this may take a while)", file=sys.stderr)

    videos = []
    for video in extract_bookmark_videos(token):
        videos.append(video)
        if args.limit and len(videos) >= args.limit:
            break

    if not videos:
        sys.exit("No videos found in bookmarks.")

    posts = {v["permalink"] for v in videos}
    if args.limit:
        print(f"Found {len(videos)} video(s) (limited to {args.limit}); "
              "skipping link-file write.", file=sys.stderr)
    else:
        Path(args.output).write_text(
            "".join(f"{v['permalink']}\t{v['url']}\n" for v in videos)
        )
        Path(args.urls_output).write_text(
            "".join(f"{v['url']}\n" for v in videos)
        )
        print(f"Found {len(videos)} video(s) across {len(posts)} post(s).\n"
              f"  {args.output}\n  {args.urls_output}", file=sys.stderr)

    if args.download:
        asyncio.run(_download_all(videos, Path(args.dir).expanduser()))


def cmd_download(args):
    token = require_token(args)

    urls = list(args.urls)
    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            sys.exit(f"Error: file not found: {args.file}")
        urls += [ln.strip() for ln in path.read_text().splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        sys.exit("Error: provide a tweet URL or use -f/--file.")

    videos = []
    for url in urls:
        if not url.startswith("http"):
            url = f"https://{url}"
        print(f"\nFetching: {url}")
        try:
            found = list(extract_tweet_videos(url, token))
        except Exception as exc:
            print(f"✗ Failed: {exc}")
            continue
        if not found:
            print("✗ No videos found")
            continue
        if args.name and len(found) == 1 and len(urls) == 1:
            found[0]["filename"] = f"{args.name}.mp4"
        videos.extend(found)

    if not videos:
        sys.exit("No videos to download.")
    asyncio.run(_download_all(videos, Path(args.dir).expanduser()))


def cmd_clear(args):
    token = require_token(args)
    print("Fetching all bookmarks...")
    posts = list_all_bookmarks(token)
    if not posts:
        sys.exit("No bookmarks found.")

    backup = Path(args.backup).expanduser()
    lines = [
        (f"https://x.com/{author}/status/{tid}" if author
         else f"https://x.com/i/status/{tid}")
        for tid, author in posts
    ]
    total = _merge_lines(backup, lines)
    print(f"Found {len(posts)} bookmark(s). Backup saved to {backup} "
          f"({total} total)")

    if args.limit:
        posts = posts[: args.limit]
    if not args.yes:
        print("\nDry run — no bookmarks removed. Re-run with --yes.")
        return

    print(f"\nDeleting {len(posts)} bookmark(s)...")
    session = _make_session(token)
    ok = failed = 0
    for i, (tid, _) in enumerate(posts, 1):
        success, err = _delete_bookmark(session, tid)
        if not success:
            time.sleep(5)
            success, err = _delete_bookmark(session, tid)
        if success:
            ok += 1
            status = "removed"
        else:
            failed += 1
            status = f"FAILED: {err}"
        print(f"[{i}/{len(posts)}] {tid} {status}")
        if i < len(posts):
            time.sleep(args.delay)
    print(f"\n✓ {ok} removed, {failed} failed.")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="Twitter/X bookmarks: extract videos, download, clear.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_token(p):
        p.add_argument("-t", "--token", help="auth_token cookie value")
        p.add_argument(
            "-b", "--browser",
            help="browser to read auth_token from when none is given "
                 f"({', '.join(BROWSER_ORDER)})",
        )
        p.add_argument(
            "--no-browser", action="store_true",
            help="do not fall back to browser cookies",
        )

    # videos
    p = sub.add_parser("videos", help="list/download all bookmarked videos")
    add_token(p)
    p.add_argument("-o", "--output", default="bookmark_videos.txt",
                   help="permalink <TAB> video URL output file")
    p.add_argument("--urls-output", default="bookmark_video_urls.txt",
                   help="video-URL-only output file")
    p.add_argument("--download", action="store_true",
                   help="download every video")
    p.add_argument("-d", "--dir", default="downloads",
                   help="download directory (default: downloads)")
    p.add_argument("-n", "--limit", type=int, help="only first N videos")
    p.set_defaults(func=cmd_videos)

    # download
    p = sub.add_parser("download", help="download videos from tweet URLs")
    add_token(p)
    p.add_argument("urls", nargs="*", help="tweet URL(s)")
    p.add_argument("-f", "--file", help="file with tweet URLs (one per line)")
    p.add_argument("-d", "--dir", default="downloads", help="download directory")
    p.add_argument("-n", "--name", help="custom filename (single video only)")
    p.set_defaults(func=cmd_download)

    # clear
    p = sub.add_parser("clear", help="remove all bookmarks")
    add_token(p)
    p.add_argument("--backup", default="bookmark_backup.txt",
                   help="backup file (merged with any existing backup)")
    p.add_argument("--yes", action="store_true", help="actually delete")
    p.add_argument("-n", "--limit", type=int, help="only first N bookmarks")
    p.add_argument("--delay", type=float, default=0.5,
                   help="seconds between deletions (default: 0.5)")
    p.set_defaults(func=cmd_clear)

    return parser


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")


if __name__ == "__main__":
    main()
