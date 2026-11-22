"""Lightweight local HTTP server for the Imoti Aggregator visual dashboard + scrape API."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
PORT = 8000
OPEN_SOURCES = ["alo.bg", "imot.bg", "olx.bg", "bazar.bg", "imotisilvi.bg", "imotitomov.com"]
ALLOWED_PHOTO_HOSTS = {"www.imot.bg", "imot.bg", "www.alo.bg", "alo.bg", "bazar.bg", "www.bazar.bg", "www.olx.bg", "olx.bg", "imotisilvi.bg", "imotitomov.com"}
_photo_cache: dict[str, list[str]] = {}


def _extract_detail_photos(url: str) -> list[str]:
    if url in _photo_cache:
        return _photo_cache[url]
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_PHOTO_HOSTS:
        return []
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            follow_redirects=True,
            timeout=15.0,
        )
        if r.status_code != 200:
            return []
        enc = "windows-1251" if "imot.bg" in (parsed.hostname or "") else "utf-8"
        html = r.content.decode(enc, errors="replace")
    except Exception:
        return []

    photos: list[str] = []
    host = parsed.hostname or ""

    if "imot.bg" in host:
        # Filter strictly to this listing's own ID (ignore "Подобни обяви" at bottom of page)
        m_id = re.search(r"obiava-([a-z0-9]+)-", url, re.I)
        ad_id = m_id.group(1) if m_id else ""
        raw_matches = re.findall(r"(?:https?:)?//[^\s\"'<>]+/photosimotbg/[^\s\"'<>]+\.(?:jpg|jpeg|webp|png)", html, re.I)
        seen_keys: set[str] = set()
        for m in raw_matches:
            if ad_id and ad_id not in m:
                continue
            u = f"https:{m}" if m.startswith("//") else m
            # Upgrade /med/ or small thumb to /big/ if applicable, dedupe by filename
            fname = u.rsplit("/", 1)[-1].split("?")[0]
            if fname in seen_keys:
                continue
            seen_keys.add(fname)
            photos.append(u)
    elif "alo.bg" in host:
        m_id = re.search(r"-(\d{6,})(?:/|$|\?)", url)
        ad_id = m_id.group(1) if m_id else ""
        seen_keys: set[str] = set()
        for m in re.findall(r"(?:https?://www\.alo\.bg/)?user_files/[^\s\"'<>]+?\.(?:jpg|jpeg|webp|png)", html, re.I):
            if "_avatar" in m or "logo" in m.lower():
                continue
            if ad_id and f"/{ad_id}_" not in m:
                continue
            u = m if m.startswith("http") else f"https://www.alo.bg/{m.lstrip('/')}"
            u = u.replace("_medium.", "_big.").replace("_small.", "_big.")
            fname = u.rsplit("/", 1)[-1].split("?")[0]
            if fname in seen_keys:
                continue
            seen_keys.add(fname)
            photos.append(u)
    elif "bazar.bg" in host:
        for m in re.findall(r"(?:https?:)?//cdn\d*\.focus\.bg/bazar/[^\s\"'<>]+\.(?:jpg|jpeg|webp|png)", html, re.I):
            photos.append(f"https:{m}" if m.startswith("//") else m)
    elif "olx.bg" in host:
        for m in re.findall(r"https://[^\s\"'<>]+olxcdn\.com[^\s\"'<>]+/image;s=\d+x\d+[^\s\"'<>]*", html, re.I):
            clean = re.sub(r"s=\d+x\d+[^\"'\s]*", "s=1000x700", m)
            photos.append(clean)
    else:
        soup = BeautifulSoup(html, "lxml")
        for img in soup.select("img"):
            src = img.get("data-lazy-src") or img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:") or "logo" in src.lower() or "avatar" in src.lower():
                continue
            photos.append(urljoin(url, src))

    # Deduplicate preserving order, cap at 30
    deduped = list(dict.fromkeys(photos))[:30]
    _photo_cache[url] = deduped
    return deduped

_scrape_lock = threading.Lock()
_scrape_state: dict = {
    "running": False,
    "last_status": "idle",
    "last_message": "",
    "last_finished_at": None,
}


def _run_scrape_worker(regions: list[str], pages: int) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "main.py"),
        "--append",
        "--sources",
        *OPEN_SOURCES,
        "--regions",
        *regions,
        "--transactions",
        "sale",
        "--pages",
        str(pages),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-4:])
        with _scrape_lock:
            _scrape_state["running"] = False
            _scrape_state["last_status"] = "ok" if proc.returncode == 0 else "error"
            _scrape_state["last_message"] = tail
            _scrape_state["last_finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        with _scrape_lock:
            _scrape_state["running"] = False
            _scrape_state["last_status"] = "error"
            _scrape_state["last_message"] = str(exc)
            _scrape_state["last_finished_at"] = datetime.now(timezone.utc).isoformat()


class ViewerHandler(SimpleHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/photos"):
            qs = parse_qs(urlparse(self.path).query)
            target_url = (qs.get("url") or [""])[0]
            photos = _extract_detail_photos(target_url) if target_url else []
            self._send_json(200, {"url": target_url, "count": len(photos), "photos": photos})
            return
        if self.path.startswith("/api/scrape/status"):
            with _scrape_lock:
                self._send_json(200, dict(_scrape_state))
            return
        if self.path in ("/", ""):
            self.path = "/viewer.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/scrape"):
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
            try:
                req = json.loads(body or "{}")
            except json.JSONDecodeError:
                req = {}

            reg = req.get("region", "")
            regions = [reg] if reg in ("shumen", "varna") else ["shumen", "varna"]
            pages = max(1, min(int(req.get("pages", 1) or 1), 3))

            with _scrape_lock:
                if _scrape_state["running"]:
                    self._send_json(409, {"error": "Вече тече обновяване.", **_scrape_state})
                    return
                _scrape_state["running"] = True
                _scrape_state["last_status"] = "running"
                _scrape_state["last_message"] = f"Скрейпване ({', '.join(regions)}, {pages} стр.)..."

            t = threading.Thread(target=_run_scrape_worker, args=(regions, pages), daemon=True)
            t.start()
            self._send_json(202, {"started": True, "regions": regions, "pages": pages})
            return

        self.send_error(404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()


if __name__ == "__main__":
    handler = partial(ViewerHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print(f"Serving Imoti Aggregator UI at http://127.0.0.1:{PORT}")
    server.serve_forever()
