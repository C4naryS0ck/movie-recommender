"""how it works: the method, explained for humans (and recruiters)."""
from __future__ import annotations

import streamlit as st

import ui

ui.ambient(None)
ui.page_title(
    "how it works · no, it's not rule-based",
    "it reads the <em>plot</em>,<br>not the genre tag",
    "most apps recommend by labels: you watched a \"romance\", here's every romance ever. "
    "this one uses machine learning to understand what a story is actually <i>about</i>.",
)
st.space("small")

st.html("""
<div class="steps">
  <div class="step"><div class="n">01</div><h3>it reads the plot</h3>
    <p>every title's synopsis, tagline, genres and themes go through a <b>sentence-transformer</b>
    (a small deep-learning language model). it turns each story into a 384-number "meaning vector".
    stories about similar things land close together, even with zero words in common.</p>
    <p><code>"trapped in deadly children's games" ≈ "forced to play games to survive"</code></p></div>
  <div class="step"><div class="n">02</div><h3>it matches the themes</h3>
    <p>TMDB tags like <i>time travel</i>, <i>revenge</i> or <i>chaebol</i> are compared with
    <b>TF-IDF</b>, which boosts rare, specific tags and ignores generic ones like "drama".</p></div>
  <div class="step"><div class="n">03</div><h3>it checks it's actually good</h3>
    <p>the 300 closest stories get re-ranked with a <b>Bayesian rating</b>, so a 9.5★ show with
    4 votes can't beat an 8.6★ show with 4,000. you can tweak this balance with "tweak it".</p></div>
  <div class="step"><div class="n">04</div><h3>it shows its receipts</h3>
    <p>every recommendation shows the themes it shares with your pick, and the "basically twins / same energy"
    bar shows how close it is compared with your top match. pick several shows and it averages them into one
    <b>taste vector</b>.</p></div>
</div>
""")

st.html('<div class="section">ok but is it <em>rule-based?</em></div>')
st.markdown(
    "Nope. A **rule-based** system would be hand-written logic like *\"if genre = romance, "
    "recommend other romances\"*. This is **content-based filtering** with **machine learning**: "
    "a neural language model learned what text means from millions of sentences, and the app "
    "compares stories in that learned space. Nobody wrote a rule saying *Goblin* is like "
    "*Hotel del Luna*; the model figured out they're both about curses, the afterlife and "
    "doomed romance.\n\n"
    "It's also **not collaborative filtering** (\"people who watched X also watched Y\"), so "
    "it doesn't need your watch history, an account or a profile of you. A brand-new show with "
    "zero viewers can still be recommended on day one."
)

st.html('<div class="section">what we <em>store</em></div>')
st.markdown(
    "- **No accounts, no emails, no IP addresses** from visitors.\n"
    "- Which titles get picked, searches that find nothing, and **the text you type in describe the "
    "vibe**, with the time but no name attached. Please don't type anything personal there. It shows me "
    "what to improve.\n"
    "- Whatever you write in **rate us**. Reviews stay private unless the admin features them."
)

with st.expander("tech stack (for the nerds)", icon=":material/code:"):
    st.markdown(
        "- **Data:** ~11.7k movies & series from the TMDB API, with extra Korean, Japanese, "
        "Chinese, Indian and Thai titles\n"
        "- **Model:** `sentence-transformers/all-MiniLM-L6-v2` embeddings + scikit-learn TF-IDF\n"
        "- **Ranking:** cosine similarity hybrid, Bayesian weighted rating (IMDb formula)\n"
        "- **Search:** typo-tolerant fuzzy matching (RapidFuzz) + TMDB alternative titles\n"
        "- **App:** Streamlit, custom CSS, Supabase (PostgreSQL) for feedback"
    )

ui.footer()
