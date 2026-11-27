import { createPublicKey, verify } from "node:crypto";
// The latest GitHub release: which files are for this computer, their sizes and checksums.

export const REPO = "TonyD365/YTKTV";

export type App = "YTKTV" | "YTKTV-Desk";
export const APPS: App[] = ["YTKTV", "YTKTV-Desk"];
export const label = (app: App) => app.replace("-", " ");

export interface Asset {
  name: string;
  size: number;
  browser_download_url: string;
}
export interface Release {
  tag_name: string;
  assets: Asset[];
}

/** The release file of *app* that ends in *suffix* (YTKTV must not match YTKTV-Desk). */
export function assetFor(release: Release, app: App, suffix: string): Asset | undefined {
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`^${escape(app)}-\\d[^/]*-${escape(suffix)}$`);
  return release.assets.find((asset) => pattern.test(asset.name));
}

// Ed25519 keys whose signature on SHA256SUMS (SHA256SUMS.sig) makes a release trusted: the same
// two as the app's (src/ytktv/updater.py, UPDATE_KEYS), base64 of the raw 32 bytes.
export const UPDATE_KEYS = [
  "kI2UujGRZlf32S3GcLwXe7/N2DEjMuvpRZ8rcmwyxrw=",
  "6kKFQPUmqNLUkcIt9QzSf4fMJvEpuyuBAfQJQyZPi04=",
];
// The DER prefix that turns a raw Ed25519 public key into SubjectPublicKeyInfo.
const ED25519_SPKI = Buffer.from("302a300506032b6570032100", "hex");

/** Whether *signature* (base64 text) signs *sums* with one of *keys*. */
export function sumsSigned(sums: string | Uint8Array, signature: string, keys: string[] = UPDATE_KEYS): boolean {
  const data = typeof sums === "string" ? Buffer.from(sums, "utf8") : Buffer.from(sums);
  const sig = Buffer.from(signature.trim(), "base64");
  if (sig.length !== 64) return false;
  return keys.some((key) => {
    try {
      const raw = Buffer.from(key, "base64");
      const publicKey = createPublicKey({ key: Buffer.concat([ED25519_SPKI, raw]), format: "der", type: "spki" });
      return verify(null, data, publicKey, sig);
    } catch {
      return false;
    }
  });
}

/** "file name → sha256" from a SHA256SUMS file. */
export function parseSums(text: string): Map<string, string> {
  const sums = new Map<string, string>();
  for (const line of text.split(/\r?\n/)) {
    const match = line.trim().match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (match) sums.set(match[2], match[1].toLowerCase());
  }
  return sums;
}

/** -1, 0 or 1, comparing "4.1.2"-style versions. */
export function compareVersions(a: string, b: string): number {
  const pa = a.replace(/^v/, "").split(".").map((n) => Number.parseInt(n, 10) || 0);
  const pb = b.replace(/^v/, "").split(".").map((n) => Number.parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d > 0 ? 1 : -1;
  }
  return 0;
}

export async function fetchText(url: string, tries = 3): Promise<string> {
  let last: unknown;
  for (let i = 0; i < tries; i++) {
    try {
      const headers: Record<string, string> = { "User-Agent": "ytktv-installer" };
      // A token raises GitHub's limit for anonymous API calls (CI machines share addresses).
      const token = process.env.GITHUB_TOKEN;
      if (token && url.startsWith("https://api.github.com/")) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(url, { headers });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.text();
    } catch (error) {
      last = error;
      await Bun.sleep(1000 * (i + 1));
    }
  }
  throw last;
}

export async function latestRelease(): Promise<Release> {
  return JSON.parse(await fetchText(`https://api.github.com/repos/${REPO}/releases/latest`));
}

/** A text from the repository at *tag*, or from main when that tag does not have it. */
export async function repoText(tag: string, path: string): Promise<string> {
  for (const ref of [tag, "main"]) {
    try {
      return await fetchText(`https://raw.githubusercontent.com/${REPO}/${ref}/${path}`, 1);
    } catch {}
  }
  return "";
}
