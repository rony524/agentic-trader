"use client";
import { useEffect, useState } from "react";
import { fetchAPI, postAPI } from "@/lib/api";
import { createPasskey, passkeysSupported } from "@/lib/passkey";

const TOKEN_KEY = "adminToken";

// Enrollment target of an invite link (/approvers?code=…), an admin panel to add approvers without a terminal,
// and the public list of approver passkeys.
export default function ApproversPage() {
  const [code, setCode] = useState("");
  const [passkeys, setPasskeys] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => fetchAPI("/passkeys").then(d => setPasskeys(d.passkeys || [])).catch(() => {});
  useEffect(() => {
    setCode(new URLSearchParams(window.location.search).get("code") || "");
    load();
  }, []);

  async function enroll(inviteCode: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const { options } = await postAPI("/passkeys/register/options", { code: inviteCode });
      const credential = await createPasskey(options);
      const result = await postAPI("/passkeys/register", { code: inviteCode, credential });
      setDone(result.name);
      setCode("");
      window.history.replaceState(null, "", "/approvers");  // the invite is spent; don't leave it in the URL
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold">Approvers</h1>
        <p className="text-sm text-gray-500">People who can approve trades. Each approval is signed by their passkey, and anyone can check it against the public keys below.</p>
      </div>

      {done && (
        <div className="rounded-xl p-4 border border-green-800 bg-green-950/40 text-sm">
          ✓ Passkey registered for <b>{done}</b>. You can now approve proposals with it.
        </div>
      )}
      {error && <p className="text-sm text-red-400">Couldn't register: {error}</p>}

      {code ? (
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800 space-y-3">
          <h2 className="text-lg font-semibold">Register your passkey</h2>
          <p className="text-sm text-gray-400">You were invited as an approver. Create a passkey on this device: Face ID, fingerprint, Windows Hello or your phone. This invite link works once.</p>
          {!passkeysSupported() && <p className="text-sm text-red-400">This browser doesn't support passkeys.</p>}
          <button disabled={busy || !passkeysSupported()} onClick={() => enroll(code)}
            className={`px-4 py-2 rounded font-medium text-white ${busy ? "bg-gray-700 cursor-not-allowed" : "bg-blue-600 hover:bg-blue-700"}`}>
            {busy ? "Waiting for your device…" : "🔑 Create passkey"}
          </button>
        </div>
      ) : (
        <AdminPanel busy={busy} onEnrollHere={enroll} />
      )}

      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h2 className="text-lg font-semibold mb-4">Registered passkeys</h2>
        {passkeys.length === 0 ? (
          <p className="text-sm text-gray-400">No passkeys registered yet.</p>
        ) : (
          <div className="space-y-2">
            {passkeys.map(p => (
              <div key={p.credential_id} className="flex flex-wrap justify-between gap-2 text-sm">
                <span className="font-medium">{p.name}</span>
                <span className="text-gray-400 font-mono">{p.credential_id.slice(0, 16)}…</span>
                <span className="text-gray-500">{p.created_at?.slice(0, 16).replace("T", " ")}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AdminPanel({ busy, onEnrollHere }: { busy: boolean; onEnrollHere: (code: string) => void }) {
  const [token, setToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [name, setName] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try { setToken(sessionStorage.getItem(TOKEN_KEY) || ""); } catch {}
  }, []);

  function unlock() {
    try { sessionStorage.setItem(TOKEN_KEY, tokenInput); } catch {}
    setToken(tokenInput);
    setTokenInput("");
  }

  function lock() {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
    setToken("");
    setLink(null);
  }

  // Invites are admin-only so a visitor can't make themselves an approver; the API returns a one-time link.
  async function invite(): Promise<string | null> {
    setError(null);
    setLink(null);
    try {
      const { enroll_url } = await postAPI("/admin/passkey-invites", { name }, { "X-Admin-Token": token });
      return enroll_url;
    } catch (e: any) {
      if (e.message.includes("403")) { lock(); setError("Wrong admin token."); }
      else setError(e.message);
      return null;
    }
  }

  async function registerHere() {
    const url = await invite();
    const code = url && new URL(url).searchParams.get("code");
    if (code) onEnrollHere(code);
  }

  async function copyLink() {
    const url = await invite();
    if (!url) return;
    setLink(url);
    try { await navigator.clipboard.writeText(url); } catch {}
  }

  if (!token) {
    return (
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800 space-y-3">
        <h2 className="text-lg font-semibold">Admin</h2>
        <p className="text-sm text-gray-400">Unlock to add approvers. Otherwise, ask an admin for an enrollment link.</p>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <form onSubmit={e => { e.preventDefault(); if (tokenInput) unlock(); }} className="flex flex-wrap gap-3">
          <input type="password" value={tokenInput} onChange={e => setTokenInput(e.target.value)} placeholder="Admin token"
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm flex-1 min-w-[12rem]" />
          <button type="submit" disabled={!tokenInput}
            className={`px-4 py-2 rounded font-medium text-white ${tokenInput ? "bg-gray-700 hover:bg-gray-600" : "bg-gray-800 cursor-not-allowed"}`}>
            Unlock
          </button>
        </form>
      </div>
    );
  }

  const canInvite = !!name.trim() && !busy;
  return (
    <div className="bg-gray-900 rounded-lg p-6 border border-gray-800 space-y-3">
      <div className="flex justify-between items-start">
        <h2 className="text-lg font-semibold">Add an approver</h2>
        <button onClick={lock} className="text-xs text-gray-500 hover:text-gray-300">Lock</button>
      </div>
      <p className="text-sm text-gray-400">Register a passkey on this device now, or copy a one-time link (valid 24h) to enroll someone on their own device.</p>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Approver name" maxLength={64}
        className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm w-full" />
      <div className="flex flex-wrap gap-3">
        <button disabled={!canInvite || !passkeysSupported()} onClick={registerHere}
          className={`px-4 py-2 rounded font-medium text-white ${canInvite ? "bg-blue-600 hover:bg-blue-700" : "bg-gray-700 cursor-not-allowed"}`}>
          {busy ? "Waiting for your device…" : "🔑 Register on this device"}
        </button>
        <button disabled={!canInvite} onClick={copyLink}
          className={`px-4 py-2 rounded font-medium ${canInvite ? "bg-gray-700 hover:bg-gray-600 text-white" : "bg-gray-800 text-gray-500 cursor-not-allowed"}`}>
          🔗 Copy invite link
        </button>
      </div>
      {link && (
        <p className="text-xs text-gray-400 break-all">Copied to clipboard: <span className="font-mono text-gray-300">{link}</span></p>
      )}
    </div>
  );
}
