import type { Metadata } from "next";
import ConnectWalletButton from "@/components/ConnectWalletButton";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Trader — Chips · Energy · Supply Chain",
  description: "AI research agent for chips, energy & supply chains. Paper trading only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <PaperBanner />
        <TopBar />
        <main className="max-w-7xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}

function PaperBanner() {
  return (
    <div className="bg-yellow-500 text-black text-center py-2 text-sm font-bold tracking-wide">
      PAPER TRADING · Educational project · Not financial advice
    </div>
  );
}

function TopBar() {
  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <a href="/" className="font-bold text-lg">⚡ Agentic Trader</a>
        <a href="/proposals" className="text-gray-300 hover:text-white text-sm">Proposals</a>
        <a href="/audit" className="text-gray-300 hover:text-white text-sm">Audit Log</a>
      </div>
      <div className="flex items-center gap-3">
        <span className="bg-green-600 text-white text-xs px-2 py-1 rounded font-medium">PAPER MODE</span>
        <ConnectWalletButton />
      </div>
    </nav>
  );
}
