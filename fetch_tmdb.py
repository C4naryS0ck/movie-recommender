"""
fetch_tmdb.py - Download movies + TV shows (K-dramas included) from the TMDB API.

For every title we keep: title, type (movie/tv), original language, countries,
year, genres, keywords, tagline, plot overview, rating, vote count, popularity
and poster path.

Setup
-----
1. Create a free account at https://www.themoviedb.org and request an API key
   (Settings -> API). Either the "API Key" or the "API Read Access Token" works.
2. Put it in a `.env` file next to this script:   TMDB_API_KEY=xxxxxxxx
3. Run:
       python fetch_tmdb.py                 # ~12-15k titles, ~10-15 min
       python fetch_tmdb.py --scale 0.2     # quick test run, ~2 min

The script is resumable: detail pages already downloaded are cached in
data/tmdb/cache/, so re-running only fetches what's missing.
Output: data/tmdb/titles.jsonl (one JSON object per line).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "tmdb"
API = "https://api.themoviedb.org/3"

# (language code or None for "all languages", pages of 20 titles) per media type.
# The extra Asian/international buckets are what make K-drama recs possible:
# a global "popular" list is dominated by Hollywood.
CRAWL_PLAN: dict[str, list[tuple[str | None, int]]] = {
    "movie": [(None, 200), ("ko", 40), ("ja", 30), ("zh", 15), ("cn", 10),
              ("hi", 20), ("es", 15), ("fr", 15), ("th", 5)],
    "tv": [(None, 150), ("ko", 60), ("ja", 40), ("zh", 25), ("cn", 10),
           ("hi", 10), ("es", 10), ("th", 10), ("tr", 5)],
}
MIN_VOTES = {"movie": 30, "tv": 10}  # skip obscure titles with unreliable data
# TV genre ids for News, Reality and Talk. Korean TV popularity is dominated by
# variety shows (Running Man, 2 Days and 1 Night...), which would crowd out dramas.
SKIP_TV_GENRES = "10763|10764|10767"


class TMDB:
    """Tiny TMDB client: auth, retries, and a polite rate limit."""

    def __init__(self, key: str, max_rps: float = 35.0):
        self.s = requests.Session()
        if key.startswith("eyJ"):  # v4 read-access token (a JWT)
            self.s.headers["Authorization"] = f"Bearer {key}"
            self.params = {}
        else:  # v3 API key
            self.params = {"api_key": key}
        self._lock = threading.Lock()
        self._gap = 1.0 / max_rps
        self._next = 0.0

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._gap
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, **params) -> dict:
        for attempt in range(7):
            self._throttle()
            try:
                r = self.s.get(f"{API}{path}", params={**self.params, **params}, timeout=20)
            except requests.RequestException:  # connection resets happen; back off and retry
                time.sleep(min(2**attempt, 20))
                continue
            if r.status_code == 429:  # rate limited
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code == 401:
                raise SystemExit("TMDB rejected the API key (401). Check TMDB_API_KEY in .env")
            if r.status_code == 404:
                return {}
            if r.ok:
                return r.json()
            time.sleep(min(2**attempt, 20))
        print(f"  ! gave up on {path} {params.get('page', '')}")
        return {}


def discover(api: TMDB, media: str, lang: str | None, pages: int) -> list[dict]:
    params = {
        "sort_by": "popularity.desc",
        "language": "en-US",  # English overviews where TMDB has them
        "include_adult": "false",
        "vote_count.gte": MIN_VOTES[media],
    }
    if lang:
        params["with_original_language"] = lang
    if media == "tv":
        params["without_genres"] = SKIP_TV_GENRES
    results: list[dict] = []
    total = 500  # TMDB caps discover at 500 pages
    for page in range(1, min(pages, 500) + 1):
        if page > total:
            break
        data = api.get(f"/discover/{media}", page=page, **params)
        if not data:  # failed page: skip it, don't abandon the whole list
            continue
        results.extend(data.get("results", []))
        total = data.get("total_pages", total)
    return results


def fetch_details(api: TMDB, media: str, tmdb_id: int) -> dict:
    """Details + keywords + alternative titles, cached on disk so the crawl can be resumed."""
    cache = OUT_DIR / "cache" / f"{media}_{tmdb_id}.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if "alternative_titles" in cached:  # older cache files lack it: refetch those
            return cached
    data = api.get(f"/{media}/{tmdb_id}", language="en-US",
                   append_to_response="keywords,alternative_titles")
    if data:
        cache.write_text(json.dumps(data), encoding="utf-8")
    return data


AKA_COUNTRIES = {"US", "GB", "CA", "AU", "NZ", "IE", "IN", "PH", "SG",  # English markets
                 "KR", "JP", "CN", "TW", "HK", "TH"}                      # romanized names


def alternative_titles(d: dict, title: str, countries=AKA_COUNTRIES) -> list[str]:
    """Latin-script alternative names: 'Goblin' and 'Dokkaebi' for
    'Guardian: The Lonely and Great God'. English-market names come first."""
    alt = d.get("alternative_titles", {})
    rows = alt.get("results", alt.get("titles", []))
    rows = sorted(rows, key=lambda r: r.get("iso_3166_1") not in {"US", "GB"})
    seen, out = {title.lower()}, []
    for r in rows:
        t = (r.get("title") or "").strip()
        if t and t.isascii() and r.get("iso_3166_1") in countries and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:8]


def to_record(media: str, d: dict) -> dict | None:
    overview = (d.get("overview") or "").strip()
    if not overview:
        return None
    title = d.get("title") or d.get("name")
    kw = d.get("keywords", {})
    keywords = [k["name"] for k in kw.get("keywords", kw.get("results", []))]
    date = d.get("release_date") if media == "movie" else d.get("first_air_date")
    countries = (
        [c["iso_3166_1"] for c in d.get("production_countries", [])]
        if media == "movie" else d.get("origin_country", [])
    )
    return {
        "tmdb_id": d["id"],
        "media_type": media,
        "title": title,
        "original_title": d.get("original_title") or d.get("original_name"),
        "aka": alternative_titles(d, title),
        "aka_en": alternative_titles(d, title, {"US", "GB"}),  # for "aka Goblin" labels
        "original_language": d.get("original_language"),
        "countries": countries,
        "year": int(date[:4]) if date and date[:4].isdigit() else None,
        "genres": [g["name"] for g in d.get("genres", [])],
        "keywords": keywords,
        "tagline": d.get("tagline") or "",
        "overview": overview,
        "vote_average": d.get("vote_average") or 0.0,
        "vote_count": d.get("vote_count") or 0,
        "popularity": d.get("popularity") or 0.0,
        "poster_path": d.get("poster_path"),
        "seasons": d.get("number_of_seasons"),
        "episodes": d.get("number_of_episodes"),
        "runtime": d.get("runtime"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply page counts (0.2 = quick test)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set TMDB_API_KEY in a .env file (see .env.example)")
    api = TMDB(key)
    (OUT_DIR / "cache").mkdir(parents=True, exist_ok=True)

    # 1) collect ids from discover lists ------------------------------------------
    ids: dict[tuple[str, int], None] = {}
    for media, plan in CRAWL_PLAN.items():
        for lang, pages in plan:
            n = max(1, round(pages * args.scale))
            found = discover(api, media, lang, n)
            for r in found:
                ids.setdefault((media, r["id"]), None)
            print(f"discover {media:5} lang={lang or 'all':4} pages={n:3} -> {len(found):5} "
                  f"(unique so far: {len(ids)})")

    # 2) fetch details + keywords in parallel ---------------------------------------
    records, done = [], 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(fetch_details, api, m, i): (m, i) for m, i in ids}
        for fut in as_completed(futures):
            media, _ = futures[fut]
            rec = to_record(media, fut.result())
            if rec:
                records.append(rec)
            done += 1
            if done % 500 == 0 or done == len(futures):
                print(f"details {done}/{len(futures)}")

    out = OUT_DIR / "titles.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in sorted(records, key=lambda r: -r["popularity"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by = {}
    for r in records:
        k = (r["media_type"], r["original_language"])
        by[k] = by.get(k, 0) + 1
    ko_tv = by.get(("tv", "ko"), 0)
    print(f"\nSaved {len(records)} titles to {out}  (Korean TV shows: {ko_tv})")


if __name__ == "__main__":
    main()
