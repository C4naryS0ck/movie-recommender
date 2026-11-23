"""
serve.py - Runs app.py with search-engine extras. Use this as the entry point when deployed:

    streamlit run serve.py

Why: a Streamlit page is an empty HTML shell titled "Streamlit" that fills itself in
with JavaScript, so search engines and link previews (WhatsApp, Discord, LinkedIn)
see almost nothing. This wrapper rewrites that HTML on the way out:

- real <title>, meta description, canonical URL, Open Graph + Twitter card tags
- per-title pages: /?like=tv:67915 gets "shows like Goblin…" as its title
- JSON-LD structured data (WebApplication)
- crawlable fallback content inside #root (React replaces it once the app loads)
- /robots.txt, /sitemap.xml (top titles as "shows like X" pages) and /og.png

Set SITE_URL to the public address (env var; on Streamlit Community Cloud put
SITE_URL = "https://..." at the top level of the app's secrets, which are also
exposed as environment variables).
"""
from __future__ import annotations

import html
import json
import os
from functools import lru_cache
from pathlib import Path

import joblib
import streamlit as st
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Route

from recommender import DEFAULT_INDEX, best_aka

ROOT = Path(__file__).resolve().parent
SITE_NAME = "similar stories"
TAGLINE = "find k-dramas, anime & movies like the one you loved"
DESCRIPTION = ("Finished a show and feel empty inside? Similar Stories reads the plot with machine "
               "learning and finds K-dramas, C-dramas, anime and movies with the same vibe, not just "
               "the same genre. Free, no account needed.")
KEYWORDS = ("k-drama recommendations, shows like, kdrama like, movies like, anime recommendations, "
            "what to watch next, similar shows, c-drama, recommendation engine")
SITEMAP_TITLES = 300


def site_url() -> str:
    return os.environ.get("SITE_URL", "http://localhost:8501").rstrip("/")


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict]:
    """uid -> {title, aka, year, overview, votes}; loaded once, on first request."""
    meta = joblib.load(DEFAULT_INDEX)["meta"]
    out = {}
    for r in meta.itertuples():
        out[f"{r.media_type}:{r.tmdb_id}"] = {
            "title": r.title, "aka": best_aka(r.title, r.original_language, getattr(r, "aka_en", None)),
            "kind": "series" if r.media_type == "tv" else "movies",
            "year": None if r.year != r.year else int(r.year), "overview": r.overview, "votes": int(r.vote_count),
        }
    return out


def popular(n: int) -> list[tuple[str, dict]]:
    return sorted(catalog().items(), key=lambda kv: -kv[1]["votes"])[:n]


# ---- head + fallback content --------------------------------------------------------------
def page_meta(path: str, like: str | None) -> tuple[str, str, str]:
    """(title, description, canonical URL) for the requested page."""
    base = site_url()
    first = (like or "").split(",")[0]
    item = catalog().get(first) if first else None
    if item:
        name = item["title"] + (f" ({item['aka']})" if item["aka"] else "")
        title = f"{item['kind']} like {name} · {SITE_NAME}"
        desc = (f"Loved {item['title']}? Here are {item['kind']} with the same vibe, matched by plot "
                f"with machine learning. {item['overview'][:150]}")
        return title, desc, f"{base}/?like={first}"
    if path.strip("/") == "how_it_works":
        return (f"how it works · {SITE_NAME}",
                "How Similar Stories recommends shows: sentence-transformer plot embeddings, TF-IDF "
                "theme matching and Bayesian ratings. Not rule-based, no account needed.",
                f"{base}/how_it_works")
    if path.strip("/") == "feedback":
        return f"rate us · {SITE_NAME}", "Leave feedback for Similar Stories.", f"{base}/feedback"
    return f"{SITE_NAME} · {TAGLINE}", DESCRIPTION, f"{base}/"


def head_tags(title: str, desc: str, url: str) -> str:
    e = lambda s: html.escape(s, quote=True)
    img = f"{site_url()}/og.png"
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "WebApplication", "name": "Similar Stories",
        "url": site_url() + "/", "description": DESCRIPTION, "applicationCategory": "EntertainmentApplication",
        "operatingSystem": "Any", "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    })
    return f"""
    <title>{e(title)}</title>
    <meta name="description" content="{e(desc)}" />
    <meta name="keywords" content="{e(KEYWORDS)}" />
    <link rel="canonical" href="{e(url)}" />
    <meta name="theme-color" content="#0e0c0b" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Similar Stories" />
    <meta property="og:title" content="{e(title)}" />
    <meta property="og:description" content="{e(desc)}" />
    <meta property="og:url" content="{e(url)}" />
    <meta property="og:image" content="{img}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{e(title)}" />
    <meta name="twitter:description" content="{e(desc)}" />
    <meta name="twitter:image" content="{img}" />
    <script type="application/ld+json">{ld}</script>
    """


def fallback_body(title: str, desc: str) -> str:
    """Plain HTML for crawlers. React replaces #root's children when the app boots."""
    links = "".join(
        f'<li><a href="/?like={uid}">{html.escape(i["kind"])} like {html.escape(i["title"])}</a></li>'
        for uid, i in popular(40))
    return (f'<main style="font-family:sans-serif;color:#f4ede4;padding:2rem">'
            f"<h1>{html.escape(title)}</h1><p>{html.escape(desc)}</p>"
            f'<p><a href="/how_it_works">How it works</a> · <a href="/feedback">Rate us</a></p>'
            f"<h2>Popular searches</h2><ul>{links}</ul></main>")


class SEOMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if (request.method != "GET" or "text/html" not in response.headers.get("content-type", "")
                or response.headers.get("content-encoding")):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        title, desc, url = page_meta(request.url.path, request.query_params.get("like"))
        body = body.replace("<title>Streamlit</title>", head_tags(title, desc, url), 1)
        body = body.replace('<div id="root"></div>', f'<div id="root">{fallback_body(title, desc)}</div>', 1)
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")


# ---- routes ---------------------------------------------------------------------------------
async def robots(request):
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /admin\n\nSitemap: {site_url()}/sitemap.xml\n")


async def sitemap(request):
    base = site_url()
    urls = [f"{base}/", f"{base}/how_it_works", f"{base}/feedback"]
    urls += [f"{base}/?like={uid}" for uid, _ in popular(SITEMAP_TITLES)]
    body = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset '
                    f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")


async def og_image(request):
    return FileResponse(ROOT / "assets" / "og.png", media_type="image/png")


app = st.App(
    str(ROOT / "app.py"),
    routes=[Route("/robots.txt", robots), Route("/sitemap.xml", sitemap), Route("/og.png", og_image)],
    middleware=[Middleware(SEOMiddleware)],
)
