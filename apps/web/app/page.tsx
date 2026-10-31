"use client";
import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";

const SLEEVE_COLORS: Record<string, string> = {
  "Memory & compute": "#f59e0b",
  "Semi equipment": "#8b5cf6",
  "Hyperscalers": "#3b82f6",
  "Power & grid": "#10b981",
  "Energy inputs": "#ef4444",
  "Materials / logistics": "#06b6d4",
  "Cash proxy": "#6b7280",
};

export default function PulsePage() {
  const [digest, setDigest] = useState<any>(null);
  const [signals, setSignals] = useState<any[]>([]);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    fetchAPI("/digest/latest").then(setDigest).catch(e => setError(e.message));
    fetchAPI("/signals").then(d => setSignals(d.signals || [])).catch(() => {});
    fetchAPI("/portfolio").then(setPortfolio).catch(() => {});
    fetchAPI("/status").then(setStatus).catch(() => {});
  }, []);

  return (
    <div className="space-y-8">
      {/* Status bar */}
      {status && (
        <div className="flex gap-4 text-sm">
          <StatusDot fresh={true} label="Prices" />
          <StatusDot fresh={status.freshness?.news ?? true} label="News" />
          <StatusDot fresh={status.freshness?.fred ?? true} label="Macro" />
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${status.trading_frozen ? "bg-red-600" : "bg-green-600"}`}>
            {status.trading_frozen ? "TRADING FROZEN" : "TRADING ACTIVE"}
          </span>
        </div>
      )}

      {/* Portfolio snapshot */}
      {portfolio && (
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h2 className="text-lg font-semibold mb-4">Paper Portfolio</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-gray-400 text-sm">Equity</p>
              <p className="text-2xl font-bold">${portfolio.account?.equity?.toLocaleString() || "100,000"}</p>
            </div>
            <div>
              <p className="text-gray-400 text-sm">Cash</p>
              <p className="text-2xl font-bold">${portfolio.account?.cash?.toLocaleString() || "100,000"}</p>
            </div>
            <div>
              <p className="text-gray-400 text-sm">Positions</p>
              <p className="text-2xl font-bold">{portfolio.account?.positions?.length || 0}</p>
            </div>
            <div>
              <p className="text-gray-400 text-sm">Status</p>
              <p className="text-2xl font-bold text-green-400">{portfolio.account?.status || "paper"}</p>
            </div>
          </div>
        </div>
      )}

      {/* Digest */}
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h2 className="text-lg font-semibold mb-4">Today's Digest {digest?.as_of && `— ${digest.as_of}`}</h2>
        {error ? (
          <p className="text-gray-400">{error}</p>
        ) : digest ? (
          <div className="grid md:grid-cols-3 gap-6">
            <DigestSection title="💻 Chips" content={digest.chips_section} />
            <DigestSection title="⚡ Energy" content={digest.energy_section} />
            <DigestSection title="🚢 Supply Chain" content={digest.supply_section} />
          </div>
        ) : (
          <p className="text-gray-400">No digest yet. Run the pipeline.</p>
        )}
      </div>

      {/* Signals table */}
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h2 className="text-lg font-semibold mb-4">Signals ({signals.length} tickers)</h2>
        {signals.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-800">
                  <th className="text-left py-2">Ticker</th>
                  <th className="text-right py-2">S1 Momentum</th>
                  <th className="text-right py-2">S2 News</th>
                  <th className="text-right py-2">S3 Shock</th>
                  <th className="text-right py-2">Composite</th>
                  <th className="text-right py-2">Rank</th>
                  <th className="text-center py-2">Selected</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s: any) => (
                  <tr key={s.ticker} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-1.5 font-medium">{s.ticker}</td>
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
        ) : (
          <p className="text-gray-400">No signals computed yet.</p>
        )}
      </div>
    </div>
  );
}

function DigestSection({ title, content }: { title: string; content: string }) {
  return (
    <div>
      <h3 className="font-medium mb-2 text-gray-200">{title}</h3>
      <div
        className="text-sm text-gray-300 prose prose-invert prose-sm"
        dangerouslySetInnerHTML={{ __html: content ? markdownToHtml(content) : "No data." }}
      />
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

function markdownToHtml(md: string): string {
  return md
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" class="text-blue-400 hover:underline">$1</a>')
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>)/g, "<ul class='list-disc list-inside space-y-1'>$1</ul>")
    .replace(/\n/g, "<br/>");
}
