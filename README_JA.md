# VRChat PC Parts Price Board

VRChatワールド内に置ける、16:9のPCパーツ価格ボードです。CPU・GPU・DDR4・DDR5・SSD・HDDをタブで切り替え、各カテゴリ内は性能・容量の高い順に上から表示します。縦スクロールは使わず、1ページ56件（4列×14行）とページ切替で表示します。

## 含まれるもの

- `PcPartsPriceBoard.cs`：UdonSharpランタイム。外部JSONを読み込み、当日価格と前日比を表示します。
- `PcPartsPriceBoardBuilder.cs`：16:9 PrefabをUnity上で生成するEditorツールです。
- `sample_prices.json`：画面確認用。**実際の価格ではありません**。
- `Tools/update_prices.py`：価格JSON生成ツール。前日の履歴と比較します。
- `Tools/catalog.csv`：CPU/GPUの対象SKUと、メモリ・ストレージの集計枠です。
- `Tools/manual_prices.csv`：DDR4/DDR5/SSD/HDDの容量別最安値を入力するCSVです。

## 必要環境

- VRChat Creator Companionで作ったWorldsプロジェクト
- Unity / VRChat SDK Worlds / UdonSharp
- TextMeshPro
- 日本語を含むTMP Font Asset（本パッケージにはフォントを同梱していません）
- 価格JSONを更新する場合：Python 3.11以降

## Unityへの導入

1. ZIPを展開し、`Assets/PcPartsPriceBoard`をVRChat Worldsプロジェクトの`Assets`へコピーします。
2. Unityでコンパイルが終わるまで待ちます。
3. `Tools > PC Parts Price Board > Build 16:9 Prefab`を開きます。
4. 日本語を収録したTMP Font Assetを指定します。
5. `Remote JSON URL`にJSONのURLを指定します。最初はサンプルをGitHub Pages等に置いて確認できます。
6. `Build Prefab`を押します。
7. `Assets/PcPartsPriceBoard/Prefabs/PcPartsPriceBoard_16x9.prefab`が生成されます。
8. Prefabをシーンへ置き、向き・高さを調整します。

VRChatのString LoadingはJSON等のテキストを読み込めますが、信頼済みURL以外は各ユーザーが「Allow Untrusted URLs」を有効にする必要があります。運用先は`*.github.io`が扱いやすいです。

## 表示仕様

- `↑`：当日価格が前日より高い。赤。
- `↓`：当日価格が前日より低い。青。
- `→`：同額、または前日の記録がない。白。
- `※`：取得失敗時に過去の価格を暫定使用。
- 価格がない項目は`取得なし`。
- CPU/GPUはSKU単位。メモリ・SSD・HDDは指定容量の最安対象を集計して表示します。

## 対象ルール

### Intel CPU

- Core i3 / i5 / i7 / i9：第12～第14世代のみを対象にします。
- 許可する末尾：なし、`F`、`K`、`KF`。
- 第15世代相当以降は、`Intel Core 200シリーズ` と `Intel Core Ultraシリーズ` を対象にします。
- `Intel Core 200シリーズ` と `Intel Core Ultraシリーズ` も、許可する末尾は なし、`F`、`K`、`KF` のみです。
- 現在の同梱カタログには `Intel Core Ultraシリーズ` を収録しています。`Intel Core 200シリーズ` は将来SKU追加用の扱いです。

### AMD CPU

- Ryzen 5000～9000。
- PRO除外。
- 許可する末尾：なし、`X`、`G`、`X3D`、`X3D2`（入力表記として`3D`/`3D2`も許可）。
- 一般的な自作PCに搭載できるデスクトップ用のみを対象にします。

### GPU

- NVIDIA GeForce RTX 30 / 40 / 50シリーズのデスクトップ用単体GPU。
- AMD Radeon RX 6000 / 7000シリーズのデスクトップ用単体GPU。

### メモリ・ストレージ

- DDR4 / DDR5：8GB、16GB、32GB、64GB、128GB。単体と複数枚キットは混在可。
- SSD：256GB、512GB、1TB、2TB、4TB、8TBを`SATA 2.5-inch`と`M.2 NVMe`に分離。
- HDD：通常の自作PC向け`3.5-inch SATA`。**M.2 HDDは存在しないため表示しません**。
- HDDの256GB/512GB等で現行新品が見つからない場合は`取得なし`になります。


## 価格更新ツールはどこにあるか

価格更新ツールはUnity Editor内ではなく、展開したフォルダの直下にあります。

```text
VRChat_PCPartsPriceBoard/
├─ PRICE_UPDATE_TOOL.bat          ← Windows用・通常はこちら
├─ PRICE_UPDATE_MANUAL_ONLY.bat   ← 手入力データだけで更新
├─ Tools/
│  ├─ update_prices.py            ← Python本体
│  ├─ catalog.csv                 ← 対象製品と価格.comの商品URL
│  └─ manual_prices.csv           ← 手入力価格
├─ docs/
│  └─ prices.json                 ← ワールドが読み込む公開用JSON
```

Windowsでは`PRICE_UPDATE_TOOL.bat`をダブルクリックしてください。初回だけPython仮想環境と必要ライブラリを自動準備し、`docs/prices.json`を生成します。Python 3.11以降が必要です。

重要：初期状態では価格.comの商品URLがほとんど未登録です。`Tools/catalog.csv`の`kakakuUrl`へ各商品の価格.com商品ページURLを登録するか、`Tools/manual_prices.csv`へ確認済み価格を入力してください。URLや価格がない項目は自動では埋まりません。

## 価格JSONの作成

```bash
cd Tools
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

### 推奨：手入力・確認済みデータで生成

`manual_prices.csv`へ価格.comで確認した価格と店舗名を入力します。CPU/GPUも同じCSVへ追記すると、URL取得より優先されます。

```bash
python update_prices.py --mode manual --output prices.json
```

### 混合モード

- `catalog.csv`の`kakakuUrl`があるCPU/GPUはページから取得。
- `manual_prices.csv`の値は常に優先。
- 取得は指定店舗名を含む価格だけに絞ります。
- 取得失敗時は履歴の最新値を`※`付きで表示します。

```bash
python update_prices.py --mode mixed --output prices.json
```

`catalog.csv`には動作確認用としてCore i7-13700KFのURLだけ入っています。残りのURLは価格.comの商品ページURLを一度入力してください。ページ構造変更で解析できなくなる場合があります。



### 毎日自動更新する場合

`GITHUB_DAILY_UPDATE_JA.md`と`.github/workflows/update-prices.yml`を同梱しています。GitHub Pagesを使用すると、価格JSONを毎日更新し、VRChat側はJoin時にその最新版を読み込めます。

## Join時の更新動作

Prefabの`loadOnStart`が有効なら、各プレイヤーがワールドへJoinした時に、設定された`Remote JSON URL`から最新の`prices.json`を読み込みます。したがって、外部の`prices.json`が当日分に更新済みなら、再アップロードしたワールドへ差し替えなくても当日の価格が表示されます。

ただし、VRChatワールドは価格.comのHTMLを直接巡回して`prices.json`を作成しません。次の2段階です。

1. PC、サーバー、またはGitHub Actionsなどが価格を集計して、公開先の`prices.json`を更新する。
2. VRChat側がJoin時またはボードの「更新」ボタンで、そのJSONを読み込む。

同じインスタンスに入り続けて日付が変わった場合、現在のPrefabは自動の日次再取得をしません。その場合は「更新」ボタンを押すか、再Joinしてください。

## JSON公開

生成した`prices.json`をGitHub Pagesへ置き、UnityのBuilderで次の形式を設定します。

```text
https://ユーザー名.github.io/リポジトリ名/prices.json
```

各プレイヤーのVRChatクライアントがJSONを取得します。ボードの「更新」ボタンでも再取得できます。

## 価格.com利用上の注意

価格.comの利用規約、掲載情報の転載・公衆送信、アクセス方法、公開ワールドでの利用可否を確認してください。本パッケージは技術的な表示・比較機構を提供するもので、価格.comからの自動取得や公開利用の許諾を保証しません。許諾条件が不明な場合は、手動確認済みの価格を使うか、利用許諾のある価格APIへ差し替えてください。

## JSON形式

```json
{
  "updatedAt": "2026-07-29 20:30 JST",
  "source": "価格.com掲載価格 / 指定店舗内の最安値",
  "items": [
    {
      "enabled": true,
      "category": "CPU",
      "group": "Intel 第13世代",
      "name": "Intel Core i7-13700K",
      "price": 44000,
      "previousPrice": 44980,
      "sortScore": 13700,
      "comparisonAvailable": true,
      "stale": false
    }
  ]
}
```

`sortScore`の大きい製品ほど上へ表示されます。厳密なベンチマーク順にしたい場合は`catalog.csv`の値を変更してください。
