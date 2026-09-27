#!/usr/bin/env python3
"""技術情報を各ソースから収集して data/raw/YYYY-MM-DD.json に保存する（標準ライブラリのみ）。"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())
JST = timezone(timedelta(hours=CONFIG["timezone_offset_hours"]))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) tech-digest/1.0"
LIMITS = CONFIG["limits"]


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def item(source, title, url, summary="", score=None, meta=None):
    return {"source": source, "title": title.strip(), "url": url, "summary": summary[:300],
            "score": score, "meta": meta or {}}


# ---------- 各ソース ----------

def github_trending():
    page = fetch("https://github.com/trending?since=daily")
    out = []
    for block in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S)[:LIMITS["github_trending"]]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', block, re.S)
        if not m:
            continue
        repo = m.group(1)
        desc = re.search(r'<p class="col-9[^"]*">(.*?)</p>', block, re.S)
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
        stars = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', block, re.S)
        today = re.search(r'([\d,]+) stars today', block)
        out.append(item("GitHub Trending", repo, f"https://github.com/{repo}",
                        strip_tags(desc.group(1)) if desc else "",
                        int(today.group(1).replace(",", "")) if today else None,
                        {"language": lang.group(1).strip() if lang else None,
                         "stars": stars.group(1) if stars else None,
                         "score_label": "stars today"}))
    return out


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


def lobsters():
    data = json.loads(fetch("https://lobste.rs/hottest.json"))
    return [item("Lobsters", d["title"], d.get("url") or d["short_id_url"], "", d.get("score"),
                 {"tags": d.get("tags", []), "discussion": d["short_id_url"], "score_label": "points"})
            for d in data[:LIMITS["lobsters"]]]


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


def producthunt():
    return parse_feed(fetch("https://www.producthunt.com/feed"), "Product Hunt", LIMITS["producthunt"])


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
            items = parse_feed(fetch(feed["url"]), feed["name"], LIMITS["rss_per_feed"])
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
    if it["source"] == "Product Hunt":
        cats.append("プロダクト")
    return cats or ["その他"]


def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    sources = {"GitHub Trending": github_trending, "Hacker News": hackernews, "Lobsters": lobsters,
               "Product Hunt": producthunt, "Zenn": zenn, "Qiita": qiita, "はてブ": hatena,
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
    cutoff = (datetime.now(JST) - timedelta(days=CONFIG["seen_retention_days"])).strftime("%Y-%m-%d")
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

    out = {"date": today, "collected_at": datetime.now(JST).isoformat(timespec="seconds"),
           "errors": errors, "items": list(uniq.values())}
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{today}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    seen_path.write_text(json.dumps(seen, ensure_ascii=False))
    new = sum(not i["seen_before"] for i in out["items"])
    print(f"保存: {path.relative_to(ROOT)}  ({len(out['items'])}件, うち新着{new}件)")


if __name__ == "__main__":
    main()
