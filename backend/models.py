"""Pydantic data models shared across the VeriTrace backend."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_serializer


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Source(BaseModel):
    """A single snapshotted web page used as evidence."""

    url: str
    raw_content: str
    timestamp: datetime = Field(default_factory=_now)
    # SHA-256 fingerprint of url + raw_content + timestamp. Populated by the hasher.
    sha256_hash: Optional[str] = None

    @field_serializer("timestamp")
    def _serialize_timestamp(self, value: datetime) -> str:
        # Emit the exact ISO string used when hashing (e.g. "+00:00", not "Z"),
        # so a source round-tripped through /investigate -> /verify re-hashes
        # to the identical digest. Critical for honest tamper detection.
        return value.isoformat()


class Claim(BaseModel):
    """A factual claim extracted from a source, linked back to its evidence."""

    text: str
    source_index: int           # index into the report's sources list
    source_hash: str = ""       # SHA-256 fingerprint of the originating source
    source_url: str = ""        # URL of the originating source
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Report(BaseModel):
    """A full intelligence report on a target company."""

    id: str
    target_company: str
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    merkle_root: Optional[str] = None
    solana_tx_signature: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    verified: bool = False


# ── Merkle / verification models ──────────────────────────────────


class MerkleTree(BaseModel):
    """Serializable view of a built merkle tree."""

    leaves: list[str] = Field(default_factory=list)
    root: str = ""
    tree_layers: list[list[str]] = Field(default_factory=list)


class SolanaCommitment(BaseModel):
    """Details of an on-chain merkle-root commitment (Solana devnet)."""

    tx_signature: str
    explorer_url: str
    slot: Optional[int] = None
    merkle_root: str
    timestamp: datetime


class InvestigationReport(BaseModel):
    """The full, verifiable output of an investigation."""

    id: str
    target_company: str
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    merkle_root: str = ""
    merkle_tree: MerkleTree = Field(default_factory=MerkleTree)
    solana_tx: Optional[SolanaCommitment] = None
    created_at: datetime = Field(default_factory=_now)
    verified: bool = False
    evidence_stored: bool = False  # stored in the Cognee evidence graph?


class SourceInput(BaseModel):
    """A source as submitted to /verify.

    ``timestamp`` is kept as the raw ISO string so it is hashed byte-for-byte
    the same way it was at collection time. ``sha256_hash`` is optional: when
    provided, /verify can report exactly which sources were tampered with.
    """

    url: str
    raw_content: str
    timestamp: str
    sha256_hash: Optional[str] = None


class VerifyRequest(BaseModel):
    sources: list[SourceInput] = Field(default_factory=list)
    merkle_root: str
    # Optional: when provided, /verify also checks the on-chain record.
    solana_tx_signature: Optional[str] = None


class VerifyResponse(BaseModel):
    valid: bool
    computed_root: str
    expected_root: str
    mismatched_sources: list[int] = Field(default_factory=list)
    on_chain_verification: Optional[dict] = None


# ── Evidence-graph query models ───────────────────────────────────


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    results: list = Field(default_factory=list)
