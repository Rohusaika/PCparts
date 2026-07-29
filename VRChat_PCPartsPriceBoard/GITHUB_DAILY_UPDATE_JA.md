# GitHub Pagesで毎日自動更新する方法

1. このフォルダの中身をGitHubリポジトリへアップロードします。
2. GitHubのリポジトリで `Settings > Pages` を開きます。
3. `Build and deployment` を `Deploy from a branch` にします。
4. Branchを `main`、Folderを `/docs` にして保存します。
5. `Tools/catalog.csv` の `kakakuUrl` と、必要に応じて `Tools/manual_prices.csv` を設定します。
6. `Actions` タブで `Update PC parts prices` を一度手動実行します。
7. 成功後、次のURLをUnity Builderの `Remote JSON URL` に設定します。

```text
https://GitHubユーザー名.github.io/リポジトリ名/prices.json
```

同梱ワークフローは毎日09:10 JST頃に実行されます。GitHub側の混雑により開始時刻は多少前後します。

注意：`catalog.csv`に商品URLが登録されていない製品は自動取得されません。また、価格.comのページ構造変更やアクセス条件により取得に失敗する場合があります。
