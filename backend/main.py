"""VeriTrace FastAPI entry point.

Phase 1 exposes a single endpoint, ``POST /investigate``, which runs the
Bright Data collection pipeline for a company and returns the raw snapshotted
sources. Later phases will add hashing, claim extraction, and on-chain
commitment.

Run locally:
    uvicorn main:app --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import uuid

try:  # support `uvicorn main:app` (flat) and package-style imports
    from .bright_data.collector import collect_sources
    from .hasher.merkle import build_merkle_tree, verify_merkle_root
    from .intelligence.extractor import extract_claims
    from .chain.committer import commit_to_solana, verify_on_chain
    from .memory.evidence_graph import query_evidence, store_investigation
    from .models import (
        InvestigationReport,
        MerkleTree,
        QueryRequest,
        QueryResponse,
        SolanaCommitment,
        VerifyRequest,
        VerifyResponse,
    )
except ImportError:  # pragma: no cover
    from bright_data.collector import collect_sources  # type: ignore
    from hasher.merkle import build_merkle_tree, verify_merkle_root  # type: ignore
    from intelligence.extractor import extract_claims  # type: ignore
    from chain.committer import commit_to_solana, verify_on_chain  # type: ignore
    from memory.evidence_graph import query_evidence, store_investigation  # type: ignore
    from models import (  # type: ignore
        InvestigationReport,
        MerkleTree,
        QueryRequest,
        QueryResponse,
        SolanaCommitment,
        VerifyRequest,
        VerifyResponse,
    )

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="VeriTrace",
    description="Cryptographically verifiable AI-generated intelligence.",
    version="0.1.0",
)

# Open CORS for the local demo frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvestigateRequest(BaseModel):
    company_name: str


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "veritrace", "status": "ok", "phase": "1"}


@app.post("/investigate", response_model=InvestigationReport)
async def investigate(req: InvestigateRequest) -> InvestigationReport:
    """Full pipeline: collect -> hash -> merkle -> claims -> on-chain -> graph."""
    company = req.company_name.strip()
    if not company:
        raise HTTPException(status_code=422, detail="company_name must not be empty")

    # 1. Collect + snapshot + hash sources (Phases 1-2). Blocking I/O -> threadpool.
    try:
        sources = await run_in_threadpool(collect_sources, company)
    except RuntimeError as exc:
        # e.g. missing API key — surface as a clear client error.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"collection failed: {exc}") from exc

    # 2. Build the merkle tree over the source fingerprints (Phase 2).
    leaf_hashes = [s.sha256_hash for s in sources if s.sha256_hash]
    tree = build_merkle_tree(leaf_hashes)

    # 3. Extract verifiable claims, each linked to its source hash (Phase 3).
    #    Best-effort: returns [] on failure so the report still includes evidence.
    claims = await run_in_threadpool(extract_claims, sources, company)

    report_id = str(uuid.uuid4())

    # 4. Anchor the merkle root on Solana devnet (Phase 3B).
    #    Best-effort: stays None on failure so the report still works locally.
    commitment = None
    if tree["root"]:
        result = await run_in_threadpool(commit_to_solana, report_id, tree["root"], company)
        if result:
            commitment = SolanaCommitment(**result)

    report = InvestigationReport(
        id=report_id,
        target_company=company,
        sources=sources,
        claims=claims,
        merkle_root=tree["root"],
        merkle_tree=MerkleTree(**tree),
        solana_tx=commitment,
    )

    # 5. Store the evidence chain in Cognee's knowledge graph (Phase 4).
    #    Best-effort: a graph failure must not fail the investigation.
    try:
        store_result = await store_investigation(report)
        report.evidence_stored = bool(store_result.get("stored"))
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("veritrace").error("Cognee storage failed: %s", exc)

    return report


@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    """Recompute hashes + merkle root from submitted sources and detect tampering.

    Powers the tamper-detection demo: modify any source's content and the
    recomputed root will no longer match ``merkle_root``. When sources include
    their original ``sha256_hash``, the response also names which indices changed.
    """
    sources_data = [s.model_dump() for s in req.sources]
    result = verify_merkle_root(sources_data, req.merkle_root)

    # If a tx signature was supplied, also check the on-chain record.
    on_chain = None
    if req.solana_tx_signature:
        on_chain = verify_on_chain(req.solana_tx_signature, req.merkle_root)

    return VerifyResponse(on_chain_verification=on_chain, **result)


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Ask the Cognee evidence graph a natural-language question.

    Makes the evidence chain navigable for auditors, e.g. "which sources mention
    lawsuits?" or "what evidence supports the outage claim?".
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    results = await query_evidence(question)
    return QueryResponse(question=question, results=results)
