"""
core.py - Shared state for every page: the cached recommender and the role check.

Roles
-----
visitor  everyone, no account. Can discover, read "how it works", leave feedback.
admin    signs in with Google (st.login). Only emails listed in secrets count:

    # .streamlit/secrets.toml
    [admin]
    emails = ["you@gmail.com"]

Signing in with any other Google account gives no extra access.
"""
from __future__ import annotations

import streamlit as st

from recommender import DEFAULT_INDEX, Recommender


@st.cache_resource(show_spinner="loading 11k stories…")
def get_rec() -> Recommender:
    return Recommender(DEFAULT_INDEX)


def _secrets() -> dict:
    try:
        return dict(st.secrets)
    except Exception:  # no secrets.toml at all
        return {}


def auth_configured() -> bool:
    return "auth" in _secrets()


def admin_emails() -> set[str]:
    admin = _secrets().get("admin", {})
    return {str(e).strip().lower() for e in admin.get("emails", [])}


def is_admin() -> bool:
    if not auth_configured() or not st.user.is_logged_in:
        return False
    return str(st.user.get("email", "")).lower() in admin_emails()
