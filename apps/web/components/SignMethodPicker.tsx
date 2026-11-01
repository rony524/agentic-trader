"use client";
import { useEffect, useState } from "react";
import { signWithPasskey, PasskeyRequest } from "@/lib/passkey";
import { signTypedData } from "@/lib/wallet";

export type SignMethod = "passkey" | "wallet";
const STORAGE_KEY = "sign-method";

// Passkey by default; the wallet option only appears when a wallet extension is installed.
export function useSignMethod() {
  const [hasWallet, setHasWallet] = useState(false);
  const [method, setMethodState] = useState<SignMethod>("passkey");

  useEffect(() => {
    const wallet = !!(window as any).ethereum;
    setHasWallet(wallet);
    try {
      if (wallet && localStorage.getItem(STORAGE_KEY) === "wallet") setMethodState("wallet");
    } catch {}
  }, []);

  const setMethod = (m: SignMethod) => {
    setMethodState(m);
    try { localStorage.setItem(STORAGE_KEY, m); } catch {}
  };
  return { method, setMethod, hasWallet };
}

// Signs the server-provided payload with the chosen method; returns the signature string the API expects.
export async function signWith(method: SignMethod, typed_data: any, passkey: PasskeyRequest): Promise<string> {
  return method === "wallet" ? (await signTypedData(typed_data)).signature : signWithPasskey(passkey);
}

export default function SignMethodPicker({ method, setMethod, hasWallet }: ReturnType<typeof useSignMethod>) {
  if (!hasWallet) {
    return <p className="text-xs text-gray-500">You'll confirm with your passkey: Face ID, fingerprint, Windows Hello or your phone.</p>;
  }
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-gray-500">Confirm with</span>
      <div className="inline-flex rounded-lg border border-gray-700 overflow-hidden">
        {(["passkey", "wallet"] as const).map(m => (
          <button key={m} onClick={() => setMethod(m)}
            className={`px-3 py-1 ${method === m ? "bg-gray-100 text-gray-900" : "text-gray-300 hover:bg-gray-800"}`}>
            {m === "passkey" ? "🔑 Passkey" : "🦊 Wallet"}
          </button>
        ))}
      </div>
    </div>
  );
}
