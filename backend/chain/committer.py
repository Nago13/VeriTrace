"""Solana on-chain commitment client (devnet) — the VeriTrace trust layer.

After the merkle root is computed, we anchor it on Solana devnet using the
built-in SPL **Memo** program — no custom on-chain program to deploy. The memo
carries the report metadata as a small JSON blob; the resulting transaction is
immutable, timestamped, and publicly visible on Solana Explorer. Its signature
is the proof that this exact merkle root was recorded at this moment.

Two functions:
  * ``commit_to_solana`` — write the merkle root on-chain, return tx details.
  * ``verify_on_chain``  — read it back and compare against an expected root.

Everything is best-effort: failures log and return ``None`` (commit) or a
``False`` verdict (verify) so the rest of the pipeline keeps working without
on-chain proof.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

try:  # support both package and flat imports
    from ..config import settings
except ImportError:  # pragma: no cover
    from config import settings  # type: ignore

logger = logging.getLogger("veritrace.chain")

MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
PROTOCOL = "veritrace-v1"
MEMO_MAX_BYTES = 566  # SPL Memo program hard limit

# Top up the signer if it falls below 0.01 SOL.
_MIN_LAMPORTS = 10_000_000
_AIRDROP_LAMPORTS = 1_000_000_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client() -> Client:
    return Client(settings.solana_rpc_url)


def _explorer_url(tx_signature: str) -> str:
    return f"https://explorer.solana.com/tx/{tx_signature}?cluster=devnet"


def _load_keypair() -> Keypair:
    """Load the signer from config, or generate an ephemeral one (testing)."""
    raw = (settings.solana_private_key or "").strip()
    if raw:
        if raw.startswith("["):  # JSON byte array
            return Keypair.from_bytes(bytes(json.loads(raw)))
        return Keypair.from_base58_string(raw)  # base58
    kp = Keypair()
    logger.warning(
        "No SOLANA_PRIVATE_KEY set — generated ephemeral keypair %s (testing only).",
        kp.pubkey(),
    )
    return kp


def _ensure_funds(client: Client, pubkey: Pubkey) -> None:
    """Airdrop devnet SOL if the balance is too low to pay fees. Best-effort."""
    try:
        balance = client.get_balance(pubkey).value
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read balance for %s: %s", pubkey, exc)
        return
    if balance >= _MIN_LAMPORTS:
        return
    logger.info("Balance %d lamports < min; requesting devnet airdrop…", balance)
    try:
        sig = client.request_airdrop(pubkey, _AIRDROP_LAMPORTS).value
        client.confirm_transaction(sig, commitment=Confirmed)
        logger.info("Airdrop confirmed: %s", sig)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Airdrop failed (devnet rate limit?): %s", exc)


def commit_to_solana(report_id: str, merkle_root: str, target_company: str) -> dict | None:
    """Commit a merkle root to Solana devnet via the Memo program.

    Returns a dict with the tx signature, explorer URL, slot, root and
    timestamp — or ``None`` if the commitment could not be made.
    """
    timestamp = _now_iso()
    memo = json.dumps(
        {
            "protocol": PROTOCOL,
            "report_id": report_id,
            "merkle_root": merkle_root,
            "target": target_company,
            "timestamp": timestamp,
        },
        separators=(",", ":"),
    )
    memo_bytes = memo.encode("utf-8")
    if len(memo_bytes) > MEMO_MAX_BYTES:
        logger.error("Memo payload %d bytes exceeds %d limit", len(memo_bytes), MEMO_MAX_BYTES)
        return None

    try:
        client = _client()
        payer = _load_keypair()
        _ensure_funds(client, payer.pubkey())

        memo_ix = Instruction(
            program_id=MEMO_PROGRAM_ID,
            data=memo_bytes,
            accounts=[AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=False)],
        )
        blockhash: Hash = client.get_latest_blockhash().value.blockhash
        tx = Transaction.new_signed_with_payer(
            [memo_ix], payer.pubkey(), [payer], blockhash
        )

        signature = client.send_raw_transaction(bytes(tx)).value
        client.confirm_transaction(signature, commitment=Confirmed)

        slot = None
        try:
            info = client.get_transaction(
                signature, commitment=Confirmed, max_supported_transaction_version=0
            ).value
            if info is not None:
                slot = info.slot
        except Exception as exc:  # noqa: BLE001
            logger.warning("Committed but could not fetch slot: %s", exc)

        sig_str = str(signature)
        logger.info("Committed merkle root on-chain: %s", sig_str)
        return {
            "tx_signature": sig_str,
            "explorer_url": _explorer_url(sig_str),
            "slot": slot,
            "merkle_root": merkle_root,
            "timestamp": timestamp,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Solana commitment failed: %s", exc)
        return None


def _extract_memo_from_logs(log_messages: list[str]) -> dict | None:
    """Pull the JSON memo object out of a transaction's program logs.

    The Memo program logs a line like:
        ``Program log: Memo (len 123): "<rust-debug-quoted string>"``
    The quoted part is a string literal (quotes/backslashes escaped), so a
    first ``json.loads`` unescapes it to our memo string, and a second parses
    that string into the object.
    """
    for line in log_messages or []:
        marker = "Memo (len"
        if marker not in line:
            continue
        sep = line.find("): ")
        if sep == -1:
            continue
        quoted = line[sep + 3:].strip()
        try:
            inner = json.loads(quoted)        # unescape string literal -> memo string
            return json.loads(inner)          # parse memo string -> object
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def verify_on_chain(tx_signature: str, expected_merkle_root: str) -> dict:
    """Fetch a tx from devnet and compare its on-chain merkle root to the expected one."""
    result = {
        "on_chain_verified": False,
        "on_chain_merkle_root": None,
        "expected_merkle_root": expected_merkle_root,
        "tx_signature": tx_signature,
        "explorer_url": _explorer_url(tx_signature),
        "block_time": None,
    }
    try:
        client = _client()
        sig = Signature.from_string(tx_signature)
        info = client.get_transaction(
            sig, commitment=Confirmed, max_supported_transaction_version=0
        ).value
        if info is None:
            logger.warning("Transaction not found on-chain: %s", tx_signature)
            return result

        result["block_time"] = info.block_time
        meta = info.transaction.meta
        logs = list(meta.log_messages) if meta and meta.log_messages else []
        memo = _extract_memo_from_logs(logs)
        if memo is None:
            logger.warning("No parseable memo found in tx %s", tx_signature)
            return result

        on_chain_root = memo.get("merkle_root")
        result["on_chain_merkle_root"] = on_chain_root
        result["on_chain_verified"] = on_chain_root == expected_merkle_root
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("On-chain verification failed for %s: %s", tx_signature, exc)
        return result
