# 08 — Human Approval

**Principle:** the agent proposes and a human decides. No order and no config change happens without an explicit,
recorded human approval.

## Proposal lifecycle
```
DRAFT ──▶ GATED_OUT (failed backtest gate, visible but not actionable)
  │
  ▼
PENDING_REVIEW ──▶ REJECTED (with reason)
  │          └───▶ EXPIRED (passed expires_at without decision)
  │          └───▶ CHANGES_REQUESTED ──▶ (agent may submit a new proposal referencing it)
  ▼
APPROVED (threshold signatures collected, see 15)
  │
  ▼
EXECUTING ──▶ EXECUTED | PARTIALLY_EXECUTED | FAILED
```
- Only `approval/` code may move a proposal out of PENDING_REVIEW, and only with valid signatures.
- Every state transition is written to the audit log (`10`) with actor, timestamp and reason.
- Config proposals (`param_change`) take effect at the next rebalance after approval. They do not trade on their own.

## What the approver sees (web app `/proposals/[id]`)
1. **Header:** kind, title, confidence, expires in X h.
2. **Why:** the agent's rationale + cited evidence (clickable, with publication timestamps).
3. **What changes:** config diff (side by side) or a target weights table with current → target and the order preview.
4. **Evidence of benefit:** baseline vs candidate metrics table, equity curves, drawdown chart, holdout result, variants tested, Deflated Sharpe.
5. **Risk notes:** full `07` section, including "what could go wrong".
6. **Checklist** (the approver must tick each before the Approve button enables):
   - [ ] I read the rationale and checked at least one source
   - [ ] I understand the main risk
   - [ ] Changes are within the limits I'm comfortable with
7. **Actions:** Approve (sign) · Reject (reason required) · Request changes (comment) · Edit weights down (approver may *reduce* any position or exposure, never increase it; this produces a new signed variant)

## Approval record
```json
{
  "proposal_id": "prp_2026-11-02_001",
  "proposal_hash": "sha256 of canonical proposal JSON",
  "decision": "APPROVE",
  "approver": "0xAbc...",           // signer address (15)
  "signed_at": "2026-11-02T13:05:00Z",
  "expires_at": "2026-11-02T20:00:00Z",
  "comment": "OK, but watch VST earnings",
  "signature": "0x..."              // EIP-712 signature
}
```
The signature covers `proposal_hash`, so any change to the proposal after signing invalidates the approval.

## Interfaces
- **Web app (primary):** `/proposals` inbox and detail page (`11`). Sign in with a wallet (SIWE) and sign the decision in the wallet (EIP-712, `15`). Works on desktop and in mobile wallet browsers.
- **CLI (operator fallback):** `trader proposals list|show <id>`, `trader approve <id>`, `trader reject <id> --reason "..."`. It signs with a local encrypted keystore and posts to the same API.
- **Notifications:** email/web push when a proposal enters PENDING_REVIEW. The message links to the proposal page, but approval still requires SIWE login + a wallet signature.
- Visitors can see every proposal, its decision and its signatures, but cannot act on them.

## Anti-rubber-stamping
- Minimum review time: Approve is disabled for 60 s after opening a proposal.
- A weekly summary shows the approver their approve/reject ratio and the outcomes of approved vs rejected proposals.
- Proposals cannot be bulk-approved.
