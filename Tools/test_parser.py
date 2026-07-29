#!/usr/bin/env python3
"""Offline safety tests for the v1.4 Kakaku price parser."""
from update_prices import CatalogItem, parse_kakaku_page

APPROVED = {"楽天市場", "Amazon", "TSUKUMO", "PC-IDEA", "アプライドネット"}
CPU = CatalogItem(True, "CPU", "test", "AMD Ryzen 7 5700X", 1, "", "fetch")
OTHER_CPU = CatalogItem(True, "CPU", "test", "AMD Ryzen 7 5700", 1, "", "fetch")

html = """
<html><head><title>AMD Ryzen 7 5700X BOX 価格比較 - 価格.com</title></head>
<body><nav>パソコン CPU AMD CPU</nav><h1>AMD Ryzen 7 5700X BOX</h1>
<div class="lowest-price">最安価格 31,480円</div>
<table class="price-table">
<tr><td>31,480 円 (最安)</td><td><a>PC-IDEA</a></td><td>AmazonPay対応</td></tr>
<tr><td>31,637 円 (+157)</td><td><a>アプライドネット</a></td><td>24回分割手数料無料</td></tr>
<tr><td>1,326円相当</td><td><a>楽天市場</a></td></tr>
</table></body></html>
"""
result = parse_kakaku_page(html, APPROVED, CPU)
assert result.price == 31480, result
assert result.shop == "PC-IDEA", result

# A model suffix mismatch must reject the entire page.
result = parse_kakaku_page(html, APPROVED, OTHER_CPU)
assert result.price == 0 and "mismatch" in result.error.lower(), result

# An instalment or point amount below the headline minimum cannot be selected.
installment = """
<html><head><title>AMD Ryzen 7 5700X BOX 価格比較 - 価格.com</title></head>
<body>CPU<h1>AMD Ryzen 7 5700X BOX</h1><div>最安価格 31,480円</div>
<table><tr><td>3,148円 (最安)</td><td><a>楽天市場</a></td></tr>
<tr><td>31,480円 (最安)</td><td><a>PC-IDEA</a></td></tr></table></body></html>
"""
result = parse_kakaku_page(installment, APPROVED, CPU)
assert result.price == 31480 and result.shop == "PC-IDEA", result

# If the overall cheapest shop is not approved, choose the first approved offer row.
unapproved_top = """
<html><head><title>AMD Ryzen 7 5700X BOX 価格比較 - 価格.com</title></head>
<body>CPU<h1>AMD Ryzen 7 5700X BOX</h1><div>最安価格 30,000円</div>
<table><tr><td>30,000円 (最安)</td><td><a>未承認ショップ</a></td></tr>
<tr><td>31,480円 (+1,480)</td><td><a>PC-IDEA</a></td></tr></table></body></html>
"""
result = parse_kakaku_page(unapproved_top, APPROVED, CPU)
assert result.price == 31480 and result.shop == "PC-IDEA", result

# If there is no verified approved offer, publish unavailable rather than a guessed price.
no_approved = """
<html><head><title>AMD Ryzen 7 5700X BOX 価格比較 - 価格.com</title></head>
<body>CPU<h1>AMD Ryzen 7 5700X BOX</h1><div>最安価格 30,000円</div>
<table><tr><td>30,000円 (最安)</td><td><a>未承認ショップ</a></td></tr></table></body></html>
"""
result = parse_kakaku_page(no_approved, APPROVED, CPU)
assert result.price == 0, result

print("Parser tests passed")
