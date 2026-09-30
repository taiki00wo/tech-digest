"""OSS まわりの収集: 急上昇リポジトリ（スター増分を自前で計算）・ウォッチ対象のリリース・README。

GitHub の Web ページはクラウド環境の共有IPだと 403 で弾かれるので、公式 REST API を使う。
未認証は 60回/時 と少ないため、環境変数 GITHUB_TOKEN があれば使う（読み取り専用トークンで十分）。
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
UA = "tech-digest/1.0 (+https://github.com/taiki00wo/tech-digest)"
REPO_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
NOT_REPOS = {"orgs", "users", "topics", "features", "sponsors", "settings", "marketplace", "collections", "trending"}


def gh(path, raw=False):
    headers = {"User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28",
               "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8", errors="replace")
    return body if raw else json.loads(body)


def repo_summary(r):
    return {"repo": r["full_name"], "url": r["html_url"], "description": r.get("description") or "",
            "language": r.get("language"), "stars": r["stargazers_count"], "topics": r.get("topics", [])[:6],
            "created_at": r.get("created_at", "")[:10], "pushed_at": r.get("pushed_at", "")[:10]}


def linked_repos(items):
    """記事（HN・Lobsters・はてブなど）の URL に出てくる GitHub リポジトリを拾う。"""
    found = []
    for it in items:
        m = REPO_RE.match(it["url"])
        if m and m.group(1).lower() not in NOT_REPOS:
            found.append(f"{m.group(1)}/{m.group(2).removesuffix('.git')}")
    return list(dict.fromkeys(found))


def candidates(config, items, today):
    """急上昇の候補: 最近作られた人気リポジトリ + 記事中のリポジトリ + ウォッチ対象。"""
    repos = {}
    since = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    q = urllib.parse.quote(f"created:>{since} stars:>100")
    for r in gh(f"/search/repositories?q={q}&sort=stars&order=desc&per_page=50")["items"]:
        repos[r["full_name"]] = {**repo_summary(r), "found_in": "新着人気"}

    extra = [n for n in linked_repos(items) if n not in repos][:25]

    def lookup(name):
        try:
            return gh(f"/repos/{name}")
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        for name, r in zip(extra, ex.map(lookup, extra)):
            if r:
                repos[r["full_name"]] = {**repo_summary(r), "found_in": "記事で紹介"}
    return repos


def update_stars(repos, stars_path, today_str, retention_days=14):
    """スター数を日ごとに記録し、前回記録からの増分（1日あたり）を付ける。"""
    history = json.loads(stars_path.read_text()) if stars_path.exists() else {}
    cutoff = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    for name, r in repos.items():
        h = {d: s for d, s in history.get(name, {}).items() if d >= cutoff and d != today_str}
        if h:
            prev_day = max(h)
            days = max(1, (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(prev_day, "%Y-%m-%d")).days)
            r["stars_per_day"] = round((r["stars"] - h[prev_day]) / days)
        else:
            # 初めて見るリポジトリは「作成からの平均」で代用（新しいほど実態に近い）
            age = max(1, (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(r["created_at"] or today_str, "%Y-%m-%d")).days)
            r["stars_per_day"] = round(r["stars"] / age) if age <= 60 else None
            r["estimated"] = True
        h[today_str] = r["stars"]
        history[name] = h
    history = {n: h for n, h in history.items() if h}
    stars_path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")))


def readme(name, limit=6000):
    try:
        text = gh(f"/repos/{name}/readme", raw=True)
    except Exception:
        return ""
    text = re.sub(r"<[^>]+>", "", text)          # バッジ等の HTML を除く
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


PRERELEASE_RE = re.compile(r"canary|alpha|beta|rc\.?\d|nightly|next|preview|experimental", re.I)


def releases(watch, today, days=2):
    """ウォッチ対象の正式リリース（直近 days 日）。"owner/repo:prefix" と書くとタグの接頭辞で絞る（モノレポ用）。"""
    cutoff = (today - timedelta(days=days)).isoformat()

    def one(entry):
        name, _, prefix = entry.partition(":")
        try:
            rels = gh(f"/repos/{name}/releases?per_page=5")
        except Exception as e:
            print(f"  ! releases {name}: {e}", file=sys.stderr)
            return []
        return [{"repo": name, "version": r["tag_name"], "name": r.get("name") or r["tag_name"],
                 "url": r["html_url"], "published_at": r["published_at"], "prerelease": r["prerelease"],
                 "body": (r.get("body") or "")[:3000]}
                for r in rels
                if not r["draft"] and not r["prerelease"] and not PRERELEASE_RE.search(r["tag_name"])
                and r["tag_name"].startswith(prefix) and (r.get("published_at") or "") >= cutoff]

    with ThreadPoolExecutor(8) as ex:
        return [r for rs in ex.map(one, watch) for r in rs]


def collect(config, items, today_dt, stars_path, release_days=2):
    today_str = today_dt.strftime("%Y-%m-%d")
    repos = candidates(config, items, today_dt)
    update_stars(repos, stars_path, today_str)
    ranked = sorted(repos.values(), key=lambda r: -(r.get("stars_per_day") or 0))[:config["oss"]["candidates"]]
    # README は上位だけ取る（急上昇の説明と深掘りに使う）
    with ThreadPoolExecutor(6) as ex:
        for r, text in zip(ranked[:config["oss"]["readme_top"]], ex.map(readme, [r["repo"] for r in ranked[:config["oss"]["readme_top"]]])):
            r["readme"] = text
    rels = releases(config["watch_repos"], today_dt.astimezone(timezone.utc), release_days)
    return ranked, rels
