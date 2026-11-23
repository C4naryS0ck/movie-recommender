"""rate us: anyone can leave feedback, no account. Only featured reviews are public."""
from __future__ import annotations

import time
from datetime import datetime

import streamlit as st

import feedback_store as fb
import ui

TAGS = ["recs were spot on", "found my show", "the ui is a whole mood", "describe mode slaps",
        "recs were off", "couldn't find my show", "too slow", "confusing"]
COOLDOWN_S = 60
MAX_PER_SESSION = 3

ss = st.session_state
ss.setdefault("fb_sent", [])

ui.ambient(None)
ui.page_title(
    "rate us · takes 20 seconds",
    "be honest,<br>we can <em>take it</em>",
    "loved it? hated it? recs were mid? tell me. i read every single one and use it to make this "
    "better. no account needed.",
)
st.space("small")

recent = [t for t in ss.fb_sent if time.time() - t < COOLDOWN_S]
if len(ss.fb_sent) >= MAX_PER_SESSION:
    st.success("you've already sent a few, ty! that's plenty for now.", icon=":material/favorite:",
               title="feedback received")
elif recent:
    st.success("got it, thank you! give it a minute before sending another.", icon=":material/favorite:",
               title="feedback received")
else:
    with st.container(key="fb_panel"):
        with st.form("fb_form", border=False, clear_on_submit=True):
            st.markdown("**how was it?**")
            rating = st.feedback("stars", key="fb_rating")
            tags = st.pills("what stood out", TAGS, selection_mode="multi", key="fb_tags")
            message = st.text_area("anything else? (what to fix, what show we're missing, anything)",
                                   key="fb_msg", max_chars=fb.MAX_MESSAGE, height=110,
                                   placeholder="the recs for goblin were scary accurate but…")
            name = st.text_input("name or @ (optional)", key="fb_name", max_chars=40,
                                 placeholder="shown if your review gets featured")
            sent = st.form_submit_button("send it", key="fb_submit", icon=":material/send:")
        if sent:
            if rating is None:  # st.feedback returns 0-4; None means no stars picked
                st.warning("tap the stars first so we know how it went.", icon=":material/star:")
            else:
                fb.add_feedback(rating + 1, tags or [], message, name)
                ss.fb_sent.append(time.time())
                st.toast("ty bestie, received ✦", icon=":material/favorite:")
                st.rerun()

featured = fb.featured_feedback()
if featured:
    st.html('<div class="section">the <em>wall of love</em></div>')
    quotes = "".join(
        f'<div class="quote"><div class="stars">{"★" * r["rating"]}{"☆" * (5 - r["rating"])}</div>'
        f'<p>“{ui.esc(r["message"])}”</p>'
        f'<div class="who">{ui.esc(r["name"] or "anonymous")} · '
        f'{datetime.fromtimestamp(r["created_at"]):%b %Y}</div></div>'
        for r in featured
    )
    st.html(f'<div class="steps">{quotes}</div>')

ui.footer()
