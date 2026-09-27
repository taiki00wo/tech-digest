#!/usr/bin/env python3
"""data/raw と data/picks から digest/YYYY-MM-DD.html と digest/index.html を生成する。

使い方: python3 render.py [YYYY-MM-DD]   （省略時は最新の raw）
"""
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, PICKS, OUT = ROOT / "data" / "raw", ROOT / "data" / "picks", ROOT / "digest"
CATEGORY_ORDER = ["AI", "フロントエンド", "バックエンド", "インフラ", "プロダクト", "その他"]

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1f;--muted:#6e6e73;--line:#e5e5e2;--accent:#2f6fed;--accent-soft:#e8effd;--star:#b7791f}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141416;--card:#1d1d20;--text:#ececef;--muted:#9a9aa2;--line:#2c2c31;--accent:#7aa2ff;--accent-soft:#1f2940;--star:#e0b252}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 80px}a{color:inherit}
header h1{font-size:26px;margin:0 0 4px}header p{margin:0;color:var(--muted);font-size:13px}
.nav{display:flex;gap:12px;font-size:13px;margin-top:8px}.nav a{color:var(--accent);text-decoration:none}
.headline{margin:24px 0;padding:18px 20px;background:var(--accent-soft);border-radius:12px}
.headline ul{margin:8px 0 0;padding-left:20px}
h2{font-size:18px;margin:36px 0 12px;display:flex;align-items:baseline;gap:8px}h2 small{color:var(--muted);font-weight:normal;font-size:13px}
.must{display:grid;gap:12px}.must .card{border-left:3px solid var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:10px;position:relative}
.card.read{opacity:.45}.card h3{font-size:15px;margin:0 0 4px;padding-right:28px;line-height:1.5}.card h3 a{text-decoration:none}.card h3 a:hover{text-decoration:underline}
.card p{margin:6px 0 0;font-size:14px}.why{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;font-size:12px;color:var(--muted)}.meta a{color:var(--muted)}
.badge{border:1px solid var(--line);border-radius:99px;padding:0 8px}.new{color:var(--accent);border-color:var(--accent)}.score{color:var(--star)}
.chk{position:absolute;top:14px;right:14px;width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.compact{display:flex;gap:8px;align-items:baseline;padding:6px 2px;border-bottom:1px solid var(--line);font-size:14px}
.compact a{text-decoration:none;flex:1}.compact a:hover{text-decoration:underline}.compact .meta{flex-shrink:0}
details summary{cursor:pointer;color:var(--muted);font-size:13px;margin:8px 0}
.toolbar{position:sticky;top:0;background:var(--bg);padding:10px 0;display:flex;gap:6px;flex-wrap:wrap;z-index:1;border-bottom:1px solid var(--line)}
.toolbar a{font-size:13px;text-decoration:none;padding:3px 10px;border-radius:99px;background:var(--card);border:1px solid var(--line)}
.archive li{margin:6px 0}.err{color:#c0392b;font-size:12px}
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


def meta_html(it):
    m = it["meta"]
    parts = [f'<span class="badge">{escape(it["source"])}</span>']
    if not it.get("seen_before"):
        parts.append('<span class="badge new">NEW</span>')
    if it.get("score") is not None:
        parts.append(f'<span class="score">★ {it["score"]:,} {escape(m.get("score_label") or "")}</span>')
    if m.get("language"):
        parts.append(f'<span>{escape(m["language"])}</span>')
    if m.get("discussion") and m["discussion"] != it["url"]:
        label = f'{m["comments"]} comments' if "comments" in m else "discussion"
        parts.append(f'<a href="{escape(m["discussion"])}" target="_blank" rel="noopener">{label}</a>')
    return f'<div class="meta">{"".join(parts)}</div>'


def card(it, note="", why=""):
    url = escape(it["url"])
    body = f'<p class="why">{escape(why)}</p>' if why else ""
    body += f"<p>{escape(note)}</p>" if note else ""
    return (f'<div class="card"><input type="checkbox" class="chk" data-url="{url}" title="読んだ">'
            f'<h3><a href="{url}" target="_blank" rel="noopener">{escape(it["title"])}</a></h3>{meta_html(it)}{body}</div>')


def compact(it):
    return (f'<div class="compact"><a href="{escape(it["url"])}" target="_blank" rel="noopener">{escape(it["title"])}</a>'
            f'{meta_html(it)}</div>')


def render_day(date):
    raw = json.loads((RAW / f"{date}.json").read_text())
    picks_path = PICKS / f"{date}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    notes = picks.get("items", {})
    by_url = {i["url"]: i for i in raw["items"]}

    body = [f'<header><h1>Tech Digest {date}</h1><p>収集 {escape(raw["collected_at"][:16].replace("T", " "))} ・ {len(raw["items"])}件'
            f'（新着 {sum(not i["seen_before"] for i in raw["items"])}件）</p>'
            f'<div class="nav"><a href="index.html">アーカイブ</a></div></header>']
    if raw.get("errors"):
        body.append('<p class="err">取得失敗: ' + escape(", ".join(raw["errors"])) + "</p>")

    if picks.get("headline") or picks.get("trends"):
        trends = "".join(f"<li>{escape(t)}</li>" for t in picks.get("trends", []))
        body.append(f'<section class="headline"><strong>{escape(picks.get("headline", ""))}</strong>'
                    f'{f"<ul>{trends}</ul>" if trends else ""}</section>')

    groups = {c: [] for c in CATEGORY_ORDER}
    for it in raw["items"]:
        n = notes.get(it["url"], {})
        cat = n.get("category") or it["categories"][0]
        groups.setdefault(cat, []).append(it)
    present = [c for c in groups if groups[c]]
    body.append('<nav class="toolbar">' + ('<a href="#must">今日の3本</a>' if picks.get("must_read") else "")
                + "".join(f'<a href="#c-{i}">{escape(c)} {len(groups[c])}</a>' for i, c in enumerate(present)) + "</nav>")

    if picks.get("must_read"):
        cards = "".join(card(by_url.get(m["url"], {"title": m.get("title", m["url"]), "url": m["url"], "source": "",
                                                    "meta": {}, "seen_before": True}),
                             notes.get(m["url"], {}).get("summary", ""), m.get("why", ""))
                        for m in picks["must_read"])
        body.append(f'<h2 id="must">今日読むべき3本</h2><div class="must">{cards}</div>')

    for i, cat in enumerate(present):
        items = sorted(groups[cat], key=lambda x: (-notes.get(x["url"], {}).get("importance", 0),
                                                   x["seen_before"], -(x.get("score") or 0)))
        featured = [x for x in items if x["url"] in notes]
        rest = [x for x in items if x["url"] not in notes]
        if not picks:  # 要約がまだない日は上位をカード表示
            featured, rest = items[:8], items[8:]
        html = "".join(card(x, notes.get(x["url"], {}).get("summary") or x["summary"][:160]) for x in featured)
        if rest:
            html += f'<details><summary>ほか {len(rest)}件</summary>{"".join(compact(x) for x in rest)}</details>'
        body.append(f'<h2 id="c-{i}">{escape(cat)} <small>{len(items)}件</small></h2>{html}')

    OUT.mkdir(exist_ok=True)
    (OUT / f"{date}.html").write_text(page(f"Tech Digest {date}", "".join(body), picks.get("headline", "")))


def render_index():
    days = sorted((p.stem for p in OUT.glob("????-??-??.html")), reverse=True)
    rows = []
    for d in days:
        p = PICKS / f"{d}.json"
        head = json.loads(p.read_text()).get("headline", "") if p.exists() else ""
        rows.append(f'<li><a href="{d}.html">{d}</a> <span class="meta">{escape(head)}</span></li>')
    latest = f'<p><a href="{days[0]}.html">最新号を読む →</a></p>' if days else ""
    (OUT / "index.html").write_text(page("Tech Digest", f'<header><h1>Tech Digest</h1><p>毎朝の技術ダイジェスト</p></header>'
                                                        f'{latest}<h2>アーカイブ</h2><ul class="archive">{"".join(rows)}</ul>'))


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else max(p.stem for p in RAW.glob("*.json"))
    render_day(date)
    render_index()
    print(f"生成: digest/{date}.html")
