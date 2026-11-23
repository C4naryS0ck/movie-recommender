"""
ui.py - Shared look & feel: global CSS, ambient backdrop, poster cards.

Design: "late-night cinema" with a Gen Z voice. Warm ink background lit by a
blurred copy of the poster you picked, frosted-glass panels, capsule controls,
lowercase editorial headings and a scrolling vibe ticker.
"""
from __future__ import annotations

import html
from typing import Callable
from urllib.parse import quote

import streamlit as st

TIERS = [(0.6, "basically twins"), (0.5, "same energy"), (0.0, "lowkey related")]
VIBES = ["enemies to lovers", "found family", "time loop", "chaebol drama", "slow burn",
         "revenge era", "contract marriage", "ghosts but make it romantic", "survival games",
         "second lead syndrome", "morally grey", "makjang chaos", "healing drama", "plot twist"]

# Film grain. Percent-encoded on purpose: Streamlit's HTML sanitizer drops any
# <style> block whose text contains "<tag", which would silently kill all CSS.
GRAIN = "data:image/svg+xml," + quote(
    "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' "
    "stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(#n)' "
    "opacity='.55'/></svg>")

CSS = """
<style>
  :root {
    --ink: #0e0c0b; --cream: #f4ede4; --muted: rgba(244,237,228,.62);
    --amber: #f2a93b; --coral: #ff7a59; --mint: #8fe3c8;
    --glass: rgba(255,246,236,.055); --glass-hi: rgba(255,246,236,.09);
    --edge: rgba(255,238,215,.12);
    --serif: 'Instrument Serif', Georgia, serif;
    --mono: 'IBM Plex Mono', ui-monospace, monospace;
    --ease: cubic-bezier(.2,.8,.2,1);
  }
  html, body { background: var(--ink); }
  .stApp, [data-testid="stHeader"] { background: transparent; }

  /* ---- ambient backdrop ---- */
  .ambient {
    position: fixed; inset: -12%; z-index: -2; pointer-events: none;
    background:
      radial-gradient(60% 50% at 15% 10%, rgba(242,169,59,.22), transparent 70%),
      radial-gradient(50% 45% at 90% 20%, rgba(255,122,89,.16), transparent 70%),
      radial-gradient(60% 60% at 60% 100%, rgba(64,140,130,.14), transparent 70%);
    background-size: cover; background-position: center;
    filter: blur(70px) saturate(1.25); opacity: .55;
  }
  .ambient.poster { opacity: .5; filter: blur(80px) saturate(1.4) brightness(.42); }
  .vignette { position: fixed; inset: 0; z-index: -1; pointer-events: none;
              background: radial-gradient(120% 90% at 50% 30%, transparent 35%, rgba(14,12,11,.85) 100%); }
  .grain { position: fixed; inset: 0; z-index: -1; pointer-events: none;
           background-image: url("GRAIN_URL"); mix-blend-mode: overlay; opacity: .18; }

  /* ---- type ---- */
  .eyebrow { font-family: var(--mono); font-size: .72rem; letter-spacing: .2em; text-transform: lowercase;
             color: var(--amber); display: flex; gap: .7rem; align-items: center; flex-wrap: wrap; }
  .eyebrow::before { content: ""; width: 28px; height: 1px; background: var(--amber); }
  .hero { position: relative; }
  .hero h1, .page-title h1 { font-family: var(--serif); font-weight: 400; letter-spacing: -.02em;
             line-height: .95; color: var(--cream); margin: .5rem 0 .7rem; text-transform: lowercase; }
  .hero h1 { font-size: clamp(2.5rem, 6.2vw, 5.4rem); }
  .page-title h1 { font-size: clamp(2.2rem, 5vw, 4rem); }
  .hero h1 em, .page-title h1 em { color: var(--amber); }
  .hero p, .page-title p { color: var(--muted); max-width: 42rem; font-size: 1.04rem; margin: 0; line-height: 1.55; }
  .hero p b { color: var(--cream); font-weight: 600; }
  .sticker { position: absolute; top: 2.6rem; right: 0; transform: rotate(6deg);
             padding: .55rem 1rem; border-radius: 999px; font-family: var(--mono); font-size: .72rem;
             background: var(--mint); color: #0d1f19; font-weight: 500; letter-spacing: .03em;
             box-shadow: 0 10px 30px -10px rgba(143,227,200,.5); animation: bob 4s ease-in-out infinite; }
  .sticker.two { top: 6.4rem; right: 3.5rem; transform: rotate(-5deg); background: var(--amber);
                 color: #1a1006; animation-delay: -2s; }
  @keyframes bob { 0%,100% { translate: 0 0; } 50% { translate: 0 -6px; } }
  .section { font-family: var(--serif); font-size: 2rem; margin: .4rem 0 0; color: var(--cream);
             text-transform: lowercase; }
  .section em { color: var(--amber); }
  .foot { font-family: var(--mono); font-size: .68rem; color: var(--muted); letter-spacing: .03em;
          margin-top: 2.5rem; line-height: 1.7; }

  /* ---- vibe ticker ---- */
  .ticker { overflow: hidden; white-space: nowrap; border-block: 1px solid var(--edge); padding: .55rem 0;
            mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent); }
  .ticker div { display: inline-block; animation: scroll 40s linear infinite; }
  .ticker span { font-family: var(--serif); font-style: italic; font-size: 1.35rem; color: var(--cream);
                 opacity: .85; margin-right: 1.6rem; }
  .ticker span::after { content: "✦"; font-style: normal; font-size: .8rem; color: var(--amber);
                        margin-left: 1.6rem; vertical-align: middle; }
  @keyframes scroll { to { transform: translateX(-50%); } }
  @media (prefers-reduced-motion: reduce) { .ticker div, .sticker { animation: none; } }

  /* ---- glass panels (keyed Streamlit containers) ---- */
  .st-key-controls, .st-key-spotlight, .st-key-describe_panel, .st-key-fb_panel,
  [class*="st-key-glass_"] {
    background: linear-gradient(160deg, var(--glass-hi), var(--glass));
    backdrop-filter: blur(22px) saturate(150%); -webkit-backdrop-filter: blur(22px) saturate(150%);
    border: 1px solid var(--edge); border-radius: 28px; padding: 1.1rem 1.3rem 1.2rem;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.07), 0 30px 60px -30px rgba(0,0,0,.7);
  }

  /* ---- capsule inputs & buttons ---- */
  .st-key-q div[data-baseweb="input"] {
    border-radius: 999px; background: rgba(14,12,11,.55); border-color: var(--edge);
    transition: border-color .3s, box-shadow .3s;
  }
  .st-key-q div[data-baseweb="input"]:focus-within { border-color: var(--amber);
    box-shadow: 0 0 0 4px rgba(242,169,59,.15); }
  .st-key-q input { font-size: 1.05rem; padding: .85rem 1rem; }
  .st-key-desc textarea, .st-key-fb_msg textarea { border-radius: 22px; background: rgba(14,12,11,.55);
    font-size: 1.02rem; }
  .st-key-fb_name div[data-baseweb="input"] { border-radius: 999px; background: rgba(14,12,11,.55); }

  [class*="st-key-more_"] button, [class*="st-key-rm_"] button, [class*="st-key-adm_"] button,
  .st-key-fine button, .st-key-find button, .st-key-fb_submit button, .st-key-login button,
  .st-key-logout button {
    border-radius: 999px; border: 1px solid var(--edge); background: rgba(255,246,236,.05);
    color: var(--cream); transition: transform .25s var(--ease), background .25s, border-color .25s, color .25s;
  }
  [class*="st-key-more_"] button:hover, [class*="st-key-rm_"] button:hover, [class*="st-key-adm_"] button:hover,
  .st-key-fine button:hover, .st-key-logout button:hover {
    background: rgba(242,169,59,.14); border-color: rgba(242,169,59,.55); color: var(--amber);
    transform: translateY(-1px);
  }
  [class*="st-key-more_"] button { font-size: .82rem; min-height: 2.1rem; }
  [class*="st-key-rm_"] button { background: rgba(242,169,59,.12); border-color: rgba(242,169,59,.4); }
  .st-key-find button, .st-key-fb_submit button, .st-key-login button {
    background: linear-gradient(120deg, var(--amber), var(--coral)); color: #1a1006; border: none;
    font-weight: 600; padding: .55rem 1.4rem; box-shadow: 0 10px 30px -10px rgba(242,169,59,.6);
  }
  .st-key-find button:hover, .st-key-fb_submit button:hover, .st-key-login button:hover {
    transform: translateY(-2px) scale(1.02); color: #1a1006; box-shadow: 0 16px 36px -10px rgba(255,122,89,.7);
  }

  /* ---- spotlight ---- */
  .spot { display: flex; gap: 1.4rem; align-items: flex-start; }
  .spot img { width: 128px; border-radius: 16px; box-shadow: 0 20px 40px -15px rgba(0,0,0,.8);
              transform: rotate(-2deg); transition: transform .5s var(--ease); }
  .spot img:hover { transform: rotate(0) scale(1.04); }
  .spot .lbl { font-family: var(--mono); font-size: .68rem; letter-spacing: .18em; color: var(--amber); }
  .spot h2 { font-family: var(--serif); font-weight: 400; font-size: 2.3rem; line-height: 1;
             margin: .35rem 0 .3rem; color: var(--cream); }
  .spot .meta { font-family: var(--mono); font-size: .72rem; color: var(--muted); letter-spacing: .05em;
                text-transform: uppercase; }
  .spot p { color: rgba(244,237,228,.82); margin: .7rem 0; max-width: 52rem; line-height: 1.5; }
  .blend { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
  .blend img { width: 64px; border-radius: 10px; transform: none; }
  .tags span, .chips span {
    display: inline-block; margin: 0 .3rem .3rem 0; padding: .18rem .65rem; border-radius: 999px;
    font-size: .72rem; border: 1px solid var(--edge); background: rgba(255,246,236,.05); color: var(--cream);
  }

  /* ---- poster cards ---- */
  .card { position: relative; display: block; aspect-ratio: 2/3; border-radius: 22px; overflow: hidden;
          isolation: isolate; text-decoration: none !important; color: var(--cream) !important;
          background: #1c1815; box-shadow: 0 14px 34px -14px rgba(0,0,0,.8);
          transition: transform .5s var(--ease), box-shadow .5s var(--ease); }
  .card img, .card .noposter { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
                               transition: transform .8s var(--ease), filter .6s var(--ease); }
  .card .noposter { background: linear-gradient(160deg, #2a231e, #15110f); }
  .card::after { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
                 box-shadow: inset 0 0 0 1px rgba(255,238,215,.10); transition: box-shadow .5s; }
  .card:hover { transform: translateY(-8px) rotate(-.6deg);
                box-shadow: 0 34px 60px -22px rgba(0,0,0,.9), 0 0 40px -12px rgba(242,169,59,.35); }
  .card:hover::after { box-shadow: inset 0 0 0 1px rgba(242,169,59,.55); }
  .card:hover img { transform: scale(1.08); filter: brightness(.45) saturate(1.1); }
  .rank { position: absolute; top: .4rem; left: .8rem; font-family: var(--serif); font-style: italic;
          font-size: 3.4rem; line-height: 1; color: transparent;
          -webkit-text-stroke: 1px rgba(255,244,230,.75); text-shadow: 0 4px 20px rgba(0,0,0,.5); }
  .badge { position: absolute; top: .8rem; right: .8rem; padding: .22rem .6rem; border-radius: 999px;
           font-family: var(--mono); font-size: .62rem; letter-spacing: .08em; text-transform: uppercase;
           background: rgba(14,12,11,.45); backdrop-filter: blur(10px); border: 1px solid var(--edge); }
  .plate { position: absolute; left: .55rem; right: .55rem; bottom: .55rem; padding: .75rem .85rem .7rem;
           border-radius: 16px; background: rgba(18,14,12,.58);
           backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
           border: 1px solid rgba(255,238,215,.13); }
  .plate h4 { font-family: var(--serif); font-weight: 400; font-size: 1.32rem; line-height: 1.05;
              margin: 0; color: var(--cream); }
  .plate .aka { font-size: .72rem; color: var(--amber); margin-top: .15rem; font-style: italic; }
  .plate .meta { font-family: var(--mono); font-size: .62rem; letter-spacing: .05em; text-transform: uppercase;
                 color: var(--muted); margin-top: .3rem; }
  .reveal { max-height: 0; opacity: 0; overflow: hidden;
            transition: max-height .6s var(--ease), opacity .4s, margin .5s var(--ease); }
  .card:hover .reveal { max-height: 15rem; opacity: 1; margin-top: .55rem; }
  .reveal p { font-size: .78rem; line-height: 1.42; margin: 0 0 .5rem; color: rgba(244,237,228,.9);
              display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
  .chips span { font-size: .64rem; padding: .1rem .5rem; }
  .echo { display: flex; align-items: center; gap: .55rem; margin-top: .55rem; }
  .echo i { flex: 1; height: 3px; border-radius: 3px; background: rgba(255,255,255,.12); position: relative;
            overflow: hidden; }
  .echo i::after { content: ""; position: absolute; inset: 0 auto 0 0; width: var(--w); border-radius: 3px;
                   background: linear-gradient(90deg, var(--amber), var(--coral)); }
  .echo b { font-family: var(--mono); font-weight: 500; font-size: .6rem; letter-spacing: .06em;
            color: var(--amber); white-space: nowrap; }

  /* ---- how-it-works steps & review quotes ---- */
  .steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
  .step, .quote { background: linear-gradient(160deg, var(--glass-hi), var(--glass));
                  backdrop-filter: blur(18px); border: 1px solid var(--edge); border-radius: 24px;
                  padding: 1.2rem 1.3rem; transition: transform .4s var(--ease), border-color .4s; }
  .step:hover, .quote:hover { transform: translateY(-4px) rotate(-.4deg); border-color: rgba(242,169,59,.45); }
  .step .n { font-family: var(--serif); font-style: italic; font-size: 3rem; line-height: 1;
             color: transparent; -webkit-text-stroke: 1px var(--amber); }
  .step h3 { font-family: var(--serif); font-weight: 400; font-size: 1.6rem; margin: .4rem 0 .3rem;
             color: var(--cream); text-transform: lowercase; }
  .step p, .quote p { color: rgba(244,237,228,.8); font-size: .92rem; line-height: 1.5; margin: 0; }
  .step code { font-family: var(--mono); font-size: .72rem; color: var(--amber); background: transparent; }
  .quote .stars { color: var(--amber); letter-spacing: .15em; font-size: .9rem; }
  .quote p { font-family: var(--serif); font-size: 1.25rem; line-height: 1.3; color: var(--cream); margin: .4rem 0; }
  .quote .who { font-family: var(--mono); font-size: .66rem; color: var(--muted); }

  @media (max-width: 640px) {
    .spot { flex-direction: column; gap: .9rem; }
    .spot img { width: 96px; }
    .spot h2 { font-size: 1.9rem; }
    .sticker { position: static; display: inline-block; margin: .3rem .4rem 0 0; }
  }
  @media (hover: none) { .reveal { max-height: none; opacity: 1; margin-top: .5rem; }
                         .reveal p { display: none; } }
</style>
""".replace("GRAIN_URL", GRAIN)


def inject_css() -> None:
    st.html(CSS)  # its own call: st.html drops <style> when mixed with other markup


def ambient(poster_url: str | None) -> None:
    """Blurred poster light behind the page (or warm glows when nothing is picked)."""
    if poster_url:
        big = poster_url.replace("/w342/", "/w780/")
        st.html(f"<style>.ambient.poster {{ background-image: url('{big}'); }}</style>")
    st.html(f'<div class="ambient {"poster" if poster_url else ""}"></div>'
            '<div class="vignette"></div><div class="grain"></div>')


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def kind_word(card: dict) -> str:
    return "series" if card["media_type"] == "tv" else "film"


def ticker() -> None:
    items = "".join(f"<span>{esc(v)}</span>" for v in VIBES)
    st.html(f'<div class="ticker"><div>{items}{items}</div></div>')  # doubled for a seamless loop


def page_title(eyebrow: str, title_html: str, sub_html: str = "") -> None:
    st.html(f'<div class="page-title"><div class="eyebrow">{eyebrow}</div><h1>{title_html}</h1>'
            f'{f"<p>{sub_html}</p>" if sub_html else ""}</div>')


def footer() -> None:
    st.html('<div class="foot">made during way too many 3am k-drama binges ✦ '
            "data &amp; posters from TMDB. this product uses the TMDB API but is not endorsed or "
            "certified by TMDB.</div>")


def card_html(card: dict, rank: int, top_match: float) -> str:
    shared = card.get("shared_keywords") or card.get("shared_genres") or card["genres"][:3]
    strength = card["match"] / top_match if top_match > 0 else 0
    tier = next(label for cut, label in TIERS if card["match"] >= cut)
    poster = (f'<img src="{card["poster_url"]}" alt="{esc(card["title"])} poster" loading="lazy">'
              if card["poster_url"] else '<div class="noposter"></div>')
    aka = f'<div class="aka">aka {esc(card["aka"])}</div>' if card.get("aka") else ""
    chips = "".join(f"<span>{esc(s)}</span>" for s in shared[:4])
    echo = ("" if card.get("starter") else
            f'<div class="echo"><i style="--w:{strength * 100:.0f}%"></i><b>{tier}</b></div>')
    return f"""
    <a class="card" href="{card['tmdb_url']}" target="_blank" rel="noopener">
      {poster}
      <div class="rank">{rank:02d}</div>
      <div class="badge">{kind_word(card)} · {esc(card['language'].upper())}</div>
      <div class="plate">
        <h4>{esc(card['title'])}</h4>
        {aka}
        <div class="meta">{card['year'] or '—'} · ★ {card['rating']} · {card['language_name']}</div>
        <div class="reveal">
          <p>{esc(card['overview'])}</p>
          <div class="chips">{chips}</div>
        </div>
        {echo}
      </div>
    </a>"""


def show_grid(results: list[dict], prefix: str, on_more: Callable[[str], None]) -> None:
    if not results:
        st.caption("nothing here bestie. try loosening the language or year filters.")
        return
    top = max(r["match"] for r in results)
    with st.grid("auto", min_column_width=200, gap="medium"):
        for rank, r in enumerate(results, 1):
            uid = r["uid"].replace(":", "_")
            with st.container(key=f"cell_{prefix}_{uid}", gap="xsmall"):
                st.html(card_html(r, rank, top))
                st.button("more like this", key=f"more_{prefix}_{uid}", icon=":material/all_inclusive:",
                          width="stretch", on_click=on_more, args=(r["uid"],))
