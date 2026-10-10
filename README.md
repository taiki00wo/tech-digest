# Tech Digest

毎朝、AI・フロントエンド・バックエンド・インフラ・プロダクトの技術情報を集めて、Claudeが要約したHTMLダイジェストを作るツール。
日〜金は「今日の3本＋OSS 1件」の日刊、土曜は「今週のベスト5・OSS・深掘り・登壇・見出し」の週刊（`config.json` の `reader_profile`）。
英語の練習用に、毎号「今日の英語」（英語記事1本の英語3文要約＋フレーズ3つ）と「英語の動画」（その日の題材を解説する動画。ByteByteGo を優先して検索）が付く。

- `.github/workflows/collect.yml` … 毎朝7時のルーチンが起動する GitHub Actions で `collect.py` を実行して収集結果をコミット
- `oss.py` … GitHub APIで急上昇リポジトリ（スター増分）・リリース・READMEを取得
- `collect.py` … Hacker News / Zenn / Qiita / はてブ / 公式ブログ・Speaker Deck（RSS）から収集 → `data/raw/`
- `TASK.md` … Claudeが毎朝行う手順（日刊・週刊の選定 → `data/picks/`）
- `notify.py` … Discord Webhook（環境変数 `DISCORD_WEBHOOK_URL`）にダイジェストを送信
- `render.py` … `digest/YYYY-MM-DD.html` と `digest/index.html` を生成。各記事の ☆ で「あとで読む」に保存でき（ブラウザに保存）、`/bookmarks` で一覧できる
- `config.json` … 情報源・件数・カテゴリ分類のキーワード（RSSフィードはここに追加）

手動で実行する場合: `python3 collect.py && python3 render.py`（AI要約なしでも表示可能）

毎朝のデータ（収集結果・要約・HTML）は main ブランチの `data/` と `digest/` に保存され、`digest/` は Cloudflare（wrangler.jsonc）で公開されます。
