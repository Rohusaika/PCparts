#!/usr/bin/env python3
"""Generate docs/prices.json for the VRChat PC-parts price board.

Version 1.4 focuses on correctness rather than maximum coverage:
- Verifies that every Kakaku item page is the exact requested model.
- Reads the page's headline minimum price and real offer rows only.
- Never treats points, instalments, shipping, or price differences as item prices.
- Resolves shop names from link/shop cells before scanning descriptive text.
- Rejects implausible day-to-day jumps and falls back to the last valid value.
- Keeps detailed failures in Tools/last_update_report.json, not public prices.json.

The script does not bypass access restrictions. If the page cannot be verified, the item
is marked unavailable instead of publishing a suspicious value.
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
PRICE_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,9})"
TOP_PRICE_RE = re.compile(
    rf"最安価格(?:\s*\(税込\))?\s*[:：]?\s*(?:¥|￥)?\s*({PRICE_NUMBER})\s*円",
    re.I,
)
OFFER_PRICE_RE = re.compile(
    rf"(?:¥|￥)?\s*({PRICE_NUMBER})\s*円\s*\(\s*(?:最安|\+\s*[0-9,]+)\s*\)",
    re.I,
)
ANY_YEN_RE = re.compile(rf"(?:¥|￥)?\s*({PRICE_NUMBER})\s*円", re.I)

# Aliases are deliberately strict. In particular, "Amazon" alone is not used because
# descriptions frequently contain AmazonPay even when the seller is another shop.
SHOP_ALIASES = {
    "ドスパラ": ["ドスパラ"],
    "Amazon": ["amazon.co.jp"],
    "楽天市場": ["楽天市場"],
    "TSUKUMO": ["tsukumo", "ツクモ"],
    "マウスコンピューター": ["マウスコンピューター"],
    "パソコン工房": ["パソコン工房"],
    "Joshin": ["joshin web", "joshin"],
    "PCSHOPアーク": ["pcshopアーク", "パソコンshopアーク", "パソコンショップアーク", "arkオンラインストア"],
    "PC-IDEA": ["pc-idea"],
    "アプライドネット": ["アプライドネット", "applied"],
    "ソフマップ": ["ソフマップ.com", "ソフマップ", "sofmap"],
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
    method: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog.csv"))
    parser.add_argument("--manual", type=Path, default=Path("manual_prices.csv"))
    parser.add_argument("--history", type=Path, default=Path("price_history.json"))
    parser.add_argument("--output", type=Path, default=Path("prices.json"))
    parser.add_argument("--report", type=Path, default=Path("last_update_report.json"))
    parser.add_argument("--shops", type=Path, default=Path("approved_shops.txt"))
    parser.add_argument("--mode", choices=("manual", "fetch", "mixed"), default="mixed")
    parser.add_argument("--date", help="Japan date, YYYY-MM-DD. Defaults to today in JST.")
    parser.add_argument("--sleep", type=float, default=2.5, help="Seconds between fetches.")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--min-daily-ratio", type=float, default=0.55)
    parser.add_argument("--max-daily-ratio", type=float, default=1.80)
    return parser.parse_args()


def normalize(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def compact(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


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


def model_signature(name: str) -> str | None:
    """Return an exact model signature; suffix differences remain significant."""
    text = normalize(name)
    patterns = [
        (r"Intel Core Ultra ([3579]) (\d{3}(?:KF|K|F)?)$", "COREULTRA{}{}"),
        (r"Intel Core i([3579])-(\d{5}(?:KF|K|F)?)$", "COREI{}{}"),
        (r"Intel Core ([3579]) (2\d{2}(?:KF|K|F)?)$", "CORE{}{}"),
        (r"AMD Ryzen ([3579]) ([5-9]\d{3}(?:X3D2|X3D|3D2|3D|X|G)?)$", "RYZEN{}{}"),
        (r"NVIDIA GeForce RTX ((?:30|40|50)\d{2})(?: (Ti SUPER|Ti|SUPER))?$", "RTX{}{}"),
        (r"AMD Radeon RX ([67]\d{3})(?: (XTX|XT|GRE))?$", "RX{}{}"),
    ]
    for pattern, template in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            a = compact(match.group(1))
            b = compact(match.group(2) or "")
            return template.format(a, b)
    return None


def signatures_in_text(text: str) -> set[str]:
    compact_text = compact(text)
    found: set[str] = set()
    regexes = [
        (r"COREULTRA([3579])(\d{3}(?:KF|K|F)?)", "COREULTRA{}{}"),
        (r"COREI([3579])(\d{5}(?:KF|K|F)?)", "COREI{}{}"),
        (r"(?:INTEL)?CORE([3579])(2\d{2}(?:KF|K|F)?)", "CORE{}{}"),
        (r"RYZEN([3579])([5-9]\d{3}(?:X3D2|X3D|3D2|3D|X|G)?)", "RYZEN{}{}"),
        (r"RTX((?:30|40|50)\d{2})(TISUPER|TI|SUPER)?", "RTX{}{}"),
        (r"RX([67]\d{3})(XTX|XT|GRE)?", "RX{}{}"),
    ]
    for pattern, template in regexes:
        for match in re.finditer(pattern, compact_text, re.I):
            found.add(template.format(compact(match.group(1)), compact(match.group(2) or "")))
    return found


def page_identity(soup: "BeautifulSoup", item: CatalogItem) -> tuple[bool, str]:
    expected = model_signature(item.name)
    if not expected:
        return False, "Could not build an exact model signature"
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    heading = h1.get_text(" ", strip=True) if h1 else ""
    head_text = normalize(f"{title} {heading}")
    signatures = signatures_in_text(head_text)
    if expected not in signatures:
        return False, f"URL model mismatch: expected {expected}, page has {sorted(signatures)}"

    page_prefix = normalize(soup.get_text(" ", strip=True))[:8000].lower()
    if item.category == "CPU" and "cpu" not in page_prefix:
        return False, "Page is not verified as a CPU page"
    if item.category == "GPU" and not any(word in page_prefix for word in ("グラフィックボード", "ビデオカード", "gpu")):
        return False, "Page is not verified as a graphics-card page"
    return True, "verified"


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


def detect_shops_in_text(text: str, approved: set[str]) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for shop in sorted(approved):
        aliases = SHOP_ALIASES.get(shop, [shop])
        if any(alias.lower() in lower for alias in aliases):
            found.append(shop)
    return found


def detect_shops_in_node(node: "Tag", approved: set[str]) -> list[str]:
    # Shop names are normally links. Looking at links first avoids false matches such as
    # AmazonPay or 楽天ペイ in a different seller's description.
    anchor_text = " ".join(normalize(a.get_text(" ", strip=True)) for a in node.find_all("a"))
    found = detect_shops_in_text(anchor_text, approved)
    if found:
        return sorted(set(found))
    return sorted(set(detect_shops_in_text(normalize(node.get_text(" ", strip=True)), approved)))


def plausible_range(item: CatalogItem) -> tuple[int, int]:
    if item.category == "CPU":
        tier_match = re.search(r"(?:i|Ultra |Core |Ryzen )([3579])", item.name, re.I)
        tier = int(tier_match.group(1)) if tier_match else 3
        minimum = {3: 3_500, 5: 6_000, 7: 9_000, 9: 14_000}.get(tier, 3_500)
        return minimum, 800_000
    if item.category == "GPU":
        return 8_000, 2_500_000
    if item.category in {"DDR4", "DDR5"}:
        return 500, 1_000_000
    if item.category == "SSD":
        return 500, 2_000_000
    if item.category == "HDD":
        return 1_000, 2_000_000
    return 500, 5_000_000


def parse_int_price(raw: str) -> int:
    return int(raw.replace(",", ""))


def valid_price(value: int, item: CatalogItem) -> bool:
    minimum, maximum = plausible_range(item)
    return minimum <= value <= maximum


def iter_offer_containers(soup: "BeautifulSoup") -> Iterable["Tag"]:
    seen: set[int] = set()
    for tag_name in ("tr", "li", "article"):
        for node in soup.find_all(tag_name):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                yield node
    for node in soup.find_all(["div", "section"]):
        classes = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
        if not re.search(r"price|shop|item|offer|store|lowest", classes, re.I):
            continue
        text = normalize(node.get_text(" ", strip=True))
        if 10 <= len(text) <= 1000:
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                yield node


def headline_min_price(soup: "BeautifulSoup", item: CatalogItem) -> int | None:
    text = normalize(soup.get_text(" ", strip=True))
    match = TOP_PRICE_RE.search(text)
    if not match:
        return None
    value = parse_int_price(match.group(1))
    return value if valid_price(value, item) else None


def offer_candidates(soup: "BeautifulSoup", approved: set[str], item: CatalogItem, top_price: int | None) -> list[tuple[int, str]]:
    candidates: set[tuple[int, str]] = set()
    for node in iter_offer_containers(soup):
        text = normalize(node.get_text(" ", strip=True))
        if len(text) < 8 or len(text) > 1200:
            continue
        shops = detect_shops_in_node(node, approved)
        if len(shops) != 1:
            continue

        values = [parse_int_price(m.group(1)) for m in OFFER_PRICE_RE.finditer(text)]
        values = [v for v in values if valid_price(v, item)]

        # The highlighted "lowest-price shop" card sometimes omits (+difference), but its
        # exact amount must equal the independently parsed headline minimum.
        if not values and top_price is not None:
            all_values = [parse_int_price(m.group(1)) for m in ANY_YEN_RE.finditer(text)]
            if top_price in all_values and ("最安" in text or "最安価格ショップ" in text):
                values = [top_price]

        for value in values:
            # No genuine offer on a correctly parsed page can be cheaper than the page's
            # own headline minimum. This rejects instalments, points, and unrelated prices.
            if top_price is not None and value < top_price:
                continue
            candidates.add((value, shops[0]))
    return sorted(candidates, key=lambda pair: pair[0])


def parse_kakaku_page(html: str, approved: set[str], item: CatalogItem) -> PriceResult:
    if BeautifulSoup is None:
        raise RuntimeError("Install requirements.txt first.")
    soup = BeautifulSoup(html, "html.parser")

    identity_ok, reason = page_identity(soup, item)
    if not identity_ok:
        return PriceResult(0, "", error=reason, method="fetch")

    top_price = headline_min_price(soup, item)
    candidates = offer_candidates(soup, approved, item, top_price)
    if not candidates:
        if top_price is None:
            return PriceResult(0, "", error="Headline minimum price was not found", method="fetch")
        return PriceResult(0, "", error="No approved-shop offer row matched the headline price table", method="fetch")

    value, shop = candidates[0]
    return PriceResult(value, shop, method="fetch")


def fetch_price(session: "requests.Session", item: CatalogItem, approved: set[str], timeout: float) -> PriceResult:
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


def apply_anomaly_guard(result: PriceResult, history: dict, item: CatalogItem, min_ratio: float, max_ratio: float) -> PriceResult:
    if result.price <= 0 or result.method == "manual":
        return result
    old = latest_valid_history(history, item.name)
    if old is None or old <= 0:
        return result
    ratio = result.price / old
    if ratio < min_ratio or ratio > max_ratio:
        return PriceResult(
            0,
            "",
            error=f"Suspicious change rejected: previous={old}, fetched={result.price}, ratio={ratio:.3f}",
            method="fetch",
        )
    return result


def apply_history_fallback(result: PriceResult, history: dict, item: CatalogItem) -> PriceResult:
    if result.price > 0:
        return result
    old = latest_valid_history(history, item.name)
    if old is None:
        return result
    return PriceResult(old, "前回の正常値", stale=True, error=result.error or "Today's price unavailable", method="history")


def build_output(items: Iterable[CatalogItem], prices: dict[str, PriceResult], history: dict, target_date: date) -> tuple[dict, dict]:
    output_items = []
    diagnostics = []
    today_map: dict[str, int] = {}
    priced = stale = unavailable = 0
    for item in items:
        if not item.enabled:
            continue
        result = prices.get(item.name, PriceResult(0, "", error="No price result"))
        prev, comparison = previous_price(history, target_date, item.name, result.price)
        if result.price > 0:
            priced += 1
            status = "stale" if result.stale else "ok"
            if result.stale:
                stale += 1
            else:
                today_map[item.name] = result.price
        else:
            unavailable += 1
            status = "unavailable"

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
            "status": status,
            "shop": result.shop,
            "sourceUrl": item.kakaku_url,
            "method": result.method,
        })
        diagnostics.append({
            "name": item.name,
            "status": status,
            "price": result.price,
            "shop": result.shop,
            "sourceUrl": item.kakaku_url,
            "method": result.method,
            "message": result.error,
        })

    payload = {
        "schemaVersion": 4,
        "updatedAt": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "priceDate": target_date.isoformat(),
        "source": "価格.com掲載価格 / 指定店舗内の販売価格",
        "summary": {"total": len(output_items), "priced": priced, "stale": stale, "unavailable": unavailable},
        "items": output_items,
        "_todayHistory": today_map,
    }
    report = {
        "schemaVersion": 4,
        "updatedAt": payload["updatedAt"],
        "summary": payload["summary"],
        "items": diagnostics,
    }
    return payload, report


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
            except Exception as exc:
                result = PriceResult(0, "", error=str(exc), method="fetch")
                print(f"WARN {item.name}: {exc}", file=sys.stderr)

        result = apply_anomaly_guard(result, history, item, args.min_daily_ratio, args.max_daily_ratio)
        result = apply_history_fallback(result, history, item)
        results[item.name] = result
        if result.price <= 0:
            print(f"WARN {item.name}: {result.error}", file=sys.stderr)
        if args.sleep > 0 and did_network_request and index + 1 < len(enabled_items):
            time.sleep(args.sleep)

    payload, report = build_output(items, results, history, target_date)
    today_history = payload.pop("_todayHistory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    save_history(args.history, history, target_date, today_history)
    summary = payload["summary"]
    print(
        f"Wrote {args.output}: total={summary['total']} priced={summary['priced']} "
        f"stale={summary['stale']} unavailable={summary['unavailable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
