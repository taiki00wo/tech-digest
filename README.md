# Tech Digest

毎朝、AI・フロントエンド・バックエンド・インフラ・プロダクトの技術情報を集めて、Claudeが要約したHTMLダイジェストを作るツール。

- `.github/workflows/collect.yml` … 毎朝6:00 JSTに GitHub Actions で `collect.py` を実行して収集結果をコミット
- `oss.py` … GitHub APIで急上昇リポジトリ（スター増分）・リリース・READMEを取得
- `collect.py` … GitHub Trending / Hacker News / Lobsters / Product Hunt / Zenn / Qiita / はてブ / 公式ブログ（RSS）から収集 → `data/raw/`
- `TASK.md` … Claudeが毎朝行う手順（要約・今日の3本の選定 → `data/picks/`）
- `notify.py` … Discord Webhook（環境変数 `DISCORD_WEBHOOK_URL`）にダイジェストを送信
- `render.py` … `digest/YYYY-MM-DD.html` と `digest/index.html` を生成
- `config.json` … 情報源・件数・カテゴリ分類のキーワード（RSSフィードはここに追加）

手動で実行する場合: `python3 collect.py && python3 render.py`（AI要約なしでも表示可能）

毎朝のデータ（収集結果・要約・HTML）は main ブランチの `data/` と `digest/` に保存され、`digest/` は Cloudflare（wrangler.jsonc）で公開されます。
