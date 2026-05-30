import { useMemo, useState } from "react";

// Backend (CORS is open on the FastAPI side). Override with VITE_API_BASE if needed.
const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const PIPELINE_STEPS = [
  "Collecting sources via Bright Data…",
  "Hashing and fingerprinting sources…",
  "Extracting claims with AI…",
  "Committing merkle root to Solana…",
  "Storing evidence graph in Cognee…",
];

const SUGGESTED_QUERIES = [
  "What are the most serious claims?",
  "Which sources mention security incidents?",
  "What evidence supports the outage claim?",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function trunc(h, head = 10, tail = 8) {
  if (!h) return "—";
  if (h.length <= head + tail + 1) return h;
  return `${h.slice(0, head)}…${h.slice(-tail)}`;
}

// Matches backend hash_source: SHA-256(url + raw_content + timestamp).
async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function confColor(c) {
  if (c > 0.8) return "#22c55e";
  if (c > 0.5) return "#eab308";
  return "#ef4444";
}

export default function App() {
  const [company, setCompany] = useState("CrowdStrike");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");

  const [report, setReport] = useState(null);
  // Editable working copy of sources used for the tamper demo.
  const [workingSources, setWorkingSources] = useState([]);
  // claimIndex -> edited text
  const [claimDrafts, setClaimDrafts] = useState({});
  const [editingIdx, setEditingIdx] = useState(null);
  const [editText, setEditText] = useState("");
  const [tamperedSources, setTamperedSources] = useState({}); // sourceIdx -> true

  const [verifyResult, setVerifyResult] = useState(null);
  const [recomputed, setRecomputed] = useState({}); // sourceIdx -> new hash
  const [verifying, setVerifying] = useState(false);

  const [question, setQuestion] = useState("");
  const [queryResults, setQueryResults] = useState(null);
  const [querying, setQuerying] = useState(false);

  const anyTampered = Object.keys(tamperedSources).length > 0;

  // ── Investigate ──────────────────────────────────────────
  async function runInvestigation() {
    if (!company.trim() || loading) return;
    setLoading(true);
    setStep(0);
    setError("");
    setReport(null);
    setVerifyResult(null);
    setClaimDrafts({});
    setTamperedSources({});
    setRecomputed({});
    setQueryResults(null);

    const timer = setInterval(
      () => setStep((s) => Math.min(s + 1, PIPELINE_STEPS.length - 1)),
      1700
    );
    const started = Date.now();
    try {
      const res = await fetch(`${API}/investigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_name: company.trim() }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();

      // Let the staged pipeline animation breathe even if the API is fast.
      const minMs = PIPELINE_STEPS.length * 1500;
      const elapsed = Date.now() - started;
      if (elapsed < minMs) await sleep(minMs - elapsed);

      setReport(data);
      setWorkingSources(
        (data.sources || []).map((s) => ({
          url: s.url,
          raw_content: s.raw_content,
          timestamp: s.timestamp,
          sha256_hash: s.sha256_hash,
        }))
      );
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  }

  // ── Claim editing (doctors the underlying source evidence) ───
  function startEdit(claimIdx, currentText) {
    setEditingIdx(claimIdx);
    setEditText(currentText);
  }

  function saveEdit(claim, claimIdx) {
    const original = claim.text;
    const next = editText;
    const srcIdx = claim.source_index;

    setClaimDrafts((d) => ({ ...d, [claimIdx]: next }));

    setWorkingSources((srcs) => {
      const copy = srcs.slice();
      if (copy[srcIdx]) {
        const changed = next.trim() !== original.trim();
        copy[srcIdx] = {
          ...copy[srcIdx],
          // Doctoring the claim means doctoring its evidence content.
          raw_content: changed
            ? `[ALTERED EVIDENCE] ${next}`
            : (report.sources[srcIdx]?.raw_content ?? copy[srcIdx].raw_content),
        };
      }
      return copy;
    });

    setTamperedSources((t) => {
      const copy = { ...t };
      if (next.trim() !== original.trim()) copy[srcIdx] = true;
      else delete copy[srcIdx];
      return copy;
    });

    setVerifyResult(null); // editing invalidates a previous verdict
    setEditingIdx(null);
  }

  // ── Verify integrity ─────────────────────────────────────
  async function verifyIntegrity() {
    if (!report || verifying) return;
    setVerifying(true);
    setError("");
    try {
      const payload = {
        merkle_root: report.merkle_root,
        sources: workingSources.map((s) => ({
          url: s.url,
          raw_content: s.raw_content,
          timestamp: s.timestamp,
          sha256_hash: s.sha256_hash,
        })),
      };
      if (report.solana_tx?.tx_signature) {
        payload.solana_tx_signature = report.solana_tx.tx_signature;
      }
      const res = await fetch(`${API}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();

      // Recompute the new fingerprints client-side for a dramatic before/after.
      const newHashes = {};
      for (const idx of data.mismatched_sources || []) {
        const s = workingSources[idx];
        if (s) newHashes[idx] = await sha256Hex(`${s.url}${s.raw_content}${s.timestamp}`);
      }
      setRecomputed(newHashes);
      setVerifyResult(data);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setVerifying(false);
    }
  }

  // ── Evidence query ───────────────────────────────────────
  async function runQuery(q) {
    const text = (q ?? question).trim();
    if (!text || querying) return;
    setQuestion(text);
    setQuerying(true);
    setQueryResults(null);
    try {
      const res = await fetch(`${API}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      setQueryResults(data.results || []);
    } catch (e) {
      setQueryResults([{ result: `Query failed: ${e.message || e}` }]);
    } finally {
      setQuerying(false);
    }
  }

  const claims = report?.claims || [];
  const claimsBySource = useMemo(() => {
    const m = {};
    claims.forEach((c) => {
      (m[c.source_index] ||= []).push(c);
    });
    return m;
  }, [claims]);

  return (
    <div className="min-h-screen px-4 py-8 sm:px-8 max-w-5xl mx-auto">
      {/* Header */}
      <header className="mb-8">
        <h1 className="text-4xl font-extrabold tracking-tight text-white">
          Veri<span className="text-emerald-400">Trace</span>
        </h1>
        <p className="text-lg text-gray-300 mt-1">Verifiable AI Intelligence</p>
        <p className="text-sm text-gray-500 mt-1">
          Any AI can investigate. Only VeriTrace proves what it finds.
        </p>
      </header>

      {/* Investigation panel */}
      <section className="bg-[#111726] border border-white/10 rounded-2xl p-5 shadow-xl">
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            className="flex-1 bg-[#0b0f1a] border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-emerald-400/60"
            placeholder="Enter company name to investigate"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runInvestigation()}
            disabled={loading}
          />
          <button
            onClick={runInvestigation}
            disabled={loading}
            className="bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-[#0b0f1a] font-semibold rounded-xl px-6 py-3 transition-colors"
          >
            {loading ? "Investigating…" : "Investigate"}
          </button>
        </div>

        {loading && (
          <div className="mt-5 space-y-2">
            {PIPELINE_STEPS.map((label, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 text-sm transition-opacity ${
                  i <= step ? "opacity-100" : "opacity-30"
                }`}
              >
                {i < step ? (
                  <span className="text-emerald-400">✓</span>
                ) : i === step ? (
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-emerald-400 border-t-transparent spinner inline-block" />
                ) : (
                  <span className="w-3.5 h-3.5 rounded-full border border-gray-600 inline-block" />
                )}
                <span className={i === step ? "text-emerald-300" : "text-gray-400"}>
                  {label}
                </span>
              </div>
            ))}
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-400 mono">⚠ {error}</p>
        )}
      </section>

      {/* Report */}
      {report && (
        <div className="animate-fade-in">
          {/* Top bar */}
          <section className="mt-6 bg-[#111726] border border-white/10 rounded-2xl p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-2xl font-bold text-white">{report.target_company}</div>
                <div className="text-xs text-gray-500 mono mt-1">ID: {report.id}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {new Date(report.created_at).toLocaleString()}
                </div>
              </div>
              <div className="text-right">
                {report.solana_tx ? (
                  <span className="inline-block bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 rounded-full px-3 py-1 text-sm font-semibold">
                    ✓ Verified On-Chain
                  </span>
                ) : (
                  <span className="inline-block bg-amber-500/15 text-amber-300 border border-amber-500/40 rounded-full px-3 py-1 text-sm font-semibold">
                    Merkle proof ready · not committed
                  </span>
                )}
                {report.solana_tx?.explorer_url && (
                  <div className="mt-2">
                    <a
                      href={report.solana_tx.explorer_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-emerald-400 hover:underline"
                    >
                      View on Solana Explorer ↗
                    </a>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-white/10">
              <div className="text-xs text-gray-500 uppercase tracking-wide">Merkle Root</div>
              <div className="mono text-emerald-300 break-all text-sm mt-1">
                {report.merkle_root || "—"}
              </div>
            </div>
          </section>

          {/* Sources */}
          <section className="mt-6">
            <h2 className="text-lg font-semibold text-white mb-3">
              Sources <span className="text-gray-500 text-sm">({report.sources.length})</span>
            </h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {report.sources.map((s, i) => {
                const tampered = tamperedSources[i];
                return (
                  <div
                    key={i}
                    className={`rounded-xl p-4 border ${
                      tampered
                        ? "bg-red-500/10 border-red-500/50"
                        : "bg-[#141b2d] border-white/10"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">Source [{i}]</span>
                      {tampered && (
                        <span className="text-xs text-red-400 font-semibold">● altered</span>
                      )}
                    </div>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-sm text-emerald-400 hover:underline break-all mt-1"
                    >
                      {s.url}
                    </a>
                    <div className="mono text-xs text-gray-400 mt-2 break-all">
                      {trunc(s.sha256_hash, 16, 12)}
                    </div>
                    <div className="text-xs text-gray-600 mt-1">
                      {new Date(s.timestamp).toLocaleString()}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Claims */}
          <section className="mt-6">
            <h2 className="text-lg font-semibold text-white mb-3">
              Claims <span className="text-gray-500 text-sm">({claims.length})</span>
            </h2>
            {claims.length === 0 && (
              <p className="text-sm text-gray-500">
                No claims extracted (set an AI/ML key to enable extraction).
              </p>
            )}
            <div className="space-y-3">
              {claims.map((c, i) => {
                const text = claimDrafts[i] ?? c.text;
                const isTampered = tamperedSources[c.source_index];
                const editing = editingIdx === i;
                return (
                  <div
                    key={i}
                    className={`rounded-xl p-4 border ${
                      isTampered
                        ? "bg-red-500/10 border-red-500/50"
                        : "bg-[#141b2d] border-white/10"
                    }`}
                  >
                    {editing ? (
                      <div>
                        <textarea
                          className="w-full bg-[#0b0f1a] border border-white/15 rounded-lg p-2 text-sm text-white"
                          rows={2}
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                        />
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={() => saveEdit(c, i)}
                            className="bg-amber-500 hover:bg-amber-400 text-[#0b0f1a] text-sm font-semibold rounded-lg px-3 py-1"
                          >
                            Save tampered claim
                          </button>
                          <button
                            onClick={() => setEditingIdx(null)}
                            className="text-sm text-gray-400 hover:text-white px-3 py-1"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-3">
                        <p className={`text-sm ${isTampered ? "text-red-300" : "text-gray-100"}`}>
                          {isTampered && "✎ "}
                          {text}
                        </p>
                        <button
                          onClick={() => startEdit(i, text)}
                          className="shrink-0 text-xs text-gray-400 hover:text-amber-300 border border-white/10 rounded-lg px-2 py-1"
                        >
                          Edit
                        </button>
                      </div>
                    )}

                    {/* Confidence bar */}
                    <div className="mt-3">
                      <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.round((c.confidence || 0) * 100)}%`,
                            backgroundColor: confColor(c.confidence || 0),
                          }}
                        />
                      </div>
                      <div className="flex justify-between mt-1">
                        <span className="text-[11px] text-gray-500">
                          confidence {(c.confidence ?? 0).toFixed(2)}
                        </span>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-emerald-400 hover:underline break-all"
                      >
                        Source: {c.source_url || "—"}
                      </a>
                      <span className="text-xs text-gray-500 mono break-all">
                        Hash: {trunc(c.source_hash, 12, 10)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Tamper detection */}
          {anyTampered && (
            <section className="mt-8">
              <button
                onClick={verifyIntegrity}
                disabled={verifying}
                className="w-full bg-white text-[#0b0f1a] hover:bg-gray-200 disabled:opacity-60 font-bold text-lg rounded-2xl py-4 transition-colors"
              >
                {verifying ? "Verifying against merkle root…" : "🔒 Verify Report Integrity"}
              </button>

              {verifyResult && (
                <div className="mt-5">
                  {verifyResult.valid ? (
                    <div className="animate-fade-in rounded-2xl border border-emerald-500/50 bg-emerald-500/10 p-6 text-center">
                      <div className="text-5xl">✓</div>
                      <div className="text-xl font-bold text-emerald-300 mt-2">
                        Report integrity verified — no tampering detected
                      </div>
                    </div>
                  ) : (
                    <div className="animate-shake animate-danger-glow rounded-2xl border-2 border-red-500 bg-red-600/20 p-6">
                      <div className="text-center">
                        <div className="text-6xl">✗</div>
                        <div className="text-3xl font-extrabold text-red-400 mt-2 tracking-wide">
                          TAMPERING DETECTED
                        </div>
                        <p className="text-red-200/80 mt-2 text-sm">
                          The recomputed merkle root does not match the on-chain commitment.
                        </p>
                      </div>

                      <div className="mt-5 grid gap-3">
                        {(verifyResult.mismatched_sources || []).map((idx) => (
                          <div
                            key={idx}
                            className="rounded-xl bg-black/30 border border-red-500/40 p-4"
                          >
                            <div className="text-sm font-semibold text-red-300">
                              Source [{idx}] — {workingSources[idx]?.url}
                            </div>
                            {(claimsBySource[idx] || []).map((c, k) => (
                              <div key={k} className="text-xs text-red-200/80 mt-1">
                                affected claim: “{claimDrafts[claims.indexOf(c)] ?? c.text}”
                              </div>
                            ))}
                            <div className="mt-2 mono text-xs break-all">
                              <div className="text-gray-400">
                                committed: <span className="text-emerald-300">{trunc(report.sources[idx]?.sha256_hash, 18, 14)}</span>
                              </div>
                              <div className="text-gray-400">
                                recomputed: <span className="text-red-400">{trunc(recomputed[idx], 18, 14)}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="mt-4 mono text-xs break-all text-center text-red-200/70">
                        expected root {trunc(verifyResult.expected_root, 14, 10)} ≠ computed{" "}
                        {trunc(verifyResult.computed_root, 14, 10)}
                      </div>

                      {verifyResult.on_chain_verification && (
                        <div className="mt-3 text-center text-xs text-red-200/70">
                          on-chain check:{" "}
                          {verifyResult.on_chain_verification.on_chain_verified
                            ? "root present on-chain"
                            : "does not match on-chain record"}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* Evidence query */}
          <section className="mt-10 bg-[#111726] border border-white/10 rounded-2xl p-5">
            <h2 className="text-lg font-semibold text-white">Ask the Evidence Graph</h2>
            <p className="text-xs text-gray-500 mb-3">Powered by Cognee</p>
            <div className="flex flex-col sm:flex-row gap-3">
              <input
                className="flex-1 bg-[#0b0f1a] border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-emerald-400/60"
                placeholder="Ask a question about the evidence…"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runQuery()}
              />
              <button
                onClick={() => runQuery()}
                disabled={querying}
                className="bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-[#0b0f1a] font-semibold rounded-xl px-6 py-2.5"
              >
                {querying ? "Querying…" : "Query"}
              </button>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              {SUGGESTED_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => runQuery(q)}
                  className="text-xs text-gray-300 bg-white/5 hover:bg-white/10 border border-white/10 rounded-full px-3 py-1"
                >
                  {q}
                </button>
              ))}
            </div>
            {queryResults && (
              <div className="mt-4 space-y-2">
                {queryResults.length === 0 ? (
                  <p className="text-sm text-gray-500">
                    No results (graph empty or Cognee not configured).
                  </p>
                ) : (
                  queryResults.map((r, i) => (
                    <div
                      key={i}
                      className="rounded-xl bg-[#141b2d] border border-white/10 p-3 text-sm text-gray-200 whitespace-pre-wrap"
                    >
                      {r.result}
                    </div>
                  ))
                )}
              </div>
            )}
          </section>
        </div>
      )}

      <footer className="mt-12 text-center text-xs text-gray-600">
        VeriTrace · Bright Data × AI/ML API × Cognee × Solana devnet
      </footer>
    </div>
  );
}
