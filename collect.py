#!/usr/bin/env python3
"""技術情報を各ソースから収集して data/raw/YYYY-MM-DD.json に保存する（標準ライブラリのみ）。"""
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import oss

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())
JST = timezone(timedelta(hours=CONFIG["timezone_offset_hours"]))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) tech-digest/1.0"
LIMITS = CONFIG["limits"]


def fetch(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def item(source, title, url, summary="", score=None, meta=None):
    return {"source": source, "title": title.strip(), "url": url, "summary": summary[:300],
            "score": score, "meta": meta or {}}


# ---------- 各ソース ----------

def hackernews():
    ids = json.loads(fetch("https://hacker-news.firebaseio.com/v0/topstories.json"))[:60]

    def get(i):
        try:
            return json.loads(fetch(f"https://hacker-news.firebaseio.com/v0/item/{i}.json"))
        except Exception:
            return None

    with ThreadPoolExecutor(16) as ex:
        stories = [s for s in ex.map(get, ids) if s]
    out = []
    for s in stories:
        if s.get("score", 0) < CONFIG["hackernews_min_score"] or s.get("type") != "story":
            continue
        hn = f"https://news.ycombinator.com/item?id={s['id']}"
        out.append(item("Hacker News", s.get("title", ""), s.get("url") or hn, "", s.get("score"),
                        {"comments": s.get("descendants", 0), "discussion": hn, "score_label": "points"}))
    return out[:LIMITS["hackernews"]]


def zenn():
    data = json.loads(fetch("https://zenn.dev/api/articles?order=daily"))
    return [item("Zenn", a["title"], "https://zenn.dev" + a["path"], "", a.get("liked_count"),
                 {"author": a.get("user", {}).get("username"), "score_label": "likes"})
            for a in data["articles"][:LIMITS["zenn"]] if a.get("article_type") == "tech"]


ATOM = "{http://www.w3.org/2005/Atom}"


def parse_feed(xml_text, source, limit, score_ns=None):
    """RSS 2.0 / RSS 1.0 (RDF) / Atom をまとめて扱う。"""
    root = ET.fromstring(xml_text.encode("utf-8"))
    out = []
    entries = root.findall(f"{ATOM}entry")
    if entries:
        for e in entries[:limit]:
            link = e.find(f"{ATOM}link[@rel='alternate']")
            if link is None:
                link = e.find(f"{ATOM}link")
            summ = e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or ""
            out.append(item(source, e.findtext(f"{ATOM}title") or "",
                            link.get("href") if link is not None else "", strip_tags(summ),
                            meta={"published": e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")}))
        return out
    items = root.findall(".//item") or root.findall(".//{http://purl.org/rss/1.0/}item")
    for it in items[:limit]:
        def t(tag):
            v = it.find(tag)
            if v is None:
                v = it.find("{http://purl.org/rss/1.0/}" + tag)
            return v.text if v is not None and v.text else ""
        score = None
        if score_ns:
            v = it.findtext(score_ns)
            score = int(v) if v and v.isdigit() else None
        out.append(item(source, t("title"), t("link").strip(), strip_tags(t("description")), score,
                        {"published": t("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"),
                         "score_label": "users" if score_ns else None}))
    return out


def qiita():
    out = parse_feed(fetch("https://qiita.com/popular-items/feed"), "Qiita", LIMITS["qiita"])
    for i in out:
        i["url"] = i["url"].split("?")[0]
    return out


def hatena():
    return parse_feed(fetch("https://b.hatena.ne.jp/hotentry/it.rss"), "はてブ テクノロジー", LIMITS["hatena"],
                      score_ns="{http://www.hatena.ne.jp/info/xmlns#}bookmarkcount")


def rss_feeds():
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    def one(feed):
        try:
            items = parse_feed(fetch(feed["url"]), feed["name"], feed.get("limit", LIMITS["rss_per_feed"]))
        except Exception as e:
            print(f"  ! {feed['name']}: {e}", file=sys.stderr)
            return []
        return [i for i in items if is_recent(i["meta"].get("published"), cutoff)]

    with ThreadPoolExecutor(8) as ex:
        return [i for items in ex.map(one, CONFIG["rss_feeds"]) for i in items]


def is_recent(published, cutoff):
    if not published:
        return True
    from email.utils import parsedate_to_datetime
    for parse in (lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")), parsedate_to_datetime):
        try:
            d = parse(published.strip())
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)) >= cutoff
        except Exception:
            continue
    return True


# ---------- 分類・重複管理 ----------

def keyword_pattern(kw):
    # 英数字のキーワードは単語境界で判定（"ai" が "maintain" に当たらないように）
    kw = kw.strip().lower()
    return re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])" if kw.isascii() else re.escape(kw))


CATEGORY_PATTERNS = {c: [keyword_pattern(k) for k in kws] for c, kws in CONFIG["categories"].items()}


def categorize(it):
    text = f" {it['title']} {it['summary']} {it['meta'].get('language') or ''} {' '.join(it['meta'].get('tags', []))} ".lower()
    cats = [c for c, pats in CATEGORY_PATTERNS.items() if any(p.search(text) for p in pats)]
    return cats or ["その他"]


def clean_markdown(text, limit):
    """README をAIに読ませる用に圧縮する（画像・バッジ・リンクURL・HTML・コードブロックを除く）。"""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)   # 見出し記号は brief の区切りと紛らわしいので外す
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    return text[:limit]


def write_brief(out, path):
    """Claude が読む用の圧縮版（raw の JSON は大きいので、選定に必要な項目だけ Markdown にする）。
    紹介済みの記事・OSS は載せない。"""
    lines = [f"# {out['date']}（{out['weekday']}） edition=daily",
             f"取得失敗: {', '.join(out['errors']) or 'なし'}", "", "## 記事（source | score | 自動分類 | タイトル | 概要 | url）"]
    for it in out["items"]:
        if it["seen_before"] or it["source"] == "Speaker Deck":  # 登壇スライドは週刊で扱う
            continue
        score = it["score"] if it["score"] is not None else "-"
        summary = re.sub(r"\s+", " ", it["summary"])[:80]
        lines.append(f"- {it['source']} | {score} | {'/'.join(it['categories'])} | {it['title']} | {summary} | {it['url']}")
    lines += ["", "## OSS候補（stars_per_day順。~ は作成からの平均で代用）"]
    for r in out["oss"]:
        if r.get("featured_before"):
            continue
        spd = f"{'~' if r.get('estimated') else ''}{r.get('stars_per_day')}"
        lines.append(f"### {r['repo']} | {r['language']} | ★{r['stars']} | +{spd}/日 | {r['found_in']} | {r['url']}")
        lines.append(r["description"])
        if r.get("readme"):
            lines.append("README: " + clean_markdown(r["readme"], 900))
    lines += ["", "## リリース"]
    latest = {}
    for r in out["releases"]:
        latest.setdefault(r["repo"], r)   # API は新しい順なので最初の1件が最新
    for r in latest.values():
        lines.append(f"### {r['repo']} {r['version']} | {r['url']}")
        lines.append(clean_markdown(r["body"], 700))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


WEEKLY_PER_SOURCE = {"Hacker News": 15, "はてブ テクノロジー": 15, "Zenn": 10, "Qiita": 10, "Speaker Deck": 20}  # 他（公式ブログ）は全部


def featured_urls(today, days=7):
    """直近のダイジェストで紹介済みの URL（週刊で同じ記事を出さないため）。"""
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    urls = set()
    for p in (ROOT / "data" / "picks").glob("*.json"):
        if cutoff <= p.stem < today:
            picks = json.loads(p.read_text())
            for key in ("reading_list", "headlines", "talks", "oss"):
                urls |= {x.get("url") for x in picks.get(key, [])}
    return urls - {None}


def weekly_star_growth(repo, stars_history, start):
    """stars.json の履歴から、週の間に増えたスター数を返す（記録が1点しか無ければ None）。"""
    h = {d: s for d, s in stars_history.get(repo, {}).items() if d >= start}
    if len(h) < 2:
        return None
    return h[max(h)] - h[min(h)]


def write_weekly_brief(out, path):
    """週刊用の brief: 直近7日分の raw をまとめ、紹介済みを除き、ソースごとに上位だけ残す。"""
    today = out["date"]
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    raws = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "raw").glob("*.json")) if start <= p.stem <= today]

    items = {}
    for raw in raws:
        for it in raw["items"]:
            prev = items.get(it["url"])
            if prev is None or (it.get("score") or 0) > (prev.get("score") or 0):
                items[it["url"]] = it
    done = featured_urls(today)
    by_source = {}
    for it in items.values():
        if it["url"] not in done:
            by_source.setdefault(it["source"], []).append(it)

    lines = [f"# {start} 〜 {today}（{out['weekday']}） edition=weekly",
             f"取得失敗（今日の収集）: {', '.join(out['errors']) or 'なし'}", "",
             "## 今週の記事（日刊で紹介済みのものは除外。source | score | 自動分類 | タイトル | 概要 | url）"]
    for source, its in by_source.items():
        its.sort(key=lambda x: -(x.get("score") or 0))  # score が無いソースは収集順（＝人気順）のまま
        for it in its[:WEEKLY_PER_SOURCE.get(source)]:
            score = it["score"] if it["score"] is not None else "-"
            summary = re.sub(r"\s+", " ", it["summary"])[:80]
            lines.append(f"- {source} | {score} | {'/'.join(it['categories'])} | {it['title']} | {summary} | {it['url']}")

    # OSS: 週内の候補を集め、7日間のスター増分で並べる
    stars_path = ROOT / "data" / "stars.json"
    history = json.loads(stars_path.read_text()) if stars_path.exists() else {}
    pool = {}
    for raw in raws:
        for r in raw.get("oss", []):
            if r.get("readme") or r["repo"] not in pool:
                pool[r["repo"]] = r
    featured = recently_featured(today)
    ranked = []
    for r in pool.values():
        if r["repo"] in featured or r["repo"] in done:
            continue
        growth = weekly_star_growth(r["repo"], history, start)
        ranked.append((growth if growth is not None else (r.get("stars_per_day") or 0) * 7, growth is None, r))
    ranked.sort(key=lambda x: -x[0])
    lines += ["", "## 今週のOSS候補（週間スター増分順。~ は1日あたりの平均から推定）"]
    for growth, estimated, r in ranked[:10]:
        lines.append(f"### {r['repo']} | {r['language']} | ★{r['stars']} | 今週 +{'~' if estimated else ''}{growth} | {r['url']}")
        lines.append(r["description"])
        if r.get("readme"):
            lines.append("README: " + clean_markdown(r["readme"], 900))

    lines += ["", "## 今週のリリース"]
    latest = {}
    for r in out["releases"]:
        latest.setdefault(r["repo"], r)
    for r in latest.values():
        lines.append(f"### {r['repo']} {r['version']} | {r['url']}")
        lines.append(clean_markdown(r["body"], 500))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def recently_featured(today, days=30):
    """過去のダイジェストで紹介済みのリポジトリ（同じOSSを繰り返し出さないため）。"""
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    names = set()
    for p in (ROOT / "data" / "picks").glob("*.json"):
        if cutoff <= p.stem < today:
            picks = json.loads(p.read_text())
            names |= {o.get("repo") for o in picks.get("oss", [])}
            names.add((picks.get("deep_dive") or {}).get("repo"))
    return names - {None}


def main():
    now = datetime.now(JST)
    if os.environ.get("DIGEST_DATE"):  # 動作確認用: 日付を上書きする（例: 土曜にして週刊を試す）
        now = datetime.strptime(os.environ["DIGEST_DATE"], "%Y-%m-%d").replace(hour=6, tzinfo=JST)
    today = now.strftime("%Y-%m-%d")
    edition = "weekly" if now.weekday() == CONFIG["reader_profile"]["weekly"]["weekday"] else "daily"
    sources = {"Hacker News": hackernews, "Zenn": zenn, "Qiita": qiita, "はてブ": hatena,
               "公式ブログ": rss_feeds}
    items, errors = [], {}
    with ThreadPoolExecutor(len(sources)) as ex:
        futures = {name: ex.submit(fn) for name, fn in sources.items()}
        for name, f in futures.items():
            try:
                got = f.result()
                print(f"  {name}: {len(got)}件")
                items += got
            except Exception as e:
                errors[name] = str(e)
                print(f"  ! {name}: {e}", file=sys.stderr)

    seen_path = ROOT / "data" / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    cutoff = (now - timedelta(days=CONFIG["seen_retention_days"])).strftime("%Y-%m-%d")
    seen = {u: d for u, d in seen.items() if d >= cutoff}

    uniq = {}
    for it in items:
        if not it["url"] or it["url"] in uniq:
            continue
        it["categories"] = categorize(it)
        first = seen.get(it["url"])
        it["seen_before"] = bool(first and first < today)
        seen.setdefault(it["url"], today)
        uniq[it["url"]] = it

    # OSS（急上昇・リリース・README）
    oss_repos, releases = [], []
    try:
        oss_repos, releases = oss.collect(CONFIG, items, now, ROOT / "data" / "stars.json",
                                         release_days=7 if edition == "weekly" else 2)
        featured = recently_featured(today)
        for r in oss_repos:
            r["featured_before"] = r["repo"] in featured
        print(f"  OSS候補: {len(oss_repos)}件 / リリース: {len(releases)}件")
    except Exception as e:
        errors["GitHub"] = str(e)
        print(f"  ! GitHub: {e}", file=sys.stderr)

    out = {"date": today, "weekday": "月火水木金土日"[now.weekday()], "edition": edition,
           "collected_at": now.isoformat(timespec="seconds"),
           "errors": errors, "items": list(uniq.values()), "oss": oss_repos, "releases": releases}
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{today}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    seen_path.write_text(json.dumps(seen, ensure_ascii=False))
    brief = ROOT / "data" / "brief" / f"{today}.md"
    write_weekly_brief(out, brief) if edition == "weekly" else write_brief(out, brief)
    new = sum(not i["seen_before"] for i in out["items"])
    print(f"保存: {path.relative_to(ROOT)}  [{edition}] (記事{len(out['items'])}件・新着{new}件 / OSS{len(oss_repos)}件 / リリース{len(releases)}件)")


if __name__ == "__main__":
    main()
