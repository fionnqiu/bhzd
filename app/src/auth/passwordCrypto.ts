/**
 * Password request-envelope helpers.
 *
 * The browser encrypts each password with a fresh AES-GCM key and only sends
 * that key wrapped by the server's short-lived RSA public key.  This reduces
 * plaintext exposure in request bodies and logs; HTTPS remains mandatory.
 */
import { api } from "../api/client";

export interface PasswordEnvelope {
  keyId: string;
  encryptedKey: string;
  iv: string;
  ciphertext: string;
}

interface PasswordKeyResponse {
  keyId: string;
  algorithm: "RSA-OAEP-256+A256GCM";
  publicKeyPem: string;
}

function bytesToBase64(bytes: Uint8Array): string {
  // Avoid a spread into String.fromCharCode: ciphertext may be larger than the
  // engine argument limit even though ordinary passwords are short today.
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function pemToDer(pem: string): ArrayBuffer {
  const encoded = pem
    .replace(/-----BEGIN PUBLIC KEY-----/g, "")
    .replace(/-----END PUBLIC KEY-----/g, "")
    .replace(/\s/g, "");
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

/** Encrypt one password with the currently advertised server key. */
export async function createPasswordEnvelope(password: string): Promise<PasswordEnvelope> {
  if (!globalThis.crypto?.subtle) {
    // Never silently fall back to a plaintext request in an unsupported browser.
    throw new Error("当前浏览器不支持安全密码加密，请升级浏览器后重试");
  }

  const key = await api.get<PasswordKeyResponse>("/api/auth/password-key");
  const publicKey = await globalThis.crypto.subtle.importKey(
    "spki",
    pemToDer(key.publicKeyPem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
  const rawAesKey = globalThis.crypto.getRandomValues(new Uint8Array(32));
  const aesKey = await globalThis.crypto.subtle.importKey(
    "raw",
    rawAesKey,
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await globalThis.crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    aesKey,
    new TextEncoder().encode(password),
  );
  const encryptedKey = await globalThis.crypto.subtle.encrypt(
    { name: "RSA-OAEP" },
    publicKey,
    rawAesKey,
  );

  return {
    keyId: key.keyId,
    encryptedKey: bytesToBase64(new Uint8Array(encryptedKey)),
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  };
}
