#!/usr/bin/env python3
"""Build a compact VRChat prices.json file.

Recommended operation:
  1. Keep product metadata and Kakaku.com item URLs in catalog.csv.
  2. Run once per day in Japan time.
  3. Host the generated JSON on GitHub Pages (*.github.io), which VRChat trusts.

The optional fetch mode parses user-specified Kakaku.com product pages and only accepts
shops in approved_shops.txt. Site structure and terms can change; confirm permission and
terms before automated/public use. Manual CSV overrides are supported for aggregates such
as the cheapest DDR4/DDR5 capacity and storage-interface buckets.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None

JST = ZoneInfo("Asia/Tokyo")
YEN_RE = re.compile(r"(?:¥|￥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,9})\s*円?")
SPACE_RE = re.compile(r"\s+")

SHOP_ALIASES = {
    "ドスパラ": ["ドスパラ"],
    "Amazon": ["amazon.co.jp", "amazon"],
    "楽天市場": ["楽天市場"],
    "TSUKUMO": ["tsukumo", "ツクモ"],
    "マウスコンピューター": ["マウスコンピューター"],
    "パソコン工房": ["パソコン工房"],
    "Joshin": ["joshin web", "joshin"],
    "PCSHOPアーク": ["pcshopアーク", "パソコンshopアーク", "ark"],
    "PC-IDEA": ["pc-idea"],
    "アプライドネット": ["アプライドネット", "applied"],
    "ソフマップ": ["ソフマップ", "sofmap"],
    "ノジマオンライン": ["ノジマオンライン"],
    "ビックカメラ": ["ビックカメラ", "biccamera"],
    "ヨドバシカメラ": ["ヨドバシカメラ", "ヨドバシ.com", "yodobashi"],
}


@dataclass
class CatalogItem:
    enabled: bool
    category: str
    group: str
    name: str
    sort_score: int
    kakaku_url: str
    source_mode: str


@dataclass
class PriceResult:
    price: int
    shop: str
    stale: bool = False
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog.csv"))
    parser.add_argument("--manual", type=Path, default=Path("manual_prices.csv"))
    parser.add_argument("--history", type=Path, default=Path("price_history.json"))
    parser.add_argument("--output", type=Path, default=Path("prices.json"))
    parser.add_argument("--shops", type=Path, default=Path("approved_shops.txt"))
    parser.add_argument("--mode", choices=("manual", "fetch", "mixed"), default="mixed")
    parser.add_argument("--date", help="Japan date, YYYY-MM-DD. Defaults to today in JST.")
    parser.add_argument("--sleep", type=float, default=2.5, help="Seconds between fetches.")
    parser.add_argument("--timeout", type=float, default=25.0)
    return parser.parse_args()


def normalize(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def read_catalog(path: Path) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            enabled = row.get("enabled", "1").strip().lower() not in {"0", "false", "no"}
            item = CatalogItem(
                enabled=enabled,
                category=row["category"].strip(),
                group=row["group"].strip(),
                name=row["name"].strip(),
                sort_score=int(row.get("sortScore", "0") or 0),
                kakaku_url=row.get("kakakuUrl", "").strip(),
                source_mode=(row.get("sourceMode", "fetch") or "fetch").strip().lower(),
            )
            validate_item(item)
            items.append(item)
    return items


def validate_item(item: CatalogItem) -> None:
    name = item.name
    if item.category == "CPU":
        intel_legacy = re.fullmatch(r"Intel Core i[3579]-(?:12|13|14)\d{3}(?:F|K|KF)?", name)
        intel_core_200 = re.fullmatch(r"Intel Core [3579] 2\d{2}(?:F|K|KF)?", name)
        intel_ultra = re.fullmatch(r"Intel Core Ultra [3579] \d{3}(?:F|K|KF)?", name)
        amd = re.fullmatch(r"AMD Ryzen [3579] [5-9]\d{3}(?:X|G|X3D|X3D2|3D|3D2)?", name)
        if not (intel_legacy or intel_core_200 or intel_ultra or amd):
            raise ValueError(f"CPU name violates the requested suffix/series filter: {name}")
        if "PRO" in name.upper():
            raise ValueError(f"PRO CPU is excluded: {name}")
    elif item.category == "GPU":
        geforce = re.fullmatch(r"NVIDIA GeForce RTX (?:30|40|50)\d{2}(?: Ti| SUPER| Ti SUPER)?", name)
        radeon = re.fullmatch(r"AMD Radeon RX [67]\d{3}(?: XT| XTX| GRE)?", name)
        if not (geforce or radeon):
            raise ValueError(f"GPU name violates the requested generation filter: {name}")
    elif item.category in {"DDR4", "DDR5"}:
        if not re.fullmatch(r"DDR[45] (?:8|16|32|64|128)GB", name):
            raise ValueError(f"Memory capacity is outside the requested set: {name}")
    elif item.category == "SSD":
        if not re.fullmatch(r"(?:SATA|M\.2) SSD (?:256GB|512GB|1TB|2TB|4TB|8TB)", name):
            raise ValueError(f"SSD format/capacity is outside the requested set: {name}")
    elif item.category == "HDD":
        if not re.fullmatch(r"HDD (?:256GB|512GB|1TB|2TB|4TB|8TB)", name):
            raise ValueError(f"HDD capacity is outside the requested set: {name}")


def read_manual_prices(path: Path) -> dict[str, PriceResult]:
    if not path.exists():
        return {}
    result: dict[str, PriceResult] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = row.get("name", "").strip()
            raw_price = row.get("price", "").replace(",", "").strip()
            if not name or not raw_price:
                continue
            result[name] = PriceResult(
                price=int(raw_price),
                shop=row.get("shop", "manual").strip() or "manual",
                stale=row.get("stale", "0").strip().lower() in {"1", "true", "yes"},
            )
    return result


def read_approved_shops(path: Path) -> set[str]:
    if not path.exists():
        return set(SHOP_ALIASES)
    names = {line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()}
    canonical: set[str] = set()
    for wanted in names:
        wanted_lower = wanted.lower()
        for shop, aliases in SHOP_ALIASES.items():
            if wanted_lower == shop.lower() or any(wanted_lower == alias.lower() for alias in aliases):
                canonical.add(shop)
    return canonical or set(SHOP_ALIASES)


def detect_shop(text_lower: str, approved: set[str]) -> str | None:
    for shop in approved:
        aliases = SHOP_ALIASES.get(shop, [shop])
        if any(alias.lower() in text_lower for alias in aliases):
            return shop
    return None


def parse_kakaku_page(html: str, approved: set[str]) -> PriceResult:
    if BeautifulSoup is None:
        raise RuntimeError("Install requirements.txt first.")
    soup = BeautifulSoup(html, "html.parser")
    candidates: set[tuple[int, str]] = set()

    # Shop rows are commonly represented by tr/li/div. Requiring both a shop alias and
    # a yen-like value avoids using the overall minimum when it belongs to another shop.
    for node in soup.find_all(["tr", "li", "article", "section", "div"]):
        text = normalize(node.get_text(" ", strip=True))
        if len(text) < 5 or len(text) > 900:
            continue
        shop = detect_shop(text.lower(), approved)
        if shop is None:
            continue
        for match in YEN_RE.finditer(text):
            value = int(match.group(1).replace(",", ""))
            if 500 <= value <= 5_000_000:
                candidates.add((value, shop))

    if not candidates:
        return PriceResult(0, "", error="No approved-shop price found")
    value, shop = min(candidates, key=lambda pair: pair[0])
    return PriceResult(value, shop)


def fetch_price(session: "requests.Session", item: CatalogItem, approved: set[str], timeout: float) -> PriceResult:
    if not item.kakaku_url:
        return PriceResult(0, "", error="kakakuUrl is blank")
    response = session.get(item.kakaku_url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return parse_kakaku_page(response.text, approved)


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"dates": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("dates"), dict):
            return {"dates": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"dates": {}}


def previous_price(history: dict, target_date: date, name: str, current_price: int) -> tuple[int, bool]:
    yesterday = (target_date - timedelta(days=1)).isoformat()
    raw = history.get("dates", {}).get(yesterday, {}).get(name)
    if isinstance(raw, int) and raw > 0:
        return raw, True
    return current_price, False


def save_history(path: Path, history: dict, target_date: date, prices: dict[str, int]) -> None:
    dates = history.setdefault("dates", {})
    dates[target_date.isoformat()] = prices
    # Retain 120 days.
    keep_after = target_date - timedelta(days=120)
    for key in list(dates):
        try:
            if date.fromisoformat(key) < keep_after:
                del dates[key]
        except ValueError:
            del dates[key]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def build_output(items: Iterable[CatalogItem], prices: dict[str, PriceResult], history: dict, target_date: date) -> dict:
    output_items = []
    today_map: dict[str, int] = {}
    for item in items:
        if not item.enabled:
            continue
        result = prices.get(item.name, PriceResult(0, "", error="No price result"))
        prev, comparison = previous_price(history, target_date, item.name, result.price)
        if result.price > 0:
            today_map[item.name] = result.price
        output_items.append({
            "enabled": True,
            "category": item.category,
            "group": item.group,
            "name": item.name,
            "price": result.price,
            "previousPrice": prev,
            "sortScore": item.sort_score,
            "comparisonAvailable": comparison,
            "stale": result.stale,
            "shop": result.shop,
            "sourceUrl": item.kakaku_url,
            "error": result.error,
        })

    return {
        "updatedAt": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "priceDate": target_date.isoformat(),
        "source": "価格.com掲載価格 / 指定店舗内の最安値",
        "items": output_items,
        "_todayHistory": today_map,
    }


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(JST).date()
    items = read_catalog(args.catalog)
    manual = read_manual_prices(args.manual)
    approved = read_approved_shops(args.shops)
    history = load_history(args.history)
    results: dict[str, PriceResult] = {}

    session = None
    if args.mode in {"fetch", "mixed"}:
        if requests is None:
            print("requests/beautifulsoup4 are required for fetch mode", file=sys.stderr)
            return 2
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36 PCPartsPriceBoard/1.0",
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
        })

    for index, item in enumerate(items):
        if not item.enabled:
            continue
        if item.name in manual:
            results[item.name] = manual[item.name]
            continue
        if args.mode == "manual" or item.source_mode == "manual":
            results[item.name] = PriceResult(0, "", error="Manual price missing")
            continue
        assert session is not None
        try:
            results[item.name] = fetch_price(session, item, approved, args.timeout)
        except Exception as exc:  # noqa: BLE001 - keep batch running and report per item.
            old = None
            dates = history.get("dates", {})
            for key in sorted(dates, reverse=True):
                candidate = dates[key].get(item.name)
                if isinstance(candidate, int) and candidate > 0:
                    old = candidate
                    break
            if old:
                results[item.name] = PriceResult(old, "previous history", stale=True, error=str(exc))
            else:
                results[item.name] = PriceResult(0, "", error=str(exc))
            print(f"WARN {item.name}: {exc}", file=sys.stderr)
        if args.sleep > 0 and index + 1 < len(items):
            time.sleep(args.sleep)

    payload = build_output(items, results, history, target_date)
    today_history = payload.pop("_todayHistory")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    save_history(args.history, history, target_date, today_history)
    print(f"Wrote {args.output} ({len(payload['items'])} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
