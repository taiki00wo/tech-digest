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
CATEGORY_ORDER = ["AI", "フロントエンド", "バックエンド", "インフラ", "プロダクト", "その他"]
COLORS = {"AI": 0x8B5CF6, "フロントエンド": 0x0EA5E9, "バックエンド": 0x10B981, "インフラ": 0xF59E0B,
          "プロダクト": 0xEC4899, "その他": 0x9CA3AF, "_head": 0x2F6FED}
# Discord の制限: 1メッセージの embed は10個・合計6000文字、description は4096文字
MAX_EMBEDS, MAX_TOTAL, MAX_DESC = 10, 5800, 4000


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def link(title, url):
    return f"[{clip(title.replace('[', '(').replace(']', ')'), 90)}]({url})"


def build_embeds(date):
    raw = json.loads((RAW / f"{date}.json").read_text())
    picks_path = PICKS / f"{date}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    notes = picks.get("items", {})
    by_url = {i["url"]: i for i in raw["items"]}
    embeds = []

    head = []
    if picks.get("headline"):
        head.append(f"**{picks['headline']}**")
    if picks.get("trends"):
        head.append("\n".join(f"• {t}" for t in picks["trends"]))
    if picks.get("must_read"):
        lines = [f"**{n}. {link(m.get('title') or by_url.get(m['url'], {}).get('title', m['url']), m['url'])}**\n{m.get('why', '')}"
                 for n, m in enumerate(picks["must_read"], 1)]
        head.append("📌 **今日読むべき3本**\n" + "\n\n".join(lines))
    new = sum(not i["seen_before"] for i in raw["items"])
    embeds.append({"title": f"📰 Tech Digest {date}", "description": clip("\n\n".join(head) or "（要約なし・収集結果のみ）", MAX_DESC),
                   "color": COLORS["_head"], "footer": {"text": f"収集 {len(raw['items'])}件 / 新着 {new}件"}})

    groups = {c: [] for c in CATEGORY_ORDER}
    for it in raw["items"]:
        n = notes.get(it["url"])
        if picks and not n:
            continue
        cat = (n or {}).get("category") or it["categories"][0]
        groups.setdefault(cat, []).append(it)
    for cat, items in groups.items():
        if not items:
            continue
        items.sort(key=lambda x: (-notes.get(x["url"], {}).get("importance", 0), x["seen_before"], -(x.get("score") or 0)))
        lines = []
        for it in items[:10]:
            n = notes.get(it["url"], {})
            mark = "🔥 " if n.get("importance") == 3 else ""
            summary = n.get("summary") or it["summary"]
            lines.append(f"{mark}{link(it['title'], it['url'])}" + (f"\n{clip(summary, 160)}" if summary else ""))
        embeds.append({"title": f"{cat}（{len(items)}）", "description": clip("\n\n".join(lines), MAX_DESC),
                       "color": COLORS.get(cat, COLORS["その他"])})
    return embeds


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
        page_url = f"{site}/{date}.html"
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
