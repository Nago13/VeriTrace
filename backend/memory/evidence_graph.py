"""Cognee integration — the VeriTrace evidence graph.

Cognee (https://www.cognee.ai) turns the investigation into a queryable
knowledge graph linking sources, claims, and companies. That's the upgrade
over a static report: an auditor can ask natural-language questions like
"which sources mention lawsuits?" or "what evidence supports the outage claim?"
and navigate the evidence chain.

Design notes:
* Cognee is imported defensively — if it (or its heavy deps) isn't installed,
  the rest of VeriTrace keeps working and these functions degrade gracefully.
* All Cognee calls are async. Storage and queries each swallow errors and
  return a clear status so /investigate never crashes on a graph failure.
* The LLM Cognee uses can reuse the AI/ML API key (OpenAI-compatible).
"""
from __future__ import annotations

import logging
import os

try:  # support both package and flat imports
    from ..config import settings
    from ..models import Claim, InvestigationReport, Source
except ImportError:  # pragma: no cover
    from config import settings  # type: ignore
    from models import Claim, InvestigationReport, Source  # type: ignore

logger = logging.getLogger("veritrace.memory")

# Defensive import: a broken/absent cognee must not take down the API.
try:
    import cognee

    COGNEE_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    cognee = None  # type: ignore
    COGNEE_AVAILABLE = False
    logger.warning("Cognee not available (%s) — evidence graph disabled.", exc)

_CONFIGURED = False


def _configure_cognee() -> None:
    """Point Cognee at our LLM + vector DB. Idempotent; reuses the AI/ML key."""
    global _CONFIGURED
    if _CONFIGURED or not COGNEE_AVAILABLE:
        return

    # Cognee 1.0+ turns on multi-user access control by default, which requires
    # a user context for add/cognify/search. For the single-tenant demo we keep
    # it simple and disable that so the basic pipeline just works.
    os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")

    # Cognee reads most config from the environment; set sane defaults if the
    # operator didn't provide dedicated COGNEE_* values, reusing AI/ML creds.
    llm_key = settings.cognee_llm_api_key or settings.aiml_api_key
    if llm_key:
        os.environ.setdefault("LLM_API_KEY", llm_key)
        os.environ.setdefault("COGNEE_LLM_API_KEY", llm_key)
    endpoint = settings.cognee_llm_endpoint or settings.aiml_api_base
    if endpoint:
        os.environ.setdefault("LLM_ENDPOINT", endpoint)
    if settings.cognee_llm_model:
        os.environ.setdefault("LLM_MODEL", settings.cognee_llm_model)
    if settings.cognee_vector_db_provider:
        os.environ.setdefault("VECTOR_DB_PROVIDER", settings.cognee_vector_db_provider)

    # Best-effort programmatic config (API varies across cognee versions).
    try:
        if llm_key and hasattr(cognee, "config") and hasattr(cognee.config, "set_llm_api_key"):
            cognee.config.set_llm_api_key(llm_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cognee.config.set_llm_api_key failed: %s", exc)

    _CONFIGURED = True


# ── formatting helpers ────────────────────────────────────────────


def format_sources(sources: list[Source]) -> str:
    if not sources:
        return "  (none)"
    lines = []
    for i, s in enumerate(sources):
        snippet = (s.raw_content or "")[:200].replace("\n", " ")
        lines.append(
            f"  [{i}] URL: {s.url}\n"
            f"      Hash: {s.sha256_hash}\n"
            f"      Snippet: {snippet}"
        )
    return "\n".join(lines)


def format_claims(claims: list[Claim]) -> str:
    if not claims:
        return "  (none)"
    lines = []
    for i, c in enumerate(claims):
        lines.append(
            f"  [{i}] {c.text}\n"
            f"      Confidence: {c.confidence}\n"
            f"      Source URL: {c.source_url}\n"
            f"      Source Hash: {c.source_hash}"
        )
    return "\n".join(lines)


def format_evidence_links(claims: list[Claim], sources: list[Source]) -> str:
    if not claims:
        return "  (none)"
    lines = []
    for c in claims:
        url = c.source_url
        h = c.source_hash
        if (not url or not h) and 0 <= c.source_index < len(sources):
            src = sources[c.source_index]
            url = url or src.url
            h = h or (src.sha256_hash or "")
        lines.append(
            f"  Claim '{c.text}' is evidenced by Source '{url}' with hash '{h}'."
        )
    return "\n".join(lines)


def _build_investigation_text(report: InvestigationReport) -> str:
    return (
        "VeriTrace Investigation Report\n"
        f"Target Company: {report.target_company}\n"
        f"Report ID: {report.id}\n"
        f"Date: {report.created_at}\n"
        f"Merkle Root: {report.merkle_root}\n\n"
        "Sources:\n"
        f"{format_sources(report.sources)}\n\n"
        "Claims:\n"
        f"{format_claims(report.claims)}\n\n"
        "Evidence Links:\n"
        f"{format_evidence_links(report.claims, report.sources)}\n"
    )


# ── public async API ──────────────────────────────────────────────


async def store_investigation(report: InvestigationReport) -> dict:
    """Store a full investigation in Cognee's knowledge graph.

    Returns a status dict. Never raises — on failure ``stored`` is False and an
    ``error`` is included, so /investigate can continue without the graph.
    """
    dataset = f"investigation_{report.id}"
    if not COGNEE_AVAILABLE:
        return {"stored": False, "dataset": dataset, "error": "cognee not installed"}

    _configure_cognee()
    investigation_text = _build_investigation_text(report)

    try:
        await cognee.add(investigation_text, dataset_name=dataset)
        # Process the raw text into a structured knowledge graph (can take a
        # few seconds — fine for the demo).
        await cognee.cognify()
    except Exception as exc:  # noqa: BLE001
        logger.error("Cognee store_investigation failed: %s", exc)
        return {"stored": False, "dataset": dataset, "error": str(exc)}

    logger.info("Stored investigation %s in Cognee", report.id)
    return {
        "stored": True,
        "dataset": dataset,
        "sources_count": len(report.sources),
        "claims_count": len(report.claims),
    }


def _resolve_search_type():
    """Locate the SearchType enum across cognee versions (path moved over time)."""
    try:
        from cognee.modules.search.types import SearchType  # type: ignore

        return SearchType
    except Exception:  # noqa: BLE001
        pass
    try:
        from cognee import SearchType  # type: ignore

        return SearchType
    except Exception:  # noqa: BLE001
        return None


async def _run_search(question: str):
    """Run a GRAPH_COMPLETION search using keyword args (matches the current API)."""
    search_type = _resolve_search_type()
    graph_completion = search_type.GRAPH_COMPLETION if search_type else "GRAPH_COMPLETION"
    return await cognee.search(query_text=question, query_type=graph_completion)


async def query_evidence(question: str) -> list[dict]:
    """Query the evidence graph in natural language. Returns [] on any failure."""
    if not COGNEE_AVAILABLE:
        logger.warning("query_evidence called but Cognee is unavailable.")
        return []

    _configure_cognee()
    try:
        results = await _run_search(question)
    except Exception as exc:  # noqa: BLE001
        logger.error("Cognee query_evidence failed: %s", exc)
        return []

    return [{"result": str(r)} for r in results] if results else []
