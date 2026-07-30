#!/usr/bin/env python3
"""Idempotently upgrade an existing catalog.csv to v1.5 without losing CPU URLs."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from urllib.parse import quote_plus

RADEON_9000 = [
    ("AMD Radeon RX 9070 XT", 99970),
    ("AMD Radeon RX 9070", 99960),
    ("AMD Radeon RX 9070 GRE", 99950),
    ("AMD Radeon RX 9060 XT", 99940),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog.csv"))
    return parser.parse_args()


def aggregate_url(category: str, name: str) -> str:
    if category == "GPU":
        query = name.replace("NVIDIA ", "").replace("AMD ", "")
        return f"https://kakaku.com/pc/videocard/itemlist.aspx?pdf_kw={quote_plus(query)}&pdf_so=p1"
    if category in {"DDR4", "DDR5"}:
        spec = "6" if category == "DDR4" else "7"
        cap = name.split()[-1]
        return f"https://kakaku.com/pc/pc-memory/itemlist.aspx?pdf_Spec101={spec}&pdf_kw={quote_plus(cap)}&pdf_so=p1"
    if category == "SSD":
        cap = name.split()[-1]
        if name.startswith("M.2"):
            return f"https://kakaku.com/pc/ssd/itemlist.aspx?pdf_Spec102=6%2C8%2C9%2C10&pdf_kw={quote_plus(cap)}&pdf_so=p1"
        return f"https://kakaku.com/pc/ssd/itemlist.aspx?pdf_Spec102=2&pdf_kw={quote_plus(cap)}&pdf_so=p1"
    if category == "HDD":
        cap = name.split()[-1]
        if cap.endswith("TB"):
            return f"https://kakaku.com/pc/hdd-35inch/itemlist.aspx?pdf_Spec309={cap[:-2]}&pdf_so=p1"
        return f"https://kakaku.com/pc/hdd-35inch/itemlist.aspx?pdf_kw={quote_plus(cap)}&pdf_so=p1"
    return ""


def main() -> int:
    args = parse_args()
    with args.catalog.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("catalog.csv has no header")
        rows = [dict(row) for row in reader]

    existing = {row.get("name", "") for row in rows}
    insert_at = next((i for i, row in enumerate(rows) if row.get("name") == "AMD Radeon RX 7900 XTX"), len(rows))
    additions = []
    for name, score in RADEON_9000:
        if name not in existing:
            additions.append({
                "enabled": "1", "category": "GPU", "group": "Radeon RX 9000",
                "name": name, "sortScore": str(score), "kakakuUrl": "", "sourceMode": "aggregate",
            })
    rows[insert_at:insert_at] = additions

    changed = bool(additions)
    for row in rows:
        category = row.get("category", "").strip()
        name = row.get("name", "").strip()
        if name == "AMD Ryzen 7 5700X" and not row.get("kakakuUrl", "").strip():
            row["kakakuUrl"] = "https://kakaku.com/item/K0001429753/"
            row["sourceMode"] = "fetch"
            changed = True
        if category in {"GPU", "DDR4", "DDR5", "SSD", "HDD"}:
            wanted_url = aggregate_url(category, name)
            if row.get("kakakuUrl", "") != wanted_url or row.get("sourceMode", "") != "aggregate":
                row["kakakuUrl"] = wanted_url
                row["sourceMode"] = "aggregate"
                changed = True

    with args.catalog.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"v1.5 catalog upgrade complete: rows={len(rows)} changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
