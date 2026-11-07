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
