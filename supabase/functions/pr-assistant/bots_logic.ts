// Decisions for commands, issue triage and file labels, with no network access.
import { addressed } from "./logic.ts";

export type Command = { cmd: string; arg: string; rest: string };

export function parseCommand(body: string): Command | null {
  const text = addressed(body);
  if (text === null) return null;
  const line = text.split("\n")[0].replaceAll("\r", "").trim();
  const m = line.match(/^(\/[A-Za-z]+)(?:\s+(.*))?$/);
  if (!m) return null;
  const rest = (m[2] ?? "").trim();
  return { cmd: m[1].toLowerCase(), arg: (rest.split(/\s+/)[0] ?? "").toLowerCase(), rest };
}

export function isMaintainer(role: string): boolean {
  return ["OWNER", "MEMBER", "COLLABORATOR"].includes(role);
}

export function remindSeconds(arg: string): number | null {
  const m = arg.match(/^([1-9][0-9]{0,2})([dh])$/);
  if (!m) return null;
  const seconds = Number(m[1]) * (m[2] === "d" ? 86400 : 3600);
  return seconds <= 30 * 86400 ? seconds : null;
}

export function labelNames(rest: string): string[] {
  return rest.split(/[,\s]+/).filter(Boolean);
}

export function reminderNote(rest: string): string {
  return rest.replace(/^\S+\s*/, "").replace(/[`<>@]/g, "").slice(0, 200);
}

// Areas from the issue forms' answers and plain keywords, in English and Chinese.
const AREAS: [RegExp, string][] = [
  [/desk|front desk|staff terminal|前台|管理终端|server mode/, "desk"],
  [/microphone|mixer|mixing console|麦克风|调音/, "mixer"],
  [/vocal separation|instrumental|original \/ instrumental|去人声|伴奏|人声分离/, "separation"],
  [/lyrics|歌词/, "lyrics"],
  [/scor(e|ing)|打分|评分/, "scoring"],
  [/phone page|phone microphone|qr code|手机|扫码/, "phone"],
  [/update|updater|patch|更新/, "updater"],
  [/install|installer|winget|install\.sh|install\.ps1|安装/, "installer"],
  [/playback|video|mpv|播放|视频/, "player"],
  [/windows|win(10|11)/, "platform: Windows"],
  [/macos|mac os|apple silicon|intel mac|macbook|imac|苹果/, "platform: macOS"],
  [/linux|ubuntu|debian|fedora|arch|raspberry|appimage|树莓派/, "platform: Linux"],
];

export function triageLabels(title: string, body: string): string[] {
  const text = `${title}\n${body}`.toLowerCase();
  return AREAS.filter(([re]) => re.test(text)).map(([, label]) => label);
}

export function missingInfo(title: string, body: string): string[] {
  const text = `${title}\n${body}`.toLowerCase();
  const missing: string[] = [];
  if (!/[0-9]+\.[0-9]+\.[0-9]+/.test(text)) missing.push("the **YTKTV version** (Settings → Updates, or the Release you installed)");
  if (!/windows|macos|mac os|apple silicon|intel|linux|ubuntu|debian|fedora|raspberry/.test(text)) {
    missing.push("your **system** (macOS, Windows or Linux, and which version)");
  }
  return missing;
}

export function fixedIssues(title: string, body: string): number[] {
  const found = `${title}\n${body}`.matchAll(/(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) +#([0-9]+)/gi);
  return [...new Set([...found].map((m) => Number(m[1])))].sort((a, b) => a - b);
}

// The area labels from the old labeler.yml. desk, separation, packaging and installer are left
// out: added by the bot's token they would start area-tests / installer-tests a second time
// (those already run for these files by themselves); /run adds them on purpose.
export const TEST_LABELS = ["desk", "separation", "packaging", "installer"];

export function fileLabels(files: string[]): string[] {
  const any = (...res: RegExp[]) => (f: string) => res.some((re) => re.test(f));
  const rules: [string, (f: string) => boolean][] = [
    ["player", any(/^src\/ytktv\/player\//, /^src\/ytktv\/ui\/mv_(window|overlays)\.py$/, /^src\/ytktv\/bootstrap\.py$/, /^src\/ytktv\/core\/preload\.py$/)],
    ["mixer", any(/^src\/ytktv\/audio\//, /^src\/ytktv\/ui\/(mixer_panel|console_widgets)\.py$/)],
    ["phone", any(/^src\/ytktv\/server\//, /^src\/ytktv\/audio\/phone_mic\.py$/)],
    ["lyrics", any(/^src\/ytktv\/youtube\/lyrics\.py$/, /^src\/ytktv\/lyrics_ai\//)],
    ["scoring", any(/^src\/ytktv\/core\/scoring\.py$/, /^src\/ytktv\/separation\/pitch_core\.py$/)],
    ["updater", any(/^src\/ytktv\/updater\.py$/, /^src\/ytktv\/ui\/update_manager\.py$/, /^src\/ytktv\/mpv_pack\.py$/)],
    ["ci", any(/^\.github\//)],
    ["documentation", any(/^[^/]+\.md$/, /^docs\//, /^site\//)],
    ["dependencies", any(/^pyproject\.toml$/)],
    ["tests", any(/^tests\//)],
  ];
  return rules.filter(([, match]) => files.some(match)).map(([label]) => label);
}

export type StaleAction = "none" | "mark" | "unmark" | "close";

export function staleAction(o: {
  labels: string[];
  lastActivity: number;
  staleNote: number | null;
  now: number;
}): StaleAction {
  const limit = 30 * 86400_000;
  if (o.labels.includes("Stale")) {
    if (o.staleNote !== null && o.lastActivity > o.staleNote) return "unmark";
    if (o.staleNote !== null && o.now - o.staleNote >= limit) return "close";
    return "none";
  }
  if (o.labels.includes("Needs-Author-Action") && o.now - o.lastActivity >= limit) return "mark";
  return "none";
}
