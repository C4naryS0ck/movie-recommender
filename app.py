"""
app.py - Entry point: shared styles + page navigation.

    streamlit run app.py         # plain
    streamlit run serve.py       # same app + SEO (meta tags, robots.txt, sitemap.xml)

Pages live in app_pages/. The admin page is hidden from the menu unless you're
signed in as an admin (see core.py), but it's always reachable at /admin.
"""
from __future__ import annotations

import streamlit as st

import ui
from core import is_admin
from recommender import DEFAULT_INDEX

st.set_page_config(page_title="similar stories · find shows like the one you loved",
                   page_icon=":material/movie:", layout="wide")

if not DEFAULT_INDEX.exists():
    st.error("Run `python fetch_tmdb.py` then `python recommender.py build` first.",
             title="No index found")
    st.stop()

ui.inject_css()

page = st.navigation(
    [
        st.Page("app_pages/discover.py", title="discover", icon=":material/explore:", default=True,
                help="find movies and series with the same vibe as the ones you loved"),
        st.Page("app_pages/how_it_works.py", title="how it works", icon=":material/psychology:",
                help="the machine-learning method behind the recommendations, explained simply"),
        st.Page("app_pages/feedback.py", title="rate us", icon=":material/reviews:",
                help="leave a rating and feedback, no account needed"),
        st.Page("app_pages/admin.py", title="admin", icon=":material/admin_panel_settings:",
                url_path="admin", visibility="visible" if is_admin() else "hidden",
                help="feedback moderation and usage insights, for the site owner only"),
    ],
    position="top",
)
page.run()
