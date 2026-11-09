// What this computer has and how to install on it: macOS, Windows or Linux.
import { existsSync, readFileSync, renameSync, chmodSync, mkdirSync, writeFileSync, statfsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { type App, label } from "./release";

export type System = "macOS" | "Windows" | "Linux";

export const SYSTEM: System =
  process.platform === "darwin" ? "macOS" : process.platform === "win32" ? "Windows" : "Linux";
const ARM = process.arch === "arm64";
export const ARCH_LABEL = ARM ? (SYSTEM === "macOS" ? "Apple Silicon" : "ARM") : SYSTEM === "macOS" ? "Intel" : "x64";

/** The end of the release file's name for this computer. */
export function suffix(): string {
  if (SYSTEM === "macOS") return "macos-universal.pkg";
  if (SYSTEM === "Windows") return `windows-${ARM ? "arm64" : "x64"}-setup.exe`;
  return `linux-${ARM ? "aarch64" : "x86_64"}.AppImage`;
}

const WINDOWS_KEYS: Record<App, string> = {
  YTKTV: "{6B0C5B0E-6C1B-4D0B-9E0F-59A7C0E6B2A1}_is1",
  "YTKTV-Desk": "{C2E7A1D4-3F6B-4E58-9A21-7D0B5E4C8F13}_is1",
};
const exeName = (app: App) => `${label(app)}.exe`;

function run(command: string[]): { ok: boolean; out: string } {
  try {
    const result = Bun.spawnSync(command, { stdout: "pipe", stderr: "pipe" });
    return { ok: result.exitCode === 0, out: result.stdout.toString() };
  } catch {
    return { ok: false, out: "" };
  }
}

function registry(app: App, value: string): string | undefined {
  for (const hive of ["HKCU", "HKLM"]) {
    const key = `${hive}\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${WINDOWS_KEYS[app]}`;
    const { ok, out } = run(["reg", "query", key, "/v", value]);
    const match = ok ? out.match(new RegExp(`${value}\\s+REG_\\w+\\s+(.+)`)) : null;
    if (match) return match[1].trim();
  }
  return undefined;
}

/** Where the app is, or will be, installed. */
export function appPath(app: App): string {
  if (SYSTEM === "macOS") return `/Applications/${label(app)}.app`;
  if (SYSTEM === "Linux") return join(homedir(), "Applications", `${app}.AppImage`);
  const location = registry(app, "InstallLocation");
  return join(location ?? join(process.env.LOCALAPPDATA ?? homedir(), "Programs", label(app)), exeName(app));
}

/** The installed version: undefined when not installed, "?" when it cannot be told. */
export function installedVersion(app: App): string | undefined {
  if (SYSTEM === "Windows") return registry(app, "DisplayVersion");
  const path = appPath(app);
  if (!existsSync(path)) return undefined;
  if (SYSTEM === "macOS") {
    const { ok, out } = run(["defaults", "read", `${path}/Contents/Info.plist`, "CFBundleShortVersionString"]);
    return ok ? out.trim() : "?";
  }
  try {
    return readFileSync(`${path}.version`, "utf8").trim() || "?";
  } catch {
    return "?";
  }
}

export function isRunning(app: App): boolean {
  if (SYSTEM === "Windows") {
    const { out } = run(["tasklist", "/FI", `IMAGENAME eq ${exeName(app)}`, "/NH"]);
    return out.toLowerCase().includes(exeName(app).toLowerCase());
  }
  const pattern = SYSTEM === "macOS" ? `${appPath(app)}/Contents/MacOS/` : appPath(app);
  return run(["pgrep", "-f", pattern]).ok;
}

/** Asks the app to quit, then makes it. */
export async function close(app: App): Promise<void> {
  if (SYSTEM === "macOS") run(["osascript", "-e", `quit app "${label(app)}"`]);
  else if (SYSTEM === "Windows") run(["taskkill", "/IM", exeName(app)]);
  else run(["pkill", "-f", appPath(app)]);
  for (let i = 0; i < 30 && isRunning(app); i++) await Bun.sleep(500);
  if (!isRunning(app)) return;
  if (SYSTEM === "Windows") run(["taskkill", "/F", "/IM", exeName(app)]);
  else run(["pkill", "-9", "-f", SYSTEM === "macOS" ? `${appPath(app)}/Contents/MacOS/` : appPath(app)]);
  await Bun.sleep(1000);
}

/** Free bytes where the apps go, or 0 when it cannot be told. */
export function freeSpace(): number {
  let where = homedir();
  if (SYSTEM === "macOS") where = "/Applications";
  try {
    const stats = statfsSync(where);
    return Number(stats.bavail) * Number(stats.bsize);
  } catch {
    return 0;
  }
}

/** Installs the downloaded file. Throws with a message for the user when it fails. */
export async function install(app: App, file: string, version: string): Promise<void> {
  if (SYSTEM === "macOS" && run(["sudo", "-n", "true"]).ok) {
    // sudo works without a password here (already given in this terminal, or a CI machine).
    const result = Bun.spawn(["sudo", "-n", "/usr/sbin/installer", "-pkg", file, "-target", "/"], { stdout: "pipe", stderr: "pipe" });
    if ((await result.exited) !== 0) throw new Error(`The installer failed: ${(await new Response(result.stderr).text()).trim()}`);
    return;
  }
  if (SYSTEM === "macOS") {
    const prompt =
      `The YTKTV installer is installing ${label(app)} ${version}. ` +
      "It needs your password to put it in /Applications.";
    const script =
      'on run argv\ndo shell script "/usr/sbin/installer -pkg " & quoted form of (item 1 of argv) & ' +
      '" -target /" with prompt (item 2 of argv) with administrator privileges\nend run';
    const result = Bun.spawn(["osascript", "-e", script, file, prompt], { stdout: "pipe", stderr: "pipe" });
    if ((await result.exited) !== 0) {
      const error = (await new Response(result.stderr).text()).trim();
      throw new Error(error.includes("-128") ? "You cancelled the password request." : `The installer failed: ${error}`);
    }
    return;
  }
  if (SYSTEM === "Windows") {
    const args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/CLOSEAPPLICATIONS"];
    const code = await Bun.spawn([file, ...args], { stdout: "ignore", stderr: "ignore" }).exited;
    if (code !== 0) throw new Error(`The installer stopped with code ${code}.`);
    return;
  }
  // The version comes from the release's tag: write it only if it is a plain version number.
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`Unexpected version: ${version.slice(0, 40)}`);
  const target = appPath(app);
  mkdirSync(dirname(target), { recursive: true });
  renameSync(file, target);
  chmodSync(target, 0o755);
  writeFileSync(`${target}.version`, `${version}\n`);
}

export function open(app: App): void {
  const path = appPath(app);
  if (SYSTEM === "macOS") Bun.spawn(["open", path]);
  else Bun.spawn([path], { stdio: ["ignore", "ignore", "ignore"] }).unref();
}

/** The command that installs mpv here, or undefined when there is none (Windows: YTKTV does it). */
export function mpvInstaller(): string[] | undefined {
  const found = (name: string) => Bun.which(name) ?? ["/opt/homebrew/bin", "/usr/local/bin"].map((d) => `${d}/${name}`).find(existsSync);
  if (SYSTEM === "Windows" || found("mpv")) return undefined;
  if (SYSTEM === "macOS") {
    const brew = found("brew");
    return brew ? [brew, "install", "mpv"] : undefined;
  }
  if (Bun.which("apt-get")) return ["sudo", "apt-get", "install", "-y", "mpv", "libmpv2"];
  if (Bun.which("dnf")) return ["sudo", "dnf", "install", "-y", "mpv", "mpv-libs"];
  if (Bun.which("pacman")) return ["sudo", "pacman", "-S", "--noconfirm", "mpv"];
  if (Bun.which("zypper")) return ["sudo", "zypper", "install", "-y", "mpv"];
  return undefined;
}

export function mpvMissing(): boolean {
  if (SYSTEM === "Windows") return false;
  const found = (name: string) => Bun.which(name) ?? ["/opt/homebrew/bin", "/usr/local/bin"].map((d) => `${d}/${name}`).find(existsSync);
  return !found("mpv");
}
