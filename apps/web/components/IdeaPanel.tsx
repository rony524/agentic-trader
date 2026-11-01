"use client";
import { useEffect, useState } from "react";
import { fetchAPI, postAPI } from "@/lib/api";
import SignMethodPicker, { useSignMethod, signWith } from "@/components/SignMethodPicker";

const EXAMPLES = [
  "Reduce Power & grid — utilities have run far ahead of earnings.",
  "Overweight Memory & compute: HBM supply is sold out through next year.",
  "Hold fewer names (top 6) so the best signals get more weight.",
];
const MIN_CHARS = 15, MAX_CHARS = 2000;

const IDEA_STATUS: Record<string, { label: string; cls: string }> = {
  QUEUED: { label: "Queued", cls: "bg-gray-700" },
  PROCESSING: { label: "Backtesting…", cls: "bg-blue-700 animate-pulse" },
  PROPOSED: { label: "Proposal drafted", cls: "bg-green-700" },
  NO_PROPOSAL: { label: "Not testable", cls: "bg-yellow-700" },
  FAILED: { label: "Failed", cls: "bg-red-700" },
};

export default function IdeaPanel({ onProposed }: { onProposed?: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [ideas, setIdeas] = useState<any[]>([]);
  const signMethod = useSignMethod();

  const load = () => fetchAPI("/ideas?limit=10").then(d => setIdeas(d.ideas || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  // poll while the agent is working on something, and refresh proposals when a draft lands
  const busy = ideas.some(i => i.status === "QUEUED" || i.status === "PROCESSING");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(async () => {
      const before = ideas.filter(i => i.status === "PROPOSED").length;
      const d = await fetchAPI("/ideas?limit=10").catch(() => null);
      if (!d) return;
      setIdeas(d.ideas || []);
      if ((d.ideas || []).filter((i: any) => i.status === "PROPOSED").length > before) onProposed?.();
    }, 4000);
    return () => clearInterval(t);
  }, [busy, ideas]);

  const len = text.trim().length;
  const canSubmit = len >= MIN_CHARS && len <= MAX_CHARS && !submitting;

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      const { typed_data, issued_at, passkey } = await postAPI("/ideas/typed-data", { text, evidence_url: url });
      const signature = await signWith(signMethod.method, typed_data, passkey);
      await postAPI("/ideas", { text, evidence_url: url, issued_at, signature });
      setText("");
      setUrl("");
      load();
    } catch (e: any) {
      setError(e.message.replace(/^API error \d+: /, "").replace(/^\{"detail":"(.*)"\}$/, "$1"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between p-4 text-left">
        <div>
          <p className="font-semibold">💡 Suggest an idea</p>
          <p className="text-xs text-gray-500 mt-0.5">The agent turns it into a backtested proposal. It still needs a signed approval like any other.</p>
        </div>
        <span className="text-gray-500 text-sm">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-800 pt-4">
          <ol className="text-xs text-gray-400 grid sm:grid-cols-4 gap-2">
            <li className="bg-gray-800/60 rounded-lg p-2"><b className="text-gray-200">1.</b> Describe a hypothesis</li>
            <li className="bg-gray-800/60 rounded-lg p-2"><b className="text-gray-200">2.</b> Confirm it with your approver passkey</li>
            <li className="bg-gray-800/60 rounded-lg p-2"><b className="text-gray-200">3.</b> Agent maps it to a change & backtests</li>
            <li className="bg-gray-800/60 rounded-lg p-2"><b className="text-gray-200">4.</b> A proposal appears for review</li>
          </ol>

          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map(ex => (
              <button key={ex} onClick={() => setText(ex)}
                className="text-xs border border-gray-700 hover:border-gray-500 rounded-full px-3 py-1 text-gray-300">{ex}</button>
            ))}
          </div>

          <div>
            <textarea value={text} onChange={e => setText(e.target.value)} rows={3}
              placeholder="What should the strategy do differently, and why? Mention a sleeve (e.g. Power & grid) and a direction."
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-500" />
            <p className={`text-xs text-right ${len > MAX_CHARS ? "text-red-400" : "text-gray-500"}`}>{len} / {MAX_CHARS}</p>
          </div>
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="Supporting source URL (optional)"
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-500" />

          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <SignMethodPicker {...signMethod} />
              <p className="text-xs text-gray-500">Only <a href="/approvers" className="text-blue-400 hover:underline">approvers</a> can submit. One idea at a time.</p>
            </div>
            <button disabled={!canSubmit} onClick={submit}
              className={`px-4 py-2 rounded-lg text-sm font-medium text-white ${canSubmit ? "bg-blue-600 hover:bg-blue-700" : "bg-gray-700 cursor-not-allowed"}`}>
              {submitting ? "Confirming…" : "Submit idea"}
            </button>
          </div>
        </div>
      )}

      {ideas.length > 0 && (
        <div className="border-t border-gray-800 divide-y divide-gray-800">
          {ideas.map(i => {
            const st = IDEA_STATUS[i.status] ?? { label: i.status, cls: "bg-gray-700" };
            return (
              <div key={i.id} className="px-4 py-3 flex items-start justify-between gap-4 text-sm">
                <div className="min-w-0">
                  <p className="text-gray-200 truncate">{i.text}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {i.submitted_by?.slice(0, 8)}… · {i.created_at?.slice(0, 16).replace("T", " ")}
                    {i.note && <> · {i.note}</>}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {i.proposal_id && <a href={`/proposals/${i.proposal_id}`} className="text-xs text-blue-400 hover:underline">Review →</a>}
                  <span className={`${st.cls} text-white text-xs px-2 py-0.5 rounded`}>{st.label}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
