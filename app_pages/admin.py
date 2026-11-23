"""admin: feedback moderation + anonymous usage insights. Google sign-in, allow-listed emails only."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import feedback_store as fb
import ui
from core import auth_configured, is_admin

ui.ambient(None)
ui.page_title("admin · you're backstage", "the <em>control room</em>")
st.space("small")

# ---- gate -----------------------------------------------------------------------------
if not auth_configured():
    st.info("Admin sign-in isn't configured on this server yet. See the README's "
            "**Admin access** section.", icon=":material/lock:", title="Admin login is off")
    st.stop()

if not st.user.is_logged_in:
    st.caption("this area is for the site owner. visitors don't need an account for anything.")
    st.button("sign in with google", key="login", icon=":material/login:", on_click=st.login)
    st.stop()

if not is_admin():
    st.warning(f"You're signed in as {st.user.get('email', 'unknown')}, which isn't an admin account.",
               icon=":material/block:", title="No admin access")
    st.button("sign out", key="logout", icon=":material/logout:", on_click=st.logout)
    st.stop()

# ---- admin only below ----------------------------------------------------------------------
with st.container(horizontal=True, vertical_alignment="center"):
    st.caption(f"signed in as **{st.user.get('email')}** · storage: **{fb.backend()}**")
    st.button("sign out", key="logout", icon=":material/logout:", on_click=st.logout)

reviews = fb.all_feedback(include_archived=True)
events = fb.event_counts()
active = [r for r in reviews if r["status"] != "archived"]
avg = sum(r["rating"] for r in active) / len(active) if active else 0

with st.container(horizontal=True):
    st.metric("reviews", len(active), border=True)
    st.metric("avg rating", f"{avg:.1f} ★" if active else "—", border=True)
    st.metric("unread", sum(r["status"] == "new" for r in reviews), border=True)
    st.metric("titles picked", events.get("pick", 0), border=True)
    st.metric("vibe searches", events.get("describe", 0), border=True)

tab = st.segmented_control("View", ["reviews", "insights"], default="reviews", required=True,
                           key="adm_view", label_visibility="collapsed")

if tab == "reviews":
    show = st.pills("Status", list(fb.STATUSES), default=["new", "read", "featured"],
                    selection_mode="multi", key="adm_status", label_visibility="collapsed")
    rows = [r for r in reviews if r["status"] in (show or [])]
    if reviews:
        csv = pd.DataFrame(reviews).assign(
            created_at=lambda d: pd.to_datetime(d["created_at"], unit="s"),
            tags=lambda d: d["tags"].map(", ".join),
        ).to_csv(index=False)
        st.download_button("export csv", csv, "feedback.csv", "text/csv", key="adm_csv",
                           icon=":material/download:")
    if not rows:
        st.caption("no reviews here yet.")
    for r in rows:
        with st.container(border=True, key=f"adm_card_{r['id']}"):
            stars = "★" * r["rating"] + "☆" * (5 - r["rating"])
            st.markdown(f"**{stars}** · {r['name'] or 'anonymous'} · "
                        f"{datetime.fromtimestamp(r['created_at']):%d %b %Y, %H:%M} · "
                        f":{'orange' if r['status'] == 'new' else 'violet' if r['status'] == 'featured' else 'gray'}"
                        f"-badge[{r['status']}]")
            if r["tags"]:
                st.caption(" · ".join(r["tags"]))
            if r["message"]:
                st.write(r["message"])
            with st.container(horizontal=True, gap="xsmall"):
                if r["status"] == "new":
                    st.button("mark read", key=f"adm_read_{r['id']}", icon=":material/done:",
                              on_click=fb.set_status, args=(r["id"], "read"))
                if r["status"] != "featured" and r["message"]:
                    st.button("feature", key=f"adm_feat_{r['id']}", icon=":material/star:",
                              help="show it publicly on the wall of love",
                              on_click=fb.set_status, args=(r["id"], "featured"))
                if r["status"] == "featured":
                    st.button("unfeature", key=f"adm_unfeat_{r['id']}", icon=":material/star_half:",
                              on_click=fb.set_status, args=(r["id"], "read"))
                if r["status"] != "archived":
                    st.button("archive", key=f"adm_arch_{r['id']}", icon=":material/archive:",
                              on_click=fb.set_status, args=(r["id"], "archived"))
                st.button("delete", key=f"adm_del_{r['id']}", icon=":material/delete:",
                          on_click=fb.delete_feedback, args=(r["id"],))

else:
    left, right = st.columns(2)
    with left:
        st.subheader("most picked titles")
        picks = fb.top_events("pick", 10)
        if picks:
            st.bar_chart(pd.DataFrame(picks, columns=["title", "picks"]), x="title", y="picks",
                         horizontal=True, sort="-picks", height=320)
        else:
            st.caption("no picks yet.")
    with right:
        st.subheader("searches with no match")
        st.caption("titles people want that aren't in the dataset: add these next.")
        misses = fb.top_events("search_miss", 15)
        if misses:
            st.dataframe(pd.DataFrame(misses, columns=["search", "times"]), hide_index=True,
                         height=320)
        else:
            st.caption("no misses yet.")
    st.subheader("recent vibe searches")
    vibes = fb.top_events("describe", 15)
    if vibes:
        st.dataframe(pd.DataFrame(vibes, columns=["description", "times"]), hide_index=True)
    else:
        st.caption("nobody has described a vibe yet.")
