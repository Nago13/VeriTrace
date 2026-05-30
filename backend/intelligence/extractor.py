"""Claim extraction via the AI/ML API (OpenAI-compatible, https://api.aimlapi.com/v1).

``extract_claims`` reads the raw content of the collected sources and asks an
LLM to pull out specific, verifiable factual claims about the target company.
Each returned Claim is linked back to the exact source it came from — carrying
that source's URL and SHA-256 fingerprint — so a claim can always be traced to
tamper-evident evidence.

Extraction is best-effort: any API/parse failure logs a warning and yields an
empty list, so the rest of the /investigate pipeline (sources + merkle root)
still succeeds.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
from typing import Any

import httpx

try:  # support both package and flat imports
    from ..config import settings
    from ..models import Claim, Source
except ImportError:  # pragma: no cover
    from config import settings  # type: ignore
    from models import Claim, Source  # type: ignore

logger = logging.getLogger("veritrace.intelligence")

# Characters of cleaned text fed to the model per source.
MAX_SOURCE_CHARS = 5000
_TIMEOUT = httpx.Timeout(180.0, connect=15.0)

# Strip boilerplate so the model sees article text, not <head>/CSS/scripts.
_BLOCK_RE = re.compile(
    r"<(script|style|head|noscript|svg|nav|footer)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

SYSTEM_PROMPT = (
    "You are an aggressive, exhaustive corporate due-diligence analyst building "
    "a risk dossier on a target company. You will be given several web sources, "
    "each labelled with a 0-based index. Mine EVERY source thoroughly and pull "
    "out as many SPECIFIC, VERIFIABLE FACTUAL CLAIMS as the text supports.\n\n"
    "TARGET: extract 8-15 claims total, and aim for 2-4 claims from EACH source. "
    "Cover a SPREAD of categories — do not return only one type:\n"
    "  • Incidents & outages — what failed, scope, duration, affected systems\n"
    "  • Financial impact — dollar amounts, revenue/loss, stock moves, market cap\n"
    "  • Legal issues — lawsuits, case names, plaintiffs, settlements, fines\n"
    "  • Regulatory actions — SEC filings, investigations, government responses\n"
    "  • Leadership changes — executive hires/departures, board changes\n"
    "  • Layoffs / restructuring — headcount, percentages, office closures\n"
    "  • Security breaches — vulnerabilities, root cause, data exposed\n"
    "  • Timeline events — dated milestones (e.g. 'on July 19, 2024 …')\n\n"
    "Each claim MUST be concrete and self-contained. Prefer claims that contain "
    "a NUMBER, DATE, NAME, DOLLAR AMOUNT, or COUNT of affected users/devices. "
    "Good examples:\n"
    "  - 'A faulty CrowdStrike update on July 19, 2024 crashed ~8.5 million "
    "Windows devices worldwide.'\n"
    "  - 'Delta Air Lines estimated the outage cost it $500 million and sued "
    "CrowdStrike in October 2024.'\n"
    "  - 'CrowdStrike shares fell roughly 11% in the days after the incident.'\n\n"
    "Rules: never invent facts or numbers not in the text; no opinions, marketing "
    "language, or vague generalities; every claim must tie to a specific provided "
    "source via its 0-based index; set confidence in [0.0, 1.0] by how clearly "
    "the source supports it. Return ONLY valid JSON, no prose, in exactly this "
    "shape:\n"
    '{\n'
    '  "claims": [\n'
    '    {"text": "<concrete factual claim with a date/number/name>", '
    '"source_index": 0, "confidence": 0.95}\n'
    '  ]\n'
    '}'
)


def _html_to_text(raw: str) -> str:
    """Reduce raw HTML to readable text so the model sees content, not markup."""
    if not raw:
        return ""
    if "<" not in raw:
        return raw  # already plain text
    text = _BLOCK_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _build_user_content(sources: list[Source], company_name: str) -> str:
    parts = [
        f"Target company: {company_name}",
        f"There are {len(sources)} sources (indices 0-{len(sources) - 1}). "
        "Extract claims from ALL of them.",
        "",
    ]
    for i, src in enumerate(sources):
        snippet = _html_to_text(src.raw_content)[:MAX_SOURCE_CHARS]
        parts.append(f"Source [{i}] (URL: {src.url}):")
        parts.append(snippet)
        parts.append("")
    return "\n".join(parts)


def _call_aiml(user_content: str) -> str:
    """Call the AI/ML chat completions API and return the raw message content."""
    payload = {
        "model": settings.aiml_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.aiml_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.aiml_api_base.rstrip('/')}/chat/completions"

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]


def _parse_claims(raw: str, sources: list[Source]) -> list[Claim]:
    """Parse the model's JSON output into Claim objects linked to their sources."""
    data: Any = json.loads(raw)
    items = data.get("claims", []) if isinstance(data, dict) else []

    claims: list[Claim] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        idx = item.get("source_index")
        if not text or not isinstance(idx, int):
            continue
        if idx < 0 or idx >= len(sources):
            logger.warning("Dropping claim with out-of-range source_index %r", idx)
            continue

        src = sources[idx]
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        claims.append(
            Claim(
                text=text,
                source_index=idx,
                source_hash=src.sha256_hash or "",
                source_url=src.url,
                confidence=confidence,
            )
        )
    return claims


def extract_claims(sources: list[Source], company_name: str) -> list[Claim]:
    """Extract verifiable factual claims from sources, linked to source hashes.

    Returns an empty list (with a logged warning) on any failure so the caller
    can still return sources and the merkle root.
    """
    if not sources:
        return []
    if not settings.aiml_api_key:
        logger.warning("AIML_API_KEY is not set — skipping claim extraction.")
        return []

    user_content = _build_user_content(sources, company_name)

    try:
        raw = _call_aiml(user_content)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "AI/ML API returned %s: %s",
            exc.response.status_code,
            exc.response.text[:300],
        )
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI/ML API call failed: %s", exc)
        return []

    try:
        claims = _parse_claims(raw, sources)
    except json.JSONDecodeError as exc:
        logger.warning("AI/ML API returned invalid JSON: %s | raw=%.200s", exc, raw)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse claims: %s", exc)
        return []

    logger.info("extract_claims(%r): extracted %d claims", company_name, len(claims))
    return claims
