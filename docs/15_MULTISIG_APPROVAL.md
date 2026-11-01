# 15 — Multisig Approval

## Purpose
Make "a human makes every decision" **cryptographically verifiable** and optionally require more than one
person. Approvals are **EIP-712 signatures, verified off-chain** by the executor. No gas or on-chain transaction
is needed to approve, and signatures are later included in the audit log (`10`).

## Approver registry (`config/approvers.yaml`)
```yaml
threshold:
  default: 1            # dev / solo mode
  rebalance: 2
  param_change: 2
  risk_reduction: 1     # reducing risk should be fast
  risk_config_change: 3 # changes to risk.yaml / universe
approvers:
  - name: "Primary operator"
    address: "0x..."     # signer address
    roles: [operator]
  - name: "Co-approver"
    address: "0x..."
    roles: [reviewer]
  - name: "Risk reviewer"
    address: "0x..."
    roles: [risk]
```
- Changing this file requires a `risk_config_change` proposal at the current threshold, so the registry can't be loosened silently.
- **Solo builders:** run 2-of-3 with three keys you control on different devices (e.g., laptop keystore, phone wallet, hardware wallet). This still prevents an approval from a single compromised machine.

## What gets signed (EIP-712 typed data)
```json
{
  "domain": { "name": "AgenticTrader", "version": "1", "chainId": 11155111 },
  "primaryType": "Approval",
  "types": {
    "Approval": [
      { "name": "proposalId",   "type": "string"  },
      { "name": "proposalHash", "type": "bytes32" },
      { "name": "decision",     "type": "string"  },
      { "name": "kind",         "type": "string"  },
      { "name": "expiresAt",    "type": "uint256" },
      { "name": "nonce",        "type": "uint256" }
    ]
  }
}
```
- `proposalHash` = sha256 of the canonical proposal JSON (including target weights / config diff). If the proposal changes, the signature no longer matches.
- `chainId` = Sepolia, so signatures cannot be replayed on another chain. `nonce` is per approver, which prevents replay across proposals.
- Wallets show EIP-712 fields in readable form, so approvers can see what they are signing.

## Signing methods
| Method | How | Phase |
|--------|-----|-------|
| Browser wallet (primary) | Web app fetches `GET /proposals/{id}/typed-data`, calls `signTypedData` via wagmi/viem (MetaMask, Rabby, Coinbase Wallet, WalletConnect for mobile), then `POST /proposals/{id}/signatures` | 3 |
| Hardware wallet | Through the browser wallet | 3 |
| CLI keystore (fallback) | `trader approve <id>` → local encrypted keystore → `eth-account` → posts to the same API | 3 |

The same wallet address is used for SIWE login (`11`). The login only grants access to the approver UI. Each
**decision** still needs its own EIP-712 signature.

## Verification (executor, before every order batch)
```
sigs = approvals.where(proposal_id = p.id, decision = APPROVE)
valid = { recover(sig) for sig in sigs
          if recover(sig) in registry
          and sig.proposalHash == hash(p)
          and sig.expiresAt > now
          and sig.nonce unused }
if any approver signed REJECT → proposal REJECTED (a single reject vetoes)
require len(valid) >= threshold[p.kind]
```
- Distinct signers only (the same key twice counts once).
- A reject from any registered approver vetoes the proposal. Reducing risk still needs only `risk_reduction` threshold.

## Optional: Safe (Gnosis) on Sepolia
For a fully on-chain version, approvers can sign through a Safe multisig on Sepolia that calls an added
`approve(bytes32 proposalHash)` function on the anchor contract (emitting an `Approved` event). This is **not needed** for the MVP. Off-chain EIP-712 + anchoring (`10`)
gives the same verifiability without gas or extra UX. Only consider it as a stretch goal.

## Tests
- Under threshold → executor refuses.
- Signature from an unregistered key → ignored.
- Proposal edited after signing → hash mismatch → refused.
- Expired signature → refused.
- Duplicate signer → counted once.
- One REJECT among approvals → proposal rejected.
