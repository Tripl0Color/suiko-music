"""YouTube Music service – browser-based auth (OAuth broken server-side Sep 2025)."""

from __future__ import annotations

import json
import logging
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic
from ytmusicapi.auth.browser import setup_browser

from config import YTMUSIC_BROWSER_FILE

logger = logging.getLogger(__name__)

# ── YouTube Music domain ────────────────────────────────────────
_YT_MUSIC_DOMAIN = ".music.youtube.com"


class YTMusicService:
    """Wrapper around ytmusicapi with browser cookie auth."""

    def __init__(self) -> None:
        self._yt: YTMusic | None = None
        self._load_token()

    # ── Token persistence ──────────────────────────────────────────

    def _load_token(self) -> None:
        path = Path(YTMUSIC_BROWSER_FILE)
        if not path.exists():
            logger.info("[YT] No browser file at %s", path)
            return

        logger.info("[YT] Loading browser auth from %s", path)
        try:
            self._yt = YTMusic(str(path))
            logger.info("[YT] Auth loaded OK, auth_type=%s", self._yt.auth_type)
        except Exception:
            logger.exception("[YT] Failed to load auth from %s", path)
            self._yt = None

    def _save_browser_auth(self, headers_raw: str) -> bool:
        """Parse raw browser headers (cURL format) and save to file."""
        path = Path(YTMUSIC_BROWSER_FILE)
        try:
            setup_browser(filepath=str(path), headers_raw=headers_raw)
            logger.info("[YT] Browser auth saved to %s (%d bytes)", path, path.stat().st_size)
            return True
        except Exception:
            logger.exception("[YT] Failed to save browser auth")
            return False

    def _save_browser_dict(self, headers: dict[str, str]) -> bool:
        """Save pre-parsed headers dict to file."""
        path = Path(YTMUSIC_BROWSER_FILE)
        try:
            init = {
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "accept": "*/*",
                "accept-encoding": "gzip, deflate",
                "content-type": "application/json",
                "content-encoding": "gzip",
                "origin": "https://music.youtube.com",
            }
            init.update(headers)
            path.write_text(json.dumps(init, indent=4, sort_keys=True), encoding="utf-8")
            logger.info("[YT] Browser dict saved to %s", path)
            return True
        except Exception:
            logger.exception("[YT] Failed to save browser dict")
            return False

    def reload_token(self) -> None:
        """Reload auth from disk (e.g. after user uploads new file)."""
        self._yt = None
        self._load_token()

    @property
    def is_authorized(self) -> bool:
        return self._yt is not None

    # ── Browser cookie extraction ──────────────────────────────────

    def extract_browser_cookies(self, browser: str = "chrome") -> dict[str, str] | None:
        """
        Extract YouTube Music cookies from a local browser and build
        the headers dict needed for YTMusic browser auth.

        Args:
            browser: "chrome", "edge", or "firefox"

        Returns:
            Dict with keys: cookie, authorization, x-goog-authuser, user-agent, origin
            None on failure
        """
        try:
            import browser_cookie3
        except ImportError:
            logger.error("[YT] browser_cookie3 not installed: pip install browser_cookie3")
            return None

        logger.info("[YT] Extracting cookies from %s…", browser)

        # Try with domain filter first, fall back to all cookies
        cj = None
        for domain in (_YT_MUSIC_DOMAIN, "youtube.com", None):
            try:
                kwargs = {"domain_name": domain} if domain else {}
                if browser == "edge":
                    cj = browser_cookie3.edge(**kwargs)
                elif browser == "firefox":
                    cj = browser_cookie3.firefox(**kwargs)
                else:
                    cj = browser_cookie3.chrome(**kwargs)
                logger.info("[YT] Loaded cookie jar from %s (domain=%s)", browser, domain)
                break
            except ImportError:
                logger.error("[YT] browser_cookie3 not installed: pip install browser_cookie3")
                return None
            except Exception as e:
                logger.warning("[YT] %s domain=%s failed: %s", browser, domain, e)
                continue

        if cj is None:
            logger.error("[YT] Could not load cookies from any browser")
            return None

        # Build cookie string, filtering for YouTube Music
        cookie_parts: list[str] = []
        sapisid_value = ""
        yt_cookie_count = 0

        for c in cj:
            if "youtube" not in c.domain and "google" not in c.domain:
                continue
            cookie_parts.append(f"{c.name}={c.value}")
            yt_cookie_count += 1
            if c.name == "__Secure-3PAPISID":
                sapisid_value = c.value

        if not cookie_parts:
            logger.error("[YT] No YouTube cookies found in %s", browser)
            return None

        if not sapisid_value:
            logger.error("[YT] __Secure-3PAPISID cookie not found in %s", browser)
            logger.error(
                "[YT] Make sure you are logged in to music.youtube.com in %s", browser
            )
            return None

        cookie_str = "; ".join(cookie_parts)

        # Compute SAPISIDHASH authorization
        # Algorithm: SAPISIDHASH {timestamp}_{sha1(timestamp + " " + sapisid + " " + origin)}
        from hashlib import sha1

        origin = "https://music.youtube.com"
        unix_ts = str(int(time.time()))
        sha_input = f"{unix_ts} {sapisid_value} {origin}"
        sha_hash = sha1(sha_input.encode("utf-8")).hexdigest()
        authorization = f"SAPISIDHASH {unix_ts}_{sha_hash}"

        headers = {
            "cookie": cookie_str,
            "authorization": authorization,
            "x-goog-authuser": "0",
        }

        logger.info(
            "[YT] Extracted %d yt-cookies (total %d), sapisid length=%d, auth=%s…",
            yt_cookie_count, len(cookie_parts), len(sapisid_value), authorization[:40],
        )

        return headers

    def parse_netscape_cookies(self, raw_text: str) -> dict[str, str] | None:
        """
        Parse Netscape HTTP Cookie File format (from yt-dlp, curl, etc.)
        and build the headers dict needed for YTMusic browser auth.
        """
        logger.info("[YT] Parsing Netscape cookie format (%d bytes)…", len(raw_text))

        cookie_parts: list[str] = []
        sapisid_value = ""

        for line in raw_text.splitlines():
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 7:
                continue

            # Netscape format: domain\tflag\tpath\tsecure\texpiry\tname\tvalue
            domain, _flag, _path, _secure, _expiry, name, value = parts[:7]

            # Only keep YouTube/Google cookies
            if "youtube" not in domain and "google" not in domain:
                continue

            cookie_parts.append(f"{name}={value}")

            if name == "__Secure-3PAPISID":
                sapisid_value = value

        if not cookie_parts:
            logger.error("[YT] No YouTube cookies found in Netscape format")
            return None

        if not sapisid_value:
            logger.error("[YT] __Secure-3PAPISID not found in Netscape cookies")
            return None

        cookie_str = "; ".join(cookie_parts)

        # Compute SAPISIDHASH authorization
        from hashlib import sha1

        origin = "https://music.youtube.com"
        unix_ts = str(int(time.time()))
        sha_input = f"{unix_ts} {sapisid_value} {origin}"
        sha_hash = sha1(sha_input.encode("utf-8")).hexdigest()
        authorization = f"SAPISIDHASH {unix_ts}_{sha_hash}"

        headers = {
            "cookie": cookie_str,
            "authorization": authorization,
            "x-goog-authuser": "0",
        }

        logger.info(
            "[YT] Netscape: %d cookies, auth=%s…",
            len(cookie_parts), authorization[:40],
        )

        return headers

    # ── Liked songs ────────────────────────────────────────────────

    def get_liked_songs(self, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch liked songs from YouTube Music."""
        if not self._yt:
            raise RuntimeError("YouTube Music is not authorized")

        logger.info("[YT] get_liked_songs(limit=%d)…", limit)
        auth_hdr = self._yt.headers.get("authorization", "NONE")
        logger.info("[YT] auth_type=%s, auth_header=%s…", self._yt.auth_type, auth_hdr[:40])

        data = self._yt.get_liked_songs(limit=limit)

        logger.info(
            "[YT] Response keys: %s",
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
        raw_tracks = data.get("tracks", [])
        logger.info("[YT] Raw tracks count: %d", len(raw_tracks))

        if raw_tracks:
            logger.info(
                "[YT] First track keys: %s",
                list(raw_tracks[0].keys()) if isinstance(raw_tracks[0], dict) else type(raw_tracks[0]),
            )

        tracks: list[dict[str, Any]] = []
        for t in raw_tracks:
            video_id = t.get("videoId", "")
            if not video_id:
                continue

            title = t.get("title", "Unknown")
            artists_list = t.get("artists", [])
            artists_text = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))
            if not artists_text:
                artists_text = "Unknown Artist"

            album_obj = t.get("album")
            album_text = ""
            if album_obj and isinstance(album_obj, dict):
                album_text = album_obj.get("name", "")
            elif isinstance(album_obj, str):
                album_text = album_obj

            duration = t.get("duration", "")
            if not duration:
                secs = t.get("duration_seconds")
                if secs:
                    mins, s = divmod(int(secs), 60)
                    duration = f"{mins}:{s:02d}"

            tracks.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "artists": artists_text,
                    "album": album_text,
                    "duration": duration,
                    "thumbnails": t.get("thumbnails", []),
                }
            )

        logger.info("[YT] Parsed %d tracks (from %d raw)", len(tracks), len(raw_tracks))
        if tracks:
            logger.info("[YT] Sample: %s — %s", tracks[0]["title"], tracks[0]["artists"])
        return tracks

    # ── Audio download ─────────────────────────────────────────────

    def download_audio(self, video_id: str, output_dir: str = "/tmp/yt_audio") -> str | None:
        """
        Download audio from YouTube Music using yt-dlp.

        Args:
            video_id: YouTube video ID
            output_dir: Directory to save the file

        Returns:
            Path to the downloaded .mp3 file, or None on failure
        """
        import os
        import yt_dlp

        os.makedirs(output_dir, exist_ok=True)
        url = f"https://music.youtube.com/watch?v={video_id}"
        output_path = os.path.join(output_dir, f"{video_id}.mp3")

        # Skip if already downloaded
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info("[YT] Audio already cached: %s", output_path)
            return output_path

        logger.info("[YT] Downloading audio for %s…", video_id)

        # Step 1: Download raw audio (webm/opus) via yt-dlp
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, f"{video_id}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "postprocessors": [],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            logger.exception("[YT] yt-dlp download FAILED for %s", video_id)
            return None

        # Find the downloaded file
        raw_path = None
        for ext in (".webm", ".opus", ".m4a", ".mp3"):
            candidate = os.path.join(output_dir, f"{video_id}{ext}")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                raw_path = candidate
                break

        if not raw_path:
            logger.error("[YT] Audio file not found after download for %s", video_id)
            return None

        # If already mp3, return it
        if raw_path.endswith(".mp3"):
            size_mb = os.path.getsize(raw_path) / (1024 * 1024)
            logger.info("[YT] Downloaded %s (mp3, %.1f MB)", video_id, size_mb)
            return raw_path

        # Step 2: Convert to mp3 via ffmpeg (from imageio-ffmpeg)
        ffmpeg_path = None
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass

        if ffmpeg_path:
            import subprocess

            logger.info("[YT] Converting %s to mp3…", video_id)
            try:
                subprocess.run(
                    [
                        ffmpeg_path, "-y", "-i", raw_path,
                        "-codec:a", "libmp3lame", "-q:a", "2",
                        "-loglevel", "error",
                        output_path,
                    ],
                    check=True, timeout=120,
                )
                # Remove raw file
                os.remove(raw_path)
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                logger.info("[YT] Converted to mp3: %s (%.1f MB)", video_id, size_mb)
                return output_path
            except Exception:
                logger.warning("[YT] ffmpeg conversion failed for %s, returning raw file", video_id)
                return raw_path
        else:
            logger.warning("[YT] No ffmpeg found, returning raw %s file", os.path.splitext(raw_path)[1])
            return raw_path

        logger.error("[YT] Audio file not found after download for %s", video_id)
        return None

    @staticmethod
    def cleanup_audio(video_id: str, output_dir: str = "/tmp/yt_audio") -> None:
        """Remove downloaded audio file."""
        import glob
        import os
        for f in glob.glob(os.path.join(output_dir, f"{video_id}.*")):
            try:
                os.remove(f)
            except OSError:
                pass
