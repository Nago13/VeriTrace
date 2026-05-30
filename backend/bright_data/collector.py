"""Bright Data data pipeline.

Three public functions:

* ``search_sources(company_name)``  -> list[str] of candidate URLs
* ``fetch_page(url)``               -> dict with the page's full content
* ``collect_sources(company_name)`` -> list[Source] (search + fetch + snapshot)

Bright Data is accessed through its **Direct API** (``/request`` endpoint),
which proxies a target URL through a given zone and returns the response.
This is the most reliable way to drive both the SERP API and the Web Unlocker
from server code, and it avoids needing a local proxy/CA setup.

Docs: https://docs.brightdata.com/scraping-automation/serp-api  and
      https://docs.brightdata.com/scraping-automation/web-unlocker
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

try:  # allow running both as a package and as a flat module
    from ..config import settings
    from ..hasher.merkle import hash_source
    from ..models import Source
except ImportError:  # pragma: no cover - fallback for `python collector.py`
    from config import settings  # type: ignore
    from hasher.merkle import hash_source  # type: ignore
    from models import Source  # type: ignore

logger = logging.getLogger("veritrace.bright_data")

# Search terms that tend to surface material intelligence about a company.
INTEL_TERMS = ["outage", "lawsuit", "SEC filing", "layoff", "acquisition"]

# How many of the discovered URLs to actually fetch & snapshot.
MAX_SOURCES = 5

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.bright_data_api_key}",
        "Content-Type": "application/json",
    }


def _bright_data_request(
    target_url: str, zone: str, data_format: str = "raw"
) -> tuple[int, str]:
    """Fetch ``target_url`` through Bright Data's Direct API.

    Returns ``(http_status, response_text)``. ``data_format`` is "raw" for
    HTML/text, or "json" when we want Bright Data to wrap the result in a
    ``{status_code, headers, body}`` envelope. SERP parsing into structured
    JSON is requested separately via the ``brd_json=1`` query flag on the URL.
    """
    if not settings.bright_data_api_key:
        raise RuntimeError(
            "BRIGHT_DATA_API_KEY is not set — copy .env.example to .env and fill it in."
        )

    payload = {"zone": zone, "url": target_url, "format": data_format}
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            settings.bright_data_request_url,
            headers=_auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.status_code, resp.text


def _ensure_brd_json(url: str) -> str:
    """Ensure the SERP URL carries ``brd_json=1`` so results come back parsed."""
    if "brd_json=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}brd_json=1"


def _unwrap_body(text: str) -> Any:
    """Normalise a Bright Data response into its payload.

    Handles three shapes:
      * envelope ``{"status_code", "headers", "body"}`` — returns the inner body
        (parsed again if it is itself a JSON string, e.g. a brd_json SERP);
      * direct JSON (already the parsed SERP) — returned as-is;
      * plain text/HTML — returned unchanged as a string.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text  # plain HTML/text

    # Envelope detection: a dict with a "body" alongside status_code/headers.
    if isinstance(parsed, dict) and "body" in parsed and (
        "status_code" in parsed or "headers" in parsed
    ):
        body = parsed["body"]
        if isinstance(body, str):
            try:
                return json.loads(body)  # brd_json SERP delivered as a string
            except (json.JSONDecodeError, TypeError):
                return body  # HTML string
        return body  # already structured

    return parsed


def _unwrap_to_text(text: str) -> str:
    """Like ``_unwrap_body`` but always returns a string (for page content)."""
    payload = _unwrap_body(text)
    return payload if isinstance(payload, str) else json.dumps(payload)


def _top_level_keys(payload: Any) -> Any:
    if isinstance(payload, dict):
        return list(payload.keys())
    if isinstance(payload, list):
        return f"<list len={len(payload)}>"
    return f"<{type(payload).__name__}>"


def search_sources(company_name: str) -> list[str]:
    """Search the web for intelligence-relevant pages about ``company_name``.

    Uses Bright Data's SERP API (Google) with ``brd_json=1`` so results come
    back as structured JSON. Aggregates organic result links across all
    ``INTEL_TERMS`` queries, de-duplicated, preserving discovery order.
    """
    if not settings.bright_data_api_key:
        raise RuntimeError(
            "BRIGHT_DATA_API_KEY is not set — copy .env.example to .env and fill it in."
        )

    seen: set[str] = set()
    urls: list[str] = []

    for term in INTEL_TERMS:
        query = f"{company_name} {term}"
        # brd_json=1 asks the SERP API to return parsed JSON instead of HTML.
        search_url = _ensure_brd_json(
            f"https://www.google.com/search?q={quote_plus(query)}"
        )
        try:
            http_status, body = _bright_data_request(
                search_url, zone=settings.bright_data_serp_zone, data_format="json"
            )
        except Exception as exc:  # noqa: BLE001 - keep one bad query from killing all
            logger.warning("SERP query failed for %r: %s", query, exc)
            continue

        payload = _unwrap_body(body)
        # Detailed diagnostics: HTTP status, structure, and a content preview.
        logger.info(
            "SERP %r | HTTP %s | raw_keys=%s | payload_keys=%s | preview=%s",
            query,
            http_status,
            _top_level_keys(_safe_json(body)),
            _top_level_keys(payload),
            (body or "")[:300].replace("\n", " "),
        )

        links = _extract_organic_links(payload)
        logger.info("SERP %r -> %d organic links", query, len(links))
        for link in links:
            if link not in seen:
                seen.add(link)
                urls.append(link)

    logger.info("search_sources(%r) found %d unique URLs", company_name, len(urls))
    return urls


def _safe_json(text: str) -> Any:
    """Parse JSON for logging only; return the raw string if it isn't JSON."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


_ORGANIC_KEYS = ("organic", "organic_results", "results")
_LINK_KEYS = ("link", "url", "href", "display_link")


def _extract_organic_links(payload: Any) -> list[str]:
    """Pull organic result URLs out of a (possibly nested) SERP payload.

    Accepts the unwrapped payload from ``_unwrap_body`` — a dict, a list, or a
    JSON string — and is tolerant of the various shapes Bright Data's SERP
    parser returns.
    """
    if isinstance(payload, str):
        payload = _safe_json(payload)

    organic = _find_organic_list(payload)
    if not organic:
        logger.warning(
            "No organic results found in SERP payload (keys=%s)", _top_level_keys(payload)
        )
        return []

    links: list[str] = []
    for item in organic:
        if not isinstance(item, dict):
            continue
        for key in _LINK_KEYS:
            link = item.get(key)
            if isinstance(link, str) and link.startswith("http"):
                links.append(link)
                break
    return links


def _find_organic_list(payload: Any) -> list | None:
    """Locate the organic-results list, checking the top level then one nesting deep."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    for key in _ORGANIC_KEYS:
        if isinstance(payload.get(key), list):
            return payload[key]
    # Some responses nest the SERP under another object (e.g. {"serp": {...}}).
    for value in payload.values():
        if isinstance(value, dict):
            for key in _ORGANIC_KEYS:
                if isinstance(value.get(key), list):
                    return value[key]
    return None


def fetch_page(url: str) -> dict:
    """Fetch the full content of ``url`` via Bright Data's Web Unlocker.

    Returns a dict: ``{"url", "content", "status", "error"}``. ``content`` is
    the raw HTML/text of the page (empty string on failure, with ``error`` set).
    """
    result: dict[str, Optional[str | int]] = {
        "url": url,
        "content": "",
        "status": None,
        "error": None,
    }
    try:
        http_status, body = _bright_data_request(
            url, zone=settings.bright_data_unlocker_zone, data_format="raw"
        )
        content = _unwrap_to_text(body)
        result["content"] = content
        result["status"] = http_status
        logger.info(
            "fetch_page(%r) | HTTP %s | %d chars", url, http_status, len(content)
        )
    except httpx.HTTPStatusError as exc:
        result["status"] = exc.response.status_code
        result["error"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        logger.warning("fetch_page(%r) failed: %s", url, result["error"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        logger.warning("fetch_page(%r) failed: %s", url, exc)

    return result


def collect_sources(company_name: str) -> list[Source]:
    """End-to-end: search, fetch the top URLs, and snapshot each as a Source.

    The returned ``Source`` objects carry the raw page content and a UTC
    timestamp. Hashing (``sha256_hash``) is left for Phase 2.
    """
    urls = search_sources(company_name)
    if not urls:
        logger.info("collect_sources(%r): no URLs discovered", company_name)
        return []

    sources: list[Source] = []
    for url in urls[:MAX_SOURCES]:
        page = fetch_page(url)
        content = page.get("content") or ""
        if not content:
            logger.info("Skipping %r — empty content (%s)", url, page.get("error"))
            continue
        source = Source(url=url, raw_content=content)
        # Fingerprint the page at this exact moment (url + content + timestamp).
        source.sha256_hash = hash_source(source)
        sources.append(source)

    logger.info(
        "collect_sources(%r): snapshotted %d/%d fetched sources",
        company_name,
        len(sources),
        min(len(urls), MAX_SOURCES),
    )
    return sources
