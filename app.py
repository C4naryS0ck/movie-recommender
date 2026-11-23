"""
app.py - Streamlit UI for the concept-based recommender.

    streamlit run app.py

Design: a "late-night cinema". Warm ink background lit by a heavily blurred
copy of the poster you picked, frosted-glass panels, capsule controls, and
poster cards that open on hover to show the plot and the themes they share.
"""
from __future__ import annotations

import html
from urllib.parse import quote

import streamlit as st

from recommender import DEFAULT_INDEX, LANGUAGES, Recommender

st.set_page_config(page_title="Similar Stories", page_icon=":material/movie:", layout="wide")

STARTERS = [  # shown before the user picks anything
    "Crash Landing on You", "Goblin", "Squid Game", "Parasite",
    "Business Proposal", "Alice in Borderland", "Oldboy (2003)", "Your Name.",
]
EXAMPLES = [
    "A cold CEO falls for a time traveler from the Joseon era",
    "Strangers trapped in deadly children's games for money",
    "A grim reaper and a ghost run a hotel for the dead",
    "A detective who can talk to the past through a radio",
]


# ---- data -------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading 11k stories…")
def load() -> Recommender:
    return Recommender(DEFAULT_INDEX)


if not DEFAULT_INDEX.exists():
    st.error("Run `python fetch_tmdb.py` then `python recommender.py build` first.",
             title="No index found")
    st.stop()

rec = load()
meta = rec.meta
ss = st.session_state
if "liked" not in ss:  # first run of a session: restore picks from a shared link (?like=tv:67915)
    ss.liked = [u for u in st.query_params.get("like", "").split(",") if u in rec._uid_to_idx][:5]
ss.setdefault("mode", "More like this")  # set here (not via default=) so callbacks can switch it


# ---- callbacks ----------------------------------------------------------------------
def add_liked(widget_key: str) -> None:
    uid = ss.get(widget_key)
    if uid and uid not in ss.liked:
        ss.liked = (ss.liked + [uid])[-5:]
    ss.q = ""


def set_seed(uid: str) -> None:
    ss.liked = [uid]
    ss.q = ""
    ss.mode = "More like this"


def remove_liked(uid: str) -> None:
    ss.liked = [u for u in ss.liked if u != uid]


def use_example() -> None:
    if ss.get("example"):
        ss.desc = ss.example
    ss.example = None


# ---- small HTML builders ------------------------------------------------------------
def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def kind_code(card: dict) -> str:
    return "Series" if card["media_type"] == "tv" else "Film"


def big_poster(url: str | None) -> str | None:
    return url.replace("/w342/", "/w780/") if url else None


def card_html(card: dict, rank: int, top_match: float) -> str:
    shared = card.get("shared_keywords") or card.get("shared_genres") or card["genres"][:3]
    strength = card["match"] / top_match if top_match > 0 else 0
    tier = "Strong match" if card["match"] >= 0.6 else "Close match" if card["match"] >= 0.5 else "Related"
    poster = (f'<img src="{card["poster_url"]}" alt="{esc(card["title"])} poster" loading="lazy">'
              if card["poster_url"] else '<div class="noposter"></div>')
    aka = f'<div class="aka">aka {esc(card["aka"])}</div>' if card.get("aka") else ""
    chips = "".join(f"<span>{esc(s)}</span>" for s in shared[:4])
    return f"""
    <a class="card" href="{card['tmdb_url']}" target="_blank" rel="noopener">
      {poster}
      <div class="rank">{rank:02d}</div>
      <div class="badge">{kind_code(card)} · {esc(card['language'].upper())}</div>
      <div class="plate">
        <h4>{esc(card['title'])}</h4>
        {aka}
        <div class="meta">{card['year'] or '—'} · ★ {card['rating']} · {card['language_name']}</div>
        <div class="reveal">
          <p>{esc(card['overview'])}</p>
          <div class="chips">{chips}</div>
        </div>
        {"" if card.get("starter") else f'<div class="echo"><i style="--w:{strength * 100:.0f}%"></i><b>{tier}</b></div>'}
      </div>
    </a>"""


def show_grid(results: list[dict], prefix: str) -> None:
    if not results:
        st.caption("Nothing matches these filters. Try widening the language or year range.")
        return
    top = max(r["match"] for r in results)
    with st.grid("auto", min_column_width=200, gap="medium"):
        for rank, r in enumerate(results, 1):
            with st.container(key=f"cell_{prefix}_{r['uid'].replace(':', '_')}", gap="xsmall"):
                st.html(card_html(r, rank, top))
                st.button("More like this", key=f"more_{prefix}_{r['uid'].replace(':', '_')}",
                          icon=":material/all_inclusive:", width="stretch",
                          on_click=set_seed, args=(r["uid"],))


# keep the URL in sync with the picks so recommendations can be shared as a link
if ss.liked:
    st.query_params["like"] = ",".join(ss.liked)
else:
    st.query_params.pop("like", None)

# ---- styles ---------------------------------------------------------------------------
seed_cards = [rec._card(rec._uid_to_idx[u]) for u in ss.liked if u in rec._uid_to_idx]
ambient = big_poster(seed_cards[0]["poster_url"]) if seed_cards else None
ambient_css = f"background-image:url('{ambient}');" if ambient else ""

# Film-grain texture. Percent-encoded: the HTML sanitizer drops any <style> block
# whose text contains "<tag", so raw inline SVG would silently kill the stylesheet.
GRAIN = "data:image/svg+xml," + quote(
    "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' "
    "stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(#n)' "
    "opacity='.55'/></svg>")

st.html(f"""
<style>
  :root {{
    --ink: #0e0c0b; --cream: #f4ede4; --muted: rgba(244,237,228,.62);
    --amber: #f2a93b; --coral: #ff7a59;
    --glass: rgba(255,246,236,.055); --glass-hi: rgba(255,246,236,.09);
    --edge: rgba(255,238,215,.12);
    --serif: 'Instrument Serif', Georgia, serif;
    --mono: 'IBM Plex Mono', ui-monospace, monospace;
    --ease: cubic-bezier(.2,.8,.2,1);
  }}
  html, body {{ background: var(--ink); }}
  .stApp, [data-testid="stHeader"] {{ background: transparent; }}

  /* ambient light: the picked poster, blurred huge behind everything + film grain */
  .ambient {{
    position: fixed; inset: -12%; z-index: -2; pointer-events: none;
    background:
      radial-gradient(60% 50% at 15% 10%, rgba(242,169,59,.22), transparent 70%),
      radial-gradient(50% 45% at 90% 20%, rgba(255,122,89,.16), transparent 70%),
      radial-gradient(60% 60% at 60% 100%, rgba(64,140,130,.14), transparent 70%);
    background-size: cover; background-position: center;
    filter: blur(70px) saturate(1.25); opacity: .55;
    transition: background-image .8s var(--ease);
  }}
  .ambient.poster {{ {ambient_css} opacity: .5; filter: blur(80px) saturate(1.4) brightness(.42); }}
  .vignette {{ position: fixed; inset: 0; z-index: -1; pointer-events: none;
              background: radial-gradient(120% 90% at 50% 30%, transparent 35%, rgba(14,12,11,.85) 100%); }}
  .grain {{
    position: fixed; inset: 0; z-index: -1; pointer-events: none;
    background-image: url("{GRAIN}"); mix-blend-mode: overlay; opacity: .18;
  }}

  /* hero */
  .eyebrow {{ font-family: var(--mono); font-size: .72rem; letter-spacing: .22em;
             text-transform: uppercase; color: var(--amber); display: flex; gap: .7rem; align-items: center; }}
  .eyebrow::before {{ content: ""; width: 28px; height: 1px; background: var(--amber); }}
  .hero h1 {{ font-family: var(--serif); font-weight: 400; font-size: clamp(2.6rem, 6vw, 5.2rem);
              line-height: .95; letter-spacing: -.02em; margin: .5rem 0 .6rem; color: var(--cream); }}
  .hero h1 em {{ color: var(--amber); }}
  .hero p {{ color: var(--muted); max-width: 40rem; font-size: 1.02rem; margin: 0; }}

  /* glass panels (keyed Streamlit containers) */
  .st-key-controls, .st-key-spotlight, .st-key-describe_panel {{
    background: linear-gradient(160deg, var(--glass-hi), var(--glass));
    backdrop-filter: blur(22px) saturate(150%); -webkit-backdrop-filter: blur(22px) saturate(150%);
    border: 1px solid var(--edge); border-radius: 28px; padding: 1.1rem 1.3rem 1.2rem;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.07), 0 30px 60px -30px rgba(0,0,0,.7);
  }}

  /* capsule everything inside the app's own controls */
  .st-key-q div[data-baseweb="input"] {{
    border-radius: 999px; background: rgba(14,12,11,.55); border-color: var(--edge);
    transition: border-color .3s, box-shadow .3s;
  }}
  .st-key-q div[data-baseweb="input"]:focus-within {{
    border-color: var(--amber); box-shadow: 0 0 0 4px rgba(242,169,59,.15);
  }}
  .st-key-q input {{ font-size: 1.05rem; padding: .85rem 1rem; }}
  .st-key-desc textarea {{ border-radius: 22px; background: rgba(14,12,11,.55); font-size: 1.05rem; }}

  [class*="st-key-more_"] button, [class*="st-key-rm_"] button, .st-key-find button,
  .st-key-fine button {{
    border-radius: 999px; border: 1px solid var(--edge);
    background: rgba(255,246,236,.05); color: var(--cream);
    transition: transform .25s var(--ease), background .25s, border-color .25s, color .25s;
  }}
  [class*="st-key-more_"] button:hover, [class*="st-key-rm_"] button:hover, .st-key-fine button:hover {{
    background: rgba(242,169,59,.14); border-color: rgba(242,169,59,.55); color: var(--amber);
    transform: translateY(-1px);
  }}
  [class*="st-key-more_"] button {{ font-size: .82rem; min-height: 2.1rem; }}
  .st-key-find button {{
    background: linear-gradient(120deg, var(--amber), var(--coral)); color: #1a1006;
    border: none; font-weight: 600; padding: .55rem 1.4rem;
    box-shadow: 0 10px 30px -10px rgba(242,169,59,.6);
  }}
  .st-key-find button:hover {{ transform: translateY(-2px) scale(1.02); color: #1a1006;
                               box-shadow: 0 16px 36px -10px rgba(255,122,89,.7); }}
  [class*="st-key-rm_"] button {{ background: rgba(242,169,59,.12); border-color: rgba(242,169,59,.4); }}

  /* spotlight (what you picked) */
  .spot {{ display: flex; gap: 1.4rem; align-items: flex-start; }}
  .spot img {{ width: 128px; border-radius: 16px; box-shadow: 0 20px 40px -15px rgba(0,0,0,.8);
              transform: rotate(-2deg); transition: transform .5s var(--ease); }}
  .spot img:hover {{ transform: rotate(0) scale(1.04); }}
  .spot .lbl {{ font-family: var(--mono); font-size: .68rem; letter-spacing: .2em; text-transform: uppercase;
               color: var(--amber); }}
  .spot h2 {{ font-family: var(--serif); font-weight: 400; font-size: 2.3rem; line-height: 1;
             margin: .35rem 0 .3rem; color: var(--cream); }}
  .spot .meta {{ font-family: var(--mono); font-size: .72rem; color: var(--muted); letter-spacing: .05em;
                text-transform: uppercase; }}
  .spot p {{ color: rgba(244,237,228,.82); margin: .7rem 0; max-width: 52rem; line-height: 1.5; }}
  .blend {{ display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }}
  .blend img {{ width: 64px; border-radius: 10px; transform: none; }}
  .tags span, .chips span {{
    display: inline-block; margin: 0 .3rem .3rem 0; padding: .18rem .65rem; border-radius: 999px;
    font-size: .72rem; border: 1px solid var(--edge); background: rgba(255,246,236,.05); color: var(--cream);
  }}

  /* poster cards */
  .card {{
    position: relative; display: block; aspect-ratio: 2/3; border-radius: 22px; overflow: hidden;
    isolation: isolate; text-decoration: none !important; color: var(--cream) !important;
    background: #1c1815; box-shadow: 0 14px 34px -14px rgba(0,0,0,.8);
    transition: transform .5s var(--ease), box-shadow .5s var(--ease);
  }}
  .card img, .card .noposter {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
                               transition: transform .8s var(--ease), filter .6s var(--ease); }}
  .card .noposter {{ background: linear-gradient(160deg, #2a231e, #15110f); }}
  .card::after {{ content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
                 box-shadow: inset 0 0 0 1px rgba(255,238,215,.10); transition: box-shadow .5s; }}
  .card:hover {{ transform: translateY(-8px) rotate(-.6deg);
                box-shadow: 0 34px 60px -22px rgba(0,0,0,.9), 0 0 40px -12px rgba(242,169,59,.35); }}
  .card:hover::after {{ box-shadow: inset 0 0 0 1px rgba(242,169,59,.55); }}
  .card:hover img {{ transform: scale(1.08); filter: brightness(.45) saturate(1.1); }}
  .rank {{ position: absolute; top: .4rem; left: .8rem; font-family: var(--serif); font-style: italic;
          font-size: 3.4rem; line-height: 1; color: transparent;
          -webkit-text-stroke: 1px rgba(255,244,230,.75); text-shadow: 0 4px 20px rgba(0,0,0,.5); }}
  .badge {{ position: absolute; top: .8rem; right: .8rem; padding: .22rem .6rem; border-radius: 999px;
           font-family: var(--mono); font-size: .62rem; letter-spacing: .08em; text-transform: uppercase;
           background: rgba(14,12,11,.45); backdrop-filter: blur(10px); border: 1px solid var(--edge); }}
  .plate {{ position: absolute; left: .55rem; right: .55rem; bottom: .55rem; padding: .75rem .85rem .7rem;
           border-radius: 16px; background: rgba(18,14,12,.58);
           backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
           border: 1px solid rgba(255,238,215,.13); }}
  .plate h4 {{ font-family: var(--serif); font-weight: 400; font-size: 1.32rem; line-height: 1.05;
              margin: 0; color: var(--cream); }}
  .plate .aka {{ font-size: .72rem; color: var(--amber); margin-top: .15rem; font-style: italic; }}
  .plate .meta {{ font-family: var(--mono); font-size: .62rem; letter-spacing: .05em; text-transform: uppercase;
                 color: var(--muted); margin-top: .3rem; }}
  .reveal {{ max-height: 0; opacity: 0; overflow: hidden;
            transition: max-height .6s var(--ease), opacity .4s, margin .5s var(--ease); }}
  .card:hover .reveal {{ max-height: 15rem; opacity: 1; margin-top: .55rem; }}
  .reveal p {{ font-size: .78rem; line-height: 1.42; margin: 0 0 .5rem; color: rgba(244,237,228,.9);
              display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }}
  .chips span {{ font-size: .64rem; padding: .1rem .5rem; }}
  .echo {{ display: flex; align-items: center; gap: .55rem; margin-top: .55rem; }}
  .echo i {{ flex: 1; height: 3px; border-radius: 3px; background: rgba(255,255,255,.12); position: relative;
            overflow: hidden; }}
  .echo i::after {{ content: ""; position: absolute; inset: 0 auto 0 0; width: var(--w); border-radius: 3px;
                   background: linear-gradient(90deg, var(--amber), var(--coral)); }}
  .echo b {{ font-family: var(--mono); font-weight: 500; font-size: .6rem; letter-spacing: .08em;
            text-transform: uppercase; color: var(--amber); white-space: nowrap; }}
  @media (max-width: 640px) {{
    .spot {{ flex-direction: column; gap: .9rem; }}
    .spot img {{ width: 96px; }}
    .spot h2 {{ font-size: 1.9rem; }}
    .eyebrow {{ flex-wrap: wrap; letter-spacing: .16em; }}
  }}
  @media (hover: none) {{ .reveal {{ max-height: none; opacity: 1; margin-top: .5rem; }}
                          .reveal p {{ display: none; }} }}

  .section {{ font-family: var(--serif); font-size: 2rem; margin: .4rem 0 0; color: var(--cream); }}
  .section em {{ color: var(--amber); }}
  .foot {{ font-family: var(--mono); font-size: .68rem; color: var(--muted); letter-spacing: .04em;
          margin-top: 2.5rem; }}
</style>
""")
# Separate call: st.html drops <style> when it shares a call with other markup.
st.html(f'<div class="ambient {"poster" if ambient else ""}"></div>'
        '<div class="vignette"></div><div class="grain"></div>')

# ---- hero -------------------------------------------------------------------------------
st.html(f"""
<div class="hero">
  <div class="eyebrow">Similar Stories · {len(meta):,} films &amp; series</div>
  <h1>Loved a story?<br><em>Find its echoes.</em></h1>
  <p>Recommendations by what a story is <i>about</i>, not just its genre. Plots are read by a
     sentence-embedding model, so a heiress stranded in North Korea finds other forbidden,
     border-crossing romances, not just any rom-com.</p>
</div>
""")

# ---- controls -------------------------------------------------------------------------------
langs_present = meta["original_language"].value_counts()
lang_options = [c for c in ["ko", "ja", "zh", "en", "hi", "th", "es", "fr", "cn", "tr"]
                if langs_present.get(c, 0) >= 20]
y_min, y_max = int(meta["year"].min()), int(meta["year"].max())

with st.container(key="controls", gap="small"):
    mode = st.segmented_control(
        "Mode", ["More like this", "Describe a story"], key="mode", required=True,
        label_visibility="collapsed",
        format_func=lambda m: (":material/all_inclusive: " if m == "More like this" else ":material/edit_note: ") + m,
    )
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        kind = st.segmented_control(
            "Type", ["All", "Series", "Films"], key="kind", required=True, default="All",
            label_visibility="collapsed", bind="query-params",
        )
        languages = st.pills(
            "Language", lang_options, selection_mode="multi", key="lang", bind="query-params",
            format_func=lambda c: LANGUAGES.get(c, c).split(" (")[0] if c != "cn" else "Cantonese",
            label_visibility="collapsed", wrap=True,  # wrap: otherwise it widens the page on phones
        )
        with st.popover("Fine-tune", icon=":material/tune:", key="fine"):
            years = st.slider("Release year", y_min, y_max, (1980, y_max), key="years")
            top_n = st.slider("Results", 6, 30, 12, step=3, key="top_n")
            semantic_weight = st.slider(
                "Story meaning vs. tag overlap", 0.0, 1.0, 0.75, 0.05, key="sw",
                help="1.0 = only plot embeddings, 0.0 = only TMDB genres and keywords")
            alpha = st.slider("Closeness vs. ratings", 0.0, 0.6, 0.10, 0.05, key="alpha",
                              help="Higher values favour well-rated titles over closer matches")

filters = dict(top_n=top_n, media_type={"Series": "tv", "Films": "movie"}.get(kind),
               languages=languages or None, years=years)

# ---- mode: more like this ------------------------------------------------------------------------
if mode == "More like this":
    q = st.text_input(
        "Search a title you loved", key="q", type="search", live="300ms",
        placeholder="Search a title you loved: Goblin, Parasite, Squid Game…",
        icon=":material/search:", label_visibility="collapsed",
    )
    if q and q.strip():
        hits = [h for h in rec.search(q, 8) if h["uid"] not in ss.liked]
        if hits:
            key = "sugg_" + "_".join(q.lower().split())  # new key per query: no stale pick
            st.pills(
                "Matches", [h["uid"] for h in hits], key=key, label_visibility="collapsed",
                format_func=lambda u: (rec.label(rec._uid_to_idx[u])
                                       .replace(" · Movie · ", " · Film · ").replace(" · TV · ", " · Series · ")),
                on_change=add_liked, args=(key,),
            )
        else:
            st.caption("No title found. Try another spelling, or describe the story instead.")

    if seed_cards:
        with st.container(key="spotlight"):
            if len(seed_cards) == 1:
                c = seed_cards[0]
                img = f'<img src="{c["poster_url"]}" alt="{esc(c["title"])} poster">' if c["poster_url"] else ""
                tags = "".join(f"<span>{esc(k)}</span>" for k in c["keywords"][:10])
                aka = f' · aka {esc(c["aka"])}' if c.get("aka") else ""
                st.html(f"""
                <div class="spot">{img}<div>
                  <div class="lbl">Because you loved</div>
                  <h2>{esc(c['title'])}</h2>
                  <div class="meta">{c['year'] or ''} · {kind_code(c)} · {c['language_name']} · ★ {c['rating']}{aka}</div>
                  <p>{esc(c['overview'])}</p>
                  <div class="tags">{tags}</div>
                </div></div>""")
            else:
                imgs = "".join(f'<img src="{c["poster_url"]}" alt="{esc(c["title"])}">'
                               for c in seed_cards if c["poster_url"])
                st.html(f"""<div class="spot"><div>
                  <div class="lbl">Blending your taste</div>
                  <h2>{len(seed_cards)} stories, one mood</h2>
                  <div class="blend">{imgs}</div></div></div>""")
            with st.container(horizontal=True, gap="xsmall"):
                for c in seed_cards:
                    st.button(c["title"], key=f"rm_{c['uid'].replace(':', '_')}", icon=":material/close:",
                              icon_position="right", on_click=remove_liked, args=(c["uid"],),
                              help="Remove from your picks")

        out = rec.recommend(ss.liked, semantic_weight=semantic_weight, alpha=alpha, **filters)
        st.html('<div class="section">You might <em>also</em> love</div>')
        show_grid(out["results"], "rec")
    else:
        starters = [rec._card(i) for i in (rec.resolve(t) for t in STARTERS) if i is not None]
        for c in starters:
            c["match"], c["starter"] = 1.0, True
        st.html('<div class="section">Or start from a <em>favourite</em></div>')
        show_grid(starters, "start")

# ---- mode: describe a story ------------------------------------------------------------------------
else:
    with st.container(key="describe_panel", gap="small"):
        text = st.text_area(
            "Describe the story you're in the mood for", key="desc", height=110,
            placeholder="A heiress paraglides into North Korea and falls for the officer who hides her…",
        )
        st.pills("Try one", EXAMPLES, key="example", on_change=use_example, label_visibility="collapsed")
        st.button("Find stories", key="find", icon=":material/auto_awesome:")
    if text and text.strip():
        with st.spinner("Reading your story…"):
            out = rec.describe(text, alpha=alpha * 0.5, **filters)
        st.html('<div class="section">Stories that <em>echo</em> yours</div>')
        show_grid(out["results"], "desc")

st.html('<div class="foot">Data &amp; posters from TMDB. This product uses the TMDB API but is not '
        "endorsed or certified by TMDB.</div>")
