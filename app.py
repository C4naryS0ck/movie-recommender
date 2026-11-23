"""
app.py - Streamlit UI for the concept-based recommender.

    streamlit run app.py
"""
from __future__ import annotations

import html

import streamlit as st

from recommender import DEFAULT_INDEX, LANGUAGES, Recommender

st.set_page_config(page_title="Similar Stories", page_icon="🎬", layout="wide")


@st.cache_resource(show_spinner="Loading index…")
def load() -> Recommender:
    return Recommender(DEFAULT_INDEX)


if not DEFAULT_INDEX.exists():
    st.error("No index found. Run `python fetch_tmdb.py` then `python recommender.py build` first.")
    st.stop()

rec = load()
meta = rec.meta

st.markdown(
    """
    <style>
      .card-title {font-weight: 600; font-size: 1rem; margin: .35rem 0 .1rem; line-height: 1.25}
      .card-sub   {color: #888; font-size: .8rem}
      .chip {display: inline-block; padding: 1px 8px; margin: 2px 3px 0 0; border-radius: 999px;
             font-size: .72rem; background: rgba(127,127,127,.15)}
      .match {font-size: .8rem; font-weight: 600; color: #e05a47}
      .noposter {aspect-ratio: 2/3; display: flex; align-items: center; justify-content: center;
                 background: rgba(127,127,127,.12); border-radius: 8px; font-size: 2rem}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎬 Similar Stories")
st.caption("Loved a drama or movie? Find others with the same *concept*, not just the same genre. "
           f"{len(meta):,} movies & TV shows from TMDB, matched by meaning using sentence embeddings.")

# ---- sidebar filters --------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    kind = st.radio("Show", ["Movies & TV", "TV shows only", "Movies only"], index=0)
    media_type = {"TV shows only": "tv", "Movies only": "movie"}.get(kind)

    langs_present = meta["original_language"].value_counts()
    lang_options = [l for l in langs_present.index if langs_present[l] >= 10]
    languages = st.multiselect(
        "Original language", lang_options,
        format_func=lambda c: f"{LANGUAGES.get(c, c)} ({langs_present[c]})",
        placeholder="Any language",
    )
    y_min, y_max = int(meta["year"].min()), int(meta["year"].max())
    years = st.slider("Year", y_min, y_max, (max(y_min, 1970), y_max))
    top_n = st.slider("Number of results", 6, 30, 12, step=3)
    with st.expander("Ranking"):
        semantic_weight = st.slider("Story meaning vs. tag overlap", 0.0, 1.0, 0.75, 0.05,
                                    help="1.0 = only plot embeddings, 0.0 = only TMDB genres/keywords")
        alpha = st.slider("Similarity vs. ratings", 0.0, 0.6, 0.10, 0.05,
                          help="Higher values favour well-rated titles over closer matches")

filters = dict(top_n=top_n, media_type=media_type, languages=languages or None, years=years)


# ---- result grid --------------------------------------------------------------------
def show(results: list[dict], cols: int = 6) -> None:
    if not results:
        st.info("No titles match these filters. Try widening the language or year range.")
        return
    for row_start in range(0, len(results), cols):
        for col, r in zip(st.columns(cols), results[row_start:row_start + cols]):
            with col:
                if r["poster_url"]:
                    st.image(r["poster_url"], width="stretch")
                else:
                    st.markdown('<div class="noposter">🎞️</div>', unsafe_allow_html=True)
                kind = "TV" if r["media_type"] == "tv" else "Movie"
                st.markdown(
                    f'<div class="card-title"><a href="{r["tmdb_url"]}" target="_blank" '
                    f'style="color:inherit;text-decoration:none">{html.escape(r["title"])}</a></div>'
                    f'<div class="card-sub">{r["year"] or ""} · {kind} · {r["language_name"]} · ★ {r["rating"]}</div>'
                    f'<div class="match">{r["match"] * 100:.0f}% match</div>',
                    unsafe_allow_html=True,
                )
                shared = r.get("shared_keywords") or r.get("shared_genres") or []
                if shared:
                    st.markdown("".join(f'<span class="chip">{html.escape(s)}</span>' for s in shared[:4]),
                                unsafe_allow_html=True)
                with st.expander("Plot"):
                    st.write(r["overview"])


tab_similar, tab_describe = st.tabs(["🔁  More like this", "✍️  Describe a story"])

with tab_similar:
    order = meta["vote_count"].sort_values(ascending=False).index
    picked = st.multiselect(
        "Titles you loved (pick one or more; the more you add, the better it learns your taste)",
        options=list(order),
        format_func=rec.label,
        max_selections=5,
        placeholder="Start typing, e.g. Crash Landing on You, Goblin, Parasite…",
    )
    if picked:
        out = rec.recommend([rec.uids[i] for i in picked], semantic_weight=semantic_weight,
                            alpha=alpha, **filters)
        if len(picked) == 1:
            m = out["matched"][0]
            with st.container(border=True):
                c1, c2 = st.columns([1, 6])
                if m["poster_url"]:
                    c1.image(m["poster_url"], width="stretch")
                c2.markdown(f"**{m['title']}** ({m['year']}) · {', '.join(m['genres'])}")
                c2.write(m["overview"])
                if m["keywords"]:
                    c2.markdown("".join(f'<span class="chip">{html.escape(k)}</span>'
                                        for k in m["keywords"][:12]), unsafe_allow_html=True)
        st.subheader("You might also love")
        show(out["results"])

with tab_describe:
    text = st.text_area(
        "Describe the concept you're in the mood for",
        placeholder="e.g. A heiress paraglides into North Korea and falls for an army officer who hides her",
        height=90,
    )
    if st.button("Find stories", type="primary") and text.strip():
        with st.spinner("Understanding your description…"):
            out = rec.describe(text, alpha=alpha * 0.5, **filters)
        show(out["results"])

st.divider()
st.caption("Data and posters from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.")
