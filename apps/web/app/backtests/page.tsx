"use client";
import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";

export default function BacktestsPage() {
  const [baselines, setBaselines] = useState<any[]>([]);
  useEffect(() => {
    fetchAPI("/proposals").then(d => {
      const pids = (d.proposals || []).map((p: any) => p.id);
      Promise.all(pids.map((id: string) => fetchAPI(`/proposals/${id}`)))
        .then(proposals => {
          const bts = proposals.filter((p: any) => p.backtest_baseline_id).map((p: any) => ({
            id: p.backtest_baseline_id, kind: "baseline", metrics: p.baseline_metrics,
            curve: p.baseline_curve, proposal: p.id,
          }));
          setBaselines(bts);
        }).catch(() => {});
    }).catch(() => {});
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Backtests</h1>
      {baselines.length === 0 ? <p className="text-gray-400">No backtests yet.</p> : baselines.map(b => (
        <div key={b.id} className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <div className="flex justify-between items-center mb-3">
            <p className="font-mono text-sm">{b.id}</p>
            <span className="bg-gray-700 text-xs px-2 py-0.5 rounded">{b.kind}</span>
          </div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            {Object.entries(b.metrics || {}).map(([k, v]) => (
              <div key={k} className="bg-gray-800 rounded p-3">
                <p className="text-xs text-gray-400">{k}</p>
                <p className="text-lg font-bold">{typeof v === "number" ? v.toFixed(4) : String(v)}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
