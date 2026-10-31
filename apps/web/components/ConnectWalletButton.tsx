"use client";

export default function ConnectWalletButton() {
  async function connect() {
    if (typeof (window as any).ethereum === "undefined") {
      alert("MetaMask not detected. Please install it.");
      return;
    }
    try {
      const accs = await (window as any).ethereum.request({ method: "eth_requestAccounts" });
      if (accs.length > 0) {
        const el = document.getElementById("wallet-addr");
        if (el) el.textContent = `${accs[0].slice(0, 6)}…${accs[0].slice(-4)}`;
      }
    } catch (e) {
      console.error("Wallet connection failed:", e);
    }
  }

  return (
    <button
      onClick={connect}
      className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-3 py-1.5 rounded"
    >
      <span id="wallet-addr">Connect Wallet</span>
    </button>
  );
}
