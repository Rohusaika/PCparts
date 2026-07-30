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

# Aggregate listing: exact GPU family, approved seller, and first product price.
from update_prices import parse_kakaku_listing
GPU = CatalogItem(True, "GPU", "test", "NVIDIA GeForce RTX 5080", 1, "", "aggregate")
gpu_list = """
<html><body><div class="item-row">
<a href="/item/K0002000001/">MSI GeForce RTX 5080 16G VENTUS 3X OC [PCIExp 16GB]</a>
<span>¥229,800</span><a class="shop">Amazon.co.jp</a>
<div>GeForce RTX 5080 GDDR7 16GB</div></div>
<div class="item-row"><a href="/item/K0002000002/">MSI GeForce RTX 5070 12G</a>
<span>¥99,800</span><a class="shop">Amazon.co.jp</a><div>GeForce RTX 5070</div></div>
</body></html>
"""
candidates = parse_kakaku_listing(gpu_list, APPROVED, GPU)
assert candidates and candidates[0][0] == 229800, candidates

# Desktop memory uses total kit capacity and excludes S.O.DIMM.
MEM = CatalogItem(True, "DDR4", "test", "DDR4 32GB", 1, "", "aggregate")
mem_list = """
<html><body><div class="item-row">
<a href="/item/K0003000001/">crucial ABC [DDR4 PC4-25600 16GB 2枚組]</a>
<span>¥6,980</span><a>Amazon.co.jp</a><div>16GB 2枚 DDR4 SDRAM DIMM ¥218</div></div>
<div class="item-row"><a href="/item/K0003000002/">crucial NOTE [SODIMM DDR4 32GB]</a>
<span>¥5,980</span><a>Amazon.co.jp</a><div>32GB 1枚 DDR4 SDRAM S.O.DIMM</div></div>
</body></html>
"""
candidates = parse_kakaku_listing(mem_list, APPROVED, MEM)
assert candidates and candidates[0][0] == 6980, candidates

M2 = CatalogItem(True, "SSD", "test", "M.2 SSD 1TB", 1, "", "aggregate")
ssd_list = """
<html><body><div class="item-row"><a href="/item/K0004000001/">Example NVMe 1TB</a>
<span>¥9,980</span><a>TSUKUMO</a><div>容量1000GB M.2 (Type2280) PCI-Express Gen4</div></div>
<div class="item-row"><a href="/item/K0004000002/">Example SATA 1TB</a>
<span>¥7,980</span><a>Amazon.co.jp</a><div>容量1000GB 2.5インチ Serial ATA</div></div></body></html>
"""
candidates = parse_kakaku_listing(ssd_list, APPROVED, M2)
assert candidates and candidates[0][0] == 9980, candidates

print("Aggregate parser tests passed")
