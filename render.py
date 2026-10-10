#!/usr/bin/env python3
"""data/raw と data/picks から digest/YYYY-MM-DD.html と digest/index.html を生成する。

使い方: python3 render.py [YYYY-MM-DD]   （省略時は最新の raw）
構成（picks.edition で切り替え）:
  日刊: 今日の流れ → 今日の3本 → 今日の英語 → 英語の動画 → 今日のOSS → リリース（畳む）
  週刊: 今週の流れ → 今週のベスト5 → 今週の英語 → 英語の動画 → 今週のOSS → 深掘り → 登壇スライド → リリース → 見出し → 未読の「あとで読む」
各記事の ☆ で「あとで読む」に保存でき（ブラウザの localStorage）、bookmarks.html で一覧できる。
"""
import json
import re
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
.card h3{font-size:16px;margin:0 0 6px;padding-right:60px;line-height:1.5;overflow-wrap:anywhere}.card h3 a{text-decoration:none}.card h3 a:hover{text-decoration:underline}
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
.bm{background:none;border:0;cursor:pointer;font-size:19px;line-height:1;color:var(--muted);padding:0 2px}
.bm[aria-pressed=true]{color:var(--star)}.card>.bm{position:absolute;top:13px;right:44px}
.heads li{display:flex;gap:6px;align-items:baseline}.heads li .t{flex:1}
.bmrow{display:flex;gap:10px;align-items:baseline;padding:10px 2px;border-bottom:1px solid var(--line)}.bmrow .t{flex:1}
.bmrow button,.tools button{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:2px 10px;cursor:pointer;color:var(--text);font-size:13px}
.tools{display:flex;gap:8px;margin:12px 0}.empty{color:var(--muted)}
.en{font-size:15.5px;line-height:1.75}
.phr{list-style:none;margin:12px 0 0;padding:0;font-size:14.5px}.phr li{padding:7px 0;border-top:1px solid var(--line)}
.phr b{font-weight:600}.phr .note{color:var(--muted);font-size:13.5px}
details>summary{cursor:pointer;list-style:none;margin:36px 0 12px}details>summary::-webkit-details-marker{display:none}
details>summary h2{margin:0}details>summary::after{content:" ▸";color:var(--muted)}details[open]>summary::after{content:" ▾"}
"""

JS = """
const BKEY='tech-digest-bookmarks';let bms={};try{bms=JSON.parse(localStorage.getItem(BKEY)||'{}')}catch(e){}
function saveBms(){try{localStorage.setItem(BKEY,JSON.stringify(bms))}catch(e){}document.querySelectorAll('.bm-count').forEach(e=>e.textContent=Object.keys(bms).length||'')}
document.querySelectorAll('.bm').forEach(b=>{const u=b.dataset.url;const on=()=>{b.setAttribute('aria-pressed',!!bms[u]);b.textContent=bms[u]?'★':'☆';b.title=bms[u]?'あとで読むから外す':'あとで読む'};on();
b.addEventListener('click',()=>{bms[u]?delete bms[u]:bms[u]={title:b.dataset.title,date:b.dataset.date,added:Date.now()};saveBms();on()})});
saveBms();
const list=document.getElementById('bm-list');
function drawList(){if(!list)return;const lim=+list.dataset.limit||1e9;const rows=Object.entries(bms).sort((a,b)=>b[1].added-a[1].added).slice(0,lim);
list.innerHTML=rows.length?'':'<p class="empty">まだありません。各記事の ☆ を押すとここに溜まります。</p>';
rows.forEach(([u,v])=>{const r=document.createElement('div');r.className='bmrow';const a=document.createElement('a');a.href=u;a.target='_blank';a.rel='noopener';a.className='t';a.textContent=v.title||u;
const m=document.createElement('span');m.className='meta';m.textContent=v.date||'';const x=document.createElement('button');x.textContent='読んだ・外す';x.onclick=()=>{delete bms[u];saveBms();drawList()};r.append(a,m,x);list.append(r)})}
drawList();
const ex=document.getElementById('bm-export');if(ex)ex.onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(bms,null,1)],{type:'application/json'}));a.download='tech-digest-bookmarks.json';a.click()};
const im=document.getElementById('bm-import');if(im)im.onchange=async()=>{try{Object.assign(bms,JSON.parse(await im.files[0].text()));saveBms();drawList()}catch(e){alert('読み込めませんでした')}};
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


def bm(url, title, date):
    return (f'<button type="button" class="bm" data-url="{escape(url)}" data-title="{escape(title)}" '
            f'data-date="{escape(date)}" aria-pressed="false" title="あとで読む">☆</button>')


NAV = '<div class="nav"><a href="./">アーカイブ</a> ・ <a href="bookmarks">☆ あとで読む <span class="bm-count"></span></a></div>'


def source_meta(raw_item):
    if not raw_item:
        return ""
    m, parts = raw_item["meta"], [escape(raw_item["source"])]
    if raw_item.get("score") is not None:
        parts.append(f'<span class="score">★ {raw_item["score"]:,}</span>')
    if m.get("discussion") and m["discussion"] != raw_item["url"]:
        parts.append(a(m["discussion"], f'{m["comments"]} comments' if "comments" in m else "discussion"))
    return " · ".join(parts)


def reading_card(n, r, raw_item, date):
    meta = f'<span class="chip">{escape(r.get("category", ""))}</span><span>⏱ {r.get("minutes", "?")}分</span>'
    src = source_meta(raw_item)
    return (f'<div class="card">{chk(r["url"])}{bm(r["url"], r["title"], date)}<div class="rank"><div class="num">{n}</div><div class="body">'
            f'<h3>{a(r["url"], r["title"])}</h3><div class="meta">{meta}{" · " + src if src else ""}</div>'
            f'<p><span class="label">なぜ</span>{escape(r.get("why", ""))}</p>'
            f'<p><span class="label">わかること</span>{escape(r.get("takeaway", ""))}</p></div></div></div>')


def oss_card(o, date):
    spd, week = o.get("stars_per_day"), o.get("stars_week")
    meta = [escape(o.get("language") or ""), f'<span class="score">★ {o.get("stars", 0):,}</span>']
    if week:
        meta.append(f'<span class="chip">今週 +{week:,}</span>')
    elif spd:
        meta.append(f'<span class="chip">+{spd:,}/日</span>')
    try_html = f'<pre>{escape(o["try"])}</pre>' if o.get("try") else ""
    return (f'<div class="card">{chk(o["url"])}{bm(o["url"], o["repo"], date)}<h3>{a(o["url"], o["repo"])}</h3>'
            f'<div class="meta">{" · ".join(m for m in meta if m)}</div>'
            f'<p><span class="label">何ができる</span>{escape(o.get("what", ""))}</p>'
            f'<p><span class="label">なぜ伸びてる</span>{escape(o.get("why", ""))}</p>{try_html}</div>')


def english_card(e, raw_item, date):
    """英語記事1本を、やさしい英語の要約とフレーズで読む枠。"""
    src = e.get("source") or (raw_item or {}).get("source", "")
    phrases = "".join(f'<li><b lang="en">{escape(p.get("en", ""))}</b> <span class="note">— {escape(p.get("ja", ""))}</span></li>'
                      for p in e.get("phrases") or [] if p.get("en"))
    return (f'<div class="card">{chk(e["url"])}{bm(e["url"], e.get("title", ""), date)}'
            f'<h3 lang="en">{a(e["url"], e.get("title", ""))}</h3>'
            + (f'<div class="meta">{escape(src)}</div>' if src else "")
            + f'<p class="en" lang="en">{escape(e.get("summary_en", ""))}</p>'
            + (f'<ul class="phr">{phrases}</ul>' if phrases else "") + "</div>")


VIDEO_ID = re.compile(r"(?:youtube\.com/watch\?(?:[^#]*&)?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})")


def video_card(v, date):
    m = VIDEO_ID.search(v["url"])  # 検索結果の URL は余分なパラメータが付くので、動画IDだけの形にそろえる
    url = f"https://www.youtube.com/watch?v={m.group(1)}" if m else v["url"]
    meta = (f'<span class="chip">{escape(v["topic"])}</span>' if v.get("topic") else "") + ("<span>YouTube</span>" if m else "")
    return (f'<div class="card">{chk(url)}{bm(url, v.get("title", ""), date)}<h3 lang="en">▶ {a(url, v.get("title", ""))}</h3>'
            f'<div class="meta">{meta}</div><p>{escape(v.get("why", ""))}</p></div>')


def releases_block(rels, date, open_=False):
    """リリースは1行ずつ。日刊では畳んでおく。"""
    rows = "".join(f'<li>{bm(r["url"], r["repo"] + " " + r["version"], date)}<span class="t">{a(r["url"], r["repo"] + " " + r["version"])}'
                   f' <span class="note">— {escape(" ".join(r.get("summary", "").split()))}</span></span></li>' for r in rels)
    return (f'<details{" open" if open_ else ""}><summary><h2 style="display:inline">リリース <small>{len(rels)}件</small></h2></summary>'
            f'<ul class="heads">{rows}</ul></details>')


def deep_dive(d, date):
    def ul(xs):
        return "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in xs) + "</ul>"
    tries = "".join(f"<pre>{escape(t)}</pre>" for t in d.get("try", []))
    parts = [f'<h3>{a(d["url"], d["repo"])}</h3><p>{escape(d.get("overview", ""))}</p>',
             f'<h4>仕組み・設計</h4><p>{escape(d["how_it_works"])}</p>' if d.get("how_it_works") else "",
             f'<h4>使いどころ</h4>{ul(d["use_cases"])}' if d.get("use_cases") else "",
             f'<h4>試してみる</h4>{tries}' if tries else "",
             f'<h4>似たツールとの違い</h4><p>{escape(d["compare"])}</p>' if d.get("compare") else ""]
    return f'<div class="card dive">{chk(d["url"])}{bm(d["url"], d["repo"], date)}{"".join(parts)}</div>'


def render_day(date):
    raw = json.loads((RAW / f"{date}.json").read_text())
    picks_path = PICKS / f"{date}.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    by_url = {i["url"]: i for i in raw["items"]}
    weekly = picks.get("edition") == "weekly"
    reading = picks.get("reading_list", [])
    total = sum(r.get("minutes") or 0 for r in reading)

    title = f"今週のまとめ {date}" if weekly else f"Tech Digest {date}"
    sub = ("土曜日・今週のまとめ" if weekly else (f'{raw["weekday"]}曜日' if raw.get("weekday") else "")) + (f" ・ 読む時間の目安 {total}分" if total else "")
    body = [f'<header><h1>{"🗞 " if weekly else ""}{title}</h1><p>{sub}</p>{NAV}</header>']
    if raw.get("errors"):
        body.append('<p class="err">取得できなかった情報源: ' + escape(", ".join(raw["errors"])) + "</p>")

    if picks.get("headline"):
        trends = "".join(f"<li>{escape(t)}</li>" for t in picks.get("trends", []))
        body.append(f'<section class="flow"><strong>{escape(picks["headline"])}</strong>{f"<ul>{trends}</ul>" if trends else ""}</section>')

    if reading:
        body.append(f'<h2>{"今週のベスト" if weekly else "今日の"}{len(reading)}{"" if weekly else "本"} <small>上から順に</small></h2>')
        body += [reading_card(n, r, by_url.get(r["url"]), date) for n, r in enumerate(reading, 1)]
    else:  # 要約が無い日（AI処理が失敗した日など）はスコア上位だけ出す
        top = sorted(raw["items"], key=lambda x: -(x.get("score") or 0))[:10]
        body.append('<h2>スコア上位 <small>要約なし</small></h2><ul class="heads">'
                    + "".join(f'<li>{bm(i["url"], i["title"], date)}<span class="t">{a(i["url"], i["title"])} <span class="note">{escape(i["source"])}</span></span></li>' for i in top) + "</ul>")

    english = picks.get("english") or {}
    if english.get("url") and english.get("summary_en"):
        body.append(f'<h2>{"今週" if weekly else "今日"}の英語 <small>3文で読む</small></h2>' + english_card(english, by_url.get(english["url"]), date))
    videos = [v for v in picks.get("videos") or [] if v.get("url")]
    if videos:
        body.append('<h2>英語の動画 <small>聞き取り・シャドーイング用</small></h2>' + "".join(video_card(v, date) for v in videos))

    if picks.get("oss"):
        body.append(f'<h2>{"今週" if weekly else "今日"}のOSS</h2>' + "".join(oss_card(o, date) for o in picks["oss"]))
    if picks.get("releases") and not weekly:
        body.append(releases_block(picks["releases"], date))
    if picks.get("deep_dive"):
        body.append('<h2>OSS深掘り <small>READMEから</small></h2>' + deep_dive(picks["deep_dive"], date))
    if picks.get("talks"):
        body.append('<h2>登壇スライド <small>Speaker Deck</small></h2>' + "".join(
            f'<div class="card">{chk(t["url"])}{bm(t["url"], t["title"], date)}<h3>{a(t["url"], t["title"])}</h3>'
            + (f'<div class="meta">{escape(t["event"])}</div>' if t.get("event") else "")
            + f'<p>{escape(t.get("why", ""))}</p></div>' for t in picks["talks"]))
    if picks.get("releases") and weekly:
        body.append(releases_block(picks["releases"], date, open_=True))
    if picks.get("headlines"):
        body.append('<h2>見出しだけ</h2><ul class="heads">' + "".join(
            f'<li>{bm(h["url"], h["title"], date)}<span class="t"><span class="chip">{escape(h.get("category", ""))}</span> {a(h["url"], h["title"])}'
            + (f' <span class="note">— {escape(h["note"])}</span>' if h.get("note") else "") + "</span></li>"
            for h in picks["headlines"]) + "</ul>")

    if weekly:  # 中身はブラウザの localStorage から JS で描画する
        body.append('<h2>未読の「あとで読む」</h2><div id="bm-list" data-limit="5"></div>'
                    '<p class="nav"><a href="bookmarks">すべて見る →</a></p>')

    OUT.mkdir(exist_ok=True)
    (OUT / f"{date}.html").write_text(page(title, "".join(body), picks.get("headline", "")))


def render_index():
    days = sorted((p.stem for p in OUT.glob("????-??-??.html")), reverse=True)
    rows = []
    for d in days:
        p = PICKS / f"{d}.json"
        picks = json.loads(p.read_text()) if p.exists() else {}
        mark = "🗞 今週のまとめ " if picks.get("edition") == "weekly" else ""
        rows.append(f'<li><a href="{d}">{mark}{d}</a> <span class="meta">{escape(picks.get("headline", ""))}</span></li>')
    latest = f'<p><a href="{days[0]}">最新号を読む →</a></p>' if days else ""
    (OUT / "index.html").write_text(page("Tech Digest", f'<header><h1>Tech Digest</h1><p>毎朝の技術ダイジェスト</p>{NAV}</header>'
                                                        f'{latest}<h2>アーカイブ</h2><ul class="archive">{"".join(rows)}</ul>'))
    # あとで読む（中身はブラウザの localStorage から JS で描画する）
    (OUT / "bookmarks.html").write_text(page("あとで読む - Tech Digest",
        f'<header><h1>☆ あとで読む</h1><p>このブラウザに保存されています</p>{NAV}</header>'
        '<div class="tools"><button type="button" id="bm-export">書き出し</button>'
        '<label><button type="button" onclick="this.nextElementSibling.click()">読み込み</button>'
        '<input type="file" id="bm-import" accept="application/json" hidden></label></div>'
        '<div id="bm-list"></div>'))


if __name__ == "__main__":
    if sys.argv[1:] == ["--all"]:  # テンプレートを変えたときに過去分も作り直す
        for p in sorted(RAW.glob("*.json")):
            render_day(p.stem)
        render_index()
        print("生成: 全日分")
        sys.exit()
    date = sys.argv[1] if len(sys.argv) > 1 else max(p.stem for p in RAW.glob("*.json"))
    render_day(date)
    render_index()
    print(f"生成: digest/{date}.html")
