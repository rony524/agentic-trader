"""Passkey (WebAuthn) signatures: the no-wallet alternative to EIP-712 (15_MULTISIG_APPROVAL).

Same guarantee as a wallet signature: the approver's device signs a challenge derived from the exact typed
message (proposal id + hash + decision + expiry + nonce), and anyone holding the registered public key can
re-verify it later without trusting the server. Public keys are written to the audit log on registration.

A passkey signature is stored as "webauthn:" + the browser's assertion JSON, next to wallet signatures.
"""
from __future__ import annotations
import base64, hashlib, json
from urllib.parse import urlparse

from trader.settings import settings
from trader.approval.eip712 import SignatureError, verify_signature, approver_registry

PREFIX = "webauthn:"
PASSKEY_SIGNER = "passkey:"  # signer ids for passkeys are "passkey:<approver name>"

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def from_b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def rp_id() -> str:
    return urlparse(settings.WEB_ORIGIN).hostname or "localhost"

def expected_origins() -> list[str]:
    return sorted({settings.WEB_ORIGIN.rstrip("/"), "http://localhost:3000"})

def challenge_for(typed_data: dict) -> bytes:
    return hashlib.sha256(json.dumps(typed_data, sort_keys=True, separators=(",", ":")).encode()).digest()

def request_options(typed_data: dict, credential_ids: list[str]) -> dict:
    """What the browser needs for navigator.credentials.get()."""
    return {"challenge": b64url(challenge_for(typed_data)), "rp_id": rp_id(), "allow_credentials": credential_ids}

# ---------- registration ----------

def registration_options(name: str, challenge: bytes, exclude: list[str]) -> dict:
    try:
        from webauthn import generate_registration_options, options_to_json
    except ImportError as e:
        raise SignatureError("webauthn is not installed; passkeys cannot be registered") from e
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    opts = generate_registration_options(
        rp_id=rp_id(), rp_name="Agentic Trader", user_name=name, user_display_name=name,
        user_id=hashlib.sha256(name.encode()).digest()[:16], challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=from_b64url(c)) for c in exclude],
    )
    return json.loads(options_to_json(opts))

def verify_registration(credential: dict, challenge: bytes) -> tuple[str, str, int]:
    """Returns (credential_id, public_key, sign_count), both strings base64url."""
    try:
        from webauthn import verify_registration_response
    except ImportError as e:
        raise SignatureError("webauthn is not installed; passkeys cannot be registered") from e
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id(),
                                         expected_origin=expected_origins(), require_user_verification=True)
    except Exception as e:
        raise SignatureError(f"passkey registration failed: {e}") from e
    return b64url(v.credential_id), b64url(v.credential_public_key), v.sign_count

# ---------- verification ----------

def verify_passkey(typed_data: dict, signature: str, passkeys: dict, check_counter: bool = True) -> tuple[str, str, int]:
    """`passkeys` maps credential_id -> Passkey row. Returns (signer id, credential_id, new sign count).

    Re-verification later (e.g. by the executor) skips the counter: it only detects cloned authenticators
    at the moment a signature is first submitted."""
    try:
        from webauthn import verify_authentication_response
    except ImportError as e:
        raise SignatureError("webauthn is not installed; passkey signatures cannot be verified") from e
    try:
        credential = json.loads(signature[len(PREFIX):])
        row = passkeys.get(credential.get("id"))
    except (ValueError, AttributeError) as e:
        raise SignatureError("malformed passkey signature") from e
    if row is None:
        raise SignatureError("unknown passkey")
    try:
        v = verify_authentication_response(
            credential=credential, expected_challenge=challenge_for(typed_data), expected_rp_id=rp_id(),
            expected_origin=expected_origins(), credential_public_key=from_b64url(row.public_key),
            credential_current_sign_count=row.sign_count if check_counter else 0, require_user_verification=True,
        )
    except Exception as e:
        raise SignatureError(f"invalid passkey signature: {e}") from e
    return PASSKEY_SIGNER + row.name, row.credential_id, v.new_sign_count

def verify_any(typed_data: dict, signature: str, db, approvers_cfg: dict, *, check_counter: bool = True) -> str:
    """Verify a wallet or passkey signature and return the signer id if it belongs to a registered approver.

    Raises SignatureError for a bad signature and PermissionError for a valid signature from a non-approver."""
    from trader.store.models import Passkey
    if not signature.startswith(PREFIX):
        signer = verify_signature(typed_data, signature)
        if signer not in approver_registry(approvers_cfg):  # an empty registry means nobody can sign
            raise PermissionError(f"Signer {signer} is not in the approver registry")
        return signer
    rows = {p.credential_id: p for p in db.query(Passkey).all()}
    signer, cred_id, count = verify_passkey(typed_data, signature, rows, check_counter)
    if check_counter:
        rows[cred_id].sign_count = count  # committed with the caller's transaction
    return signer

def person(signer: str, approvers_cfg: dict) -> str:
    """Who a signer is, for threshold counting: one person with a wallet and a passkey counts once.
    A passkey enrolled under the same name as a wallet in approvers.yaml is the same person."""
    if signer.startswith(PASSKEY_SIGNER):
        return signer[len(PASSKEY_SIGNER):]
    for a in approvers_cfg.get("approvers", []):
        if a.get("address", "").lower() == signer and a.get("name") and a["name"] != "env":
            return a["name"]
    return signer
