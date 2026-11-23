"""discover: the recommender itself ("more like this" + "describe the vibe")."""
from __future__ import annotations

import streamlit as st

import feedback_store as fb
import ui
from core import get_rec
from recommender import LANGUAGES

STARTERS = ["Crash Landing on You", "Goblin", "Squid Game", "Parasite",
            "Business Proposal", "Alice in Borderland", "Oldboy (2003)", "Your Name."]
EXAMPLES = [
    "enemies to lovers but one of them is a ghost",
    "rich kids, dark secrets, and literally everyone is lying",
    "a time travel romance that will emotionally destroy me",
    "strangers forced into deadly games for money",
]

rec = get_rec()
meta = rec.meta
ss = st.session_state

if "liked" not in ss:  # first run of a session: restore picks from a shared link (?like=tv:67915)
    ss.liked = [u for u in st.query_params.get("like", "").split(",") if u in rec._uid_to_idx][:5]
ss.setdefault("mode", "more like this")  # set here (not via default=) so callbacks can switch it
ss.setdefault("logged", set())


def title_of(uid: str) -> str:
    return rec.meta.at[rec._uid_to_idx[uid], "title"]


# ---- callbacks ------------------------------------------------------------------------
def add_liked(widget_key: str) -> None:
    uid = ss.get(widget_key)
    if uid and uid not in ss.liked:
        ss.liked = (ss.liked + [uid])[-5:]
        fb.log_event("pick", title_of(uid))
    ss.q = ""


def set_seed(uid: str) -> None:
    ss.liked = [uid]
    ss.q = ""
    ss.mode = "more like this"
    fb.log_event("pick", title_of(uid))


def remove_liked(uid: str) -> None:
    ss.liked = [u for u in ss.liked if u != uid]


def use_example() -> None:
    if ss.get("example"):
        ss.desc = ss.example
    ss.example = None


def log_once(kind: str, value: str) -> None:
    if (kind, value) not in ss.logged:
        ss.logged.add((kind, value))
        fb.log_event(kind, value)


# keep the URL in sync so recommendations can be shared as a link
if ss.liked:
    st.query_params["like"] = ",".join(ss.liked)
else:
    st.query_params.pop("like", None)

seed_cards = [rec._card(rec._uid_to_idx[u]) for u in ss.liked if u in rec._uid_to_idx]
ui.ambient(seed_cards[0]["poster_url"] if seed_cards else None)

# ---- hero -------------------------------------------------------------------------------
st.html(f"""
<div class="hero">
  <div class="eyebrow">similar stories · {len(meta):,} films &amp; series · no account needed</div>
  <h1>finished a show and now<br>you feel <em>empty inside?</em></h1>
  <p>same. tell us what you loved and we'll find its <b>twin</b>. this thing actually reads the plot,
     so you get stories with the same <i>vibe</i>, not just the same genre tag. k-dramas, anime,
     c-dramas, films, all of it.</p>
  <div class="sticker">no algorithm brainrot</div>
  <div class="sticker two">reads plots, not tags</div>
</div>
""")
ui.ticker()

# ---- controls -------------------------------------------------------------------------------
langs_present = meta["original_language"].value_counts()
lang_options = [c for c in ["ko", "ja", "zh", "en", "hi", "th", "es", "fr", "cn", "tr"]
                if langs_present.get(c, 0) >= 20]
y_min, y_max = int(meta["year"].min()), int(meta["year"].max())

with st.container(key="controls", gap="small"):
    mode = st.segmented_control(
        "Mode", ["more like this", "describe the vibe"], key="mode", required=True,
        label_visibility="collapsed",
        format_func=lambda m: (":material/all_inclusive: " if m == "more like this" else ":material/edit_note: ") + m,
    )
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        kind = st.segmented_control(
            "Type", ["everything", "series", "films"], key="kind", required=True, default="everything",
            label_visibility="collapsed", bind="query-params",
        )
        languages = st.pills(
            "Language", lang_options, selection_mode="multi", key="lang", bind="query-params",
            format_func=lambda c: LANGUAGES.get(c, c).split(" (")[0].lower() if c != "cn" else "cantonese",
            label_visibility="collapsed", wrap=True,  # wrap: otherwise it widens the page on phones
        )
        with st.popover("tweak it", icon=":material/tune:", key="fine"):
            years = st.slider("release year", y_min, y_max, (1980, y_max), key="years")
            top_n = st.slider("how many recs", 6, 30, 12, step=3, key="top_n")
            semantic_weight = st.slider(
                "plot meaning vs. tag overlap", 0.0, 1.0, 0.75, 0.05, key="sw",
                help="1.0 = only the plot embeddings, 0.0 = only TMDB genres and keywords")
            alpha = st.slider("closest match vs. highest rated", 0.0, 0.6, 0.10, 0.05, key="alpha",
                              help="crank it up if you only want certified bangers")

filters = dict(top_n=top_n, media_type={"series": "tv", "films": "movie"}.get(kind),
               languages=languages or None, years=years)

# ---- mode: more like this ------------------------------------------------------------------------
if mode == "more like this":
    q = st.text_input(
        "Search a title you loved", key="q", type="search", live="300ms",
        placeholder="type a show you're obsessed with… goblin? squid game? parasite?",
        icon=":material/search:", label_visibility="collapsed",
    )
    if q and q.strip():
        hits = [h for h in rec.search(q, 8) if h["uid"] not in ss.liked]
        if hits:
            key = "sugg_" + "_".join(q.lower().split())  # new key per query: no stale pick
            st.pills(
                "Matches", [h["uid"] for h in hits], key=key, label_visibility="collapsed",
                format_func=lambda u: (rec.label(rec._uid_to_idx[u])
                                       .replace(" · Movie · ", " · film · ").replace(" · TV · ", " · series · ")),
                on_change=add_liked, args=(key,),
            )
        else:
            if len(q.strip()) >= 3:
                log_once("search_miss", q.strip().lower())  # tells the admin what's missing
            st.caption("we don't have that one (yet). try describing the vibe instead?")

    if seed_cards:
        with st.container(key="spotlight"):
            if len(seed_cards) == 1:
                c = seed_cards[0]
                img = f'<img src="{c["poster_url"]}" alt="{ui.esc(c["title"])} poster">' if c["poster_url"] else ""
                tags = "".join(f"<span>{ui.esc(k)}</span>" for k in c["keywords"][:10])
                aka = f' · aka {ui.esc(c["aka"])}' if c.get("aka") else ""
                st.html(f"""
                <div class="spot">{img}<div>
                  <div class="lbl">currently obsessed with</div>
                  <h2>{ui.esc(c['title'])}</h2>
                  <div class="meta">{c['year'] or ''} · {ui.kind_word(c)} · {c['language_name']} · ★ {c['rating']}{aka}</div>
                  <p>{ui.esc(c['overview'])}</p>
                  <div class="tags">{tags}</div>
                </div></div>""")
            else:
                imgs = "".join(f'<img src="{c["poster_url"]}" alt="{ui.esc(c["title"])}">'
                               for c in seed_cards if c["poster_url"])
                st.html(f"""<div class="spot"><div>
                  <div class="lbl">taste blend</div>
                  <h2>{len(seed_cards)} shows, one vibe</h2>
                  <div class="blend">{imgs}</div></div></div>""")
            with st.container(horizontal=True, gap="xsmall"):
                for c in seed_cards:
                    st.button(c["title"], key=f"rm_{c['uid'].replace(':', '_')}", icon=":material/close:",
                              icon_position="right", on_click=remove_liked, args=(c["uid"],),
                              help="kick it out of your picks")
            st.caption("add more shows from the search to blend your taste (up to 5).")

        out = rec.recommend(ss.liked, semantic_weight=semantic_weight, alpha=alpha, **filters)
        st.html('<div class="section">your next <em>3am binge</em></div>')
        ui.show_grid(out["results"], "rec", set_seed)
    else:
        starters = [rec._card(i) for i in (rec.resolve(t) for t in STARTERS) if i is not None]
        for c in starters:
            c["match"], c["starter"] = 1.0, True
        st.html('<div class="section">no thoughts? start with a <em>comfort show</em></div>')
        ui.show_grid(starters, "start", set_seed)

# ---- mode: describe the vibe ------------------------------------------------------------------------
else:
    with st.container(key="describe_panel", gap="small"):
        text = st.text_area(
            "describe the vibe. be specific. be unhinged. we can take it.", key="desc", height=110,
            max_chars=500,
            placeholder="a heiress paraglides into north korea and falls for the soldier who hides her…",
        )
        st.pills("try one", EXAMPLES, key="example", on_change=use_example, label_visibility="collapsed")
        st.button("find my next obsession", key="find", icon=":material/auto_awesome:")
    if text and text.strip():
        log_once("describe", text.strip())
        with st.spinner("reading your vibe…"):
            out = rec.describe(text, alpha=alpha * 0.5, **filters)
        st.html('<div class="section">stories that <em>get it</em></div>')
        ui.show_grid(out["results"], "desc", set_seed)

ui.footer()
