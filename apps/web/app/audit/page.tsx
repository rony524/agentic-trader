"use client";
import { useEffect, useState, useCallback } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CountBarChart } from "@/components/charts";

// SHA-256 via Web Crypto
async function sha256hex(data: string): Promise<string> {
  const buf = new TextEncoder().encode(data);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
}

export default function AuditPage() {
  const [entries, setEntries] = useState<any[]>([]);
  const [verification, setVerification] = useState<any>(null);
  const [browserVerification, setBrowserVerification] = useState<any>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => { fetchAPI("/audit?limit=500").then(d => setEntries(d.entries || [])).catch(() => {}); }, []);

  const verifyInBrowser = useCallback(async () => {
    setVerifying(true);
    try {
      const { entries: fresh } = await fetchAPI("/audit?limit=1000");
      let prevHash = "";
      let valid = true;
      let brokenAt: number | null = null;
      for (const e of fresh) {
        // hash the exact stored payload text (re-serializing in JS would differ from Python on unicode escapes)
        const payloadHash = await sha256hex(e.payload_json);
        const expected = await sha256hex(`${e.seq}|${e.ts}|${e.actor}|${e.event_type}|${payloadHash}|${prevHash}`);
        if (payloadHash !== e.payload_hash || e.entry_hash !== expected) {
          valid = false;
          brokenAt = e.seq;
          break;
        }
        prevHash = e.entry_hash;
      }
      setBrowserVerification({ valid, count: fresh.length, brokenAt });
    } catch (e: any) {
      setBrowserVerification({ valid: false, error: e.message });
    }
    setVerifying(false);
  }, []);

  const verifyServer = () => {
    fetchAPI("/audit/verify").then(setVerification).catch(() => {});
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <div className="flex gap-3">
          <button onClick={verifyServer} className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded text-sm">Verify (Server)</button>
          <button onClick={verifyInBrowser} disabled={verifying} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm">
            {verifying ? "Verifying…" : "Verify (Browser)"}
          </button>
        </div>
      </div>

      {(verification || browserVerification) && (
        <div className="grid grid-cols-2 gap-4">
          {verification && (
            <div className={`rounded-lg p-4 border ${verification.valid ? "bg-green-900/30 border-green-700" : "bg-red-900/30 border-red-700"}`}>
              <p className="font-medium">Server verification: {verification.valid ? "✅ Valid" : "❌ Broken"}</p>
              <p className="text-sm text-gray-400">Entries: {verification.count}</p>
              {verification.broken_at && <p className="text-sm text-red-400">Broken at seq {verification.broken_at}</p>}
            </div>
          )}
          {browserVerification && (
            <div className={`rounded-lg p-4 border ${browserVerification.valid ? "bg-green-900/30 border-green-700" : "bg-red-900/30 border-red-700"}`}>
              <p className="font-medium">Browser verification (Web Crypto): {browserVerification.valid ? "✅ Valid" : "❌ Broken"}</p>
              <p className="text-sm text-gray-400">Entries: {browserVerification.count}</p>
              {browserVerification.brokenAt && <p className="text-sm text-red-400">Broken at seq {browserVerification.brokenAt}</p>}
            </div>
          )}
        </div>
      )}

      <Card title="Activity by event type" subtitle={`${entries.length} entries in the chain`}>
        <CountBarChart labelWidth={170} data={Object.entries(
          entries.reduce((acc: Record<string, number>, e) => { acc[e.event_type] = (acc[e.event_type] || 0) + 1; return acc; }, {})
        ).map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count)} />
      </Card>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-800 text-gray-300">
              <th className="text-left px-4 py-2">Seq</th>
              <th className="text-left px-4 py-2">Timestamp</th>
              <th className="text-left px-4 py-2">Actor</th>
              <th className="text-left px-4 py-2">Event</th>
              <th className="text-left px-4 py-2">Hash</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.seq} className="border-t border-gray-800 hover:bg-gray-800/30">
                <td className="px-4 py-2 font-mono">{e.seq}</td>
                <td className="px-4 py-2 text-gray-400">{e.ts?.slice(0, 19)}</td>
                <td className="px-4 py-2 font-mono text-xs">{e.actor?.slice(0, 12)}…</td>
                <td className="px-4 py-2">{e.event_type}</td>
                <td className="px-4 py-2 font-mono text-xs text-gray-500">{e.entry_hash?.slice(0, 16)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
        {entries.length === 0 && <p className="text-gray-400 p-4">No audit entries.</p>}
      </div>
    </div>
  );
}
