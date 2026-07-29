#!/usr/bin/env python3
"""Offline safety tests for the Kakaku price parser."""
from update_prices import CatalogItem, parse_kakaku_page

APPROVED = {"楽天市場", "Amazon", "TSUKUMO"}
CPU = CatalogItem(True, "CPU", "test", "Intel Core i7-13700KF", 1, "", "fetch")
GPU = CatalogItem(True, "GPU", "test", "NVIDIA GeForce RTX 5090", 1, "", "fetch")

html = """
<table>
<tr><td>145,861 円</td><td>1,326円相当</td><td>楽天市場</td></tr>
<tr><td>150,000 円</td><td>Amazon.co.jp</td></tr>
<tr><td>140,000 円</td><td>許可していない店</td></tr>
</table>
"""
result = parse_kakaku_page(html, APPROVED, CPU)
assert result.price == 145861, result
assert result.shop == "楽天市場", result

points_only = "<table><tr><td>1,326円相当</td><td>楽天市場</td></tr></table>"
result = parse_kakaku_page(points_only, APPROVED, CPU)
assert result.price == 0, result

low_cpu = "<table><tr><td>1,326円</td><td>楽天市場</td></tr></table>"
result = parse_kakaku_page(low_cpu, APPROVED, CPU)
assert result.price == 0, result

valid_gpu = "<table><tr><td>499,800円</td><td>TSUKUMO</td></tr></table>"
result = parse_kakaku_page(valid_gpu, APPROVED, GPU)
assert result.price == 499800, result

print("Parser tests passed")
