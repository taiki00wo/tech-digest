#!/usr/bin/env python3
"""data/raw と data/picks から digest/YYYY-MM-DD.html と digest/index.html を生成する。

使い方: python3 render.py [YYYY-MM-DD]   （省略時は最新の raw）
構成: 今日の流れ → 読む順の5本 → 今日のOSS → リリース → 深掘り（火・金）→ 登壇スライド → 見出しだけ
"""
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, PICKS, OUT = ROOT / "data" / "raw", ROOT / "data" / "picks", ROOT / "digest"

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1f;--muted:#6e6e73;--line:#e5e5e2;--accent:#2f6fed;--accent-soft:#e8effd;--star:#b7791f;--code:#f2f2ef}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141416;--card:#1d1d20;--text:#ececef;--muted:#9a9aa2;--line:#2c2c31;--accent:#7aa2ff;--accent-soft:#1f2940;--star:#e0b252;--code:#26262b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:720px;margin:0 auto;padding:28px 16px 80px}a{color:inherit}
header h1{font-size:24px;margin:0}header p{margin:2px 0 0;color:var(--muted);font-size:13px}
.nav{font-size:13px;margin-top:6px}.nav a{color:var(--accent);text-decoration:none}
.flow{margin:20px 0 8px;padding:16px 18px;background:var(--accent-soft);border-radius:12px}
.flow strong{display:block;line-height:1.6}.flow ul{margin:8px 0 0;padding-left:20px;font-size:14px}
h2{font-size:17px;margin:36px 0 12px;display:flex;align-items:baseline;gap:8px}h2 small{color:var(--muted);font-weight:normal;font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px;position:relative}
.card.read{opacity:.45}
.rank{display:flex;gap:14px}.num{flex-shrink:0;width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;font-weight:700;font-size:15px}
.body{flex:1;min-width:0}
.card h3{font-size:16px;margin:0 0 6px;padding-right:26px;line-height:1.5;overflow-wrap:anywhere}.card h3 a{text-decoration:none}.card h3 a:hover{text-decoration:underline}
.card p{margin:6px 0 0;font-size:14.5px}.label{color:var(--muted);font-size:12px;margin-right:6px}
.meta{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;color:var(--muted);align-items:center}.meta a{color:var(--muted)}
.chip{border-radius:99px;padding:0 8px;background:var(--accent-soft);color:var(--accent);font-weight:600;font-size:12px}
.score{color:var(--star)}
code,pre{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);border-radius:6px}
pre{padding:10px 12px;margin:8px 0 0;overflow-x:auto;white-space:pre-wrap;word-break:break-all}
.chk{position:absolute;top:16px;right:16px;width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.dive h4{font-size:13px;color:var(--muted);margin:14px 0 4px}.dive ul{margin:4px 0 0;padding-left:20px;font-size:14.5px}
.heads{list-style:none;padding:0;margin:0}.heads li{padding:8px 2px;border-bottom:1px solid var(--line);font-size:14.5px}
.heads a{text-decoration:none}.heads a:hover{text-decoration:underline}.heads .note{color:var(--muted);font-size:13px}
.archive li{margin:6px 0}.err{color:#c0392b;font-size:12px;margin-top:6px}
"""

JS = """
const KEY='tech-digest-read';let read={};try{read=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
document.querySelectorAll('.chk').forEach(c=>{const u=c.dataset.url;if(read[u]){c.checked=true;c.closest('.card').classList.add('read')}
c.addEventListener('change',()=>{c.checked?read[u]=Date.now():delete read[u];c.closest('.card').classList.toggle('read',c.checked);try{localStorage.setItem(KEY,JSON.stringify(read))}catch(e){}})});
"""


def page(title, body, description=""):
    # og:* は Discord などでリンクを貼ったときのプレビューに使われる
    og = (f'<meta property="og:title" content="{escape(title)}"><meta property="og:type" content="article">'
          f'<meta property="og:description" content="{escape(description)}"><meta name="description" content="{escape(description)}">'
          '<meta name="theme-color" content="#2f6fed">')
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>{og}<style>{CSS}</style></head><body><main>{body}</main><script>{JS}</script></body></html>"""


def a(url, text):
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(text)}</a>'


def chk(url):
    return f'<input type="checkbox" class="chk" data-url="{escape(url)}" title="読んだ">'


def source_meta(raw_item):
    if not raw_item:
        return ""
    m, parts = raw_item["meta"], [escape(raw_item["source"])]
    if raw_item.get("score") is not None:
        parts.append(f'<span class="score">★ {raw_item["score"]:,}</span>')
    if m.get("discussion") and m["discussion"] != raw_item["url"]:
        parts.append(a(m["discussion"], f'{m["comments"]} comments' if "comments" in m else "discussion"))
    return " · ".join(parts)


def reading_card(n, r, raw_item):
    meta = f'<span class="chip">{escape(r.get("category", ""))}</span><span>⏱ {r.get("minutes", "?")}分</span>'
    src = source_meta(raw_item)
    return (f'<div class="card">{chk(r["url"])}<div class="rank"><div class="num">{n}</div><div class="body">'
            f'<h3>{a(r["url"], r["title"])}</h3><div class="meta">{meta}{" · " + src if src else ""}</div>'
            f'<p><span class="label">なぜ</span>{escape(r.get("why", ""))}</p>'
            f'<p><span class="label">わかること</span>{escape(r.get("takeaway", ""))}</p></div></div></div>')


def oss_card(o):
    spd = o.get("stars_per_day")
    meta = [escape(o.get("language") or ""), f'<span class="score">★ {o.get("stars", 0):,}</span>']
    if spd:
        meta.append(f'<span class="chip">+{spd:,}/日</span>')
    try_html = f'<pre>{escape(o["try"])}</pre>' if o.get("try") else ""
    return (f'<div class="card">{chk(o["url"])}<h3>{a(o["url"], o["repo"])}</h3>'
            f'<div class="meta">{" · ".join(m for m in meta if m)}</div>'
            f'<p><span class="label">何ができる</span>{escape(o.get("what", ""))}</p>'
            f'<p><span class="label">なぜ伸びてる</span>{escape(o.get("why", ""))}</p>{try_html}</div>')


def release_card(r):
    return (f'<div class="card"><h3>{a(r["url"], r["repo"] + " " + r["version"])}</h3>'
            f'<p style="white-space:pre-line">{escape(r.get("summary", ""))}</p></div>')


def deep_dive(d):
    def ul(xs):
        return "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in xs) + "</ul>"
    tries = "".join(f"<pre>{escape(t)}</pre>" for t in d.get("try", []))
    parts = [f'<h3>{a(d["url"], d["repo"])}</h3><p>{escape(d.get("overview", ""))}</p>',
             f'<h4>仕組み・設計</h4><p>{escape(d["how_it_works"])}</p>' if d.get("how_it_works") else "",
             f'<h4>使いどころ</h4>{ul(d["use_cases"])}' if d.get("use_cases") else "",
             f'<h4>試してみる</h4>{tries}' if tries else "",
             f'<h4>似たツールとの違い</h4><p>{escape(d["compare"])}</p>' if d.get("compare") else ""]
    return f'<div class="card dive">{chk(d["url"])}{"".join(parts)}</div>'


def render_day(date):
    raw = json.loads((RAW / f"{date}.json").read_text())
    picks_path = PICKS / f"{date}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    by_url = {i["url"]: i for i in raw["items"]}
    reading = picks.get("reading_list", [])
    total = sum(r.get("minutes") or 0 for r in reading)

    sub = (f'{raw["weekday"]}曜日' if raw.get("weekday") else "") + (f" ・ 読む時間の目安 {total}分" if total else "")
    body = [f'<header><h1>Tech Digest {date}</h1><p>{sub}</p><div class="nav"><a href="./">アーカイブ</a></div></header>']
    if raw.get("errors"):
        body.append('<p class="err">取得できなかった情報源: ' + escape(", ".join(raw["errors"])) + "</p>")

    if picks.get("headline"):
        trends = "".join(f"<li>{escape(t)}</li>" for t in picks.get("trends", []))
        body.append(f'<section class="flow"><strong>{escape(picks["headline"])}</strong>{f"<ul>{trends}</ul>" if trends else ""}</section>')

    if reading:
        body.append(f'<h2>読む順に{len(reading)}本 <small>上から順に</small></h2>')
        body += [reading_card(n, r, by_url.get(r["url"])) for n, r in enumerate(reading, 1)]
    else:  # 要約が無い日（AI処理が失敗した日など）はスコア上位だけ出す
        top = sorted(raw["items"], key=lambda x: -(x.get("score") or 0))[:10]
        body.append('<h2>スコア上位 <small>要約なし</small></h2><ul class="heads">'
                    + "".join(f'<li>{a(i["url"], i["title"])} <span class="note">{escape(i["source"])}</span></li>' for i in top) + "</ul>")

    if picks.get("oss"):
        body.append('<h2>今日のOSS</h2>' + "".join(oss_card(o) for o in picks["oss"]))
    if picks.get("releases"):
        body.append('<h2>リリース <small>ウォッチ中のリポジトリ</small></h2>' + "".join(release_card(r) for r in picks["releases"]))
    if picks.get("deep_dive"):
        body.append('<h2>OSS深掘り <small>READMEから</small></h2>' + deep_dive(picks["deep_dive"]))
    if picks.get("talks"):
        body.append('<h2>登壇スライド <small>Speaker Deck</small></h2>' + "".join(
            f'<div class="card">{chk(t["url"])}<h3>{a(t["url"], t["title"])}</h3>'
            + (f'<div class="meta">{escape(t["event"])}</div>' if t.get("event") else "")
            + f'<p>{escape(t.get("why", ""))}</p></div>' for t in picks["talks"]))
    if picks.get("headlines"):
        body.append('<h2>見出しだけ</h2><ul class="heads">' + "".join(
            f'<li><span class="chip">{escape(h.get("category", ""))}</span> {a(h["url"], h["title"])}'
            + (f' <span class="note">— {escape(h["note"])}</span>' if h.get("note") else "") + "</li>"
            for h in picks["headlines"]) + "</ul>")

    OUT.mkdir(exist_ok=True)
    (OUT / f"{date}.html").write_text(page(f"Tech Digest {date}", "".join(body), picks.get("headline", "")))


def render_index():
    days = sorted((p.stem for p in OUT.glob("????-??-??.html")), reverse=True)
    rows = []
    for d in days:
        p = PICKS / f"{d}.json"
        head = json.loads(p.read_text()).get("headline", "") if p.exists() else ""
        rows.append(f'<li><a href="{d}">{d}</a> <span class="meta">{escape(head)}</span></li>')
    latest = f'<p><a href="{days[0]}">最新号を読む →</a></p>' if days else ""
    (OUT / "index.html").write_text(page("Tech Digest", f'<header><h1>Tech Digest</h1><p>毎朝の技術ダイジェスト</p></header>'
                                                        f'{latest}<h2>アーカイブ</h2><ul class="archive">{"".join(rows)}</ul>'))


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else max(p.stem for p in RAW.glob("*.json"))
    render_day(date)
    render_index()
    print(f"生成: digest/{date}.html")
