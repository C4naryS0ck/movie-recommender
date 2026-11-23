# 🎬 Similar Stories: a concept-based movie & K-drama recommender

> Finished a drama you loved and want *more of that feeling*? Most platforms recommend by genre
> ("Romance", "Drama"), so a story about a heiress stranded in North Korea gets matched with any
> generic rom-com. This project recommends by **what the story is actually about**.

It covers movies **and TV shows** from TMDB, with dedicated coverage of Korean, Japanese, Chinese,
Indian, Thai and other non-Hollywood titles.

<!-- Add a screenshot or GIF of the app here: ![demo](assets/demo.gif) -->

## Features

- **More like this:** pick one or more titles you loved. The app averages them into a "taste
  vector" and finds the closest stories.
- **Describe a story:** type a concept in plain English ("a cold CEO falls for a time traveler
  from Joseon") and get matching titles. This is semantic search, so no keywords need to match.
- **Explainable results:** each recommendation shows the themes it shares with your pick
  (e.g. `survival game`, `class inequality`).
- **Filters:** movie / TV, original language, year range, and a slider that trades similarity
  against ratings.
- **Typo-tolerant, alias-aware search:** "crash landng" finds *Crash Landing on You*, and "Goblin" finds *Guardian: The Lonely and Great God* (via TMDB alternative titles).
- **Shareable links:** picks and filters live in the URL (`/?like=tv:67915`).
- **Feedback without accounts:** visitors rate the site and leave notes; only reviews the admin
  features appear publicly ("wall of love").
- **Role-based access:** visitors never sign in. The owner signs in with Google to reach `/admin`
  (feedback moderation, CSV export, most-picked titles, searches that found nothing).
- **SEO-ready:** `serve.py` gives crawlers and link previews real titles, descriptions, Open Graph
  tags, structured data, per-title "shows like X" pages, `robots.txt` and `sitemap.xml`.

## App structure

| File | Role |
|---|---|
| `app.py` | Entry point: theme CSS + top navigation |
| `app_pages/discover.py` | The recommender UI |
| `app_pages/how_it_works.py` | The method, explained for visitors |
| `app_pages/feedback.py` | "rate us" form + featured reviews |
| `app_pages/admin.py` | Owner-only dashboard (hidden from the menu for visitors) |
| `core.py` / `ui.py` | Cached recommender + role check / shared styles and poster cards |
| `feedback_store.py` | SQLite storage for feedback and anonymous usage events |
| `serve.py` | Production entry point: wraps `app.py` with SEO tags, robots.txt, sitemap.xml |

## How it works

```
TMDB API ──► fetch_tmdb.py ──► titles.jsonl ──► recommender.py build ──► tmdb_index.joblib ──► app.py
             (movies + TV,       (overview,        │                                          (Streamlit)
              K-dramas etc.)      keywords, ...)   ├─ Sentence-Transformer embeddings (384-d)
                                                   ├─ TF-IDF over genres + keywords
                                                   └─ Bayesian quality score
```

For a liked title *q* and every candidate *c*:

```
similarity = 0.75 · cos(embed(q), embed(c))  +  0.25 · cos(tfidf_tags(q), tfidf_tags(c))
score      = (1 − α) · similarity  +  α · quality(c),  α = 0.1  # applied to the top 300 candidates
```

| Component | Why |
|---|---|
| **Sentence embeddings** (`all-MiniLM-L6-v2`) over overview, tagline, genres and keywords | Captures *meaning*: "trapped in a deadly children's game" ≈ "forced to compete in games to survive", with zero shared words. The title is left out on purpose so names don't drive matches. |
| **TF-IDF on TMDB keywords + genres** | Precise thematic overlap (`time travel`, `revenge`, `chaebol`). IDF down-weights generic tags. |
| **Bayesian weighted rating**, computed separately for movies and TV | A 9.5★ title with 4 votes shouldn't beat an 8.6★ title with 4,000. TV gets far fewer votes on TMDB, so each type has its own prior. |
| **Re-rank only the top-300 similar candidates** | Ratings break ties between similar stories without letting popular but unrelated hits sneak in. |

## Project evolution

| Phase | File | Approach | Limitation |
|---|---|---|---|
| 1 | [`phase-1.ipynb`](phase-1.ipynb), [`phase1_movielens.py`](phase1_movielens.py) | MovieLens 9.7k movies, TF-IDF on genres + user tags, cosine similarity, popularity hybrid | No TV / K-dramas, no plot text, so *Oldboy* → *Citizen Kane* ("Drama, Mystery") |
| 2 | [`fetch_tmdb.py`](fetch_tmdb.py), [`recommender.py`](recommender.py) | TMDB movies + TV, sentence-transformer embeddings + keyword TF-IDF hybrid, semantic search | Single-page prototype |
| 3 | [`app.py`](app.py), [`app_pages/`](app_pages), [`serve.py`](serve.py) | Multi-page app: feedback, Google-sign-in admin dashboard, usage insights, SEO | See *Future work* |

## Run it locally

```bash
python -m venv .venv && .venv\Scripts\activate        # Windows (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt

# 1. Free TMDB API key: https://www.themoviedb.org/settings/api
copy .env.example .env                                  # then paste your key into .env

# 2. Download ~11.7k titles (≈15 min, resumable). Use --scale 0.2 for a quick test.
python fetch_tmdb.py

# 3. Build the embedding index (≈2 min on CPU)
python recommender.py build

# 4. Try it
python recommender.py recommend "Crash Landing on You" --type tv
python recommender.py describe "a grim reaper and an immortal goblin share a house"
streamlit run app.py            # or: streamlit run serve.py  (same app + SEO extras)
```

## Admin access

Visitors never need an account. Only the owner signs in, using Google (Streamlit's `st.login`, a
real OpenID Connect sign-in, not a shared password):

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials) create an
   **OAuth client ID** (type *Web application*). Add the redirect URI
   `http://localhost:8501/oauth2callback` (and `https://<your-app>/oauth2callback` once deployed).
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (git-ignored) and fill in
   the client ID/secret, a random `cookie_secret`, and your email under `[admin] emails`.
3. Open `/admin` and sign in. Any other Google account gets "no admin access".

**Storage note:** feedback is saved in SQLite (`data/feedback.db`). Streamlit Community Cloud
wipes the disk on restart, so before relying on it in production, move `feedback_store.py` to a
hosted database (e.g. Supabase). It's the only file that would change.

## Future work

- **Offline evaluation:** compare TF-IDF vs. embeddings vs. hybrid using TMDB's own
  "recommendations" lists as a weak ground truth (Hit-Rate@10, nDCG@10).
- **Collaborative filtering:** add user–item signals (e.g. MovieLens ratings or a two-tower
  model) alongside the content signal.
- **Better encoders:** try `bge-base` / `e5` embeddings or fine-tune on title pairs that
  TMDB lists as recommendations of each other.
- **Fast nearest-neighbour search:** FAISS index for 100k+ titles.

## Credits

Data and images from [TMDB](https://www.themoviedb.org). This product uses the TMDB API but is
not endorsed or certified by TMDB.
