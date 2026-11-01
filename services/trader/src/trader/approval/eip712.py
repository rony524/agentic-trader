"""EIP-712 approval verification."""
from __future__ import annotations
import hashlib, json

EIP712_DOMAIN = {"name": "AgenticTrader", "version": "1", "chainId": 11155111}
EIP712_TYPES = {
    "Approval": [
        {"name": "proposalId", "type": "string"},
        {"name": "proposalHash", "type": "bytes32"},
        {"name": "decision", "type": "string"},
        {"name": "kind", "type": "string"},
        {"name": "expiresAt", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
    ]
}
DECISIONS = ("APPROVE", "REJECT")

IDEA_TYPES = {
    "Idea": [
        {"name": "contentHash", "type": "bytes32"},
        {"name": "issuedAt", "type": "uint256"},
    ]
}

def idea_content_hash(text: str, evidence_url: str) -> str:
    payload = json.dumps({"text": text, "evidence_url": evidence_url}, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(payload.encode()).hexdigest()

def build_idea_typed_data(text: str, evidence_url: str, issued_at: int) -> dict:
    """What an approver signs to submit an idea: binds the exact text + source URL to their wallet."""
    return {
        "types": {"EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
        ], **IDEA_TYPES},
        "primaryType": "Idea",
        "domain": EIP712_DOMAIN,
        "message": {"contentHash": idea_content_hash(text, evidence_url), "issuedAt": issued_at},
    }

class SignatureError(Exception): pass

def compute_proposal_hash(proposal: dict) -> str:
    payload = json.dumps(proposal, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

def build_typed_data(proposal_id: str, proposal_hash: str, decision: str, kind: str, expires_at: int, nonce: int) -> dict:
    # bytes32 must be 0x-prefixed for wallets (MetaMask rejects bare hex)
    hash_hex = proposal_hash if proposal_hash.startswith("0x") else "0x" + proposal_hash
    return {
        "types": {"EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
        ], **EIP712_TYPES},
        "primaryType": "Approval",
        "domain": EIP712_DOMAIN,
        "message": {
            "proposalId": proposal_id,
            "proposalHash": hash_hex,
            "decision": decision,
            "kind": kind,
            "expiresAt": expires_at,
            "nonce": nonce,
        },
    }

def verify_signature(typed_data: dict, signature: str) -> str:
    """Returns the recovered signer address (lowercase). Raises SignatureError if it can't be verified.

    There is deliberately no fallback: without eth-account nothing can be approved.
    """
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
    except ImportError as e:
        raise SignatureError("eth-account is not installed; signatures cannot be verified") from e
    try:
        signable = encode_typed_data(full_message=typed_data)
        recovered = Account.recover_message(signable, signature=signature)
    except Exception as e:
        raise SignatureError(f"invalid signature: {e}") from e
    return recovered.lower()

def approver_registry(approvers_cfg: dict) -> set[str]:
    return {a["address"].lower() for a in approvers_cfg.get("approvers", []) if a.get("address")}

def threshold_for(approvers_cfg: dict, kind: str) -> int:
    th = approvers_cfg.get("threshold", {})
    return max(1, int(th.get(kind, th.get("default", 1))))
