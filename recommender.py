"""
recommender.py - Find movies & TV shows with a similar *concept*.

How it works
------------
1. Semantic similarity (deep learning): each title's plot overview, tagline,
   genres and keywords are encoded by a Sentence-Transformer into a 384-d
   vector. Titles whose stories are about similar things land close together,
   even when they share no words or genre labels.
2. Tag similarity: TF-IDF over TMDB genres + keywords ("time travel",
   "revenge", "chaebol"...) adds precise thematic overlap.
3. Quality re-ranking: the most similar candidates are re-ranked with a
   Bayesian-weighted rating, so well-reviewed titles rise to the top and
   obscure 3-vote titles don't.
4. Explanations: every result lists the keywords/genres it shares with what
   you liked.

Usage
-----
    python recommender.py build                              # embed data/tmdb/titles.jsonl
    python recommender.py recommend "Crash Landing on You" -n 10
    python recommender.py recommend "Goblin" --type tv --lang ko
    python recommender.py describe "a cold CEO falls in love with a time traveler"

    from recommender import Recommender
    rec = Recommender()
    rec.recommend(["Squid Game", "Alice in Borderland"], media_type="tv")
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer

try:
    from rapidfuzz import fuzz as rf_fuzz
    from rapidfuzz import process as rf_process

    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data" / "tmdb" / "titles.jsonl"
DEFAULT_INDEX = Path(os.environ.get("RECOMMENDER_INDEX", ROOT / "models" / "tmdb_index.joblib"))
DEFAULT_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"
POSTER_BASE = "https://image.tmdb.org/t/p/w342"

LANGUAGES = {
    "en": "English", "ko": "Korean", "ja": "Japanese", "zh": "Chinese (Mandarin)",
    "cn": "Chinese (Cantonese)", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "th": "Thai", "tr": "Turkish", "de": "German", "it": "Italian", "ta": "Tamil",
    "te": "Telugu", "ml": "Malayalam", "pt": "Portuguese", "ru": "Russian",
    "da": "Danish", "sv": "Swedish", "no": "Norwegian", "id": "Indonesian",
    "tl": "Tagalog", "pl": "Polish", "nl": "Dutch", "fa": "Persian", "ar": "Arabic",
}


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """Lowercase, strip accents/punctuation: 'Amélie!' -> 'amelie'."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def strip_article(key: str) -> str:
    """'the avengers' -> 'avengers' so typo matching compares the real title."""
    return re.sub(r"^(the|a|an) ", "", key)


_YEAR = re.compile(r"\s*\((\d{4})\)\s*$")


def split_title_year(raw: str) -> tuple[str, int | None]:
    """'Goblin (2016)' -> ('Goblin', 2016)"""
    m = _YEAR.search(raw)
    return _YEAR.sub("", raw).strip(), (int(m.group(1)) if m else None)


def embed_text(r: dict) -> str:
    """What the encoder reads. Title is left out on purpose: we want 'similar
    story', not 'similar name'."""
    parts = []
    if r["genres"]:
        parts.append("Genres: " + ", ".join(r["genres"]) + ".")
    if r["keywords"]:
        parts.append("Themes: " + ", ".join(r["keywords"][:20]) + ".")
    if r["tagline"]:
        parts.append(r["tagline"])
    parts.append(r["overview"])
    return " ".join(parts)


def tag_tokens(r: dict) -> str:
    """Genres + keywords as single tokens: 'g_science_fiction kw_time_travel'."""
    tok = lambda prefix, s: prefix + re.sub(r"\W+", "_", s.lower()).strip("_")
    return " ".join([tok("g_", g) for g in r["genres"]] + [tok("kw_", k) for k in r["keywords"]])


# --------------------------------------------------------------------------- #
# Build the index
# --------------------------------------------------------------------------- #
def load_titles(path: str | Path = DEFAULT_DATA) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    df = pd.DataFrame(rows).drop_duplicates(["media_type", "tmdb_id"]).reset_index(drop=True)
    for col in ("genres", "keywords", "countries", "aka", "aka_en"):
        if col not in df:
            df[col] = [[] for _ in range(len(df))]
        df[col] = df[col].apply(lambda v: v if isinstance(v, list) else [])
    df["tagline"] = df["tagline"].fillna("")
    # Safety net (older downloads may include them): no reality/talk/news shows.
    unscripted = df["genres"].apply(lambda g: bool({"Reality", "Talk", "News"} & set(g)))
    return df[~unscripted].reset_index(drop=True)


def bayesian_quality(df: pd.DataFrame) -> pd.Series:
    """IMDb-style weighted rating, computed separately for movies and TV
    (TV shows get far fewer votes on TMDB), then scaled to 0..1."""
    out = pd.Series(0.0, index=df.index)
    for _, g in df.groupby("media_type"):
        C = np.average(g["vote_average"], weights=g["vote_count"].clip(lower=1))
        m = max(float(g["vote_count"].quantile(0.5)), 1.0)
        v, R = g["vote_count"], g["vote_average"]
        out[g.index] = (v / (v + m)) * R + (m / (v + m)) * C
    return (out - out.min()) / (out.max() - out.min() or 1)


def build_index(
    data_path: str | Path = DEFAULT_DATA,
    index_path: str | Path = DEFAULT_INDEX,
    encoder: str = DEFAULT_ENCODER,
    batch_size: int = 64,
) -> Path:
    from sentence_transformers import SentenceTransformer  # heavy import: only when building

    df = load_titles(data_path)
    print(f"Loaded {len(df)} titles from {data_path}")

    model = SentenceTransformer(encoder)
    texts = [embed_text(r) for r in df.to_dict("records")]
    emb = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                       show_progress_bar=True, convert_to_numpy=True)

    tags = TfidfVectorizer(token_pattern=r"\S+", min_df=2, sublinear_tf=True)
    tag_mat = tags.fit_transform([tag_tokens(r) for r in df.to_dict("records")])

    df["quality"] = bayesian_quality(df)
    payload = {
        "meta": df,
        "emb": emb.astype(np.float16),  # half precision: halves file size, no quality loss for ranking
        "tags": tag_mat.astype(np.float32).tocsr(),
        "encoder": encoder,
    }
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, index_path, compress=3)
    print(f"Saved index to {index_path} ({index_path.stat().st_size / 1e6:.1f} MB)")
    return index_path


# --------------------------------------------------------------------------- #
# Serve recommendations
# --------------------------------------------------------------------------- #
class Recommender:
    def __init__(self, index_path: str | Path = DEFAULT_INDEX):
        p = joblib.load(index_path)
        self.meta: pd.DataFrame = p["meta"]
        self.emb: np.ndarray = p["emb"].astype(np.float32)
        self.tags: csr_matrix = p["tags"]
        self.encoder_name: str = p["encoder"]
        self._encoder = None

        m = self.meta
        self.uids = (m["media_type"] + ":" + m["tmdb_id"].astype(str)).tolist()
        self._uid_to_idx = {u: i for i, u in enumerate(self.uids)}
        self._pop = m["vote_count"].to_numpy()
        self._quality = m["quality"].to_numpy()
        # Every row is searchable by its title, original title and alternative titles
        # ("Goblin" -> "Guardian: The Lonely and Great God"). Main titles win ties.
        akas = m["aka"] if "aka" in m else [[]] * len(m)
        self._names: list[list[str]] = []
        self._main_to_idx: dict[str, list[int]] = {}
        self._aka_to_idx: dict[str, list[int]] = {}
        fuzzy_names, self._fuzzy_owner = [], []
        for i, (t, o, aka) in enumerate(zip(m["title"], m["original_title"].fillna(""), akas)):
            names = list(dict.fromkeys(n for n in map(normalize, [t, o, *aka]) if n))
            self._names.append(names)
            for j, n in enumerate(names):
                (self._main_to_idx if j == 0 else self._aka_to_idx).setdefault(n, []).append(i)
                fuzzy_names.append(strip_article(n))
                self._fuzzy_owner.append(i)
        self._fuzzy_keys = fuzzy_names

    # ---- search ---------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Autocomplete with typo tolerance ('crash landng' -> Crash Landing on You)."""
        return [self._card(i) for i in self._search_idx(query, limit)]

    def _search_idx(self, query: str, limit: int) -> list[int]:
        q = normalize(split_title_year(query)[0])
        if not q:
            return []
        exact, starts, contains = [], [], []
        for i, names in enumerate(self._names):
            if q in names:
                exact.append(i)
            elif any(n.startswith(q) for n in names):
                starts.append(i)
            elif any(f" {q}" in f" {n}" for n in names):
                contains.append(i)
        by_pop = lambda idx: sorted(idx, key=lambda i: -self._pop[i])
        ordered = by_pop(exact) + by_pop(starts) + by_pop(contains)
        if len(ordered) < limit:
            seen = set(ordered)
            for i in self._fuzzy(q, limit * 2):
                if i not in seen:
                    ordered.append(i)
                    seen.add(i)
        return ordered[:limit]

    def _fuzzy(self, q: str, n: int) -> list[int]:
        # Whole-title similarity, leading articles ignored: "avangers" -> "The Avengers".
        # (WRatio's partial matching let junk through: "zzzz" -> "Z", "avangers" -> "Savages".)
        q = strip_article(q)
        own = self._fuzzy_owner
        if HAVE_RAPIDFUZZ:
            hits = rf_process.extract(q, self._fuzzy_keys, scorer=rf_fuzz.ratio, limit=n * 2, score_cutoff=75)
            hits.sort(key=lambda h: (-h[1], -self._pop[own[h[2]]]))  # ties: most-voted first (remakes)
            idx = [own[j] for _, _, j in hits]
        else:
            close = set(difflib.get_close_matches(q, self._fuzzy_keys, n=n, cutoff=0.75))
            idx = [own[j] for j, k in enumerate(self._fuzzy_keys) if k in close]
        return list(dict.fromkeys(idx))[:n]

    def resolve(self, item: str) -> int | None:
        """'tv:94796', 'Crash Landing on You', or 'Oldboy (2003)' -> row index."""
        if item in self._uid_to_idx:
            return self._uid_to_idx[item]
        title, year = split_title_year(item)
        key = normalize(title)
        for table in (self._main_to_idx, self._aka_to_idx):  # main titles first, then aliases
            exact = table.get(key, [])
            if year is not None:
                exact = [i for i in exact if self.meta.at[i, "year"] == year] or exact
            if exact:
                return max(exact, key=lambda i: self._pop[i])  # remakes: prefer most-voted
        best = self._search_idx(item, 1)
        return best[0] if best else None

    # ---- recommend --------------------------------------------------------------
    def recommend(
        self,
        liked: str | Iterable[str],
        top_n: int = 12,
        media_type: str | None = None,          # "movie", "tv" or None for both
        languages: Iterable[str] | None = None,  # e.g. ["ko", "ja"]
        years: tuple[int, int] | None = None,
        semantic_weight: float = 0.75,           # vs. genre/keyword overlap
        alpha: float = 0.10,                     # 0 = pure similarity, 1 = pure rating
        candidates: int = 300,
    ) -> dict:
        liked = [liked] if isinstance(liked, str) else list(liked)
        idxs = [i for i in (self.resolve(x) for x in liked) if i is not None]
        if not idxs:
            return {"matched": [], "results": [],
                    "suggestions": self.search(liked[0], 5) if liked else []}
        idxs = list(dict.fromkeys(idxs))

        # one "taste" vector = average of everything the user liked
        q_emb = self.emb[idxs].mean(axis=0)
        q_emb /= np.linalg.norm(q_emb) or 1
        sem = self.emb @ q_emb

        q_tag = np.asarray(self.tags[idxs].mean(axis=0)).ravel()
        n = np.linalg.norm(q_tag)
        tag = self.tags @ (q_tag / n) if n else np.zeros(len(self.meta))

        sims = semantic_weight * sem + (1 - semantic_weight) * tag
        sims[idxs] = -np.inf
        results = self._rank(sims, top_n, media_type, languages, years, alpha, candidates,
                             why_from=idxs)
        return {"matched": [self._card(i) for i in idxs], "results": results, "suggestions": []}

    def describe(self, text: str, top_n: int = 12, media_type: str | None = None,
                 languages: Iterable[str] | None = None, years: tuple[int, int] | None = None,
                 alpha: float = 0.1) -> dict:
        """Free-text search: 'a contract marriage between a chaebol heir and a webtoon artist'."""
        q = self.encoder.encode([text], normalize_embeddings=True)[0].astype(np.float32)
        sims = self.emb @ q
        return {"matched": [], "suggestions": [],
                "results": self._rank(sims, top_n, media_type, languages, years, alpha, 300)}

    @property
    def encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(self.encoder_name)
        return self._encoder

    def _rank(self, sims, top_n, media_type, languages, years, alpha, candidates,
              why_from: list[int] | None = None) -> list[dict]:
        m = self.meta
        mask = np.ones(len(m), dtype=bool)
        if media_type in ("movie", "tv"):
            mask &= (m["media_type"] == media_type).to_numpy()
        if languages:
            mask &= m["original_language"].isin(list(languages)).to_numpy()
        if years:
            y = m["year"].fillna(0).to_numpy()
            mask &= (y >= years[0]) & (y <= years[1])
        sims = np.where(mask, sims, -np.inf)

        k = min(candidates, int(np.isfinite(sims).sum()))
        if k == 0:
            return []
        top = np.argpartition(-sims, k - 1)[:k]
        final = (1 - alpha) * sims[top] + alpha * self._quality[top]
        order = top[np.argsort(-final)][:top_n]

        liked_kw, liked_g = set(), set()
        for i in why_from or []:
            liked_kw |= set(m.at[i, "keywords"])
            liked_g |= set(m.at[i, "genres"])
        out = []
        for i in order:
            card = self._card(int(i))
            card["match"] = round(float(sims[i]), 3)
            if why_from:
                card["shared_keywords"] = [k for k in m.at[i, "keywords"] if k in liked_kw][:6]
                card["shared_genres"] = [g for g in m.at[i, "genres"] if g in liked_g]
            out.append(card)
        return out

    # ---- output -------------------------------------------------------------------
    def _card(self, i: int) -> dict:
        r = self.meta.iloc[i]
        year = None if pd.isna(r["year"]) else int(r["year"])
        return {
            "uid": self.uids[i],
            "tmdb_id": int(r["tmdb_id"]),
            "media_type": r["media_type"],
            "title": r["title"],
            "original_title": r["original_title"],
            "aka": self.aka(i),
            "year": year,
            "language": r["original_language"],
            "language_name": LANGUAGES.get(r["original_language"], r["original_language"]),
            "genres": list(r["genres"]),
            "keywords": list(r["keywords"]),
            "overview": r["overview"],
            "rating": round(float(r["vote_average"]), 1),
            "votes": int(r["vote_count"]),
            "poster_url": f"{POSTER_BASE}{r['poster_path']}" if r["poster_path"] else None,
            "tmdb_url": f"https://www.themoviedb.org/{r['media_type']}/{int(r['tmdb_id'])}",
        }

    def label(self, i: int) -> str:
        r = self.meta.iloc[i]
        kind = "TV" if r["media_type"] == "tv" else "Movie"
        year = "" if pd.isna(r["year"]) else f" ({int(r['year'])})"
        aka = self.aka(i)
        return (f"{r['title']}{year} · {kind} · "
                f"{LANGUAGES.get(r['original_language'], r['original_language'])}"
                + (f" · aka {aka}" if aka else ""))

    def aka(self, i: int) -> str | None:
        """Best-known English alias for non-English titles ('Goblin'), else None."""
        r = self.meta.iloc[i]
        if r["original_language"] == "en" or "aka_en" not in r:
            return None
        names = [a for a in r["aka_en"] if 2 < len(a) < len(r["title"]) and ":" not in a]
        return min(names, key=len) if names else None


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def _print_results(out: dict) -> None:
    for i, x in enumerate(out["results"], 1):
        kind = "TV" if x["media_type"] == "tv" else "Movie"
        why = ", ".join(x.get("shared_keywords") or x.get("shared_genres") or [])
        print(f"{i:>2}. {x['title']} ({x['year']}) [{kind}, {x['language']}]  "
              f"match={x['match']:.2f}  rating={x['rating']} ({x['votes']} votes)"
              + (f"\n      shares: {why}" if why else ""))


def _main() -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap =argparse.ArgumentParser(description="Concept-based movie & TV recommender")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="embed titles and save the index")
    b.add_argument("--data", default=DEFAULT_DATA)
    b.add_argument("--out", default=DEFAULT_INDEX)
    b.add_argument("--encoder", default=DEFAULT_ENCODER)

    for name in ("recommend", "describe"):
        p = sub.add_parser(name)
        p.add_argument("query", nargs="+", help="title(s)" if name == "recommend" else "plot description")
        p.add_argument("-n", type=int, default=10)
        p.add_argument("--type", choices=["movie", "tv"])
        p.add_argument("--lang", nargs="*", help="original language codes, e.g. ko ja")
        p.add_argument("--index", default=DEFAULT_INDEX)

    a = ap.parse_args()
    if a.cmd == "build":
        build_index(a.data, a.out, a.encoder)
        return

    rec = Recommender(a.index)
    if a.cmd == "describe":
        _print_results(rec.describe(" ".join(a.query), a.n, a.type, a.lang))
        return
    out = rec.recommend(a.query, a.n, a.type, a.lang)
    if not out["matched"]:
        print("No match." + (" Did you mean:" if out["suggestions"] else " Try another spelling."), *[f"  - {rec.label(rec.resolve(s['uid']))}"
                                          for s in out["suggestions"]], sep="\n")
        return
    print("Because you liked:", "; ".join(f"{m['title']} ({m['year']})" for m in out["matched"]), "\n")
    _print_results(out)


if __name__ == "__main__":
    _main()
