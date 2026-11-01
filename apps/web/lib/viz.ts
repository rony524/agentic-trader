// Chart tokens. The app is dark-only, so these are the dark-mode steps,
// validated as a set against the card surface (#111827).

export const INK = {
  primary: "#f0efec",
  secondary: "#c3c2b7",
  muted: "#898781",
  grid: "#1f2937",
  axis: "#374151",
};

// Fixed categorical order — follows config/universe.yaml sleeve order, never re-ranked.
export const SLEEVE_ORDER = [
  "Memory & compute",
  "Semi equipment",
  "Hyperscalers",
  "Power & grid",
  "Energy inputs",
  "Materials / logistics",
  "Cash proxy",
];

const CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"];

export const SLEEVE_COLORS: Record<string, string> = Object.fromEntries(
  SLEEVE_ORDER.map((s, i) => [s, CATEGORICAL[i]])
);

// Baseline is the reference (muted), candidate is the emphasized series.
export const SERIES = { baseline: INK.muted, candidate: CATEGORICAL[0] };

export const STATUS = { good: "#0ca30c", warning: "#fab219", critical: "#d03b3b" };

export type Universe = { sleeves: { sleeve: string; tickers: string[] }[] };

export function tickerToSleeve(u: Universe | null): Record<string, string> {
  const map: Record<string, string> = {};
  u?.sleeves.forEach(s => s.tickers.forEach(t => { map[t] = s.sleeve; }));
  return map;
}

export function sleeveColor(sleeve: string | undefined): string {
  return (sleeve && SLEEVE_COLORS[sleeve]) || INK.muted;
}

export const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;

type CurvePoint = { date: string; equity: number };

// Merge two equity curves into one row per date, as % return from each curve's start.
export function mergeCurves(baseline: CurvePoint[] = [], candidate: CurvePoint[] = []) {
  const rows = new Map<string, any>();
  const add = (curve: CurvePoint[], key: string) => {
    if (!curve.length) return;
    const start = curve[0].equity;
    let peak = -Infinity;
    for (const p of curve) {
      peak = Math.max(peak, p.equity);
      const row = rows.get(p.date) ?? { date: p.date };
      row[key] = p.equity / start - 1;
      row[`${key}_dd`] = p.equity / peak - 1;
      rows.set(p.date, row);
    }
  };
  add(baseline, "baseline");
  add(candidate, "candidate");
  return Array.from(rows.values()).sort((a, b) => a.date.localeCompare(b.date));
}
