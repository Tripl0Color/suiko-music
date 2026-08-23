"""YouTube Music service – browser-based auth with auto-refresh via Chrome DevTools Protocol."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

from config import YTMUSIC_BROWSER_FILE, BROWSER

logger = logging.getLogger(__name__)

_YT_MUSIC_DOMAIN = ".music.youtube.com"
_CDP_PORT = 9222
_BROWSER_DEBUG_ARG = f"--remote-debugging-port={_CDP_PORT}"
# Separate Edge profile for the bot (avoids conflicts with user's main browser)
# Separate browser profile for the bot (main profile can't bind debug port)
_BOT_BROWSER_PROFILE = os.path.join(
    os.environ.get("TEMP", os.path.expandvars("%TEMP%")), "YTMusicBot_BrowserProfile"
)


# ════════════════════════════════════════════════════════════════════
#  Minimal WebSocket client (RFC 6455) – no external dependencies
# ════════════════════════════════════════════════════════════════════

class _MiniWebSocket:
    """Bare-minimum WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        import random
        from urllib.parse import urlparse

        parsed = urlparse(url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or 80
        self._path = parsed.path or "/"
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._key = bytes(random.getrandbits(8) for _ in range(16))

    def connect(self) -> None:
        """Open TCP connection and perform WebSocket handshake."""
        import base64

        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._sock.settimeout(self._timeout)

        # WebSocket upgrade request
        key_b64 = base64.b64encode(self._key).decode()
        handshake = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key_b64}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self._sock.sendall(handshake.encode())

        # Read response until double-CRLF
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed: connection closed")
            response += chunk

        if b"101" not in response.split(b"\r\n")[0]:
            raise ConnectionError(f"WebSocket handshake failed: {response[:200]}")

    def send(self, data: str) -> None:
        """Send a text frame."""
        payload = data.encode("utf-8")
        length = len(payload)
        mask = os.urandom(4)

        # Build header
        header = bytearray()
        header.append(0x81)  # FIN + text frame
        if length < 126:
            header.append(0x80 | length)  # masked
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)

        # Masked payload
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + bytes(masked))

    def recv(self) -> str:
        """Receive one text frame."""
        # Read 2-byte header
        h1, h2 = self._recv_exact(2)
        opcode = h1 & 0x0F
        masked = bool(h2 & 0x80)
        length = h2 & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]

        if masked:
            mask = self._recv_exact(4)

        payload = bytearray(self._recv_exact(length))

        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]

        if opcode == 0x8:
            raise ConnectionError("WebSocket closed by peer")
        if opcode == 0x9:  # ping → pong
            self._send_pong(bytes(payload))
            return self.recv()

        return payload.decode("utf-8")

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _send_pong(self, payload: bytes) -> None:
        header = bytearray([0x8A, len(payload)])
        self._sock.sendall(bytes(header) + payload)


# ════════════════════════════════════════════════════════════════════
#  YTMusicService
# ════════════════════════════════════════════════════════════════════

class YTMusicService:
    """YouTube Music service using Chrome DevTools Protocol for auth and data."""

    def __init__(self) -> None:
        self._load_token()

    # ── Token persistence ──────────────────────────────────────────

    def _load_token(self) -> None:
        path = Path(YTMUSIC_BROWSER_FILE)
        if path.exists():
            logger.info("[YT] Browser file at %s", path)
        else:
            logger.info("[YT] No browser file at %s", path)

    def _save_browser_dict(self, headers: dict[str, str]) -> bool:
        path = Path(YTMUSIC_BROWSER_FILE)
        try:
            init = {
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
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
        self._load_token()

    @property
    def is_authorized(self) -> bool:
        """Check if Chrome debug port is active (our source of truth)."""
        return self._is_chrome_debug_running()

    # ── CDP helpers ─────────────────────────────────────────────

    @staticmethod
    def _cdp_get_page_ws() -> str | None:
        """Get WebSocket URL for the first page tab in Chrome."""
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{_CDP_PORT}/json", timeout=3) as resp:
                tabs = json.loads(resp.read())
            for t in tabs:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
            if tabs:
                return tabs[0].get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None

    @staticmethod
    def _cdp_send_cmd(ws: _MiniWebSocket, method: str, params: dict | None = None, timeout_s: float = 10) -> dict | None:
        """Send a CDP command and wait for its response."""
        import random
        cmd_id = random.randint(1, 999999)
        msg = {"id": cmd_id, "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == cmd_id:
                return data
        return None

    @staticmethod
    def _cdp_js(ws: _MiniWebSocket, expression: str, timeout_s: float = 10) -> Any:
        """Evaluate JavaScript in Chrome and return the value."""
        r = YTMusicService._cdp_send_cmd(ws, "Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout_s)
        if r and "result" in r:
            return r["result"].get("result", {}).get("value")
        return None

    # ── Chrome DevTools Protocol (CDP) cookie extraction ──────────

    @staticmethod
    def _is_chrome_debug_running() -> bool:
        """Check if Chrome is reachable on the debug port."""
        try:
            s = socket.create_connection(("127.0.0.1", _CDP_PORT), timeout=2)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def _launch_chrome_with_debug() -> bool:
        """Launch browser with --remote-debugging-port in a SEPARATE profile.

        Uses config.BROWSER to choose between 'edge' and 'chrome'.
        """
        if YTMusicService._is_chrome_debug_running():
            return True

        browser_name = BROWSER.lower().strip()

        if browser_name == "chrome":
            browser_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ]
        else:  # edge (default)
            browser_paths = [
                os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            ]

        browser_exe = None
        for p in browser_paths:
            if os.path.isfile(p):
                browser_exe = p
                break

        if not browser_exe:
            logger.warning("[CDP] %s not found on system", browser_name)
            return False

        # Use separate profile (main profile can't bind debug port)
        os.makedirs(_BOT_BROWSER_PROFILE, exist_ok=True)

        try:
            subprocess.Popen(
                [
                    browser_exe,
                    _BROWSER_DEBUG_ARG,
                    f"--user-data-dir={_BOT_BROWSER_PROFILE}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "https://music.youtube.com",
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for _ in range(15):
                time.sleep(0.5)
                if YTMusicService._is_chrome_debug_running():
                    logger.info("[CDP] %s launched with debug port %d", browser_name, _CDP_PORT)
                    return True
            logger.warning("[CDP] %s launched but debug port not ready", browser_name)
            return False
        except Exception:
            logger.exception("[CDP] Failed to launch %s", browser_name)
            return False

    @staticmethod
    def _cdp_extract_cookies() -> dict[str, str] | None:
        """Extract YouTube Music cookies from running Chrome via DevTools Protocol.

        Uses PAGE-level WebSocket (not browser-level) because Storage.getCookies
        only works on page targets.
        """
        import urllib.request

        # Step 1: Get a PAGE-level WebSocket URL (NOT browser-level)
        try:
            tabs_url = f"http://127.0.0.1:{_CDP_PORT}/json"
            with urllib.request.urlopen(tabs_url, timeout=3) as resp:
                tabs = json.loads(resp.read())
            # Find first page tab
            page_ws = None
            for t in tabs:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    page_ws = t["webSocketDebuggerUrl"]
                    break
            if not page_ws and tabs:
                page_ws = tabs[0].get("webSocketDebuggerUrl")
            if not page_ws:
                logger.error("[CDP] No page tabs found")
                return None
            logger.info("[CDP] Page WebSocket: %s", page_ws[:60])
        except Exception:
            logger.exception("[CDP] Failed to reach Chrome debug port")
            return None

        # Step 2: Connect to PAGE tab and get cookies
        ws = _MiniWebSocket(page_ws, timeout=5)
        try:
            ws.connect()

            # Navigate to YouTube Music to ensure cookies are available
            ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": "https://music.youtube.com"},
            }))
            # Drain events until we get id:1
            for _ in range(20):
                raw = ws.recv()
                data = json.loads(raw)
                if data.get("id") == 1:
                    break
            time.sleep(3)  # Wait for page load

            # Get cookies via Storage domain (works on page-level target)
            ws.send(json.dumps({"id": 2, "method": "Storage.enable"}))
            for _ in range(5):
                raw = ws.recv()
                if json.loads(raw).get("id") == 2:
                    break

            ws.send(json.dumps({"id": 3, "method": "Storage.getCookies"}))
            for _ in range(10):
                raw = ws.recv()
                data = json.loads(raw)
                if data.get("id") == 3:
                    break

            response = data
        finally:
            ws.close()

        cookies = response.get("result", {}).get("cookies", [])
        logger.info("[CDP] Storage.getCookies returned %d cookies", len(cookies))

        if not cookies:
            logger.error("[CDP] No cookies returned from Chrome")
            return None

        logger.info("[CDP] Got %d cookies from Chrome, filtering for YouTube…", len(cookies))

        # Step 3: Filter and build headers
        cookie_parts: list[str] = []
        sapisid_value = ""

        for c in cookies:
            domain = c.get("domain", "")
            name = c.get("name", "")
            value = c.get("value", "")

            if "youtube" not in domain and "google" not in domain:
                continue
            # Only include cookies from music.youtube.com or .youtube.com
            if not (domain.endswith(".youtube.com") or domain.endswith(".music.youtube.com")
                    or domain.endswith(".google.com")):
                continue

            cookie_parts.append(f"{name}={value}")
            if name == "__Secure-3PAPISID":
                sapisid_value = value

        if not cookie_parts:
            logger.error("[CDP] No YouTube cookies found in Chrome")
            return None

        if not sapisid_value:
            logger.error("[CDP] __Secure-3PAPISID not found — are you logged in to YouTube Music?")
            return None

        cookie_str = "; ".join(cookie_parts)

        # Compute SAPISIDHASH
        origin = "https://music.youtube.com"
        unix_ts = str(int(time.time()))
        sha_input = f"{unix_ts} {sapisid_value} {origin}"
        sha_hash = hashlib.sha1(sha_input.encode("utf-8")).hexdigest()
        authorization = f"SAPISIDHASH {unix_ts}_{sha_hash}"

        headers = {
            "cookie": cookie_str,
            "authorization": authorization,
            "x-goog-authuser": "0",
        }

        logger.info(
            "[CDP] Built headers: %d cookies, auth=%s…",
            len(cookie_parts), authorization[:40],
        )
        return headers

    def try_auto_refresh(self) -> bool:
        """Ensure Chrome with debug port is running."""
        if self._is_chrome_debug_running():
            return True
        return self._launch_chrome_with_debug()

    # ── OAuth (disabled — broken server-side) ─────────────────────

    def oauth_start(self) -> dict | None:
        try:
            import requests
            from ytmusicapi.auth.oauth.credentials import OAuthCredentials

            session = requests.Session()
            creds = OAuthCredentials(client_id=None, client_secret=None, session=session)
            code = creds.get_code()
            url = f"{code['verification_url']}?user_code={code['user_code']}"
            self._oauth_creds = creds
            return {
                "url": url,
                "user_code": code["user_code"],
                "device_code": code["device_code"],
            }
        except Exception:
            logger.exception("[YT] OAuth start failed")
            return None

    def oauth_finish(self, device_code: str) -> bool:
        try:
            from ytmusicapi.auth.oauth.token import RefreshingToken

            creds = getattr(self, "_oauth_creds", None)
            if not creds:
                return False

            raw_token = creds.token_from_code(device_code)
            refresh_expires = raw_token.get("refresh_token_expires_in", raw_token["expires_in"])
            ref_token = RefreshingToken(
                credentials=creds,
                access_token=raw_token["access_token"],
                refresh_token=raw_token["refresh_token"],
                scope=raw_token["scope"],
                token_type=raw_token["token_type"],
                expires_in=refresh_expires,
            )
            ref_token.update(raw_token)

            oauth_path = Path(YTMUSIC_BROWSER_FILE).parent / "oauth.json"
            ref_token.local_cache = oauth_path
            ref_token.dump()

            self._yt = None
            try:
                self._yt = YTMusic(str(oauth_path))
                return True
            except Exception:
                logger.exception("[YT] Failed to load OAuth token")
                return False
        except Exception:
            logger.exception("[YT] OAuth finish failed")
            return False

    # ── Browser cookie extraction (browser_cookie3) ────────────────

    def extract_browser_cookies(self, browser: str = "chrome") -> dict[str, str] | None:
        try:
            import browser_cookie3
        except ImportError:
            logger.error("[YT] browser_cookie3 not installed")
            return None

        logger.info("[YT] Extracting cookies from %s…", browser)

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
                break
            except Exception as e:
                logger.warning("[YT] %s domain=%s failed: %s", browser, domain, e)
                continue

        if cj is None:
            return None

        cookie_parts: list[str] = []
        sapisid_value = ""

        for c in cj:
            if "youtube" not in c.domain and "google" not in c.domain:
                continue
            cookie_parts.append(f"{c.name}={c.value}")
            if c.name == "__Secure-3PAPISID":
                sapisid_value = c.value

        if not cookie_parts or not sapisid_value:
            return None

        cookie_str = "; ".join(cookie_parts)
        origin = "https://music.youtube.com"
        unix_ts = str(int(time.time()))
        sha_input = f"{unix_ts} {sapisid_value} {origin}"
        sha_hash = hashlib.sha1(sha_input.encode("utf-8")).hexdigest()
        authorization = f"SAPISIDHASH {unix_ts}_{sha_hash}"

        return {
            "cookie": cookie_str,
            "authorization": authorization,
            "x-goog-authuser": "0",
        }

    # ── Netscape cookie parser ─────────────────────────────────────

    def parse_netscape_cookies(self, raw_text: str) -> dict[str, str] | None:
        cookie_parts: list[str] = []
        sapisid_value = ""

        for line in raw_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
            if "youtube" not in domain and "google" not in domain:
                continue
            cookie_parts.append(f"{name}={value}")
            if name == "__Secure-3PAPISID":
                sapisid_value = value

        if not cookie_parts or not sapisid_value:
            return None

        cookie_str = "; ".join(cookie_parts)
        origin = "https://music.youtube.com"
        unix_ts = str(int(time.time()))
        sha_input = f"{unix_ts} {sapisid_value} {origin}"
        sha_hash = hashlib.sha1(sha_input.encode("utf-8")).hexdigest()
        authorization = f"SAPISIDHASH {unix_ts}_{sha_hash}"

        return {
            "cookie": cookie_str,
            "authorization": authorization,
            "x-goog-authuser": "0",
        }

    # ── Liked songs via CDP ──────────────────────────────────────

    def get_liked_songs(self, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch liked songs from Chrome via DevTools Protocol DOM scraping.
        
        Navigates to music.youtube.com/librarylikedmusic, waits for page to load,
        scrolls to load more tracks, and extracts videoId/title/artist from the DOM.
        """
        ws_url = self._cdp_get_page_ws()
        if not ws_url:
            raise RuntimeError("Chrome debug port not active")

        logger.info("[CDP] Fetching liked songs via DOM scraping...")
        ws = _MiniWebSocket(ws_url, timeout=15)
        try:
            ws.connect()

            # Navigate directly to the liked songs playlist URL
            self._cdp_send_cmd(ws, "Page.navigate", {
                "url": "https://music.youtube.com/playlist?list=LM"
            })
            time.sleep(8)  # Wait for SPA load + JS rendering

            # Scroll down multiple times to load more tracks
            for i in range(min(limit // 100 + 1, 10)):
                self._cdp_js(ws, 'window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(2)

            # Extract tracks from DOM
            result = self._cdp_js(ws, '''
                (() => {
                    const items = document.querySelectorAll('ytmusic-responsive-list-item-renderer');
                    const tracks = [];
                    items.forEach(item => {
                        const link = item.querySelector('a');
                        const href = link ? link.getAttribute('href') || '' : '';
                        const match = href.match(/v=([A-Za-z0-9_-]{11})/);
                        const titleEl = item.querySelector('.title-column yt-formatted-string') || item.querySelector('#title');
                        const title = titleEl ? titleEl.textContent.trim() : '';
                        const artists = [];
                        item.querySelectorAll('.secondary-flex-columns yt-formatted-string a').forEach(a => {
                            const h = a.getAttribute('href') || '';
                            if (h.includes('channel') || h.includes('browse'))
                                artists.push(a.textContent.trim());
                        });
                        if (match) {
                            tracks.push({
                                id: match[1],
                                title: title,
                                artists: artists.join(', ') || 'Unknown Artist',
                            });
                        }
                    });
                    return JSON.stringify(tracks);
                })()
            ''', timeout_s=15)

        finally:
            ws.close()

        if not result:
            logger.error("[CDP] DOM scraping returned nothing")
            return []

        raw_tracks = json.loads(result)
        logger.info("[CDP] Scraped %d tracks from DOM", len(raw_tracks))

        tracks: list[dict[str, Any]] = []
        for t in raw_tracks[:limit]:
            tracks.append({
                "video_id": t["id"],
                "title": t.get("title", "Unknown"),
                "artists": t.get("artists", "Unknown Artist"),
                "album": "",
                "duration": "",
                "thumbnails": [],
            })

        if tracks:
            logger.info("[CDP] Sample: %s — %s", tracks[0]["title"], tracks[0]["artists"])
        return tracks

    # ── Audio download ─────────────────────────────────────────────

    @staticmethod
    def _write_netscape_cookies_file() -> str | None:
        """Convert browser.json → Netscape cookies.txt for yt-dlp.

        Handles two formats:
        1. CDP list: [{"domain": ".youtube.com", "name": "SID", "value": "...", ...}]
        2. ytmusicapi headers: {"cookie": "SID=...; SSID=..."} (parsed from string)
        """
        browser_path = Path(YTMUSIC_BROWSER_FILE)
        if not browser_path.exists():
            return None

        try:
            with open(browser_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        lines = ["# Netscape HTTP Cookie File\n"]
        count = 0

        # Format 1: list of cookie objects (CDP format)
        cookies = data if isinstance(data, list) else data.get("cookies", [])
        if cookies:
            for c in cookies:
                domain = c.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                expires = str(int(c.get("expires", 0)))
                name = c.get("name", "")
                value = c.get("value", "")
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                count += 1

        # Format 2: ytmusicapi headers dict with "cookie" string
        if count == 0 and isinstance(data, dict) and "cookie" in data:
            cookie_str = data["cookie"]
            for part in cookie_str.split("; "):
                part = part.strip()
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name = name.strip()
                value = value.strip()
                # Guess domain from name
                if name.startswith("__Secure"):
                    domain = ".youtube.com"
                    secure = "TRUE"
                elif name in ("SID", "SSID", "HSID", "APISID", "SAPISID", "NID"):
                    domain = ".youtube.com"
                    secure = "TRUE" if name == "SAPISID" or name.startswith("__Secure") else "FALSE"
                elif "_ga" in name or name == "_gcl_au":
                    domain = ".youtube.com"
                    secure = "FALSE"
                else:
                    domain = ".youtube.com"
                    secure = "FALSE"
                lines.append(f"{domain}\tTRUE\t/\t{secure}\t0\t{name}\t{value}\n")
                count += 1

        if count == 0:
            return None

        cookie_file = str(browser_path.parent / "yt_dlp_cookies.txt")
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info("[YT] Wrote %d cookies to %s for yt-dlp", count, cookie_file)
        return cookie_file

    def download_audio(self, video_id: str, output_dir: str = "/tmp/yt_audio") -> str | None:
        """Download audio via CDP — intercepts streaming URL from running Edge browser.

        Uses browser cookies + Range: 0- to download the full audio file.
        """
        from urllib.parse import urlparse, parse_qs, urlencode

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{video_id}.mp3")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path

        if not self._is_chrome_debug_running():
            logger.warning("[CDP] Browser not running, cannot download audio")
            return None

        logger.info("[CDP] Downloading audio for %s…", video_id)

        try:
            result = self._cdp_get_audio_for_download(video_id)
            if not result:
                logger.warning("[CDP] No audio URL intercepted for %s", video_id)
                return None

            audio_url, cookie_str = result

            # Modify URL: set range=0- to get full file
            parsed = parse_qs(urlparse(audio_url).query)
            params = dict(parsed)
            params["range"] = ["0-"]
            params.pop("rn", None)
            download_url = f"{urlparse(audio_url).scheme}://{urlparse(audio_url).netloc}{urlparse(audio_url).path}?{urlencode(params, doseq=True)}"

            # Download with browser cookies
            import urllib.request
            req = urllib.request.Request(download_url)
            if cookie_str:
                req.add_header("Cookie", cookie_str)
            req.add_header("User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Edge/131.0.0.0 Safari/537.36")
            req.add_header("Referer", "https://music.youtube.com/")
            req.add_header("Origin", "https://music.youtube.com")

            resp = urllib.request.urlopen(req, timeout=60)
            audio_data = resp.read()

            if len(audio_data) < 10000:
                logger.warning("[CDP] Audio too small (%d bytes) for %s", len(audio_data), video_id)
                return None

            # Strip YouTube UMP protobuf wrapper — find WebM EBML header
            webm_magic = bytes([0x1a, 0x45, 0xdf, 0xa3])
            audio_start = audio_data.find(webm_magic)
            if audio_start > 0:
                audio_data = audio_data[audio_start:]
                logger.info("[CDP] Stripped %d bytes of UMP wrapper", audio_start)

            # Save as webm
            webm_path = os.path.join(output_dir, f"{video_id}.webm")
            with open(webm_path, "wb") as f:
                f.write(audio_data)
            logger.info("[CDP] Downloaded %d bytes for %s", len(audio_data), video_id)

            # Convert to mp3 via ffmpeg
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                logger.warning("[CDP] ffmpeg not available, returning webm")
                return webm_path

            import subprocess
            try:
                subprocess.run(
                    [ffmpeg_path, "-y", "-i", webm_path,
                     "-codec:a", "libmp3lame", "-q:a", "2",
                     "-loglevel", "error", output_path],
                    check=True, timeout=120,
                )
                os.remove(webm_path)
                return output_path
            except Exception:
                logger.warning("[CDP] ffmpeg conversion failed, returning webm")
                return webm_path

        except Exception:
            logger.exception("[CDP] Audio download FAILED for %s", video_id)
            return None

    @staticmethod
    def _cdp_get_audio_for_download(video_id: str) -> tuple[str, str] | None:
        """Navigate to video via CDP, return (audio_url, cookie_str).

        Returns the audio streaming URL and browser cookies needed to download it.
        """
        from urllib.parse import urlparse, parse_qs, urlencode
        import urllib.request as _urllib_request

        tabs_url = f"http://127.0.0.1:{_CDP_PORT}/json"
        try:
            with _urllib_request.urlopen(tabs_url, timeout=3) as resp:
                tabs = json.loads(resp.read())
        except Exception:
            logger.error("[CDP] Cannot reach debug port")
            return None

        page_ws = None
        for t in tabs:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                page_ws = t["webSocketDebuggerUrl"]
                break
        if not page_ws:
            logger.error("[CDP] No page tabs")
            return None

        ws = _MiniWebSocket(page_ws, timeout=15)
        try:
            ws.connect()

            # Enable Fetch BEFORE navigation to catch audio requests
            ws.send(json.dumps({
                "id": 2, "method": "Fetch.enable",
                "params": {
                    "patterns": [{
                        "urlPattern": "*googlevideo.com/videoplayback*",
                        "requestStage": "Request",
                    }]
                },
            }))
            for _ in range(5):
                raw = ws.recv()
                if json.loads(raw).get("id") == 2:
                    break

            # Navigate to video
            ws.send(json.dumps({
                "id": 1, "method": "Page.navigate",
                "params": {"url": f"https://music.youtube.com/watch?v={video_id}"},
            }))
            for _ in range(10):
                raw = ws.recv()
                if json.loads(raw).get("id") == 1:
                    break

            # Get cookies from browser
            ws.send(json.dumps({
                "id": 10, "method": "Network.getCookies",
                "params": {"urls": ["https://www.youtube.com"]},
            }))
            cookie_str = ""
            for _ in range(10):
                raw = ws.recv()
                d = json.loads(raw)
                if d.get("id") == 10:
                    cookies = d.get("result", {}).get("cookies", [])
                    cookie_str = "; ".join(
                        f"{c['name']}={c['value']}" for c in cookies
                    )
                    break

            audio_url = None
            start = time.time()
            while time.time() - start < 12:
                try:
                    raw = ws.recv()
                except Exception:
                    break
                data = json.loads(raw)

                if data.get("method") == "Fetch.requestPaused":
                    req_id = data["params"]["requestId"]
                    url = data["params"]["request"]["url"]

                    parsed = parse_qs(urlparse(url).query)
                    mime = parsed.get("mime", [""])[0]

                    ws.send(json.dumps({
                        "id": 200, "method": "Fetch.continueRequest",
                        "params": {"requestId": req_id},
                    }))

                    if "audio" in mime and not audio_url:
                        audio_url = url
                        logger.info("[CDP] Captured audio URL: mime=%s", mime)
                        break

            if audio_url:
                return (audio_url, cookie_str)
            return None

        finally:
            ws.close()

    @staticmethod
    def cleanup_audio(video_id: str, output_dir: str = "/tmp/yt_audio") -> None:
        import glob
        for f in glob.glob(os.path.join(output_dir, f"{video_id}.*")):
            try:
                os.remove(f)
            except OSError:
                pass
