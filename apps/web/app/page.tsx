"use client";
import { useEffect, useMemo, useState } from "react";
import { fetchAPI } from "@/lib/api";
import { tickerToSleeve, sleeveColor, Universe } from "@/lib/viz";
import { Card, StatTile, SignalRankChart, SleeveStrengthChart, EquityAreaChart } from "@/components/charts";

export default function PulsePage() {
  const [digest, setDigest] = useState<any>(null);
  const [signals, setSignals] = useState<any[]>([]);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [universe, setUniverse] = useState<Universe | null>(null);
  const [proposals, setProposals] = useState<any[]>([]);
  const [error, setError] = useState<string>("");
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    fetchAPI("/digest/latest").then(setDigest).catch(e => setError(e.message));
    fetchAPI("/signals").then(d => setSignals(d.signals || [])).catch(() => {});
    fetchAPI("/portfolio").then(setPortfolio).catch(() => {});
    fetchAPI("/status").then(setStatus).catch(() => {});
    fetchAPI("/universe").then(setUniverse).catch(() => {});
    fetchAPI("/proposals").then(d => setProposals(d.proposals || [])).catch(() => {});
  }, []);

  const sleeveOf = useMemo(() => tickerToSleeve(universe), [universe]);
  const snapshots = useMemo(() => [...(portfolio?.snapshots || [])].reverse(), [portfolio]);
  const pending = proposals.filter(p => p.status === "PENDING_REVIEW").length;
  const selected = signals.filter(s => s.selected).length;
  const acct = portfolio?.account;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Market Pulse</h1>
          <p className="text-sm text-gray-500">{digest?.as_of ? `Digest as of ${digest.as_of}` : "Chips · Energy · Supply chain"}</p>
        </div>
        {status && (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <StatusDot fresh={status.freshness?.prices ?? true} label="Prices" />
            <StatusDot fresh={status.freshness?.news ?? true} label="News" />
            <StatusDot fresh={status.freshness?.fred ?? true} label="Macro" />
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${status.trading_frozen ? "bg-red-600" : "bg-green-700"}`}>
              {status.trading_frozen ? "TRADING FROZEN" : "TRADING ACTIVE"}
            </span>
          </div>
        )}
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="Paper equity" value={`$${(acct?.equity ?? 100000).toLocaleString()}`}
          sub={acct ? `${acct.status} account` : "loading…"} />
        <StatTile label="Cash" value={`$${(acct?.cash ?? 100000).toLocaleString()}`}
          sub={`${acct?.positions?.length || 0} open positions`} />
        <StatTile label="Tickers selected" value={`${selected} / ${signals.length}`} sub="by composite signal rank" />
        <a href="/proposals?status=PENDING_REVIEW" className="block hover:opacity-90">
          <StatTile label="Awaiting review" value={pending} sub={pending ? "Open the review queue →" : "No proposals pending"} />
        </a>
      </div>

      {/* Charts */}
      <div className="grid lg:grid-cols-5 gap-6">
        <Card title="Signal ranking" subtitle="Composite score per ticker, colored by sleeve" className="lg:col-span-3">
          <SignalRankChart signals={signals} sleeveOf={sleeveOf} />
        </Card>
        <div className="lg:col-span-2 space-y-6">
          <Card title="Sleeve strength" subtitle="Average composite score by sleeve">
            <SleeveStrengthChart signals={signals} sleeveOf={sleeveOf} />
          </Card>
          <Card title="Paper equity" subtitle="Daily portfolio snapshots (last 30)">
            <EquityAreaChart data={snapshots} />
          </Card>
        </div>
      </div>

      {/* Digest */}
      <Card title="Today's digest" subtitle={digest?.as_of}>
        {error ? (
          <p className="text-gray-400 text-sm">{error}</p>
        ) : digest ? (
          <div className="grid md:grid-cols-3 gap-5">
            <DigestSection title="💻 Chips" content={digest.chips_section} />
            <DigestSection title="⚡ Energy" content={digest.energy_section} />
            <DigestSection title="🚢 Supply Chain" content={digest.supply_section} />
          </div>
        ) : (
          <p className="text-gray-400 text-sm">No digest yet. Run the pipeline.</p>
        )}
      </Card>

      {/* Signals table (the table view behind the charts) */}
      <Card title={`Signal table (${signals.length} tickers)`}
        action={signals.length > 0 && (
          <button onClick={() => setShowTable(!showTable)} className="text-xs text-blue-400 hover:underline">
            {showTable ? "Hide" : "Show"} table
          </button>
        )}>
        {signals.length === 0 ? (
          <p className="text-gray-400 text-sm">No signals computed yet.</p>
        ) : showTable && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="text-left py-2 font-normal">Ticker</th>
                  <th className="text-left py-2 font-normal">Sleeve</th>
                  <th className="text-right py-2 font-normal">Momentum</th>
                  <th className="text-right py-2 font-normal">News</th>
                  <th className="text-right py-2 font-normal">Shock</th>
                  <th className="text-right py-2 font-normal">Composite</th>
                  <th className="text-right py-2 font-normal">Rank</th>
                  <th className="text-center py-2 font-normal">Selected</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s: any) => (
                  <tr key={s.ticker} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-1.5 font-medium">{s.ticker}</td>
                    <td className="py-1.5 text-gray-400">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-sm" style={{ background: sleeveColor(sleeveOf[s.ticker]) }} />
                        {sleeveOf[s.ticker] ?? "—"}
                      </span>
                    </td>
                    <td className="text-right">{s.s1_momentum.toFixed(3)}</td>
                    <td className="text-right">{s.s2_news.toFixed(3)}</td>
                    <td className="text-right">{s.s3_shock.toFixed(3)}</td>
                    <td className="text-right font-medium">{s.composite.toFixed(3)}</td>
                    <td className="text-right text-gray-400">#{s.rank}</td>
                    <td className="text-center">{s.selected ? "✅" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// The digest arrives as markdown bullets "- [Headline - Publisher](url)"; plain bullets have no link.
function parseDigest(md: string): { headline: string; source: string; url: string }[] {
  return (md || "").split("\n").map(line => line.replace(/^- /, "").trim()).filter(Boolean).map(line => {
    const m = line.match(/^\[(.+)\]\((.+)\)$/);
    const text = m ? m[1] : line;
    const cut = text.lastIndexOf(" - ");
    return cut > 0
      ? { headline: text.slice(0, cut), source: text.slice(cut + 3), url: m ? m[2] : "" }
      : { headline: text, source: "", url: m ? m[2] : "" };
  });
}

function DigestSection({ title, content }: { title: string; content: string }) {
  const stories = parseDigest(content).filter(s => s.url);
  return (
    <div className="space-y-2.5">
      <div className="flex items-baseline justify-between">
        <h3 className="font-medium text-gray-200">{title}</h3>
        {stories.length > 0 && <span className="text-xs text-gray-500">{stories.length} {stories.length === 1 ? "story" : "stories"}</span>}
      </div>
      {stories.length === 0 ? (
        <p className="text-sm text-gray-500 bg-gray-950/50 border border-gray-800 rounded-lg p-3">No major developments today.</p>
      ) : stories.map((s, i) => (
        <a key={i} href={s.url} target="_blank" rel="noopener noreferrer"
          className="group block bg-gray-950/50 border border-gray-800 rounded-lg p-3 hover:border-gray-600 hover:bg-gray-800/40 transition-colors">
          <p className="text-sm text-gray-200 leading-snug line-clamp-3 group-hover:text-white">{s.headline}</p>
          <p className="mt-2 flex items-center justify-between gap-2 text-xs text-gray-500">
            <span className="truncate">{s.source || "Source"}</span>
            <span className="shrink-0 group-hover:text-blue-400">↗</span>
          </p>
        </a>
      ))}
    </div>
  );
}

function StatusDot({ fresh, label }: { fresh: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full ${fresh ? "bg-green-400" : "bg-red-400"}`} />
      <span className="text-gray-400">{label}</span>
    </span>
  );
}
