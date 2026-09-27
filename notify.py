#!/usr/bin/env python3
"""その日のダイジェストを Discord Webhook に送る。

使い方: DISCORD_WEBHOOK_URL=... python3 notify.py [YYYY-MM-DD] [--dry-run]
Webhook URL は環境変数からのみ読む（リポジトリには書かない）。
config.json の site_url が設定されていれば公開ページのリンクだけを送り、
未設定なら要約を embed で送る。
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, PICKS = ROOT / "data" / "raw", ROOT / "data" / "picks"
COLORS = {"_head": 0x2F6FED}
# Discord の制限: 1メッセージの embed は10個・合計6000文字、description は4096文字
MAX_EMBEDS, MAX_TOTAL, MAX_DESC = 10, 5800, 4000


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def link(title, url):
    return f"[{clip(title.replace('[', '(').replace(']', ')'), 90)}]({url})"


def build_embeds(date):
    """site_url が無いときの予備: 読む順の5本と今日のOSSを1つの embed にまとめる。"""
    picks_path = PICKS / f"{date}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    lines = [f"**{picks['headline']}**"] if picks.get("headline") else []
    for n, r in enumerate(picks.get("reading_list", []), 1):
        lines.append(f"{n}. {link(r['title'], r['url'])}（{r.get('minutes', '?')}分）\n{r.get('why', '')}")
    for o in picks.get("oss", []):
        lines.append(f"🧩 {link(o['repo'], o['url'])} — {o.get('what', '')}")
    return [{"title": f"📰 Tech Digest {date}", "description": clip("\n\n".join(lines) or "（要約なし）", MAX_DESC),
             "color": COLORS["_head"]}]


def batches(embeds):
    batch, size = [], 0
    for e in embeds:
        n = len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
        if batch and (len(batch) >= MAX_EMBEDS or size + n > MAX_TOTAL):
            yield batch
            batch, size = [], 0
        batch.append(e)
        size += n
    if batch:
        yield batch


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "tech-digest/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20):
                return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:  # レート制限
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)))
                continue
            raise


def wait_until_published(url, timeout=240):
    """Cloudflare Pages のデプロイ完了（ページが200を返す）まで待つ。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "tech-digest/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(15)
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    date = args[0] if args else max(p.stem for p in RAW.glob("*.json"))
    site = json.loads((ROOT / "config.json").read_text()).get("site_url", "").rstrip("/")
    if site:
        page_url = f"{site}/{date}"  # Cloudflare の静的アセットは .html なしのURLで配信される
        msgs = [{"content": f"📰 Tech Digest {date}\n{page_url}"}]
    else:
        msgs = [{"embeds": b} for b in batches(build_embeds(date))]
    if dry:
        print(json.dumps(msgs, ensure_ascii=False, indent=1))
        print(f"\n{len(msgs)}通に分けて送信予定", file=sys.stderr)
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        sys.exit("DISCORD_WEBHOOK_URL が設定されていません")
    if site and not wait_until_published(page_url):
        print(f"  ! {page_url} がまだ公開されていません（リンクは送ります）", file=sys.stderr)
    for m in msgs:
        post(url, {"username": "Tech Digest", **m})
        time.sleep(1)
    print(f"Discordに送信しました（{len(msgs)}通）")


if __name__ == "__main__":
    main()
