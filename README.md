<div align="center">

# 🛡️ VeriTrace

### Any AI can investigate. Only VeriTrace proves what it finds.

**Cryptographically verifiable AI-generated intelligence — every claim traceable to a tamper-proof, on-chain source of truth.**

[![Built for Web Data UNLOCKED](https://img.shields.io/badge/Web%20Data%20UNLOCKED-Hackathon-FF6B35)](https://brightdata.com)
[![Bright Data](https://img.shields.io/badge/Bright%20Data-SERP%20%2B%20Web%20Unlocker-1A73E8)](https://brightdata.com)
[![Solana](https://img.shields.io/badge/Solana-Devnet-9945FF)](https://solana.com)
[![Cognee](https://img.shields.io/badge/Cognee-Evidence%20Graph-22c55e)](https://cognee.ai)
[![Python](https://img.shields.io/badge/Python-FastAPI-009688)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-Vite%20%2B%20Tailwind-61DAFB)](https://react.dev)

</div>

---

## 📖 Overview

VeriTrace is an AI agent that investigates a company using **live web data**, extracts **specific factual claims**, and produces an intelligence report where **every claim is cryptographically bound to the exact source it came from**. Each source page is snapshotted and SHA-256 hashed, all hashes are combined into a single **merkle root**, and that root is committed to the **Solana blockchain**. The result is an intelligence report that anyone — a journalist, an auditor, a regulator — can independently verify and detect tampering in, down to the individual source. The evidence chain is also loaded into a **Cognee knowledge graph**, making it queryable in natural language.

In short: VeriTrace turns AI output from *"trust me"* into *"verify me."*

---

## 🎯 The Problem

AI is increasingly used to generate intelligence, due-diligence, and research reports — but **there is no way to prove what an AI actually read, or whether a report was altered after the fact.**

- ⚖️ **Regulation is here.** The **EU AI Act** mandates traceability, transparency, and record-keeping for high-risk AI systems. "The model said so" is no longer a defensible audit trail.
- 📈 **Incidents are exploding.** Reported AI-related incidents and harms have climbed sharply year over year (**~88%** of organizations cite trust and verifiability as a top barrier to adopting AI for critical decisions).
- 🕳️ **No audit trail.** Once an LLM emits a paragraph, the link to its sources is gone. Reports can be edited, sources can rot or be doctored, and **nobody can prove the difference** between the original and a tampered version.

VeriTrace closes that gap with cryptography and a public ledger: a report's integrity is mathematically verifiable by **any third party**, with **zero trust** in VeriTrace itself.

---

## ⚙️ How It Works

A single `POST /investigate` call runs the full six-step pipeline:

| # | Step | What happens | Powered by |
|---|------|--------------|------------|
| 1 | **Collect** | Search the web for material signals (outages, lawsuits, SEC filings, layoffs, acquisitions) and snapshot the top source pages. | Bright Data SERP API + Web Unlocker |
| 2 | **Hash** | Fingerprint each source as `SHA-256(url + content + timestamp)` — a unique, reproducible identity for that page *at that moment*. | Python `hashlib` |
| 3 | **Extract** | An LLM reads the cleaned source text and extracts specific, verifiable claims, each linked to its source index. | AI/ML API (GPT-4o) |
| 4 | **Merkle** | Combine all source hashes into a binary merkle tree, producing one **merkle root** that commits to the entire evidence set. | Python `hashlib` |
| 5 | **Commit** | Write the merkle root on-chain via Solana's SPL Memo program — immutable, timestamped, publicly visible. | Solana devnet + `solders` |
| 6 | **Verify** | Anyone can resubmit the sources to `POST /verify`; if a single byte changed, the recomputed root won't match the on-chain root, and the exact tampered source is named. | Python `hashlib` + Solana RPC |

> **Why it's tamper-proof:** the merkle root is a fingerprint of every source. Change one character in one source, and its leaf hash changes, which changes the root — which no longer matches the immutable copy on Solana. Tampering is not just *detectable*; it's *provable*.

---

## 🏗️ Architecture

```
                              ┌───────────────────────────────────────┐
   "CrowdStrike"  ──────────► │            VeriTrace API               │
                              │             (FastAPI)                  │
                              └───────────────────────────────────────┘
                                               │
        ┌──────────────────────────────────────┼──────────────────────────────────────┐
        ▼                                       ▼                                       ▼
┌───────────────┐  1. COLLECT          ┌───────────────┐  3. EXTRACT          ┌───────────────┐
│  Bright Data  │ ───────────────────► │    AI/ML API  │ ───────────────────► │    Cognee     │
│ SERP+Unlocker │   live source pages  │    (GPT-4o)   │   factual claims     │ evidence graph│
└───────────────┘                      └───────────────┘                      └───────────────┘
        │ Source[]                              │ Claim[]                              ▲
        │ (url, content, ts)                    │ (text, source_hash, confidence)      │ queryable
        ▼                                       ▼                                      │
┌───────────────┐  2. HASH             ┌───────────────┐  4. MERKLE                    │
│   hashlib     │ ───────────────────► │  merkle tree  │ ───────► merkle_root ──────────┘
│  SHA-256      │   per-source hashes  │   (binary)    │
└───────────────┘                      └───────────────┘
                                               │ 5. COMMIT
                                               ▼
                                       ┌───────────────┐         6. VERIFY
                                       │ Solana devnet │ ◄───────────────────── POST /verify
                                       │  (SPL Memo)   │   recompute root, compare to chain
                                       └───────────────┘   → ✓ verified  /  ✗ TAMPERING DETECTED
                                               │
                                               ▼
                                    🔗 explorer.solana.com/tx/...
```

---

## 🧰 Tech Stack

| Tool | Role |
|------|------|
| **Bright Data — SERP API** | Searches Google for material intelligence signals about the target company. |
| **Bright Data — Web Unlocker** | Fetches the full content of each source page, bypassing bot protection. |
| **Python + FastAPI** | Backend API and the orchestration of the six-step pipeline. |
| **`hashlib` (SHA-256 + merkle)** | Fingerprints sources and builds the tamper-evident merkle tree. |
| **AI/ML API (GPT-4o)** | LLM that extracts specific, verifiable claims from source text. |
| **Cognee** | Builds a knowledge graph of companies → sources → claims → hashes for natural-language auditing. |
| **Solana (devnet) + SPL Memo** | Immutable, public, timestamped commitment of the merkle root — the trust anchor. |
| **`solders` / `solana-py`** | Builds, signs, and submits the on-chain memo transaction. |
| **React + Vite + Tailwind** | Single-page demo UI with the live tamper-detection flow. |

---

## 📸 Screenshots

> _Add demo screenshots/GIFs here._

| Investigation in progress | Verified report | Tampering detected |
|---|---|---|
| ![Investigating](docs/screenshots/investigate.png) | ![Report](docs/screenshots/report.png) | ![Tampered](docs/screenshots/tamper.png) |

<!-- Place images in docs/screenshots/  (investigate.png, report.png, tamper.png) -->

---

## 🚀 Setup & Run Locally

### Prerequisites
- Python 3.11+
- Node.js 18+
- API keys: [Bright Data](https://brightdata.com), [AI/ML API](https://aimlapi.com), and (optionally) a funded Solana **devnet** keypair.

### 1. Configure environment

```bash
cp .env.example .env     # then fill in your keys
```

| Variable | Required | Description |
|----------|:---:|-------------|
| `BRIGHT_DATA_API_KEY` | ✅ | Bright Data API token. |
| `BRIGHT_DATA_SERP_ZONE` | ✅ | Name of your Bright Data **SERP** zone. |
| `BRIGHT_DATA_UNLOCKER_ZONE` | ✅ | Name of your Bright Data **Web Unlocker** zone. |
| `AIML_API_KEY` | ✅ | AI/ML API key (claim extraction). |
| `AIML_MODEL` | ➖ | Extraction model (default `gpt-4o`). |
| `COGNEE_LLM_API_KEY` | ➖ | LLM key for the Cognee graph (can reuse `AIML_API_KEY`). |
| `SOLANA_RPC_URL` | ➖ | Defaults to `https://api.devnet.solana.com`. |
| `SOLANA_PRIVATE_KEY` | ➖ | Funded devnet signer (base58 or JSON byte array). If unset, an ephemeral key + airdrop is attempted. |

### 2. Run the backend

> Run **from the project root in package mode** (`backend.main:app`). The on-chain client lives in `backend/chain/` — deliberately *not* named `solana`, to avoid shadowing the installed `solana` library.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload      # http://localhost:8000
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

The backend has open CORS for local dev, so the frontend talks to `http://localhost:8000` directly (override with `VITE_API_BASE`).

### 4. Try the demo

Open **http://localhost:5173**, the company field is pre-filled with `CrowdStrike` — click **Investigate**, then:
1. Watch the staged pipeline and the verified report appear (sources + hashes, claims with confidence bars, merkle root, Solana explorer link).
2. Click **Edit** on a claim and change its text — this doctors the underlying source evidence.
3. Click **Verify Report Integrity** → the recomputed root no longer matches the chain and **TAMPERING DETECTED** fires, naming the altered source.
4. (Bonus) Ask the Cognee evidence graph a question in the query panel.

---

## 🔌 API

| Endpoint | Body | Returns |
|----------|------|---------|
| `POST /investigate` | `{ "company_name": "CrowdStrike" }` | Full `InvestigationReport` — sources, claims, merkle root + tree, Solana tx. |
| `POST /verify` | `{ "sources": [...], "merkle_root": "...", "solana_tx_signature": "..." }` | Validity verdict + which sources were tampered + on-chain check. |
| `POST /query` | `{ "question": "What evidence supports claims about outages?" }` | Natural-language answers from the Cognee evidence graph. |

```bash
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"company_name": "CrowdStrike"}'
```

---

## 📁 Project Layout

```
veritrace/
├── backend/
│   ├── main.py                      # FastAPI app + endpoints
│   ├── config.py                    # env / settings loader
│   ├── models.py                    # Pydantic models (Source, Claim, Report…)
│   ├── bright_data/collector.py     # Bright Data SERP + Web Unlocker
│   ├── hasher/merkle.py             # SHA-256 + merkle tree + verification
│   ├── intelligence/extractor.py    # AI/ML API claim extraction
│   ├── memory/evidence_graph.py     # Cognee integration
│   └── chain/committer.py           # Solana commitment + on-chain verify
├── frontend/                        # React + Vite + Tailwind demo
├── requirements.txt
├── .env.example
└── README.md
```

---

## 👥 Team

> _Add your team here._

| Name | Role | Links |
|------|------|-------|
| _Your Name_ | _Role_ | [GitHub](#) · [LinkedIn](#) |
| _Teammate_ | _Role_ | [GitHub](#) · [LinkedIn](#) |

---

<div align="center">

**Built for the Web Data UNLOCKED Hackathon by Bright Data** 🌐

_Bright Data × AI/ML API × Cognee × Solana_

</div>
