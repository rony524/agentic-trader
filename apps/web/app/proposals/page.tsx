"use client";
import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<any[]>([]);
  useEffect(() => { fetchAPI("/proposals").then(d => setProposals(d.proposals || [])).catch(() => {}); }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Proposals</h1>
      {proposals.length === 0 ? (
        <p className="text-gray-400">No proposals yet.</p>
      ) : (
        proposals.map(p => (
          <a key={p.id} href={`/proposals/${p.id}`} className="block bg-gray-900 rounded-lg p-4 border border-gray-800 hover:border-gray-600">
            <div className="flex justify-between items-start">
              <div>
                <p className="font-medium">{p.title}</p>
                <p className="text-sm text-gray-400">{p.id} · {p.kind}</p>
              </div>
              <StatusBadge status={p.status} />
            </div>
          </a>
        ))
      )}
    </div>
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
  return <span className={`${colors[status] || "bg-gray-600"} text-white text-xs px-2 py-1 rounded font-medium`}>{status}</span>;
}
