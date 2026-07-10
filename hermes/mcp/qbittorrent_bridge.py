"""Minimal, allow-listed qBittorrent Web API bridge for Hermes Agent.

The bridge deliberately exposes no delete/remove operation. Credentials are
read only from environment variables or a local secret file and are never
returned by a tool.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.request
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPHandler

from mcp.server.fastmcp import FastMCP


logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("blink.qbittorrent")

BASE_URL = os.environ.get("QBITTORRENT_BASE_URL", "http://qbittorrent_server_1:8080").rstrip("/")
USERNAME = os.environ.get("QBITTORRENT_USERNAME", "admin")
PASSWORD_FILE = os.environ.get("QBITTORRENT_PASSWORD_FILE", "/opt/data/secrets/qbittorrent_password")
TIMEOUT = float(os.environ.get("QBITTORRENT_TIMEOUT", "15"))

CATEGORY_PATHS = {
    "filmes": "/media/Filmes",
    "series": "/media/Series",
    "animes": "/media/Animes",
}
ALLOWED_FILTERS = {
    "all", "downloading", "seeding", "completed", "paused", "active",
    "inactive", "resumed", "stalled", "stalled_uploading",
    "stalled_downloading", "errored",
}
HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class QBitTorrentError(RuntimeError):
    """An actionable qBittorrent bridge error."""


class QBitTorrentClient:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPHandler(), urllib.request.HTTPCookieProcessor(self.cookies))
        self.authenticated = False

    def _password(self) -> str:
        inline = os.environ.get("QBITTORRENT_PASSWORD", "").strip()
        if inline:
            return inline
        try:
            with open(PASSWORD_FILE, "r", encoding="utf-8") as handle:
                password = handle.read().strip()
        except FileNotFoundError as exc:
            raise QBitTorrentError(
                "qBittorrent credentials are not configured. Set "
                "QBITTORRENT_PASSWORD_FILE or QBITTORRENT_PASSWORD in the Hermes secret store."
            ) from exc
        if not password:
            raise QBitTorrentError("The qBittorrent password secret is empty.")
        return password

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": f"{BASE_URL}/",
            "Origin": BASE_URL,
            "User-Agent": "Blink-qBittorrent-MCP/1.0",
        }

    def _open(self, method: str, path: str, *, form: dict[str, Any] | None = None,
              query: dict[str, Any] | None = None, retry: bool = True) -> bytes:
        url = f"{BASE_URL}{path}"
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        data = None
        headers = self._headers()
        if form is not None:
            data = urlencode({k: v for k, v in form.items() if v is not None}).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return response.read()
        except HTTPError as exc:
            if retry and exc.code in (401, 403):
                self.login()
                return self._open(method, path, form=form, query=query, retry=False)
            detail = exc.read(512).decode("utf-8", "replace").strip()
            raise QBitTorrentError(f"qBittorrent API returned HTTP {exc.code}: {detail[:240]}") from exc
        except URLError as exc:
            raise QBitTorrentError(f"Cannot reach qBittorrent at {BASE_URL}: {exc.reason}") from exc

    def login(self) -> None:
        body = self._open(
            "POST",
            "/api/v2/auth/login",
            form={"username": USERNAME, "password": self._password()},
            retry=False,
        )
        self.authenticated = True
        if body and body.strip().lower() not in (b"ok.", b"ok"):
            log.debug("qBittorrent login returned a non-Ok body")

    def call(self, method: str, path: str, *, form: dict[str, Any] | None = None,
             query: dict[str, Any] | None = None) -> bytes:
        if not self.authenticated:
            self.login()
        return self._open(method, path, form=form, query=query)

    def json(self, method: str, path: str, *, form: dict[str, Any] | None = None,
             query: dict[str, Any] | None = None) -> Any:
        raw = self.call(method, path, form=form, query=query)
        if not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QBitTorrentError("qBittorrent returned invalid JSON.") from exc


def _client() -> QBitTorrentClient:
    return QBitTorrentClient()


def _category(value: str | None) -> str:
    category = (value or "").strip().lower()
    if category and category not in CATEGORY_PATHS:
        raise ValueError("category must be one of: filmes, series, animes, or empty")
    return category


def _hashes(values: list[str]) -> str:
    if not values or len(values) > 50:
        raise ValueError("Provide between 1 and 50 torrent hashes")
    if any(not HASH_RE.fullmatch(value or "") for value in values):
        raise ValueError("Every torrent hash must be a 40-character hexadecimal hash")
    return "|".join(values)


mcp = FastMCP("qbittorrent-bridge")


@mcp.tool()
def qbt_add_torrent(source: str, category: str = "") -> dict[str, Any]:
    """Add an authorized magnet or .torrent URL to qBittorrent.

    Use only for content the user owns or is legally authorized to download.
    Category routing is allow-listed and deletion is intentionally unavailable.
    """
    source = (source or "").strip()
    if not source or len(source) > 8192:
        raise ValueError("source must be a non-empty magnet or HTTP(S) URL")
    if not (source.startswith("magnet:?") or source.startswith("http://") or source.startswith("https://")):
        raise ValueError("source must be a magnet, HTTP URL, or HTTPS URL")
    selected = _category(category)
    response = _client().call(
        "POST",
        "/api/v2/torrents/add",
        form={"urls": source, "category": selected},
    ).decode("utf-8", "replace").strip()
    if response.lower() not in ("ok.", "ok", ""):
        raise QBitTorrentError(f"qBittorrent rejected the torrent: {response[:240]}")
    return {
        "ok": True,
        "source_type": "magnet" if source.startswith("magnet:") else "torrent_url",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "category": selected or None,
        "save_path": CATEGORY_PATHS.get(selected, "/downloads"),
        "message": "Torrent accepted by qBittorrent.",
    }


@mcp.tool()
def qbt_list_torrents(filter: str = "all", category: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """List torrent status and progress without exposing credentials."""
    selected_filter = (filter or "all").strip().lower()
    if selected_filter not in ALLOWED_FILTERS:
        raise ValueError(f"filter must be one of: {', '.join(sorted(ALLOWED_FILTERS))}")
    selected_category = _category(category)
    limit = max(1, min(int(limit), 100))
    data = _client().json(
        "GET",
        "/api/v2/torrents/info",
        query={"filter": selected_filter, "category": selected_category or None, "limit": limit},
    )
    return [
        {
            "hash": item.get("hash"),
            "name": item.get("name"),
            "state": item.get("state"),
            "progress": item.get("progress"),
            "size": item.get("size"),
            "downloaded": item.get("downloaded"),
            "dlspeed": item.get("dlspeed"),
            "eta": item.get("eta"),
            "category": item.get("category"),
            "save_path": item.get("save_path"),
        }
        for item in (data if isinstance(data, list) else [])
    ]


@mcp.tool()
def qbt_get_torrent_status(torrent_hash: str) -> dict[str, Any]:
    """Get detailed status for one torrent by its 40-character hash."""
    if not HASH_RE.fullmatch((torrent_hash or "").strip()):
        raise ValueError("torrent_hash must be a 40-character hexadecimal hash")
    items = _client().json("GET", "/api/v2/torrents/info", query={"hashes": torrent_hash.strip()})
    if not items:
        return {"found": False, "hash": torrent_hash}
    return {"found": True, **items[0]}


@mcp.tool()
def qbt_pause_torrents(torrent_hashes: list[str]) -> dict[str, Any]:
    """Pause one or more torrents. Does not remove data."""
    value = _hashes(torrent_hashes)
    _client().call("POST", "/api/v2/torrents/pause", form={"hashes": value})
    return {"ok": True, "hashes": torrent_hashes, "action": "paused"}


@mcp.tool()
def qbt_resume_torrents(torrent_hashes: list[str]) -> dict[str, Any]:
    """Resume one or more torrents. Does not remove data."""
    value = _hashes(torrent_hashes)
    _client().call("POST", "/api/v2/torrents/resume", form={"hashes": value})
    return {"ok": True, "hashes": torrent_hashes, "action": "resumed"}


@mcp.tool()
def qbt_get_categories() -> dict[str, Any]:
    """Return configured qBittorrent categories and their internal save paths."""
    categories = _client().json("GET", "/api/v2/torrents/categories")
    return {"categories": categories, "default_path": "/downloads"}


@mcp.tool()
def qbt_get_status() -> dict[str, Any]:
    """Return qBittorrent version and transfer connection state."""
    client = _client()
    version = client.call("GET", "/api/v2/app/version").decode("utf-8", "replace").strip()
    transfer = client.json("GET", "/api/v2/transfer/info")
    return {
        "version": version,
        "connection_status": transfer.get("connection_status"),
        "dl_info_speed": transfer.get("dl_info_speed"),
        "up_info_speed": transfer.get("up_info_speed"),
        "free_space_on_disk": transfer.get("free_space_on_disk"),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
