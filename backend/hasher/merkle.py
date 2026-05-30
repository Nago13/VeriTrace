"""SHA-256 hashing + merkle tree construction and verification.

The fingerprint of a source is ``SHA-256(url + raw_content + timestamp)`` where
``timestamp`` is the ISO-8601 string of the moment the page was snapshotted.
Using the exact ISO string (not a re-formatted datetime) is what makes the hash
reproducible: the verifier hashes the same bytes the collector did.

All source fingerprints are combined into a binary merkle tree whose single
root hash commits to the entire evidence set. Changing any byte of any source
changes its leaf hash, which changes the root — that is the basis of tamper
detection (see ``verify_merkle_root``).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

try:  # support both package and flat imports
    from ..models import Source
except ImportError:  # pragma: no cover
    from models import Source  # type: ignore


# ── low-level helpers ─────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ts_to_str(timestamp: Any) -> str:
    """Canonical ISO string for a timestamp that may be a datetime or a str.

    Sources collected in-process carry a ``datetime``; sources sent to /verify
    arrive as the ISO string that was previously emitted, and must be hashed
    verbatim so the digest round-trips.
    """
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    return str(timestamp)


def _fingerprint(url: str, raw_content: str, timestamp: Any) -> str:
    return _sha256(f"{url}{raw_content}{_ts_to_str(timestamp)}")


# ── public API ────────────────────────────────────────────────────


def hash_source(source: Source) -> str:
    """SHA-256 fingerprint of a Source: hex digest of url + raw_content + timestamp."""
    return _fingerprint(source.url, source.raw_content, source.timestamp)


def build_merkle_tree(hashes: list[str]) -> dict:
    """Build a binary merkle tree over a list of hex hash strings.

    Odd layers duplicate their last element before pairing. Returns the leaves,
    the root, and every layer of the tree (``tree_layers[0]`` is the leaves,
    the last layer is ``[root]``). An empty input yields an empty tree.
    """
    leaves = list(hashes)
    if not leaves:
        return {"leaves": [], "root": "", "tree_layers": []}

    tree_layers: list[list[str]] = [list(leaves)]
    current = list(leaves)

    while len(current) > 1:
        # Duplicate the last leaf if this layer has an odd count.
        if len(current) % 2 == 1:
            current = current + [current[-1]]

        nxt: list[str] = []
        for i in range(0, len(current), 2):
            nxt.append(_sha256(current[i] + current[i + 1]))

        tree_layers.append(nxt)
        current = nxt

    return {"leaves": leaves, "root": current[0], "tree_layers": tree_layers}


def verify_merkle_root(sources_data: list[dict], expected_root: str) -> dict:
    """Recompute hashes + root from raw source data and compare to ``expected_root``.

    Each item in ``sources_data`` must provide ``url``, ``raw_content`` and
    ``timestamp``. If an item also carries its original ``sha256_hash``, a
    per-source comparison is done so the response can name *which* sources were
    tampered with (``mismatched_sources`` holds those indices). Without the
    original hashes only the overall root comparison is possible.
    """
    computed_hashes: list[str] = []
    mismatched_sources: list[int] = []

    for index, item in enumerate(sources_data):
        recomputed = _fingerprint(
            item.get("url", ""),
            item.get("raw_content", ""),
            item.get("timestamp", ""),
        )
        computed_hashes.append(recomputed)

        original = item.get("sha256_hash")
        if original is not None and original != recomputed:
            mismatched_sources.append(index)

    computed_root = build_merkle_tree(computed_hashes)["root"]

    return {
        "valid": computed_root == expected_root,
        "computed_root": computed_root,
        "expected_root": expected_root,
        "mismatched_sources": mismatched_sources,
    }
