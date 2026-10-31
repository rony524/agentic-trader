# 10 — Blockchain: Tamper-Evident Audit Trail

## Why a blockchain here (and why not more)
The project's central promise is that **a human made every decision**. A blockchain lets anyone check that the
record of proposals, approvals and trades wasn't edited after the fact. It is used only for **integrity and
timestamping**.
- **No tokens, no trading on-chain, no real funds.** Testnet only (Ethereum **Sepolia** by default).
- The system works fully with anchoring **disabled** (`AUDIT_ANCHOR_ENABLED=false`). The local hash chain alone still gives tamper evidence.

## Layer 1: local hash chain (always on)
Table `audit_log` in Postgres:
| column | description |
|--------|-------------|
| `seq` | monotonically increasing integer |
| `ts` | UTC timestamp |
| `actor` | `agent`, `executor`, `system`, or a signer address |
| `event_type` | `INGEST_RUN`, `BACKTEST`, `PROPOSAL_CREATED`, `APPROVAL_SIGNED`, `STATE_CHANGE`, `ORDER_SUBMITTED`, `FILL`, `CONFIG_ACTIVATED`, `KILL_SWITCH`, ... |
| `payload_json` | canonical JSON (sorted keys, no whitespace) |
| `payload_hash` | sha256(payload_json) |
| `prev_hash` | `entry_hash` of seq-1 |
| `entry_hash` | sha256(seq ‖ ts ‖ actor ‖ event_type ‖ payload_hash ‖ prev_hash) |

- Append-only: no service's DB role has UPDATE/DELETE on this table, and a trigger rejects them (`16`).
- `seq` is assigned under a Postgres advisory lock so concurrent writers (api, jobs, executor) can't fork the chain.
- `trader audit verify` recomputes the chain and reports the first broken link, if any. The web `/audit` page
  runs the same check **in the visitor's browser** (Web Crypto SHA-256), so visitors don't have to trust the server.
- Large artifacts (backtest parquet, reports) are stored on disk. Only their hashes go into the log.

## Layer 2: daily Merkle anchoring (optional)
1. At 23:00 ET, build a Merkle tree over all `entry_hash` values since the last anchor.
2. Send the root to a minimal contract on Sepolia:
   ```solidity
   // contracts/AuditAnchor.sol
   contract AuditAnchor {
       event Anchored(uint256 indexed fromSeq, uint256 indexed toSeq, bytes32 root, uint256 ts);
       address public immutable owner;
       constructor() { owner = msg.sender; }
       function anchor(uint256 fromSeq, uint256 toSeq, bytes32 root) external {
           require(msg.sender == owner, "not owner");
           emit Anchored(fromSeq, toSeq, root, block.timestamp);
       }
   }
   ```
   (Alternative without a contract: send a 0-ETH self-transaction with the root in calldata.)
3. Store `(from_seq, to_seq, root, tx_hash, block_number)` in table `anchors`.
4. `trader audit prove <seq>` outputs a Merkle proof that a specific entry is included in an anchored root. Anyone can verify it against the on-chain event.

## Keys & network
- The anchoring key is a **dedicated testnet wallet** with faucet ETH only. It is set as `ANCHOR_PRIVATE_KEY` on the `jobs` service only and never reused for anything else.
- RPC: any free Sepolia RPC endpoint (`SEPOLIA_RPC_URL`).
- Deployment script: `scripts/deploy_anchor.py` (web3.py) or Foundry (`forge create`).

## What a verifier can check
1. The local chain is unbroken (`audit verify`).
2. Any approval in the log carries a valid signature from an authorized approver (`15`).
3. Every `ORDER_SUBMITTED` entry references a proposal whose `APPROVAL_SIGNED` entries meet the threshold and precede it in sequence.
4. The relevant log segment was anchored on-chain at a specific block time, so it existed unchanged since then.

## Out of scope
On-chain execution, smart-contract custody, tokenized shares, mainnet deployment.
