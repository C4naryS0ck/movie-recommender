"""
phase1_movielens.py - Phase 1 movie recommendation engine (content-based + popularity hybrid)

What this adds on top of phase-1.ipynb
--------------------------------------
1. Title cleaning that understands MovieLens' "Matrix, The (1999)" format
2. Fuzzy search / autocomplete (typos are fine: "avangers" -> "The Avengers")
3. Hybrid ranking: content similarity re-ranked by a Bayesian quality score
4. Lightweight saving: stores the sparse TF-IDF matrix (a few MB) instead of the
   9,700 x 9,700 cosine matrix (~750 MB). Similarity is computed per request.
5. JSON-friendly output

Superseded by recommender.py (Phase 2: TMDB movies + TV, sentence embeddings).
MovieLens has no TV shows and no plot text, which is why Phase 2 exists.

Usage
-----
    pip install pandas numpy scipy scikit-learn joblib rapidfuzz

    python phase1_movielens.py build                       # builds models/recommender.joblib
    python phase1_movielens.py recommend "toy story" -n 5  # try it in the terminal

    # in a notebook or your API:
    from phase1_movielens import MovieRecommender
    rec = MovieRecommender()
    rec.recommend("the matrix")
    rec.search("avatr")
"""
from __future__ import annotations

import argparse
import difflib
import re
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

try:  # rapidfuzz is faster and better; difflib is the built-in fallback
    from rapidfuzz import fuzz as rf_fuzz
    from rapidfuzz import process as rf_process

    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data" / "ml-latest-small"
DEFAULT_MODEL_PATH = ROOT / "models" / "recommender.joblib"


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
_YEAR = re.compile(r"\s*\((\d{4})\)\s*$")
_ARTICLE = re.compile(r"^(?P<main>.*), (?P<art>The|A|An)$")


def split_title_year(raw: str) -> tuple[str, int | None]:
    """'Matrix, The (1999)' -> ('Matrix, The', 1999)"""
    m = _YEAR.search(raw)
    year = int(m.group(1)) if m else None
    return _YEAR.sub("", raw).strip(), year


def fix_article(title: str) -> str:
    """'Matrix, The' -> 'The Matrix' (alt-title parentheses are left untouched)."""
    main, sep, rest = title.partition(" (")
    m = _ARTICLE.match(main)
    if m:
        main = f"{m['art']} {m['main']}"
    return main + sep + rest


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation: 'Amélie!' -> 'amelie'."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def strip_article(key: str) -> str:
    """'the avengers' -> 'avengers' so typo matching compares the real title."""
    return re.sub(r"^(the|a|an) ", "", key)


def clean_query(query: str) -> tuple[str, int | None]:
    """Turn user input into (normalized title, optional year)."""
    title, year = split_title_year(query.strip())
    return normalize(fix_article(title)), year


def genre_text(genres: str) -> str:
    """'Sci-Fi|Film-Noir' -> 'SciFi FilmNoir' (keeps hyphenated genres as one token)."""
    if genres == "(no genres listed)":
        return ""
    return " ".join(g.replace("-", "") for g in genres.split("|"))


# --------------------------------------------------------------------------- #
# Phase A: build + save the model
# --------------------------------------------------------------------------- #
def build_model(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    genre_weight: float = 0.6,
    min_df_tags: int = 2,
) -> Path:

    data_dir = Path(data_dir)
    movies = pd.read_csv(data_dir / "movies.csv")
    ratings = pd.read_csv(data_dir / "ratings.csv", usecols=["movieId", "rating"])
    tags = pd.read_csv(data_dir / "tags.csv", usecols=["movieId", "tag"]).dropna()

    # --- titles ---------------------------------------------------------------
    parsed = movies["title"].map(split_title_year)
    movies["year"] = pd.array([p[1] for p in parsed], dtype="Int64")
    movies["title_clean"] = [fix_article(p[0]) for p in parsed]

    # --- links (tmdbId is used in Phase 4 to fetch posters) ----------------------
    links_path = data_dir / "links.csv"
    if links_path.exists():
        links = pd.read_csv(links_path)[["movieId", "imdbId", "tmdbId"]]
        movies = movies.merge(links, on="movieId", how="left")
    else:
        movies["imdbId"] = np.nan
        movies["tmdbId"] = np.nan

    # --- rating stats + Bayesian (weighted) rating --------------------------------
    stats = (
        ratings.groupby("movieId")["rating"]
        .agg(avg_rating="mean", rating_count="count")
        .reset_index()
    )
    movies = movies.merge(stats, on="movieId", how="left")
    movies["rating_count"] = movies["rating_count"].fillna(0).astype(int)

    C = ratings["rating"].mean()  # global mean rating
    rated = movies.loc[movies["rating_count"] > 0, "rating_count"]
    m = max(float(rated.quantile(0.60)), 1.0)  # "votes needed to be trusted"
    R = movies["avg_rating"].fillna(C)
    v = movies["rating_count"]
    movies["bayes_rating"] = (v / (v + m)) * R + (m / (v + m)) * C

    span = movies["bayes_rating"].max() - movies["bayes_rating"].min()
    movies["quality"] = (
        (movies["bayes_rating"] - movies["bayes_rating"].min()) / span if span else 0.0
    )

    # --- text features -----------------------------------------------------------
    movies["genre_text"] = movies["genres"].map(genre_text)
    tag_text = tags.groupby("movieId")["tag"].apply(lambda s: " ".join(s.str.lower()))
    movies["tag_text"] = movies["movieId"].map(tag_text).fillna("")

    g_mat = TfidfVectorizer().fit_transform(movies["genre_text"])
    try:
        t_mat = TfidfVectorizer(
            stop_words="english", min_df=min_df_tags, sublinear_tf=True
        ).fit_transform(movies["tag_text"])
    except ValueError:  # no usable tags
        t_mat = csr_matrix((len(movies), 0))

    # Each block is L2-normalised, so scaling by sqrt(weight) makes the dot product
    #   similarity = genre_weight * cos_genres + (1 - genre_weight) * cos_tags
    matrix = hstack(
        [g_mat * np.sqrt(genre_weight), t_mat * np.sqrt(1 - genre_weight)]
    ).tocsr()

    keep = [
        "movieId", "title_clean", "year", "genres", "avg_rating",
        "rating_count", "bayes_rating", "quality", "tmdbId", "imdbId",
    ]
    payload = {"movies": movies[keep].reset_index(drop=True), "matrix": matrix}

    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, model_path, compress=3)
    return model_path


# --------------------------------------------------------------------------- #
# Phase B: load + serve recommendations
# --------------------------------------------------------------------------- #
class MovieRecommender:
    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH):
        payload = joblib.load(model_path)
        self.movies: pd.DataFrame = payload["movies"]
        self.matrix: csr_matrix = payload["matrix"]

        self._counts = self.movies["rating_count"].to_numpy()
        self._keys = [normalize(t) for t in self.movies["title_clean"]]
        self._fuzzy_keys = [strip_article(k) for k in self._keys]
        self._id_to_idx = {int(mid): i for i, mid in enumerate(self.movies["movieId"])}
        self._key_to_idx: dict[str, list[int]] = {}
        for i, k in enumerate(self._keys):
            self._key_to_idx.setdefault(k, []).append(i)

    # ---- search -----------------------------------------------------------------
    def _fuzzy(self, q: str, n: int) -> list[int]:
        # Whole-title similarity, leading articles ignored: "avangers" -> "The Avengers".
        # (WRatio's partial matching let junk through: "zzzz" -> "Z", "avangers" -> "Savages".)
        q = strip_article(q)
        if HAVE_RAPIDFUZZ:
            hits = rf_process.extract(q, self._fuzzy_keys, scorer=rf_fuzz.ratio, limit=n, score_cutoff=75)
            hits.sort(key=lambda h: (-h[1], -self._counts[h[2]]))  # ties: most-voted first (remakes)
            return [i for _, _, i in hits]
        close = difflib.get_close_matches(q, self._fuzzy_keys, n=n, cutoff=0.75)
        return [i for i, k in enumerate(self._fuzzy_keys) if k in close][:n]

    def _search_idx(self, query: str, limit: int) -> list[int]:
        q, _ = clean_query(query)
        if not q:
            return []
        starts, contains = [], []
        for i, k in enumerate(self._keys):
            if k.startswith(q):
                starts.append(i)
            elif f" {q}" in f" {k}":  # matches at the start of any later word
                contains.append(i)
        most_rated_first = lambda idxs: sorted(idxs, key=lambda i: -self._counts[i])
        ordered = most_rated_first(starts) + most_rated_first(contains)
        if len(ordered) < limit:  # fall back to typo-tolerant matching
            seen = set(ordered)
            for i in self._fuzzy(q, limit * 2):
                if i not in seen:
                    ordered.append(i)
                    seen.add(i)
        return ordered[:limit]

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Autocomplete / 'did you mean' suggestions."""
        return [self._card(i) for i in self._search_idx(query, limit)]

    def _resolve(self, movie: int | str) -> int | None:
        if isinstance(movie, (int, np.integer)):
            return self._id_to_idx.get(int(movie))
        q, year = clean_query(str(movie))
        exact = self._key_to_idx.get(q, [])
        if year is not None:
            exact = [i for i in exact if self.movies["year"].iloc[i] == year] or exact
        if exact:  # remakes share titles: prefer the most-rated one
            return max(exact, key=lambda i: self._counts[i])
        best = self._search_idx(str(movie), 1)
        return best[0] if best else None

    # ---- recommend ----------------------------------------------------------------
    def recommend(
        self,
        movie: int | str,
        top_n: int = 10,
        alpha: float = 0.25,
        candidates: int = 200,
        min_ratings: int = 3,
    ) -> dict:
        """
        alpha:       0 = pure similarity, 1 = pure quality. 0.2-0.3 works well.
        candidates:  take the N most similar movies first, then re-rank by hybrid score.
                     (Stops popular-but-unrelated movies from sneaking in.)
        min_ratings: ignore movies with fewer ratings than this.
        """
        idx = self._resolve(movie)
        if idx is None:
            return {"query": movie, "matched": None, "results": [],
                    "suggestions": self.search(str(movie), 5)}

        sims = linear_kernel(self.matrix[idx], self.matrix).ravel()
        sims = np.where(self._counts >= min_ratings, sims, -1.0)
        sims[idx] = -1.0  # never recommend the movie itself

        k = min(candidates, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[sims[top] > 0]

        quality = self.movies["quality"].to_numpy()
        final = (1 - alpha) * sims[top] + alpha * quality[top]
        order = np.argsort(-final)[:top_n]

        results = [
            self._card(int(top[o]), similarity=float(sims[top[o]]), score=float(final[o]))
            for o in order
        ]
        return {"query": movie, "matched": self._card(idx), "results": results,
                "suggestions": []}

    # ---- output -------------------------------------------------------------------
    def _card(self, i: int, similarity: float | None = None, score: float | None = None) -> dict:
        r = self.movies.iloc[i]
        genres = [] if r["genres"] == "(no genres listed)" else r["genres"].split("|")
        card = {
            "movieId": int(r["movieId"]),
            "title": r["title_clean"],
            "year": None if pd.isna(r["year"]) else int(r["year"]),
            "genres": genres,
            "avg_rating": None if pd.isna(r["avg_rating"]) else round(float(r["avg_rating"]), 2),
            "rating_count": int(r["rating_count"]),
            "tmdbId": None if pd.isna(r["tmdbId"]) else int(r["tmdbId"]),
        }
        if similarity is not None:
            card["similarity"] = round(similarity, 3)
            card["score"] = round(score, 3)
        return card


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def _main() -> None:
    parser = argparse.ArgumentParser(description="Movie recommender")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build and save the model")
    b.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    b.add_argument("--out", default=DEFAULT_MODEL_PATH)

    r = sub.add_parser("recommend", help="get recommendations for a title")
    r.add_argument("title")
    r.add_argument("-n", type=int, default=10)
    r.add_argument("--model", default=DEFAULT_MODEL_PATH)

    args = parser.parse_args()
    if args.cmd == "build":
        path = build_model(args.data_dir, args.out)
        print(f"Saved model to {path} ({path.stat().st_size / 1e6:.1f} MB)")
        return

    out = MovieRecommender(args.model).recommend(args.title, top_n=args.n)
    if out["matched"] is None:
        print(f"No match for '{args.title}'. Did you mean:")
        for s in out["suggestions"]:
            print(f"  - {s['title']} ({s['year']})")
        return
    m = out["matched"]
    print(f"Because you liked: {m['title']} ({m['year']})  [{', '.join(m['genres'])}]\n")
    for i, x in enumerate(out["results"], 1):
        print(f"{i:>2}. {x['title']} ({x['year']})  "
              f"sim={x['similarity']:.2f}  rating={x['avg_rating']}  n={x['rating_count']}")


if __name__ == "__main__":
    _main()
