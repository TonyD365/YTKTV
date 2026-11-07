// Downloads with progress, going on where it stopped when the network drops.
import { createWriteStream, existsSync, statSync } from "node:fs";

export interface Progress {
  done: number;
  total: number;
  speed: number; // bytes per second
  attempt: number;
}

export async function download(
  url: string,
  file: string,
  total: number,
  onProgress: (progress: Progress) => void,
  tries = 5,
): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= tries; attempt++) {
    let done = existsSync(file) ? statSync(file).size : 0;
    if (total && done >= total) return;
    try {
      const headers: Record<string, string> = { "User-Agent": "ytktv-installer" };
      if (done) headers.Range = `bytes=${done}-`;
      const response = await fetch(url, { headers });
      if (response.status === 200 && done) done = 0; // the server ignored the range: start over
      else if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      if (!total) total = done + Number(response.headers.get("content-length") ?? 0);
      const out = createWriteStream(file, { flags: done ? "a" : "w" });
      const reader = response.body!.getReader();
      let windowStart = Date.now();
      let windowBytes = 0;
      let speed = 0;
      for (;;) {
        const { done: finished, value } = await reader.read();
        if (finished) break;
        if (!out.write(value)) await new Promise((resolve) => out.once("drain", resolve));
        done += value.length;
        windowBytes += value.length;
        const elapsed = (Date.now() - windowStart) / 1000;
        if (elapsed >= 0.5) {
          speed = speed ? speed * 0.6 + (windowBytes / elapsed) * 0.4 : windowBytes / elapsed;
          windowStart = Date.now();
          windowBytes = 0;
        }
        onProgress({ done, total, speed, attempt });
      }
      await new Promise<void>((resolve, reject) => out.end((error?: Error) => (error ? reject(error) : resolve())));
      if (total && statSync(file).size < total) throw new Error("the download ended early");
      onProgress({ done: total || done, total: total || done, speed, attempt });
      return;
    } catch (error) {
      lastError = error;
      if (attempt < tries) {
        onProgress({ done, total, speed: 0, attempt: attempt + 1 });
        await Bun.sleep(2000 * attempt);
      }
    }
  }
  throw lastError;
}

export async function sha256(file: string): Promise<string> {
  const hasher = new Bun.CryptoHasher("sha256");
  const stream = Bun.file(file).stream();
  for await (const chunk of stream) hasher.update(chunk);
  return hasher.digest("hex");
}
