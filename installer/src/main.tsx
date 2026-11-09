// The YTKTV installer: pick YTKTV, YTKTV Desk or both, read and accept the license, then
// it checks the disk, closes running copies, downloads (with resume), verifies, installs,
// offers mpv, and can open the apps. Run by site/install.sh and site/install.ps1.
import { closeSync, mkdtempSync, openSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Text } from "ink";
import { download, sha256 } from "./download";
import notices from "./notices.txt" with { type: "text" };
import {
  APPS,
  type App,
  type Release,
  assetFor,
  compareVersions,
  fetchText,
  label,
  latestRelease,
  parseSums,
  repoText,
} from "./release";
import * as sys from "./system";
import { CYAN, Cancelled, PINK, Done, Failed, Header, Note, Page, checklist, page, print, progress, select, task } from "./ui";

const HELP = `YTKTV installer

  ytktv-installer [--room] [--desk] [--yes]

  --room   install YTKTV (for a karaoke room)
  --desk   install YTKTV Desk (for the front desk)
  --yes    accept the license and take the defaults without asking
  --licenses   the licenses of what this program is built from
`;

const args = new Set(process.argv.slice(2));
const YES = args.has("--yes") || args.has("-y");
const mb = (bytes: number) => Math.ceil(bytes / 1048576);
const pages = (app: App) => (app === "YTKTV-Desk" ? "desk" : "ytktv");

function status(app: App, latest: string): string {
  const have = sys.installedVersion(app);
  if (!have) return "not installed";
  if (have === "?") return "installed (version unknown)";
  const order = compareVersions(latest, have);
  if (order === 0) return `${have} installed · up to date`;
  return order > 0 ? `${have} installed → update to ${latest}` : `${have} installed · newer than ${latest}`;
}

async function chooseApps(latest: string): Promise<App[]> {
  const asked = APPS.filter((app) => args.has(app === "YTKTV" ? "--room" : "--desk"));
  if (asked.length || YES) return asked.length ? asked : ["YTKTV"];
  const ticks = await checklist(
    "What do you want to install?",
    [
      { label: "YTKTV", hint: `for a karaoke room · ${status("YTKTV", latest)}` },
      { label: "YTKTV Desk", hint: `for the front desk · ${status("YTKTV-Desk", latest)}` },
    ],
    [true, false],
  );
  return APPS.filter((_, i) => ticks[i]);
}

/** On macOS, asks for the password here in the terminal, saying why (sudo keeps it a while). */
async function askPassword(app: App): Promise<void> {
  if (Bun.spawnSync(["sudo", "-n", "true"], { stdout: "ignore", stderr: "ignore" }).exitCode === 0) return;
  await print(
    <Note text={`Your Mac password is needed to put ${label(app)} in /Applications (macOS's installer runs as administrator). It is typed here, not shown, and not stored.`} />,
  );
  const code = await runInTerminal(["sudo", "-v", "-p", "  Mac password for %u: "]);
  if (code !== 0) throw new Error("No password was given, so nothing was installed.");
}

/**
 * Runs *command* in the terminal (sudo's password prompt, brew). It gets its own handle on the
 * terminal: sharing ours lets it switch the terminal handle to blocking reads, and after that
 * the installer froze on the next key press in a menu.
 */
async function runInTerminal(command: string[]): Promise<number> {
  let tty: number | undefined;
  try {
    tty = openSync("/dev/tty", "r+");
  } catch {
    tty = undefined;
  }
  try {
    const io = tty ?? "inherit";
    return await Bun.spawn(command, { stdio: [io, io, io] }).exited;
  } finally {
    if (tty !== undefined) closeSync(tty);
  }
}

/**
 * Asks with buttons: each option is a key in brackets, like [O] Open  [N] Not now; type the
 * key and press enter (enter alone takes the first). After sudo the terminal can no longer
 * be read through Ink, so on macOS and Linux the answer is read by sh from its own /dev/tty.
 */
async function buttons(question: string, options: { key: string; label: string }[]): Promise<number> {
  if (sys.SYSTEM === "Windows") return select(question, options.map((o) => ({ label: o.label })));
  const row = options.map((o) => `[${o.key}] ${o.label}`).join("   ");
  for (;;) {
    await print(
      <Text>
        <Text color={PINK}>? </Text>
        <Text bold>{question}</Text> <Text color={CYAN}>{row}</Text>
      </Text>,
    );
    const reader = Bun.spawn(["sh", "-c", 'printf "  > " >/dev/tty; IFS= read -r a </dev/tty && printf %s "$a"'], {
      stdin: "ignore",
      stdout: "pipe",
      stderr: "ignore",
    });
    const answer = (await new Response(reader.stdout).text()).trim().toLowerCase();
    if ((await reader.exited) !== 0) throw new Cancelled();
    if (answer === "") return 0;
    const i = options.findIndex((o) => o.key.toLowerCase() === answer || o.label.toLowerCase() === answer);
    if (i >= 0) return i;
  }
}

async function main(): Promise<void> {
  if (args.has("--help") || args.has("-h")) return void (await Bun.write(Bun.stdout, HELP));
  if (args.has("--licenses")) return void (await Bun.write(Bun.stdout, notices));
  if (!YES && !process.stdin.isTTY) {
    throw new Error("Cannot ask questions without a terminal. Run again with --yes to accept the license.");
  }

  const release: Release = await task("Looking up the latest release…", latestRelease, (r) => `Latest release: ${r.tag_name}`);
  const latest = release.tag_name.replace(/^v/, "");
  await print(<Header version={release.tag_name} system={`${sys.SYSTEM} (${sys.ARCH_LABEL})`} />);

  // What to install, skipping (unless asked) what is already up to date.
  let apps = await chooseApps(latest);
  const keep: App[] = [];
  for (const app of apps) {
    if (sys.installedVersion(app) !== latest) {
      keep.push(app);
    } else if (YES) {
      await print(<Done text={`${label(app)} ${latest} is already installed`} />);
    } else {
      const again = await select(`${label(app)} ${latest} is already installed.`, [
        { label: "Skip", hint: "keep it as it is" },
        { label: "Reinstall", hint: "download and install it again" },
      ]);
      if (again === 1) keep.push(app);
    }
  }
  apps = keep;
  if (!apps.length) return void (await print(<Done text="Nothing to do: everything is up to date." />));

  const assets = apps.map((app) => {
    const asset = assetFor(release, app, sys.suffix());
    if (!asset) throw new Error(`The latest release has no ${label(app)} file for this computer yet. Try again in a while.`);
    return asset;
  });
  const names = apps.map(label).join(" and ");

  // What it is, and what happens next.
  for (const app of apps) {
    const text = await repoText(release.tag_name, `packaging/installer/${pages(app)}-welcome.txt`);
    if (text) await print(<Page text={text} />);
  }
  const steps = apps.map((app, i) => {
    const have = sys.installedVersion(app);
    const what = !have ? `install ${latest}` : have === latest ? `reinstall ${latest}` : `${have} → ${latest}`;
    return `- ${label(app)}: ${what}, download ${mb(assets[i].size)} MB, to ${sys.appPath(app)}`;
  });
  if (sys.SYSTEM === "macOS") steps.push("- Your Mac password is asked for here in the terminal, to install into /Applications.");
  if (sys.SYSTEM === "Windows") steps.push("- Installed for you only (no administrator needed), and listed in Settings → Apps.");
  steps.push("- Running copies are closed first. Your settings, songs and records are kept.");
  if (apps.includes("YTKTV") && sys.mpvMissing()) steps.push("- mpv, which YTKTV plays songs with, is missing: you can install it at the end.");
  await print(<Page text={["What happens next", ...steps].join("\n")} color="#b18cff" />);

  // The license.
  if (YES) {
    await print(<Done text="License accepted (--yes)" />);
  } else {
    const license = await repoText(release.tag_name, "LICENSE");
    for (;;) {
      const choice = await select("Do you accept the YTKTV License?", [
        { label: "Accept", hint: `and install ${names}` },
        { label: "Read it", hint: "the whole license" },
        { label: "Cancel", hint: "install nothing" },
      ]);
      if (choice === 0) break;
      if (choice === 2) throw new Cancelled();
      await page("YTKTV License", license || "The license could not be downloaded; see https://github.com/TonyD365/YTKTV/blob/main/LICENSE");
    }
  }

  // Room on the disk: the download plus the installed app, about 3.5 times the download.
  const need = assets.reduce((sum, asset) => sum + asset.size * 3.5, 0);
  const free = sys.freeSpace();
  if (free && free < need) {
    throw new Error(`Not enough disk space: ${mb(need)} MB needed, ${mb(free)} MB free. Free some space and try again.`);
  }
  await print(<Done text={free ? `Disk space OK (${mb(free)} MB free, ${mb(need)} MB needed)` : "Disk space not checked"} />);

  // Close running copies.
  for (const app of apps) {
    if (!sys.isRunning(app)) continue;
    if (!YES) {
      const choice = await select(`${label(app)} is running. It has to close to be updated.`, [
        { label: "Close it", hint: "and go on" },
        { label: "Cancel", hint: "install nothing" },
      ]);
      if (choice !== 0) throw new Cancelled();
    }
    await task(`Closing ${label(app)}…`, () => sys.close(app), () => `Closed ${label(app)}`);
  }

  // Download, check and install each.
  const sumsAsset = release.assets.find((asset) => asset.name === "SHA256SUMS");
  const sums = sumsAsset ? parseSums(await fetchText(sumsAsset.browser_download_url).catch(() => "")) : new Map();
  const work = mkdtempSync(join(tmpdir(), "ytktv-install-"));
  try {
    for (const [i, app] of apps.entries()) {
      const asset = assets[i];
      const file = join(work, asset.name);
      await progress(asset.name, (update) => download(asset.browser_download_url, file, asset.size, update));
      // Without a checksum to compare with, nothing is installed.
      const expected = sums.get(asset.name);
      if (!expected) {
        throw new Error(`Could not get the checksum for ${asset.name} (SHA256SUMS), so it was not installed. Please try again in a few minutes.`);
      }
      await task("Checking the download…", async () => {
        if ((await sha256(file)) !== expected) throw new Error("The download is damaged (checksum mismatch). Please try again.");
      }, () => "Checksum OK");
      if (sys.SYSTEM === "macOS") await askPassword(app);
      await task(`Installing ${label(app)} ${latest}…`, () => sys.install(app, file, latest), () => `Installed ${label(app)} ${latest}`);
    }
  } finally {
    rmSync(work, { recursive: true, force: true });
    // Done with root: forget the password now rather than leaving sudo open for minutes.
    if (sys.SYSTEM === "macOS") Bun.spawnSync(["sudo", "-k"], { stdout: "ignore", stderr: "ignore" });
  }

  // mpv, for YTKTV (the Desk does not play songs).
  if (apps.includes("YTKTV") && sys.mpvMissing()) {
    const command = sys.mpvInstaller();
    if (!command) {
      await print(<Note text="YTKTV plays songs through mpv. It offers to install it when it first opens." />);
    } else {
      const go = YES
        ? 1
        : await buttons(`YTKTV plays songs through mpv, which is not on this computer. Install it now (runs: ${command.join(" ")})?`, [
            { key: "I", label: "Install mpv" },
            { key: "L", label: "Later" },
          ]);
      if (go === 0) {
        await print(<Text color={CYAN}>$ {command.join(" ")}</Text>);
        const code = await runInTerminal(command);
        await print(code === 0 ? <Done text="Installed mpv" /> : <Note text="mpv was not installed. YTKTV offers it when it first opens." />);
      } else if (YES) {
        await print(<Note text={`YTKTV needs mpv to play songs. Install it with: ${command.join(" ")}`} />);
      }
    }
  }

  // How to start, and start it.
  for (const app of apps) {
    const text = await repoText(release.tag_name, `packaging/installer/${pages(app)}-done.txt`);
    if (text) await print(<Page text={text} color="green" />);
  }
  if (YES) return;
  const options = apps.map((app) => ({ key: app === "YTKTV" ? "Y" : "D", label: `Open ${label(app)}` }));
  if (apps.length > 1) options.push({ key: "B", label: "Open both" });
  options.push({ key: "N", label: "Not now" });
  const choice = await buttons("Open it now?", options);
  if (choice < apps.length) sys.open(apps[choice]);
  else if (apps.length > 1 && choice === apps.length) apps.forEach(sys.open);
}

main()
  .then(() => process.exit(0))
  .catch(async (error) => {
    const text = error instanceof Cancelled ? "Cancelled, nothing more was installed." : String(error?.message ?? error);
    await print(<Failed text={text} />);
    process.exit(1);
  });
