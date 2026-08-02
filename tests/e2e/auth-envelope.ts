/**
 * Browser-independent password-envelope helper for direct Playwright API calls.
 *
 * UI authentication already uses the browser WebCrypto helper.  E2E setup uses
 * a Node request context instead, so it must independently preserve the same
 * no-plaintext wire contract rather than bypassing it for test convenience.
 */
import { webcrypto } from "node:crypto";

interface PasswordKeyResponse {
  keyId: string;
  algorithm: "RSA-OAEP-256+A256GCM";
  publicKeyPem: string;
}

interface PasswordKeyRequestContext {
  get(url: string): Promise<{
    ok(): boolean;
    json(): Promise<unknown>;
  }>;
}

function isPasswordKeyResponse(value: unknown): value is PasswordKeyResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.keyId === "string"
    && candidate.algorithm === "RSA-OAEP-256+A256GCM"
    && typeof candidate.publicKeyPem === "string"
  );
}

function pemToDer(pem: string): Uint8Array {
  const body = pem
    .replace(/-----BEGIN PUBLIC KEY-----/g, "")
    .replace(/-----END PUBLIC KEY-----/g, "")
    .replace(/\s/g, "");
  return new Uint8Array(Buffer.from(body, "base64"));
}

function base64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64");
}

/** Fetch the server key and produce one fresh RSA-OAEP + AES-GCM envelope. */
export async function createPasswordEnvelope(
  context: PasswordKeyRequestContext,
  password: string,
): Promise<Record<string, string>> {
  const keyResponse = await context.get("/api/auth/password-key");
  if (!keyResponse.ok()) {
    // Do not include a response body: a setup failure should not accidentally
    // surface environment-specific details in CI output.
    throw new Error("Password encryption key is unavailable");
  }
  const key = await keyResponse.json();
  if (!isPasswordKeyResponse(key)) {
    throw new Error("Password encryption key response is invalid");
  }

  const publicKey = await webcrypto.subtle.importKey(
    "spki",
    pemToDer(key.publicKeyPem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
  const rawAesKey = webcrypto.getRandomValues(new Uint8Array(32));
  const aesKey = await webcrypto.subtle.importKey(
    "raw",
    rawAesKey,
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await webcrypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    aesKey,
    new TextEncoder().encode(password),
  );
  const encryptedKey = await webcrypto.subtle.encrypt(
    { name: "RSA-OAEP" },
    publicKey,
    rawAesKey,
  );

  return {
    keyId: key.keyId,
    encryptedKey: base64(new Uint8Array(encryptedKey)),
    iv: base64(iv),
    ciphertext: base64(new Uint8Array(ciphertext)),
  };
}
