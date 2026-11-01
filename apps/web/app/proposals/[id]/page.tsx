"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchAPI, postAPI } from "@/lib/api";
import { tickerToSleeve, Universe } from "@/lib/viz";
import { EquityCompareChart, DrawdownChart, MetricCompare, AllocationBar } from "@/components/charts";
import SignMethodPicker, { useSignMethod, signWith } from "@/components/SignMethodPicker";

export default function ProposalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<any>(null);
  const [checked, setChecked] = useState({ rationale: false, risk: false, limits: false });
  const [timer, setTimer] = useState(60);
  const [signing, setSigning] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [universe, setUniverse] = useState<Universe | null>(null);
  const signMethod = useSignMethod();

  const load = () => fetchAPI(`/proposals/${id}`).then(setP).catch(() => {});
  useEffect(() => { load(); }, [id]);
  useEffect(() => { fetchAPI("/universe").then(setUniverse).catch(() => {}); }, []);

  useEffect(() => {
    if (timer > 0) { const t = setTimeout(() => setTimer(timer - 1), 1000); return () => clearTimeout(t); }
  }, [timer]);

  if (!p) return <p className="text-gray-400">Loading…</p>;

  const allChecked = checked.rationale && checked.risk && checked.limits;
  const canApprove = allChecked && timer === 0 && p.status === "PENDING_REVIEW" && !signing;

  async function signDecision(decision: "APPROVE" | "REJECT") {
    if (decision === "REJECT" && !rejectComment) { alert("Rejection requires a comment"); return; }
    setSigning(true);
    try {
      const { typed_data, nonce, passkey } = await fetchAPI(`/proposals/${id}/typed-data?decision=${decision}`);
      const signature = await signWith(signMethod.method, typed_data, passkey);
      const result = await postAPI(`/proposals/${id}/signatures`, { decision, signature, nonce, comment: rejectComment });
      alert(`${decision === "APPROVE" ? "Approved" : "Rejected"} — ${result.message}`);
      load();
    } catch (e: any) {
      alert(`Couldn't record your decision: ${e.message}`);
    } finally {
      setSigning(false);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold">{p.title}</h1>
          <p className="text-gray-400">{p.id} · {p.kind} · Confidence: {p.confidence}</p>
          <p className="text-sm text-gray-500">Expires: {p.expires_at}</p>
        </div>
        <span className={`px-3 py-1.5 rounded text-sm font-medium ${p.status === "PENDING_REVIEW" ? "bg-yellow-600" : p.status === "APPROVED" ? "bg-green-600" : p.status === "REJECTED" ? "bg-red-600" : "bg-gray-600"} text-white`}>{p.status}</span>
      </div>

      {p.kind === "hypothesis" && (
        <div className={`rounded-xl p-4 border text-sm ${p.risk_notes?.gate_passed ? "border-green-800 bg-green-950/40" : "border-yellow-800 bg-yellow-950/40"}`}>
          <p className="font-medium">
            {p.risk_notes?.gate_passed ? "✓ Beat the baseline on the out-of-sample test window" : "⚠ Did not beat the baseline on the out-of-sample test window"}
          </p>
          {p.risk_notes?.origin && <p className="text-gray-400 mt-1">💡 Human idea: {p.risk_notes.origin}</p>}
        </div>
      )}

      {/* Rationale */}
      <Section title="Why">
        <p className="text-gray-300">{p.rationale}</p>
        {p.evidence?.length > 0 && (
          <div className="mt-3">
            <p className="text-sm font-medium text-gray-400 mb-1">Evidence:</p>
            <ul className="space-y-1">
              {p.evidence.map((e: any, i: number) => (
                <li key={i}><a href={e.url} target="_blank" rel="noopener" className="text-blue-400 hover:underline text-sm">{e.quote || e.url}</a></li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* Config diff */}
      {p.config_diff && (
        <Section title="What Changes">
          <pre className="bg-gray-950 p-4 rounded text-sm overflow-x-auto">{JSON.stringify(p.config_diff, null, 2)}</pre>
        </Section>
      )}

      {/* Target weights */}
      {p.target_weights && (
        <Section title="Target Allocation">
          <AllocationBar weights={p.target_weights} sleeveOf={tickerToSleeve(universe)} />
        </Section>
      )}

      {/* Backtest comparison */}
      {p.baseline_metrics && (
        <Section title={p.candidate_metrics ? "Backtest: Baseline vs Candidate" : "Backtest"}>
          <div className="space-y-6">
            <div>
              <p className="text-sm text-gray-400 mb-2">Cumulative return</p>
              <EquityCompareChart baseline={p.baseline_curve} candidate={p.candidate_curve} />
            </div>
            {p.baseline_curve?.length > 0 && (
              <div>
                <p className="text-sm text-gray-400 mb-2">Drawdown from peak</p>
                <DrawdownChart baseline={p.baseline_curve} candidate={p.candidate_curve} />
              </div>
            )}
            <MetricCompare baseline={p.baseline_metrics} candidate={p.candidate_metrics} />
          </div>
          <p className="text-xs text-gray-500 mt-3">
            Variants tested: {p.variants_tested} · Baseline <span className="font-mono">{p.backtest_baseline_id}</span>
            {p.backtest_candidate_id && <> · Candidate <span className="font-mono">{p.backtest_candidate_id}</span></>}
          </p>
        </Section>
      )}

      {/* Risk notes */}
      {p.risk_notes && (
        <Section title="Risk Notes">
          <p className="text-gray-300 mb-3">{p.risk_notes.summary}</p>
          {p.risk_notes.what_could_go_wrong && (
            <div>
              <p className="text-sm font-medium text-red-400 mb-1">What could go wrong:</p>
              <ul className="list-disc list-inside text-sm text-gray-300">
                {p.risk_notes.what_could_go_wrong.map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </Section>
      )}

      {/* Existing signatures */}
      {p.signatures?.length > 0 && (
        <Section title="Signatures">
          {p.signatures.map((s: any, i: number) => (
            <div key={i} className="flex justify-between text-sm bg-gray-800 rounded p-2 mb-1">
              <span className={s.decision === "APPROVE" ? "text-green-400" : "text-red-400"}>{s.decision}</span>
              <span className="text-gray-400 font-mono">{s.approver?.slice(0, 10)}…</span>
              <span className="text-gray-500">{s.signed_at}</span>
            </div>
          ))}
        </Section>
      )}

      {/* Approve / Reject */}
      {p.status === "PENDING_REVIEW" && (
        <Section title="Approve or Reject">
          <div className="space-y-3">
            <Checklist label="I read the rationale and checked at least one source" checked={checked.rationale} onChange={() => setChecked({ ...checked, rationale: !checked.rationale })} />
            <Checklist label="I understand the main risk" checked={checked.risk} onChange={() => setChecked({ ...checked, risk: !checked.risk })} />
            <Checklist label="Changes are within the limits I'm comfortable with" checked={checked.limits} onChange={() => setChecked({ ...checked, limits: !checked.limits })} />
            <p className="text-sm text-gray-500">Review timer: {timer > 0 ? `${timer}s remaining` : "✓ Ready"}</p>
            <SignMethodPicker {...signMethod} />
            <div className="flex flex-wrap gap-3">
              <button disabled={!canApprove} onClick={() => signDecision("APPROVE")}
                className={`px-4 py-2 rounded font-medium ${canApprove ? "bg-green-600 hover:bg-green-700" : "bg-gray-700 cursor-not-allowed"} text-white`}>
                {signing ? "Confirming…" : "Approve"}
              </button>
              <input value={rejectComment} onChange={e => setRejectComment(e.target.value)} placeholder="Rejection reason…" className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm flex-1 min-w-[12rem]" />
              <button onClick={() => signDecision("REJECT")}
                className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded font-medium">Reject</button>
            </div>
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="bg-gray-900 rounded-lg p-6 border border-gray-800"><h2 className="text-lg font-semibold mb-4">{title}</h2>{children}</div>;
}

function Checklist({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={onChange} className="w-4 h-4" />
      <span className="text-sm">{label}</span>
    </label>
  );
}
