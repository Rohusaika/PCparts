#!/usr/bin/env python3
"""Audit and resolve Kakaku.com item URLs conservatively.

Version 1.5 changes:
- Existing URLs can be audited and mismatched pages are cleared.
- CPU candidates require an exact model signature on the item page.
- Generic GPU families are not auto-resolved by default because one Kakaku item page is
  one board-partner product, not the cheapest card across the whole GPU family.
- Unverified candidates remain blank rather than being guessed.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from update_prices import CatalogItem, model_signature, page_identity, signatures_in_text, normalize

KNOWN_EXACT_URLS = {
    "AMD Ryzen 7 5700X": "https://kakaku.com/item/K0001429753/",
}

ITEM_RE = re.compile(r"https?://kakaku\.com/item/(K\d+)/?|/item/(K\d+)/?", re.I)


@dataclass
class Row:
    values: dict[str, str]
    index: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog.csv"))
    parser.add_argument("--report", type=Path, default=Path("url_resolution_report.json"))
    parser.add_argument("--limit", type=int, default=999)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--audit-existing", action="store_true")
    parser.add_argument("--include-gpu", action="store_true")
    return parser.parse_args()


def canonical_item_url(href: str) -> str | None:
    absolute = urljoin("https://kakaku.com/", href)
    match = ITEM_RE.search(absolute)
    if not match:
        return None
    item_id = match.group(1) or match.group(2)
    return f"https://kakaku.com/item/{item_id}/"


def make_item(values: dict[str, str]) -> CatalogItem:
    return CatalogItem(
        enabled=values.get("enabled", "1").strip().lower() not in {"0", "false", "no"},
        category=values.get("category", "").strip(),
        group=values.get("group", "").strip(),
        name=values.get("name", "").strip(),
        sort_score=int(values.get("sortScore", "0") or 0),
        kakaku_url=values.get("kakakuUrl", "").strip(),
        source_mode=(values.get("sourceMode", "fetch") or "fetch").strip().lower(),
    )


def fetch_soup(session: requests.Session, url: str, timeout: float) -> BeautifulSoup:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def candidate_urls(search_html: str, item: CatalogItem) -> list[str]:
    soup = BeautifulSoup(search_html, "html.parser")
    expected = model_signature(item.name)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = canonical_item_url(anchor.get("href", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        context_node = anchor.find_parent(["li", "article", "div", "tr"])
        context = normalize((context_node or anchor).get_text(" ", strip=True))
        signatures = signatures_in_text(context)
        score = 0
        if expected and expected in signatures:
            score += 200
        if item.category == "CPU" and "BOX" in context.upper():
            score += 10
        if any(word in context for word in ("デスクトップパソコン", "ノートパソコン", "搭載モデル", "ゲーミングPC")):
            score -= 300
        scored.append((score, url))
    scored.sort(reverse=True)
    return [url for score, url in scored if score >= 200][:12]


def resolve_one(session: requests.Session, item: CatalogItem, timeout: float) -> tuple[str | None, str]:
    if item.name in KNOWN_EXACT_URLS:
        return KNOWN_EXACT_URLS[item.name], "resolved from verified seed"
    if item.category == "GPU":
        return None, "GPU family auto-resolution is disabled; use an aggregate/manual source"
    query = item.name + " BOX"
    search_url = f"https://search.kakaku.com/{quote(query, safe='')}/"
    response = session.get(search_url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    urls = candidate_urls(response.text, item)
    if not urls:
        return None, "No exact item candidate on Kakaku search"

    for url in urls:
        soup = fetch_soup(session, url, timeout)
        ok, reason = page_identity(soup, item)
        if ok:
            return url, "resolved"
    return None, "Candidates existed, but no page passed exact model/category verification"


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
    attempted = resolved = cleared = verified = 0

    if args.audit_existing:
        for row in rows:
            item = make_item(row.values)
            if not item.enabled or item.source_mode != "fetch" or not item.kakaku_url:
                continue
            if item.category not in {"CPU", "GPU"}:
                continue
            attempted += 1
            try:
                soup = fetch_soup(session, item.kakaku_url, args.timeout)
                ok, message = page_identity(soup, item)
            except Exception as exc:
                ok, message = False, str(exc)
            if ok:
                verified += 1
                print(f"VERIFIED {item.name}: {item.kakaku_url}")
            else:
                old_url = item.kakaku_url
                row.values["kakakuUrl"] = ""
                cleared += 1
                print(f"CLEARED {item.name}: {old_url} ({message})")
            report.append({
                "line": row.index,
                "operation": "audit",
                "name": item.name,
                "url": item.kakaku_url,
                "kept": ok,
                "message": message,
            })
            if args.sleep > 0:
                time.sleep(args.sleep)

    resolve_attempts = 0
    for row in rows:
        item = make_item(row.values)
        if not item.enabled or item.source_mode != "fetch" or item.kakaku_url:
            continue
        if item.category not in {"CPU", "GPU"}:
            continue
        if item.category == "GPU" and not args.include_gpu:
            continue
        if resolve_attempts >= args.limit:
            break
        resolve_attempts += 1
        attempted += 1
        try:
            url, message = resolve_one(session, item, args.timeout)
        except Exception as exc:
            url, message = None, str(exc)
        if url:
            row.values["kakakuUrl"] = url
            resolved += 1
            print(f"RESOLVED {item.name}: {url}")
        else:
            print(f"UNRESOLVED {item.name}: {message}")
        report.append({
            "line": row.index,
            "operation": "resolve",
            "name": item.name,
            "url": url or "",
            "kept": bool(url),
            "message": message,
        })
        if args.sleep > 0:
            time.sleep(args.sleep)

    with args.catalog.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.values)

    args.report.write_text(json.dumps({
        "attempted": attempted,
        "verified": verified,
        "cleared": cleared,
        "resolved": resolved,
        "unresolved": resolve_attempts - resolved,
        "items": report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"URL audit/resolution complete: attempted={attempted} verified={verified} "
        f"cleared={cleared} resolved={resolved} unresolved={resolve_attempts-resolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
