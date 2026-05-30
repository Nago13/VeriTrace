# VeriTrace

> Cryptographically verifiable AI-generated intelligence.

An AI agent investigates a company using live web data (via Bright Data),
extracts factual claims, and produces an intelligence report. Every source
page is snapshotted and SHA-256 hashed. Every claim is linked to its source
hash. All hashes are combined into a merkle root that is committed to the
Solana blockchain (devnet) — making the entire report tamper-proof and
auditable by any third party.

## Architecture

```
company name
     │
     ▼
┌──────────────┐   Bright Data SERP + Web Unlocker
│  Collector   │ ─────────────────────────────────► live source pages
└──────────────┘
     │ Source[]  (url, raw_content, timestamp, sha256_hash)
     ▼
┌──────────────┐   AI/ML API (LLM)
│  Extractor   │ ─────────────────────────────────► Claim[]  (Phase 2)
└──────────────┘
     │
     ▼
┌──────────────┐   hashlib
│   Merkle     │ ─────────────────────────────────► merkle_root  (Phase 2)
└──────────────┘
     │
     ▼
┌──────────────┐   Anchor / web3
│  Committer   │ ─────────────────────────────────► Solana tx  (Phase 2)
└──────────────┘
```

## Phase 1 (this build)

Project skeleton + Bright Data data pipeline + a basic FastAPI endpoint.
Hashing, AI extraction, Cognee, and Solana are stubbed for later phases.

## Quick start

> **Run from the project root in package mode** (`backend.main:app`) for clean
> relative imports. The on-chain client lives in `backend/chain/` (deliberately
> not named `solana`, to avoid shadowing the installed `solana` library).

```bash
cd veritrace            # project root (the dir containing backend/)
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in your keys
uvicorn backend.main:app --reload
```

Then:

```bash
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"company_name": "Acme Corp"}'
```

## Demo frontend

A single-page React (Vite + Tailwind) demo lives in `frontend/`.

```bash
# 1. start the backend (from the project root)
uvicorn backend.main:app --reload

# 2. in another terminal, start the frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The backend has open CORS for local dev, so the frontend calls
`http://localhost:8000` directly (override with `VITE_API_BASE`).

**Demo flow (one page, one path):**
1. The company field is pre-filled (`CrowdStrike`) — click **Investigate**.
2. Watch the staged pipeline, then the verified report appears (sources +
   hashes, claims with confidence bars, merkle root, Solana explorer link).
3. Click **Edit** on a claim and change its text — this doctors the underlying
   source evidence.
4. Click **Verify Report Integrity** → the recomputed merkle root no longer
   matches and **TAMPERING DETECTED** fires, naming the altered source and
   showing the committed-vs-recomputed hash.
5. (Bonus) Ask the Cognee evidence graph a question via the query panel.

### Evidence graph (Cognee)

Every investigation is also stored in a **Cognee** knowledge graph, linking
companies → sources → claims → hashes. That makes the evidence chain queryable:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What evidence supports claims about outages?"}'
```

Demo questions that show navigability:
- "What are the most serious claims about this company?"
- "Which sources are cited as evidence for the lawsuit?"
- "What evidence exists about security incidents?"

Cognee needs an LLM to build the graph. Set `COGNEE_LLM_API_KEY` (you can reuse
your AI/ML API key) plus `COGNEE_LLM_ENDPOINT` in `.env`. If Cognee is
unavailable or unconfigured, `/investigate` still succeeds — `evidence_stored`
is simply `false` and `/query` returns an empty list.

### Solana devnet notes

- On-chain commitment uses the **SPL Memo program** — no custom program to deploy.
- The signer needs devnet SOL. Set a funded `SOLANA_PRIVATE_KEY` (base58 or JSON
  byte array) in `.env`. If unset, an ephemeral key is generated and an airdrop
  is attempted — but the devnet faucet is frequently rate-limited, so for a
  reliable demo provide a pre-funded devnet key.
- If the commit fails for any reason, `solana_tx` is `null` and the report still
  works locally (merkle root + claims) — only the on-chain proof is missing.

## Project layout

```
veritrace/
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # API keys, env vars
│   ├── models.py               # Pydantic models (Source, Claim, Report)
│   ├── bright_data/collector.py    # Bright Data SERP + Web Unlocker
│   ├── hasher/merkle.py            # SHA-256 + merkle tree (Phase 2)
│   ├── intelligence/extractor.py   # AI/ML API claim extraction (Phase 2)
│   ├── memory/evidence_graph.py    # Cognee integration (Phase 2)
│   └── chain/committer.py          # Solana commitment client (Phase 2)
├── anchor/        # Anchor program (later)
├── frontend/      # React app (later)
├── requirements.txt
├── .env.example
└── README.md
```
