#!/usr/bin/env python3
"""Generate docs/prices.json for the VRChat PC-parts price board.

Version 1.2 safety changes:
- Never treats points/"円相当" as a product price.
- Applies category-specific plausible price ranges.
- Reads prices only from a row/container that contains an approved shop.
- Uses the last valid historical value as stale data when today's fetch fails.
- A zero in manual_prices.csv is treated as "not entered", not as a valid price.

This tool does not bypass access restrictions. Kakaku.com markup and availability can
change, so unresolved/blocked items remain unavailable instead of publishing a dubious
number. Verify Kakaku.com's terms before automated or public use.
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
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover
    requests = None
    BeautifulSoup = None
    Tag = object  # type: ignore[assignment,misc]

JST = ZoneInfo("Asia/Tokyo")
SPACE_RE = re.compile(r"\s+")
# Keep the text immediately following the amount so points can be rejected.
YEN_RE = re.compile(r"(?:¥|￥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,9})\s*円(?P<after>.{0,12})")

SHOP_ALIASES = {
    "ドスパラ": ["ドスパラ"],
    "Amazon": ["amazon.co.jp", "amazon"],
    "楽天市場": ["楽天市場"],
    "TSUKUMO": ["tsukumo", "ツクモ"],
    "マウスコンピューター": ["マウスコンピューター"],
    "パソコン工房": ["パソコン工房"],
    "Joshin": ["joshin web", "joshin"],
    "PCSHOPアーク": ["pcshopアーク", "パソコンshopアーク", "arkオンラインストア"],
    "PC-IDEA": ["pc-idea"],
    "アプライドネット": ["アプライドネット", "applied"],
    "ソフマップ": ["ソフマップ", "sofmap"],
    "ノジマオンライン": ["ノジマオンライン"],
    "ビックカメラ": ["ビックカメラ", "biccamera"],
    "ヨドバシカメラ": ["ヨドバシカメラ", "ヨドバシ.com", "yodobashi"],
}

POINT_MARKERS = ("相当", "ポイント", "pt", "還元")


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
    method: str = ""


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
            try:
                price = int(raw_price)
            except ValueError:
                print(f"WARN manual price is not an integer: {name}={raw_price}", file=sys.stderr)
                continue
            # Zero means "not entered" in the bundled template.
            if price <= 0:
                continue
            result[name] = PriceResult(
                price=price,
                shop=row.get("shop", "manual").strip() or "manual",
                stale=row.get("stale", "0").strip().lower() in {"1", "true", "yes"},
                method="manual",
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


def detect_shops(text_lower: str, approved: set[str]) -> list[str]:
    found: list[str] = []
    for shop in sorted(approved):
        aliases = SHOP_ALIASES.get(shop, [shop])
        if any(alias.lower() in text_lower for alias in aliases):
            found.append(shop)
    return found


def plausible_range(item: CatalogItem) -> tuple[int, int]:
    # Broad enough for normal new retail parts, narrow enough to reject points/instalments.
    if item.category == "CPU":
        return 3_000, 800_000
    if item.category == "GPU":
        return 8_000, 2_500_000
    if item.category in {"DDR4", "DDR5"}:
        return 500, 1_000_000
    if item.category == "SSD":
        return 500, 2_000_000
    if item.category == "HDD":
        return 1_000, 2_000_000
    return 500, 5_000_000


def extract_non_point_prices(text: str, item: CatalogItem) -> list[int]:
    minimum, maximum = plausible_range(item)
    prices: list[int] = []
    for match in YEN_RE.finditer(text):
        after = match.group("after").lower().lstrip(" 　:：()（）")
        before = text[max(0, match.start() - 14):match.start()].lower().rstrip()
        # Reject only when the marker is attached to this amount. A later points amount in
        # the same row must not invalidate the actual selling price preceding it.
        if after.startswith(("相当", "分相当", "ポイント", "pt", "還元")):
            continue
        if before.endswith(("ポイント", "pt", "還元")):
            continue
        value = int(match.group(1).replace(",", ""))
        if minimum <= value <= maximum:
            prices.append(value)
    return prices


def iter_shop_containers(soup: "BeautifulSoup") -> Iterable["Tag"]:
    """Yield small offer-like containers, avoiding page-wide divs that mix prices."""
    seen: set[int] = set()
    # Price comparison pages normally use table rows. Prefer them absolutely.
    for tag_name in ("tr", "li", "article"):
        for node in soup.find_all(tag_name):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                yield node
    # Fallback for newer card layouts: only reasonably small classed div/section nodes.
    for node in soup.find_all(["div", "section"]):
        classes = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
        if not re.search(r"price|shop|item|offer|store", classes, re.I):
            continue
        text = normalize(node.get_text(" ", strip=True))
        if 10 <= len(text) <= 550:
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                yield node


def parse_kakaku_page(html: str, approved: set[str], item: CatalogItem) -> PriceResult:
    if BeautifulSoup is None:
        raise RuntimeError("Install requirements.txt first.")
    soup = BeautifulSoup(html, "html.parser")
    candidates: set[tuple[int, str]] = set()

    for node in iter_shop_containers(soup):
        text = normalize(node.get_text(" ", strip=True))
        if len(text) < 8 or len(text) > 700:
            continue
        shops = detect_shops(text.lower(), approved)
        # A true offer row should normally refer to one approved shop. Multiple shop names
        # usually mean this is a parent container spanning several offers, so skip it.
        if len(shops) != 1:
            continue
        values = extract_non_point_prices(text, item)
        if not values:
            continue
        # Within one shop row the item selling price is the lowest non-point yen amount.
        # Shipping may also be present, but is commonly "無料"; plausible ranges remove
        # tiny values. We do not add shipping because the requested display is item price.
        candidates.add((min(values), shops[0]))

    if not candidates:
        return PriceResult(0, "", error="No approved-shop selling price found", method="fetch")

    value, shop = min(candidates, key=lambda pair: pair[0])
    return PriceResult(value, shop, method="fetch")


def fetch_price(
    session: "requests.Session", item: CatalogItem, approved: set[str], timeout: float
) -> PriceResult:
    if not item.kakaku_url:
        return PriceResult(0, "", error="kakakuUrl is blank", method="fetch")
    response = session.get(item.kakaku_url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return parse_kakaku_page(response.text, approved, item)


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


def latest_valid_history(history: dict, name: str) -> int | None:
    dates = history.get("dates", {})
    for key in sorted(dates, reverse=True):
        candidate = dates.get(key, {}).get(name)
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return None


def previous_price(history: dict, target_date: date, name: str, current_price: int) -> tuple[int, bool]:
    yesterday = (target_date - timedelta(days=1)).isoformat()
    raw = history.get("dates", {}).get(yesterday, {}).get(name)
    if isinstance(raw, int) and raw > 0:
        return raw, True
    return current_price, False


def save_history(path: Path, history: dict, target_date: date, prices: dict[str, int]) -> None:
    dates = history.setdefault("dates", {})
    # Merge instead of replacing so stale/unavailable entries do not erase good same-day data.
    day_map = dates.setdefault(target_date.isoformat(), {})
    day_map.update(prices)
    keep_after = target_date - timedelta(days=120)
    for key in list(dates):
        try:
            if date.fromisoformat(key) < keep_after:
                del dates[key]
        except ValueError:
            del dates[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_history_fallback(result: PriceResult, history: dict, item: CatalogItem) -> PriceResult:
    if result.price > 0:
        return result
    old = latest_valid_history(history, item.name)
    if old is None:
        return result
    return PriceResult(
        old,
        "前回の正常値",
        stale=True,
        error=result.error or "Today's price unavailable",
        method="history",
    )


def build_output(
    items: Iterable[CatalogItem], prices: dict[str, PriceResult], history: dict, target_date: date
) -> dict:
    output_items = []
    today_map: dict[str, int] = {}
    priced = stale = unavailable = 0
    for item in items:
        if not item.enabled:
            continue
        result = prices.get(item.name, PriceResult(0, "", error="No price result"))
        prev, comparison = previous_price(history, target_date, item.name, result.price)
        if result.price > 0:
            priced += 1
            if result.stale:
                stale += 1
            else:
                today_map[item.name] = result.price
        else:
            unavailable += 1
        output_items.append({
            "enabled": True,
            "category": item.category,
            "group": item.group,
            "name": item.name,
            "price": result.price,
            "previousPrice": prev,
            "sortScore": item.sort_score,
            "comparisonAvailable": comparison and result.price > 0,
            "stale": result.stale,
            "shop": result.shop,
            "sourceUrl": item.kakaku_url,
            "method": result.method,
            "error": result.error,
        })
    return {
        "schemaVersion": 2,
        "updatedAt": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "priceDate": target_date.isoformat(),
        "source": "価格.com掲載価格 / 指定店舗内の販売価格",
        "summary": {
            "total": len(output_items),
            "priced": priced,
            "stale": stale,
            "unavailable": unavailable,
        },
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    enabled_items = [item for item in items if item.enabled]
    for index, item in enumerate(enabled_items):
        did_network_request = False
        if item.name in manual:
            result = manual[item.name]
        elif args.mode == "manual" or item.source_mode == "manual":
            result = PriceResult(0, "", error="Manual price missing", method="manual")
        else:
            assert session is not None
            did_network_request = bool(item.kakaku_url)
            try:
                result = fetch_price(session, item, approved, args.timeout)
            except Exception as exc:  # keep the batch running and report per item
                result = PriceResult(0, "", error=str(exc), method="fetch")
                print(f"WARN {item.name}: {exc}", file=sys.stderr)
        result = apply_history_fallback(result, history, item)
        results[item.name] = result
        if result.price <= 0:
            print(f"WARN {item.name}: {result.error}", file=sys.stderr)
        if args.sleep > 0 and did_network_request and index + 1 < len(enabled_items):
            time.sleep(args.sleep)

    payload = build_output(items, results, history, target_date)
    today_history = payload.pop("_todayHistory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    save_history(args.history, history, target_date, today_history)
    summary = payload["summary"]
    print(
        f"Wrote {args.output}: total={summary['total']} priced={summary['priced']} "
        f"stale={summary['stale']} unavailable={summary['unavailable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
