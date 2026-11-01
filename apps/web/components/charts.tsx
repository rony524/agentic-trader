"use client";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { INK, SERIES, STATUS, SLEEVE_ORDER, sleeveColor, mergeCurves, pct } from "@/lib/viz";

const axisProps = {
  stroke: INK.axis,
  tick: { fill: INK.muted, fontSize: 11 },
  tickLine: false,
};

// ---------- Layout pieces ----------

export function Card({ title, subtitle, action, children, className = "" }: {
  title?: string; subtitle?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`bg-gray-900 rounded-xl p-5 border border-gray-800 ${className}`}>
      {(title || action) && (
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            {title && <h2 className="text-base font-semibold text-gray-100">{title}</h2>}
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-semibold mt-1 text-gray-100">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
      {items.map(i => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="h-40 flex items-center justify-center text-sm text-gray-500 border border-dashed border-gray-800 rounded-lg">{children}</div>;
}

function TooltipBox({ title, rows }: { title?: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="bg-gray-950/95 border border-gray-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      {title && <p className="text-gray-300 font-medium mb-1">{title}</p>}
      {rows.map(r => (
        <p key={r.label} className="flex items-center gap-2 text-gray-400">
          {r.color && <span className="w-2 h-2 rounded-full" style={{ background: r.color }} />}
          <span>{r.label}</span>
          <span className="ml-auto pl-3 text-gray-100 tabular-nums">{r.value}</span>
        </p>
      ))}
    </div>
  );
}

// ---------- Backtest equity & drawdown ----------

type Curve = { date: string; equity: number }[];

export function EquityCompareChart({ baseline, candidate, height = 260 }: { baseline?: Curve; candidate?: Curve; height?: number }) {
  const data = mergeCurves(baseline, candidate);
  if (!data.length) return <Empty>No equity curve recorded for this backtest.</Empty>;
  const hasCandidate = !!candidate?.length;
  const legend = [{ label: "Baseline", color: SERIES.baseline }, ...(hasCandidate ? [{ label: "Candidate", color: SERIES.candidate }] : [])];
  return (
    <div className="space-y-2">
      {hasCandidate && <Legend items={legend} />}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="date" {...axisProps} minTickGap={48} tickFormatter={d => d.slice(0, 7)} />
          <YAxis {...axisProps} axisLine={false} width={48} tickFormatter={v => pct(v, 0)} />
          <ReferenceLine y={0} stroke={INK.axis} />
          <Tooltip
            cursor={{ stroke: INK.muted, strokeWidth: 1 }}
            content={({ active, payload, label }) => active && payload?.length ? (
              <TooltipBox title={label} rows={payload.map(p => ({
                label: p.dataKey === "candidate" ? "Candidate" : "Baseline",
                value: pct(Number(p.value)), color: String(p.color),
              }))} />
            ) : null}
          />
          <Line type="monotone" dataKey="baseline" stroke={SERIES.baseline} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
          {hasCandidate && <Line type="monotone" dataKey="candidate" stroke={SERIES.candidate} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DrawdownChart({ baseline, candidate, height = 160 }: { baseline?: Curve; candidate?: Curve; height?: number }) {
  const data = mergeCurves(baseline, candidate);
  if (!data.length) return null;
  const hasCandidate = !!candidate?.length;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} vertical={false} />
        <XAxis dataKey="date" {...axisProps} minTickGap={48} tickFormatter={d => d.slice(0, 7)} />
        <YAxis {...axisProps} axisLine={false} width={48} tickFormatter={v => pct(v, 0)} />
        <Tooltip
          cursor={{ stroke: INK.muted, strokeWidth: 1 }}
          content={({ active, payload, label }) => active && payload?.length ? (
            <TooltipBox title={label} rows={payload.map(p => ({
              label: p.dataKey === "candidate_dd" ? "Candidate drawdown" : "Baseline drawdown",
              value: pct(Number(p.value)), color: String(p.color),
            }))} />
          ) : null}
        />
        <Area type="monotone" dataKey="baseline_dd" stroke={SERIES.baseline} fill={SERIES.baseline} fillOpacity={0.15} strokeWidth={1.5} />
        {hasCandidate && <Area type="monotone" dataKey="candidate_dd" stroke={SERIES.candidate} fill={SERIES.candidate} fillOpacity={0.15} strokeWidth={1.5} />}
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ---------- Metric comparison ----------

const METRIC_LABELS: Record<string, { label: string; fmt: (v: number) => string; higherIsBetter: boolean }> = {
  sharpe: { label: "Sharpe", fmt: v => v.toFixed(2), higherIsBetter: true },
  cagr: { label: "CAGR", fmt: v => pct(v), higherIsBetter: true },
  volatility: { label: "Volatility", fmt: v => pct(v), higherIsBetter: false },
  max_drawdown: { label: "Max drawdown", fmt: v => pct(v), higherIsBetter: true }, // stored negative
  avg_turnover: { label: "Avg turnover", fmt: v => pct(v), higherIsBetter: false },
  test_sharpe: { label: "Out-of-sample Sharpe", fmt: v => v.toFixed(2), higherIsBetter: true },
  test_cagr: { label: "Out-of-sample CAGR", fmt: v => pct(v), higherIsBetter: true },
  test_max_drawdown: { label: "Out-of-sample max DD", fmt: v => pct(v), higherIsBetter: true },
};

export function MetricCompare({ baseline, candidate }: { baseline: Record<string, number>; candidate?: Record<string, number> | null }) {
  const keys = Object.keys(baseline || {});
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-gray-500 border-b border-gray-800">
          <th className="text-left font-normal py-2">Metric</th>
          <th className="text-right font-normal py-2">Baseline</th>
          {candidate && <th className="text-right font-normal py-2">Candidate</th>}
          {candidate && <th className="text-right font-normal py-2">Change</th>}
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {keys.map(k => {
          const meta = METRIC_LABELS[k] ?? { label: k, fmt: (v: number) => v.toFixed(4), higherIsBetter: true };
          const b = Number(baseline[k]);
          const c = candidate ? Number(candidate[k]) : undefined;
          const delta = c !== undefined ? c - b : 0;
          const better = meta.higherIsBetter ? delta > 0 : delta < 0;
          return (
            <tr key={k} className="border-b border-gray-800/60">
              <td className="py-1.5 text-gray-400">{meta.label}</td>
              <td className="py-1.5 text-right text-gray-200">{meta.fmt(b)}</td>
              {candidate && <td className="py-1.5 text-right text-gray-100 font-medium">{c !== undefined ? meta.fmt(c) : "—"}</td>}
              {candidate && (
                <td className="py-1.5 text-right">
                  {delta === 0 ? <span className="text-gray-500">—</span> : (
                    <span style={{ color: better ? STATUS.good : STATUS.critical }}>
                      {better ? "▲" : "▼"} {meta.fmt(Math.abs(delta))}
                    </span>
                  )}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------- Signals ----------

type SignalRow = { ticker: string; composite: number; s1_momentum: number; s2_news: number; s3_shock: number; rank: number; selected: boolean };

export function SignalRankChart({ signals, sleeveOf }: { signals: SignalRow[]; sleeveOf: Record<string, string> }) {
  if (!signals.length) return <Empty>No signals computed yet. Run the pipeline.</Empty>;
  const data = [...signals].sort((a, b) => b.composite - a.composite);
  const sleevesPresent = SLEEVE_ORDER.filter(s => data.some(d => sleeveOf[d.ticker] === s));
  return (
    <div className="space-y-3">
      <Legend items={sleevesPresent.map(s => ({ label: s, color: sleeveColor(s) }))} />
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 22)}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }} barCategoryGap={2}>
          <CartesianGrid stroke={INK.grid} horizontal={false} />
          <XAxis type="number" {...axisProps} tickFormatter={v => v.toFixed(1)} />
          <YAxis type="category" dataKey="ticker" {...axisProps} axisLine={false} width={56} interval={0}
            tick={({ x, y, payload }: any) => {
              const sel = data.find(d => d.ticker === payload.value)?.selected;
              return (
                <text x={x - 4} y={y} dy={4} textAnchor="end" fontSize={11}
                  fill={sel ? INK.primary : INK.muted} fontWeight={sel ? 600 : 400}>
                  {sel ? "● " : ""}{payload.value}
                </text>
              );
            }}
          />
          <ReferenceLine x={0} stroke={INK.axis} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as SignalRow;
              return <TooltipBox title={`${d.ticker} · #${d.rank}${d.selected ? " · selected" : ""}`} rows={[
                { label: sleeveOf[d.ticker] ?? "Unmapped", value: "", color: sleeveColor(sleeveOf[d.ticker]) },
                { label: "Composite", value: d.composite.toFixed(3) },
                { label: "Momentum", value: d.s1_momentum.toFixed(3) },
                { label: "News", value: d.s2_news.toFixed(3) },
                { label: "Shock", value: d.s3_shock.toFixed(3) },
              ]} />;
            }}
          />
          <Bar dataKey="composite" radius={[0, 4, 4, 0]} maxBarSize={14}>
            {data.map(d => <Cell key={d.ticker} fill={sleeveColor(sleeveOf[d.ticker])} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-500">● bold tickers are selected for the portfolio. Hover a bar for the signal breakdown.</p>
    </div>
  );
}

export function SleeveStrengthChart({ signals, sleeveOf }: { signals: SignalRow[]; sleeveOf: Record<string, string> }) {
  const data = SLEEVE_ORDER.map(sleeve => {
    const rows = signals.filter(s => sleeveOf[s.ticker] === sleeve);
    if (!rows.length) return null;
    return {
      sleeve,
      avg: rows.reduce((a, r) => a + r.composite, 0) / rows.length,
      selected: rows.filter(r => r.selected).length,
      count: rows.length,
    };
  }).filter(Boolean) as { sleeve: string; avg: number; selected: number; count: number }[];
  if (!data.length) return <Empty>No signals yet.</Empty>;
  return (
    <ResponsiveContainer width="100%" height={data.length * 34 + 20}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={v => v.toFixed(1)} />
        <YAxis type="category" dataKey="sleeve" {...axisProps} axisLine={false} width={130} interval={0} />
        <ReferenceLine x={0} stroke={INK.axis} />
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return <TooltipBox title={d.sleeve} rows={[
              { label: "Avg composite", value: d.avg.toFixed(3), color: sleeveColor(d.sleeve) },
              { label: "Selected", value: `${d.selected} of ${d.count}` },
            ]} />;
          }}
        />
        <Bar dataKey="avg" radius={[0, 4, 4, 0]} maxBarSize={16}>
          {data.map(d => <Cell key={d.sleeve} fill={sleeveColor(d.sleeve)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------- Allocation ----------

export function AllocationBar({ weights, sleeveOf }: { weights: Record<string, number>; sleeveOf: Record<string, string> }) {
  const bySleeve: Record<string, { total: number; tickers: [string, number][] }> = {};
  Object.entries(weights).forEach(([t, w]) => {
    const s = sleeveOf[t] ?? "Unmapped";
    bySleeve[s] ??= { total: 0, tickers: [] };
    bySleeve[s].total += Number(w);
    bySleeve[s].tickers.push([t, Number(w)]);
  });
  const order = [...SLEEVE_ORDER, "Unmapped"].filter(s => bySleeve[s]);
  const total = order.reduce((a, s) => a + bySleeve[s].total, 0) || 1;
  return (
    <div className="space-y-4">
      <div className="flex h-8 w-full gap-0.5 rounded-md overflow-hidden">
        {order.map(s => (
          <div key={s} title={`${s}: ${pct(bySleeve[s].total)}`}
            style={{ width: `${(bySleeve[s].total / total) * 100}%`, background: sleeveColor(s) }} />
        ))}
      </div>
      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
        {order.map(s => (
          <div key={s}>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-gray-300">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: sleeveColor(s) }} />{s}
              </span>
              <span className="tabular-nums text-gray-100 font-medium">{pct(bySleeve[s].total)}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5 pl-[18px]">
              {bySleeve[s].tickers.sort((a, b) => b[1] - a[1]).map(([t, w]) => `${t} ${pct(w)}`).join(" · ")}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- Generic single-series bars (audit activity etc.) ----------

export function CountBarChart({ data, labelWidth = 140 }: { data: { label: string; count: number }[]; labelWidth?: number }) {
  if (!data.length) return <Empty>Nothing to chart yet.</Empty>;
  return (
    <ResponsiveContainer width="100%" height={data.length * 28 + 20}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} horizontal={false} />
        <XAxis type="number" {...axisProps} allowDecimals={false} />
        <YAxis type="category" dataKey="label" {...axisProps} axisLine={false} width={labelWidth} interval={0} />
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
          content={({ active, payload }) => active && payload?.length ? (
            <TooltipBox title={String(payload[0].payload.label)} rows={[{ label: "Entries", value: String(payload[0].value) }]} />
          ) : null}
        />
        <Bar dataKey="count" fill={SERIES.candidate} radius={[0, 4, 4, 0]} maxBarSize={14} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function EquityAreaChart({ data, height = 180 }: { data: { date: string; equity: number }[]; height?: number }) {
  if (data.length < 2) return <Empty>The equity curve appears once there are two or more daily snapshots.</Empty>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} vertical={false} />
        <XAxis dataKey="date" {...axisProps} minTickGap={40} />
        <YAxis {...axisProps} axisLine={false} width={64} domain={["auto", "auto"]} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
        <Tooltip
          cursor={{ stroke: INK.muted, strokeWidth: 1 }}
          content={({ active, payload, label }) => active && payload?.length ? (
            <TooltipBox title={label} rows={[{ label: "Equity", value: `$${Number(payload[0].value).toLocaleString()}`, color: SERIES.candidate }]} />
          ) : null}
        />
        <Area type="monotone" dataKey="equity" stroke={SERIES.candidate} fill={SERIES.candidate} fillOpacity={0.15} strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
