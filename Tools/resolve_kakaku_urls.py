#!/usr/bin/env python3
"""Resolve blank Kakaku.com item URLs in catalog.csv.

This is intentionally a separate, manually-triggered operation. It searches Kakaku.com,
verifies that a candidate page contains the exact model token and the expected category,
and writes only high-confidence matches. Unresolved rows remain blank and are recorded in
url_resolution_report.json rather than being guessed.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ITEM_RE = re.compile(r"https?://kakaku\.com/item/(K\d+)/?|/item/(K\d+)/?", re.I)
SPACE_RE = re.compile(r"\s+")


@dataclass
class Row:
    values: dict[str, str]
    index: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog.csv"))
    parser.add_argument("--report", type=Path, default=Path("url_resolution_report.json"))
    parser.add_argument("--limit", type=int, default=999, help="Maximum blank fetch rows to attempt.")
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=25.0)
    return parser.parse_args()


def normalize(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def model_token(name: str) -> str:
    patterns = [
        r"\b\d{3,5}(?:KF|K|F|X3D2|X3D|3D2|3D|X|G)?\b",
        r"\b(?:RTX|RX)\s*\d{4}(?:\s*Ti(?:\s*SUPER)?|\s*SUPER|\s*XTX|\s*XT|\s*GRE)?\b",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, name, flags=re.I)
        if matches:
            return normalize(matches[-1]).upper().replace(" ", "")
    return normalize(name).upper().replace(" ", "")


def canonical_item_url(href: str) -> str | None:
    absolute = urljoin("https://kakaku.com/", href)
    match = ITEM_RE.search(absolute)
    if not match:
        return None
    item_id = match.group(1) or match.group(2)
    return f"https://kakaku.com/item/{item_id}/"


def category_matches(category: str, heading_text: str, page_text: str) -> bool:
    heading = heading_text.lower()
    text = page_text.lower()
    pc_words = ("デスクトップパソコン", "ノートパソコン", "ゲーミングpc")
    if any(word in heading for word in pc_words):
        return False
    if category == "CPU":
        return "cpu" in text
    if category == "GPU":
        return any(word in text for word in ("グラフィックボード", "ビデオカード"))
    return False


def token_matches(token: str, text: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    compact_token = re.sub(r"[^A-Z0-9]", "", token.upper())
    return compact_token in compact


def candidate_urls(search_html: str, item_name: str) -> list[str]:
    soup = BeautifulSoup(search_html, "html.parser")
    token = model_token(item_name)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = canonical_item_url(anchor.get("href", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        context_node = anchor.find_parent(["li", "article", "div", "tr"])
        context = normalize((context_node or anchor).get_text(" ", strip=True))
        score = 0
        if token_matches(token, context):
            score += 100
        if "BOX" in context.upper():
            score += 5
        if any(word in context for word in ("デスクトップパソコン", "ノートパソコン", "搭載モデル", "ゲーミングPC")):
            score -= 100
        scored.append((score, url))
    scored.sort(reverse=True)
    return [url for score, url in scored if score >= 100][:8]


def resolve_one(session: requests.Session, name: str, category: str, timeout: float) -> tuple[str | None, str]:
    token = model_token(name)
    query = name + (" BOX" if category == "CPU" else "")
    search_url = f"https://search.kakaku.com/{quote(query, safe='')}/"
    response = session.get(search_url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    urls = candidate_urls(response.text, name)
    if not urls:
        return None, "No exact item candidate on Kakaku search"

    for url in urls:
        page = session.get(url, timeout=timeout)
        page.raise_for_status()
        page.encoding = page.apparent_encoding or page.encoding
        soup = BeautifulSoup(page.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        h1 = soup.find("h1")
        heading = h1.get_text(" ", strip=True) if h1 else ""
        head_text = normalize(f"{title} {heading}")
        page_text = normalize(soup.get_text(" ", strip=True))[:20000]
        if token_matches(token, head_text) and category_matches(category, head_text, page_text):
            return url, "resolved"
    return None, f"Candidates found but none passed token/category verification ({token})"


def main() -> int:
    args = parse_args()
    with args.catalog.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("catalog.csv has no header")
        rows = [Row(dict(row), index) for index, row in enumerate(reader, start=2)]

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
    })

    report: list[dict[str, object]] = []
    attempted = resolved = 0
    for row in rows:
        values = row.values
        if values.get("enabled", "1").strip().lower() in {"0", "false", "no"}:
            continue
        if (values.get("sourceMode", "fetch") or "fetch").strip().lower() != "fetch":
            continue
        if values.get("kakakuUrl", "").strip():
            continue
        category = values.get("category", "").strip()
        if category not in {"CPU", "GPU"}:
            continue
        if attempted >= args.limit:
            break
        attempted += 1
        name = values.get("name", "").strip()
        try:
            url, message = resolve_one(session, name, category, args.timeout)
        except Exception as exc:  # continue the batch and report failure
            url, message = None, str(exc)
        if url:
            values["kakakuUrl"] = url
            resolved += 1
            print(f"RESOLVED {name}: {url}")
        else:
            print(f"UNRESOLVED {name}: {message}")
        report.append({"line": row.index, "name": name, "url": url or "", "message": message})
        if args.sleep > 0:
            time.sleep(args.sleep)

    with args.catalog.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.values)

    args.report.write_text(
        json.dumps(
            {"attempted": attempted, "resolved": resolved, "unresolved": attempted - resolved, "items": report},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"URL resolution complete: attempted={attempted} resolved={resolved} unresolved={attempted-resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
