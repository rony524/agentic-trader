"use client";
import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";
import IdeaPanel from "@/components/IdeaPanel";

const STATUSES = ["PENDING_REVIEW", "APPROVED", "EXECUTED", "REJECTED", "EXPIRED"];

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<any[]>([]);
  const [filter, setFilter] = useState<string>("ALL");

  const load = () => fetchAPI("/proposals").then(d => setProposals(d.proposals || [])).catch(() => {});
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("status");
    if (s) setFilter(s.toUpperCase());
    load();
  }, []);

  const counts = Object.fromEntries(STATUSES.map(s => [s, proposals.filter(p => p.status === s).length]));
  const shown = filter === "ALL" ? proposals : proposals.filter(p => p.status === filter);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Proposals</h1>
        <p className="text-sm text-gray-500">The agent drafts proposals with a backtest and risk notes. A human approves or rejects each one by signing it.</p>
      </div>

      <IdeaPanel onProposed={load} />

      <div className="flex flex-wrap gap-2">
        <FilterChip label="All" count={proposals.length} active={filter === "ALL"} onClick={() => setFilter("ALL")} />
        {STATUSES.map(s => (
          <FilterChip key={s} label={s.replace("_", " ").toLowerCase()} count={counts[s]} active={filter === s} onClick={() => setFilter(s)} />
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="text-gray-400 text-sm">{proposals.length === 0 ? "No proposals yet." : "No proposals with this status."}</p>
      ) : (
        <div className="space-y-3">
          {shown.map(p => (
            <a key={p.id} href={`/proposals/${p.id}`} className="block bg-gray-900 rounded-xl p-4 border border-gray-800 hover:border-gray-600 transition-colors">
              <div className="flex justify-between items-start gap-4">
                <div>
                  <p className="font-medium">{p.title}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {p.kind === "hypothesis" ? "💡 from a human idea" : p.kind} · confidence {p.confidence} · created {p.created_at?.slice(0, 16).replace("T", " ")}
                  </p>
                </div>
                <StatusBadge status={p.status} />
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-3 py-1 rounded-full text-xs border capitalize transition-colors ${active ? "bg-gray-100 text-gray-900 border-gray-100" : "border-gray-700 text-gray-300 hover:border-gray-500"}`}>
      {label} <span className={active ? "text-gray-600" : "text-gray-500"}>{count}</span>
    </button>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    PENDING_REVIEW: "bg-yellow-600",
    APPROVED: "bg-green-600",
    REJECTED: "bg-red-600",
    EXECUTED: "bg-blue-600",
    EXPIRED: "bg-gray-600",
  };
  return <span className={`${colors[status] || "bg-gray-600"} text-white text-xs px-2 py-1 rounded font-medium whitespace-nowrap`}>{status}</span>;
}
