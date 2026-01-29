import { readFile } from "node:fs/promises";
import path from "node:path";

type AuthConfig = {
  tokens: string[];
  secret: string;
  ttlHours: number;
};

const DEFAULT_TTL_HOURS = 168;
const CONFIG_PATH =
  process.env.AUTH_CONFIG_PATH ??
  path.join(process.cwd(), "config", "auth.yaml");

let cachedConfig: AuthConfig | null = null;
let cachedConfigPromise: Promise<AuthConfig> | null = null;

function stripQuotes(value: string): string {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function parseAuthConfig(content: string): AuthConfig {
  const tokens: string[] = [];
  let secret = "";
  let ttlHours = DEFAULT_TTL_HOURS;
  let inTokens = false;

  const lines = content.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    if (line.startsWith("tokens:")) {
      inTokens = true;
      const inline = line.slice("tokens:".length).trim();
      if (inline) {
        tokens.push(stripQuotes(inline));
      }
      continue;
    }

    if (inTokens && line.startsWith("-")) {
      const tokenValue = stripQuotes(line.slice(1).trim());
      if (tokenValue) tokens.push(tokenValue);
      continue;
    }

    inTokens = false;

    if (line.startsWith("secret:")) {
      secret = stripQuotes(line.slice("secret:".length).trim());
      continue;
    }

    if (line.startsWith("ttl_hours:")) {
      const rawValue = line.slice("ttl_hours:".length).trim();
      const parsed = Number(stripQuotes(rawValue));
      if (Number.isFinite(parsed) && parsed > 0) {
        ttlHours = parsed;
      }
    }
  }

  const uniqueTokens = Array.from(new Set(tokens.filter(Boolean)));

  if (!secret) {
    throw new Error("Auth config secret is missing");
  }

  if (uniqueTokens.length === 0) {
    throw new Error("Auth config tokens are missing");
  }

  return {
    tokens: uniqueTokens,
    secret,
    ttlHours,
  };
}

async function loadAuthConfig(): Promise<AuthConfig> {
  const raw = await readFile(CONFIG_PATH, "utf-8");
  return parseAuthConfig(raw);
}

async function getAuthConfig(): Promise<AuthConfig> {
  if (cachedConfig) return cachedConfig;
  if (cachedConfigPromise) return cachedConfigPromise;
  cachedConfigPromise = loadAuthConfig().then((config) => {
    cachedConfig = config;
    return config;
  });
  return cachedConfigPromise;
}

export type { AuthConfig };
export { getAuthConfig };
