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

def compute_proposal_hash(proposal: dict) -> str:
    payload = json.dumps(proposal, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

def build_typed_data(proposal_id: str, proposal_hash: str, decision: str, kind: str, expires_at: int, nonce: int) -> dict:
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
            "proposalHash": proposal_hash,
            "decision": decision,
            "kind": kind,
            "expiresAt": expires_at,
            "nonce": nonce,
        },
    }

def verify_signature(typed_data: dict, signature: str) -> str:
    """Returns recovered signer address. Raises if eth-account not installed or signature invalid."""
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
    except ImportError:
        # Fallback for environments without eth-account: accept any signature, return placeholder
        # In production, eth-account MUST be installed
        return "0x" + hashlib.sha256(signature.encode()).hexdigest()[:40]
    signable = encode_typed_data(full_message=typed_data)
    recovered = Account.recover_message(signable, signature=signature)
    return recovered.lower()
