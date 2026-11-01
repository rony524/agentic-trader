// Passkeys (WebAuthn): approve with Face ID, a fingerprint, Windows Hello or a phone. No wallet or extension.
// The device signs a challenge the API derives from the exact proposal, so the signature is verifiable later.

export type PasskeyRequest = { challenge: string; rp_id: string; allow_credentials: string[] };

const toB64url = (buf: ArrayBuffer) =>
  btoa(String.fromCharCode(...Array.from(new Uint8Array(buf)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

const fromB64url = (s: string): ArrayBuffer => {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, c => c.charCodeAt(0)).buffer as ArrayBuffer;
};

export const passkeysSupported = () => typeof window !== "undefined" && !!window.PublicKeyCredential;

// Returns the signature string the API expects: "webauthn:" + assertion JSON.
export async function signWithPasskey(req: PasskeyRequest): Promise<string> {
  if (!passkeysSupported()) throw new Error("This browser doesn't support passkeys");
  if (!req.allow_credentials.length) throw new Error("No approver passkeys are registered yet. Ask an admin for an enrollment link.");
  const cred = (await navigator.credentials.get({
    publicKey: {
      challenge: fromB64url(req.challenge),
      rpId: req.rp_id,
      allowCredentials: req.allow_credentials.map(id => ({ type: "public-key" as const, id: fromB64url(id) })),
      userVerification: "required",
      timeout: 60000,
    },
  })) as PublicKeyCredential | null;
  if (!cred) throw new Error("Passkey prompt was cancelled");
  const r = cred.response as AuthenticatorAssertionResponse;
  return "webauthn:" + JSON.stringify({
    id: cred.id, rawId: toB64url(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      authenticatorData: toB64url(r.authenticatorData),
      signature: toB64url(r.signature),
      userHandle: r.userHandle ? toB64url(r.userHandle) : null,
    },
  });
}

// `options` is the server's registration options JSON (base64url fields); returns the credential JSON to POST back.
export async function createPasskey(options: any): Promise<any> {
  if (!passkeysSupported()) throw new Error("This browser doesn't support passkeys");
  const cred = (await navigator.credentials.create({
    publicKey: {
      ...options,
      challenge: fromB64url(options.challenge),
      user: { ...options.user, id: fromB64url(options.user.id) },
      excludeCredentials: (options.excludeCredentials || []).map((c: any) => ({ ...c, id: fromB64url(c.id) })),
    },
  })) as PublicKeyCredential | null;
  if (!cred) throw new Error("Passkey creation was cancelled");
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id, rawId: toB64url(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      attestationObject: toB64url(r.attestationObject),
      transports: r.getTransports?.() ?? [],
    },
  };
}
