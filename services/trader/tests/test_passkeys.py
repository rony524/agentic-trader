"""Passkey approvals: enrollment, signing a proposal/idea without a wallet, executor re-verification, revocation.

A software authenticator below produces real WebAuthn registration and assertion data (P-256 / ES256)."""
import base64, hashlib, json, os
import pytest

pytest.importorskip("webauthn")
import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from test_safety import FakeClient, _make_proposal, _status
from trader.approval.passkeys import person, rp_id, expected_origins

ADMIN = {"X-Admin-Token": "test-admin-token"}

def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

class SoftAuthenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.rp_hash = hashlib.sha256(rp_id().encode()).digest()
        self.origin = expected_origins()[0]

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin}).encode()

    def register(self, options: dict) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        attested = bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose
        auth_data = self.rp_hash + bytes([0x45]) + (0).to_bytes(4, "big") + attested  # UP | UV | AT
        return {"id": b64url(self.cred_id), "rawId": b64url(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64url(self._client_data("webauthn.create", options["challenge"])),
                             "attestationObject": b64url(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data}))}}

    def sign(self, challenge: str) -> str:
        self.count += 1
        auth_data = self.rp_hash + bytes([0x05]) + self.count.to_bytes(4, "big")  # UP | UV
        client_data = self._client_data("webauthn.get", challenge)
        sig = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return "webauthn:" + json.dumps({
            "id": b64url(self.cred_id), "rawId": b64url(self.cred_id), "type": "public-key",
            "response": {"clientDataJSON": b64url(client_data), "authenticatorData": b64url(auth_data),
                         "signature": b64url(sig), "userHandle": None}})

def _api():
    from fastapi.testclient import TestClient
    from trader.api.main import app
    return TestClient(app)

def _enroll(name: str) -> SoftAuthenticator:
    api, auth = _api(), SoftAuthenticator()
    url = api.post("/admin/passkey-invites", json={"name": name}, headers=ADMIN).json()["enroll_url"]
    code = url.split("code=")[1]
    opts = api.post("/passkeys/register/options", json={"code": code}).json()
    assert opts["name"] == name
    r = api.post("/passkeys/register", json={"code": code, "credential": auth.register(opts["options"])})
    assert r.status_code == 200, r.text
    assert api.post("/passkeys/register/options", json={"code": code}).status_code == 404  # single use
    return auth

def test_invites_need_admin_token():
    api = _api()
    assert api.post("/admin/passkey-invites", json={"name": "x"}).status_code == 403
    assert api.post("/passkeys/register/options", json={"code": "nope"}).status_code == 404

def test_passkey_approval_is_accepted_and_reverified_by_executor():
    from trader.execution import executor
    auth = _enroll("alice")
    assert any(p["credential_id"] == b64url(auth.cred_id) for p in _api().get("/passkeys").json()["passkeys"])

    pid = "test_passkey_approve"
    _make_proposal(pid, "PENDING_REVIEW")
    api = _api()
    td = api.get(f"/proposals/{pid}/typed-data", params={"decision": "APPROVE"}).json()
    sig = auth.sign(td["passkey"]["challenge"])
    r = api.post(f"/proposals/{pid}/signatures", json={"decision": "APPROVE", "signature": sig, "nonce": td["nonce"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "APPROVED", "signer": "passkey:alice", "message": "Signature recorded"}
    assert api.post(f"/proposals/{pid}/signatures", json={"decision": "APPROVE", "signature": sig, "nonce": td["nonce"]}).status_code == 409

    client = FakeClient()
    executor.execute_approved_proposals(client=client)
    assert len(client.submitted) == 2 and _status(pid) == "EXECUTED"

def test_passkey_signature_is_bound_to_the_exact_decision():
    auth = _enroll("bob")
    pid = "test_passkey_bound"
    _make_proposal(pid, "PENDING_REVIEW")
    api = _api()
    reject_td = api.get(f"/proposals/{pid}/typed-data", params={"decision": "REJECT"}).json()
    approve_td = api.get(f"/proposals/{pid}/typed-data", params={"decision": "APPROVE"}).json()
    sig = auth.sign(reject_td["passkey"]["challenge"])  # signed a REJECT ...
    r = api.post(f"/proposals/{pid}/signatures", json={"decision": "APPROVE", "signature": sig, "nonce": approve_td["nonce"]})
    assert r.status_code == 400  # ... so it can't be replayed as an APPROVE
    assert _status(pid) == "PENDING_REVIEW"

def test_revoked_passkey_cannot_sign_and_its_approvals_stop_counting():
    from trader.execution import executor
    auth = _enroll("carol")
    pid = "test_passkey_revoked"
    _make_proposal(pid, "PENDING_REVIEW")
    api = _api()
    td = api.get(f"/proposals/{pid}/typed-data", params={"decision": "APPROVE"}).json()
    assert api.post(f"/proposals/{pid}/signatures",
                    json={"decision": "APPROVE", "signature": auth.sign(td["passkey"]["challenge"]), "nonce": td["nonce"]}).status_code == 200

    assert api.delete(f"/admin/passkeys/{b64url(auth.cred_id)}", headers=ADMIN).status_code == 200
    client = FakeClient()
    executor.execute_approved_proposals(client=client)
    assert client.submitted == [] and _status(pid) == "FAILED"  # executor re-verifies against current registry

    pid2 = "test_passkey_revoked_2"
    _make_proposal(pid2, "PENDING_REVIEW")
    td = api.get(f"/proposals/{pid2}/typed-data", params={"decision": "APPROVE"}).json()
    r = api.post(f"/proposals/{pid2}/signatures",
                 json={"decision": "APPROVE", "signature": auth.sign(td["passkey"]["challenge"]), "nonce": td["nonce"]})
    assert r.status_code == 400 and "unknown passkey" in r.text

def test_idea_can_be_submitted_with_a_passkey(monkeypatch):
    from trader.agent import pipeline
    monkeypatch.setattr(pipeline, "process_idea", lambda idea_id: None)
    auth = _enroll("dana")
    api = _api()
    td = api.post("/ideas/typed-data", json={"text": "Reduce power exposure, utilities look stretched"}).json()
    r = api.post("/ideas", json={"text": "Reduce power exposure, utilities look stretched", "issued_at": td["issued_at"],
                                 "signature": auth.sign(td["passkey"]["challenge"])})
    assert r.status_code == 200, r.text
    assert r.json()["submitted_by"] == "passkey:dana"

def test_wallet_and_passkey_of_one_approver_count_once():
    cfg = {"approvers": [{"name": "alice", "address": "0xabc"}, {"name": "env", "address": "0xdef"}]}
    assert person("passkey:alice", cfg) == person("0xabc", cfg) == "alice"
    assert person("0xdef", cfg) == "0xdef"  # unnamed env approvers stay distinct
