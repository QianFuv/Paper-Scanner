import { getAuthConfig } from "@/lib/auth-config";

const AUTH_COOKIE_NAME = "ps_auth";

type AuthSession = {
  tokenHash: string;
};

let cachedTokenHashes: string[] | null = null;
let cachedTokenHashesPromise: Promise<string[]> | null = null;
let cachedKey: CryptoKey | null = null;

async function getAuthTokens(): Promise<string[]> {
  const config = await getAuthConfig();
  return config.tokens;
}

async function getAuthSecret(): Promise<string> {
  const config = await getAuthConfig();
  return config.secret;
}

async function getSigningKey(): Promise<CryptoKey> {
  if (cachedKey) return cachedKey;
  const secret = await getAuthSecret();
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
  cachedKey = key;
  return key;
}

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function hashToken(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return toHex(digest);
}

async function getAuthTokenHashes(): Promise<string[]> {
  if (cachedTokenHashes) return cachedTokenHashes;
  if (cachedTokenHashesPromise) return cachedTokenHashesPromise;
  cachedTokenHashesPromise = getAuthTokens()
    .then((tokens) => Promise.all(tokens.map(hashToken)))
    .then((hashes) => {
      cachedTokenHashes = hashes;
      return hashes;
    });
  return cachedTokenHashesPromise;
}

function safeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) {
    diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return diff === 0;
}

async function signValue(value: string): Promise<string> {
  const key = await getSigningKey();
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(value),
  );
  return toHex(signature);
}

async function getExpiryMillis(): Promise<number> {
  const config = await getAuthConfig();
  const hours = Number.isFinite(config.ttlHours) && config.ttlHours > 0
    ? config.ttlHours
    : 168;
  return hours * 60 * 60 * 1000;
}

function buildAuthToken(tokenHash: string, issuedAt: number, signature: string): string {
  return `${tokenHash}|${issuedAt}|${signature}`;
}

function parseAuthToken(
  token: string,
): { tokenHash: string; issuedAt: number; signature: string } | null {
  const parts = token.split("|");
  if (parts.length !== 3) return null;
  const [tokenHash, issuedRaw, signature] = parts;
  const issuedAt = Number(issuedRaw);
  if (!tokenHash || !signature || !Number.isFinite(issuedAt)) return null;
  return { tokenHash, issuedAt, signature };
}

async function createAuthToken(rawToken: string): Promise<string> {
  const issuedAt = Date.now();
  const tokenHash = await hashToken(rawToken);
  const payload = `${tokenHash}|${issuedAt}`;
  const signature = await signValue(payload);
  return buildAuthToken(tokenHash, issuedAt, signature);
}

async function verifyAuthToken(token: string): Promise<AuthSession | null> {
  const parsed = parseAuthToken(token);
  if (!parsed) return null;
  const { tokenHash, issuedAt, signature } = parsed;
  const tokenHashes = await getAuthTokenHashes();
  if (!tokenHashes.includes(tokenHash)) return null;
  const now = Date.now();
  if (now - issuedAt > (await getExpiryMillis())) return null;
  const payload = `${tokenHash}|${issuedAt}`;
  const expected = await signValue(payload);
  if (!safeEqual(signature, expected)) return null;
  return { tokenHash };
}

async function verifyToken(rawToken: string): Promise<boolean> {
  const tokens = await getAuthTokens();
  return tokens.includes(rawToken);
}

export {
  AUTH_COOKIE_NAME,
  createAuthToken,
  getAuthTokens,
  getExpiryMillis,
  verifyAuthToken,
  verifyToken,
};
export type { AuthSession };
