<center>
  <h1 align="center">🎬 Twitter/X Bookmark Video Downloader</h1>
  <p align="center">Find every video in your X bookmarks, download them in bulk, and clear the list when you're done.</p>
</center>

## 🤔 The Problem

X has no built-in way to export your bookmarks, and saving videos one by one is painfully slow — especially when your bookmarks are full of clips you meant to watch later. There's also no bulk "unsave everything" button if you want a fresh start.

## 💡 The Solution

A single Python CLI that talks to X's bookmark feed and video CDN directly. It walks your bookmarks, pulls out every native video and GIF, and downloads them with readable filenames and live progress bars.

- **Bulk bookmark extraction** — writes both a `permalink → video URL` list and a URL-only list.
- **Direct tweet downloads** — download videos from one or more tweet URLs, or from a file of URLs.
- **Resumable downloads** — existing, non-empty files are skipped automatically.
- **Bookmark clearing with backup** — saves every bookmark to a text file before optionally removing them (dry run by default).
- **Flexible authentication** — use a token flag, an environment variable, auto-extracted browser cookies, or a local `cookies.txt` / `accounts.txt`.
- **Readable filenames** — saved as `author_tweetid_01.mp4`, including multi-video posts.

## 🖥 Demo

```console
$ ./twitter.py videos --download
Fetching bookmarks... (this may take a while)
Found 42 video(s) across 38 post(s).
  bookmark_videos.txt
  bookmark_video_urls.txt

[1/42] https://x.com/someone/status/1234567890123456789
✓ Download complete!
```

```console
$ ./twitter.py clear
Fetching all bookmarks...
Found 128 bookmark(s). Backup saved to bookmark_backup.txt (128 total)

Dry run — no bookmarks removed. Re-run with --yes.
```

## 🔬 Technologies Used

![Python](https://img.shields.io/badge/-PYTHON-FF0000?style=for-the-badge&logo=python&logoColor=white&color=3776AB)
![gallery-dl](https://img.shields.io/badge/-GALLERY--DL-FF0000?style=for-the-badge&logo=python&logoColor=white&color=4B8BBE)
![aiohttp](https://img.shields.io/badge/-AIOHTTP-FF0000?style=for-the-badge&logo=aiohttp&logoColor=white&color=2C5BB4)
![Rich](https://img.shields.io/badge/-RICH-FF0000?style=for-the-badge&logo=python&logoColor=white&color=FFD43B)
![MIT License](https://img.shields.io/badge/-MIT-FF0000?style=for-the-badge&logo=opensourceinitiative&logoColor=white&color=3DA639)

## ⌨️ Setup

If you want to run this project on your local machine:

1. Clone the repository:
   ```bash
   git clone https://github.com/melvinchia3636/twitter-video-downloader.git
   cd twitter-video-downloader
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Make the script executable and run it:
   ```bash
   chmod +x twitter.py
   ./twitter.py --help
   ```

### Authentication

The script needs the `auth_token` cookie from a logged-in X session. It tries these sources in order:

1. `-t/--token` argument
2. `TWITTER_AUTH_TOKEN` environment variable
3. Auto-extracted cookies from a logged-in browser (Chrome, Safari, Firefox, Zen, Edge, Brave, and others) — pick one with `--browser NAME`, or disable with `--no-browser`
4. `cookies.txt` (Netscape cookie format) or `accounts.txt` (raw token on the first line)

```bash
export TWITTER_AUTH_TOKEN="your_auth_token_here"
```

### Usage

```bash
# List every bookmarked video; write bookmark_videos.txt + bookmark_video_urls.txt
./twitter.py videos

# List and download everything to downloads/
./twitter.py videos --download

# Only the first 10 videos, into a custom folder
./twitter.py videos --download --limit 10 --dir clips

# Download videos from specific tweets
./twitter.py download https://x.com/user/status/1234567890

# Download from a file of tweet URLs (one per line)
./twitter.py download -f links.txt

# Preview clearing bookmarks (writes a backup first)
./twitter.py clear

# Actually remove every bookmark
./twitter.py clear --yes
```

> macOS may ask for Keychain/full-disk access the first time the script reads browser cookies. Grant it, or use `--token` / `cookies.txt` instead.

## 📈 Status

This project is actively maintained as a personal tool. If you find a bug or want a feature, please file an issue or open a pull request.

## 💡 Inspirations

Built on top of [gallery-dl](https://github.com/mikf/gallery-dl)'s excellent Twitter/X extractors. X's web GraphQL API is used for bookmark removal, so query IDs may need updating when X ships changes.

## ⚠️ Disclaimer

This tool is intended for downloading content you have permission to save, for personal and offline use. Respect creators' rights and X's Terms of Service. You are responsible for how you use it.

## 📄 License

Copyright © 2026 Melvin Chia<br/>
Licensed under the [MIT License](LICENSE).
