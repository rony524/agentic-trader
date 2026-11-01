"use client";
import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";
import { pct } from "@/lib/viz";
import { Card, StatTile, EquityCompareChart, DrawdownChart, MetricCompare } from "@/components/charts";

export default function BacktestsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAPI("/proposals").then(d => {
      const pids = (d.proposals || []).map((p: any) => p.id);
      return Promise.all(pids.map((id: string) => fetchAPI(`/proposals/${id}`)));
    }).then(proposals => {
      const bts = proposals.filter((p: any) => p.backtest_baseline_id).map((p: any) => ({
        id: p.backtest_baseline_id, proposal: p.id, title: p.title, created_at: p.created_at,
        baseline_metrics: p.baseline_metrics, candidate_metrics: p.candidate_metrics,
        baseline_curve: p.baseline_curve, candidate_curve: p.candidate_curve,
      }));
      setRuns(bts);
      if (bts.length) setSelectedId(bts[0].id);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const run = runs.find(r => r.id === selectedId);
  const m = run?.candidate_metrics ?? run?.baseline_metrics ?? {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Backtests</h1>
          <p className="text-sm text-gray-500">Each proposal is backed by a baseline backtest and, when the agent changes config, a candidate.</p>
        </div>
        {runs.length > 1 && (
          <select value={selectedId} onChange={e => setSelectedId(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm">
            {runs.map(r => <option key={r.id} value={r.id}>{r.created_at?.slice(0, 10)} · {r.title}</option>)}
          </select>
        )}
      </div>

      {loading ? <p className="text-gray-400">Loading…</p> : !run ? <p className="text-gray-400">No backtests yet.</p> : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatTile label="Sharpe" value={m.sharpe?.toFixed(2) ?? "—"} sub={m.test_sharpe !== undefined ? `out-of-sample ${m.test_sharpe.toFixed(2)}` : undefined} />
            <StatTile label="CAGR" value={m.cagr !== undefined ? pct(m.cagr) : "—"} sub={m.test_cagr !== undefined ? `out-of-sample ${pct(m.test_cagr)}` : undefined} />
            <StatTile label="Max drawdown" value={m.max_drawdown !== undefined ? pct(m.max_drawdown) : "—"} />
            <StatTile label="Volatility" value={m.volatility !== undefined ? pct(m.volatility) : "—"} sub={m.avg_turnover !== undefined ? `turnover ${pct(m.avg_turnover)}` : undefined} />
          </div>

          <Card title="Cumulative return" subtitle={run.candidate_curve?.length ? "Baseline vs candidate config" : "Baseline config"}
            action={<a href={`/proposals/${run.proposal}`} className="text-xs text-blue-400 hover:underline">View proposal →</a>}>
            <EquityCompareChart baseline={run.baseline_curve} candidate={run.candidate_curve} height={300} />
          </Card>

          <div className="grid lg:grid-cols-2 gap-6">
            <Card title="Drawdown" subtitle="Decline from running peak">
              <DrawdownChart baseline={run.baseline_curve} candidate={run.candidate_curve} height={220} />
            </Card>
            <Card title="Metrics" subtitle={<span className="font-mono">{run.id}</span>}>
              <MetricCompare baseline={run.baseline_metrics} candidate={run.candidate_metrics} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
