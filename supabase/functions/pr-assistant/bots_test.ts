import {
  fileLabels, fixedIssues, labelNames, missingInfo, parseCommand, reminderNote, remindSeconds,
  staleAction, triageLabels,
} from "./bots_logic.ts";
import { command } from "./bots.ts";

function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${JSON.stringify(a)} != ${JSON.stringify(b)}`);
}
const M = "@TonyD365-Agent";

Deno.test("commands need the mention at the start", () => {
  eq(parseCommand(`${M} /retest`)?.cmd, "/retest");
  eq(parseCommand(`${M.toLowerCase()} /LABEL Bug, Docs`)?.rest, "Bug, Docs");
  eq(parseCommand("/retest"), null);
  eq(parseCommand(`please ${M} /retest`), null);
  eq(parseCommand(`${M}x /retest`), null);
  eq(parseCommand(`${M} hello`), null);
});
Deno.test("reminders stay within 30 days", () => {
  eq(remindSeconds("3d"), 259200);
  eq(remindSeconds("12h"), 43200);
  eq(remindSeconds("720h"), 2592000);
  eq(remindSeconds("31d"), null);
  eq(remindSeconds("721h"), null);
  eq(remindSeconds("0d"), null);
  eq(remindSeconds("soon"), null);
  eq(reminderNote("3d look at @x `this`"), "look at x this");
});
Deno.test("label names split on spaces and commas", () => eq(labelNames("a, b  c"), ["a", "b", "c"]));
Deno.test("issue triage", () => {
  eq(triageLabels("No instrumental", "伴奏 on Ubuntu"), ["separation", "platform: Linux"]);
  eq(missingInfo("bug", "YTKTV 4.7.1 on macOS"), []);
  eq(missingInfo("bug", "broken").length, 2);
});
Deno.test("fixed issues", () => eq(fixedIssues("Fixes #12", "closes #3, resolved #12, see #9"), [3, 12]));
Deno.test("file labels", () => {
  eq(fileLabels(["README.md", "tests/a.py", ".github/x.yml"]), ["ci", "documentation", "tests"]);
  eq(fileLabels(["src/ytktv/audio/x.py", "src/ytktv/desk/a.py", "packaging/a"]), ["mixer"]);
});
Deno.test("stale pull requests", () => {
  const day = 86400_000;
  const now = 100 * day;
  eq(staleAction({ labels: ["Needs-Author-Action"], lastActivity: now - 31 * day, staleNote: null, now }), "mark");
  eq(staleAction({ labels: ["Needs-Review"], lastActivity: 0, staleNote: null, now }), "none");
  eq(staleAction({ labels: ["Stale"], lastActivity: now - day, staleNote: now - 2 * day, now }), "unmark");
  eq(staleAction({ labels: ["Stale"], lastActivity: now - 90 * day, staleNote: now - 31 * day, now }), "close");
});

function fakeGitHub() {
  const writes: string[] = [];
  globalThis.fetch = ((input: string, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    if (method !== "GET") writes.push(`${method} ${url.pathname}`);
    return Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
  }) as typeof fetch;
  return writes;
}
const event = (body: string, id: number, role: string, pr = true) => ({
  issue: { number: 5, user: { id: 1 }, ...(pr ? { pull_request: {} } : {}) },
  comment: { id: 9, body, author_association: role, user: { id, login: "someone" } },
});

Deno.test("a stranger cannot close or label", async () => {
  Deno.env.set("BOTS_LIVE", "1");
  Deno.env.set("GITHUB_TOKEN", "test");
  const writes = fakeGitHub();
  await command(event(`${M} /close`, 2, "NONE"));
  await command(event(`${M} /label x`, 2, "NONE"));
  eq(writes.some((w) => w.startsWith("PATCH") || w.endsWith("/issues/5/labels")), false);
});
Deno.test("the author can close; a comment without the mention does nothing", async () => {
  Deno.env.set("BOTS_LIVE", "1");
  const writes = fakeGitHub();
  await command(event("/close", 1, "NONE"));
  eq(writes.length, 0);
  await command(event(`${M} /close`, 1, "NONE", false));
  eq(writes.includes("PATCH /repos/TonyD365/YTKTV/issues/5"), true);
});
Deno.test("shadow mode sends nothing", async () => {
  Deno.env.set("BOTS_LIVE", "");
  const writes = fakeGitHub();
  await command(event(`${M} /close`, 1, "OWNER"));
  eq(writes.length, 0);
});

Deno.test("/run is for maintainers and re-adds the area label", async () => {
  Deno.env.set("BOTS_LIVE", "1");
  let writes = fakeGitHub();
  await command(event(`${M} /run desk`, 1, "NONE"));
  eq(writes.some((w) => w.endsWith("/issues/5/labels")), false);
  writes = fakeGitHub();
  await command(event(`${M} /run desk`, 2, "OWNER"));
  eq(writes.includes("DELETE /repos/TonyD365/YTKTV/issues/5/labels/desk"), true);
  eq(writes.includes("POST /repos/TonyD365/YTKTV/issues/5/labels"), true);
});
Deno.test("file labels never add the labels that start heavy tests", () => {
  eq(fileLabels(["src/ytktv/desk/a.py", "src/ytktv/separation/b.py", "installer/x.ts", "packaging/y"]), []);
});
