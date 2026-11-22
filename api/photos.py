"""Vercel Python Serverless Function for on-demand listing photo extraction (/api/photos)."""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_PHOTO_HOSTS = {
    "www.imot.bg", "imot.bg",
    "www.alo.bg", "alo.bg",
    "bazar.bg", "www.bazar.bg",
    "www.olx.bg", "olx.bg",
    "imotisilvi.bg", "imotitomov.com",
}


def extract_detail_photos(url: str) -> list[str]:
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
        m_id = re.search(r"obiava-([a-z0-9]+)-", url, re.I)
        ad_id = m_id.group(1) if m_id else ""
        seen: set[str] = set()
        for m in re.findall(r"(?:https?:)?//[^\s\"'<>]+/photosimotbg/[^\s\"'<>]+\.(?:jpg|jpeg|webp|png)", html, re.I):
            if ad_id and ad_id not in m:
                continue
            u = f"https:{m}" if m.startswith("//") else m
            fname = u.rsplit("/", 1)[-1].split("?")[0]
            if fname in seen:
                continue
            seen.add(fname)
            photos.append(u)
    elif "alo.bg" in host:
        m_id = re.search(r"-(\d{6,})(?:/|$|\?)", url)
        ad_id = m_id.group(1) if m_id else ""
        seen: set[str] = set()
        for m in re.findall(r"(?:https?://www\.alo\.bg/)?user_files/[^\s\"'<>]+?\.(?:jpg|jpeg|webp|png)", html, re.I):
            if "_avatar" in m or "logo" in m.lower():
                continue
            if ad_id and f"/{ad_id}_" not in m:
                continue
            u = m if m.startswith("http") else f"https://www.alo.bg/{m.lstrip('/')}"
            u = u.replace("_medium.", "_big.").replace("_small.", "_big.")
            fname = u.rsplit("/", 1)[-1].split("?")[0]
            if fname in seen:
                continue
            seen.add(fname)
            photos.append(u)
    elif "bazar.bg" in host:
        for m in re.findall(r"(?:https?:)?//cdn\d*\.focus\.bg/bazar/[^\s\"'<>]+\.(?:jpg|jpeg|webp|png)", html, re.I):
            photos.append(f"https:{m}" if m.startswith("//") else m)
    elif "olx.bg" in host:
        for m in re.findall(r"https://[^\s\"'<>]+olxcdn\.com[^\s\"'<>]+/image;s=\d+x\d+[^\s\"'<>]*", html, re.I):
            photos.append(re.sub(r"s=\d+x\d+[^\"'\s]*", "s=1000x700", m))
    else:
        soup = BeautifulSoup(html, "lxml")
        for img in soup.select("img"):
            src = img.get("data-lazy-src") or img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:") or "logo" in src.lower() or "avatar" in src.lower():
                continue
            photos.append(urljoin(url, src))

    return list(dict.fromkeys(photos))[:30]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        target_url = (qs.get("url") or [""])[0]
        photos = extract_detail_photos(target_url) if target_url else []
        payload = json.dumps({"url": target_url, "count": len(photos), "photos": photos}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate")
        self.end_headers()
        self.wfile.write(payload)
