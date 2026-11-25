// The assistant's decisions, with no network access, so they can be tested.

export const REPO = "TonyD365/YTKTV";
export const SERVER = "https://github.com";
export const BOT = "TonyD365-Agent";
export const PHRASE = "I agree to the YTKTV contribution terms";
export const DECLINE = "I do not agree to the YTKTV contribution terms";
export const REPLY = `@${BOT} ${PHRASE}`;
export const DECLINE_REPLY = `@${BOT} ${DECLINE}`;
const EXEMPT = new Set([
  "TonyD365",
  BOT,
  "dependabot[bot]",
  "dependabot",
  "app/dependabot",
  "github-actions[bot]",
]);

export const KEEP_LABEL = "Keep-Branch";
export const KEEP_COMMAND = `@${BOT} /keep-branch`;
export const DELETE_COMMAND = `@${BOT} /delete-branch`;

export const COLOURS: Record<string, string> = {
  "Checks-Running": "c5def5",
  "Checks-Passed": "0e8a16",
  "Checks-Failed": "d73a4a",
  "Internal-Error": "e99695",
  "Needs-Author-Action": "b60205",
  "Needs-Review": "fbca04",
  "Maintainer-Approved": "1d7a3b",
  "Needs-Terms-Agreement": "5319e7",
  "Terms-Agreed": "c2e0c6",
  "Terms-Declined": "000000",
  "Merge-Conflict": "d93f0b",
  "Changes-Requested": "e4e669",
};

export type Check = {
  name: string;
  status: string;
  conclusion: string | null;
  html_url: string;
  started_at?: string | null;
  check_suite?: { id: number } | null;
};
export type Terms = "exempt" | "yes" | "no" | "declined";
export type State = {
  number: number;
  head: string;
  author: string;
  draft: boolean;
  review: string;
  conflict: boolean;
  checks: Check[];
  busy: number;
  waiting: string[];
  terms: Terms;
  askedBy?: string;
  askedUrl?: string;
  branch?: string; // the head branch, when it is in this repository (not a fork)
  keep?: boolean;
};

export function latestChecks(all: Check[], doneSuite = 0, doneConclusion = ""): Check[] {
  const latest = new Map<string, Check>();
  for (const raw of all) {
    if (raw.name === "comment") continue;
    const c = raw.check_suite?.id === doneSuite
      ? { ...raw, status: "completed", conclusion: raw.conclusion ?? doneConclusion }
      : raw;
    const old = latest.get(c.name);
    if (!old || (c.started_at ?? "") >= (old.started_at ?? "")) latest.set(c.name, c);
  }
  return [...latest.values()];
}

export function counts(s: State) {
  const total = s.checks.length;
  const failedChecks = s.checks.filter((c) => ["failure", "timed_out"].includes(c.conclusion ?? ""));
  const runningChecks = s.checks.filter((c) => c.status !== "completed");
  const internal = s.checks.filter((c) =>
    ["cancelled", "startup_failure", "stale"].includes(c.conclusion ?? "")
  ).length;
  // A job just re-run can be missing for a few seconds; an unfinished run still counts.
  const running = runningChecks.length || s.busy;
  return { total, failed: failedChecks.length, failedChecks, runningChecks, running, internal };
}

export function wantedLabels(s: State): string[] {
  const { total, failed, running, internal } = counts(s);
  const blockedOnTerms = s.terms === "no" || s.terms === "declined";
  const want: string[] = [];
  if (total === 0 || running) want.push("Checks-Running");
  if (failed) want.push("Checks-Failed");
  if (internal) want.push("Internal-Error");
  if (total && !running && !failed) want.push("Checks-Passed");
  if (failed || blockedOnTerms || s.review === "CHANGES_REQUESTED" || s.conflict) {
    want.push("Needs-Author-Action");
  }
  if (s.conflict) want.push("Merge-Conflict");
  if (s.review === "CHANGES_REQUESTED") want.push("Changes-Requested");
  if (blockedOnTerms) want.push("Needs-Terms-Agreement");
  if (s.terms === "yes") want.push("Terms-Agreed");
  if (s.terms === "declined") want.push("Terms-Declined");
  want.push(s.review === "APPROVED" ? "Maintainer-Approved" : "Needs-Review");
  return want;
}

export function aggregate(s: State): { state: "pending" | "failure" | "success"; description: string } {
  const { total, failed, running, internal } = counts(s);
  const noTerms = s.terms === "no" || s.terms === "declined";
  let r: { state: "pending" | "failure" | "success"; description: string };
  if (s.waiting.length) r = { state: "pending", description: "Workflows wait for the maintainer's approval to run" };
  else if (total === 0 || running) r = { state: "pending", description: "Checks are running" };
  else if (failed) r = { state: "failure", description: `${failed} check(s) failed` };
  else if (internal) r = { state: "failure", description: `${internal} check(s) cancelled: comment @TonyD365-Agent /retest` };
  else if (noTerms) r = { state: "failure", description: "Contribution terms not agreed yet" };
  else r = { state: "success", description: "Every check passed" };
  if (r.state === "pending" && noTerms) r.description += "; terms not agreed yet";
  return r;
}

export function kind(s: State): string {
  const { total, failed, running, internal } = counts(s);
  if (s.review === "CHANGES_REQUESTED") return "changes";
  if (s.conflict) return "conflict";
  if (s.terms === "no" || s.terms === "declined") return "terms";
  if (s.waiting.length) return "awaiting";
  if ((total === 0 || running) && !failed) return "running";
  if (failed) return "failed";
  if (internal) return "internal";
  return `passed-${s.review}`;
}

export function hint(name: string): string {
  if (name.includes("Lint and type-check")) return "Run `ruff check .`, `ruff format .` and `mypy src`, then push the fixes.";
  if (name.startsWith("Tests")) return "A test failed: open the log, then run `pytest` locally (`QT_QPA_PLATFORM=offscreen`).";
  if (name.includes("Compare with base")) return "Something got more than 25% slower than on main (see the job summary). Make it faster, or explain why in the PR.";
  if (name.includes("Terminal installer")) return "The Ink installer (installer/) did not build or its tests failed: `cd installer && npm ci && bun build.ts && bun test`.";
  if (name.startsWith("Real installs") || name.startsWith("Install")) return "A real install failed. If it says the latest release has no files yet, a release is still being built: re-run later.";
  if (name.includes("Dependency audit")) return "A dependency has a known vulnerability: raise it to the fixed version (the log names it).";
  if (name.includes("zizmor")) return "A workflow file has a security problem: see the annotation on the Files tab.";
  if (name.startsWith("CodeQL")) return "Code scanning found a possible security problem in the changed code: see the annotation on the PR's Files tab.";
  if (name.includes("live") || name.startsWith("Separation")) return "A live area test failed (`YTKTV_LIVE=1 pytest tests/live` runs it locally).";
  if (name.startsWith("Packaging")) return "The real build or a built app's self-test failed: check the platform in the job name.";
  return "Open the log for details.";
}

export function marker(s: State): string {
  return `<!-- ytktv-pr-assistant kind=${kind(s)} -->`;
}

export function withoutTimestamp(body: string): string {
  return body.replace(/ · updated .* for [0-9a-f]{7}<\/sub>/, "</sub>");
}

export function renderStatus(s: State, labels: string[], now: Date): string {
  const c = counts(s);
  const noTerms = s.terms === "no" || s.terms === "declined";
  const out: string[] = [marker(s)];
  if (s.review === "CHANGES_REQUESTED") out.push("### ✋ Changes requested");
  else if (s.waiting.length) out.push("### ⏸️ Checks wait for the maintainer's approval to run");
  else if (c.total === 0) out.push("### ⏳ Checks are starting");
  else if (c.failed) out.push(`### ❌ ${c.failed} of ${c.total} checks failed`);
  else if (c.running) out.push(`### ⏳ ${c.running} of ${c.total} checks still running`);
  else if (c.internal) out.push(`### ⚠️ ${c.internal} of ${c.total} checks were cancelled`);
  else out.push(`### ✅ All ${c.total} checks passed`);
  out.push("", `Hi @${s.author}, I keep this comment up to date with the state of this pull request.`);
  if (s.review === "CHANGES_REQUESTED") {
    const url = s.askedUrl ?? `${SERVER}/${REPO}/pull/${s.number}/files`;
    out.push("", `**The maintainer (\`${s.askedBy ?? "maintainer"}\`) asked for changes before this can be merged.** Please read [the review](${url}), make the changes and push them; the review is then looked at again. Auto-merge stays off until it is approved.`);
  }
  if (c.failed) {
    out.push("", "**What failed, and what it usually means**", "");
    for (const f of c.failedChecks) out.push(`- [${f.name}](${f.html_url}): ${hint(f.name)}`);
  }
  if (c.running) {
    out.push("", "**Still running** (queued ones are waiting for a GitHub runner; GitHub's checks list can hide them when a newer run of the same workflow was skipped)", "");
    for (const r of c.runningChecks) out.push(`- [${r.name}](${r.html_url}): ${r.status.replace("_", " ")}`);
  }
  if (s.waiting.length) {
    out.push("", "**Waiting for approval to run:** GitHub runs workflows from a first-time contributor's fork only after the maintainer approves them, to keep the repository safe. Nothing for you to do; this comment updates once they have run.", "");
    for (const w of s.waiting) out.push(`- ${w}`);
  }
  if (s.conflict) {
    out.push("", "**Merge conflict:** this pull request and `main` change the same lines, so it cannot be merged (auto-merge waits). Bring `main` into your branch, fix the conflicting files, and push: `git fetch origin && git merge origin/main`, or use **Resolve conflicts** on this page. [How to resolve a merge conflict](https://docs.github.com/pull-requests/collaborating-with-pull-requests/addressing-merge-conflicts/resolving-a-merge-conflict-on-github)");
  }
  if (c.internal) out.push("", `**Internal error:** ${c.internal} check(s) were cancelled or could not start, which is usually GitHub, not this change. Comment \`@TonyD365-Agent /retest\` to run them again.`);
  if (noTerms) out.push("", `**Contribution terms:** please read the terms in the comment above and, if you agree, reply with a comment that says exactly \`${REPLY}\`. Nothing can be merged before that.`);
  if (labels.length) out.push("", `**Labels:** ${labels.join(", ")}`);
  out.push("", "**Next**");
  if (s.draft) out.push("- This is a draft: mark it ready for review when it is done.");
  else if (s.review === "CHANGES_REQUESTED") out.push("- Make the changes asked for in the review and push them.");
  else if (s.conflict) out.push("- Resolve the merge conflict with `main` (see above) and push.");
  else if (noTerms) out.push(`- Reply \`${REPLY}\` to agree to the contribution terms (see above).`);
  else if (s.waiting.length) out.push("- The maintainer approves the waiting workflows; then the checks run.");
  else if (c.failed) out.push("- Fix the failures above and push; the checks run again by themselves.");
  else if (c.running) out.push("- Wait for the running checks; this comment updates when they finish.");
  else if (c.internal) out.push("- Comment `@TonyD365-Agent /retest` to run the cancelled checks again.");
  if (s.review === "APPROVED") out.push("- Approved by the maintainer: it merges by itself once every check passes (auto-merge is on).");
  else if (s.review === "CHANGES_REQUESTED") out.push("- The maintainer asked for changes: see the review.");
  else out.push("- It needs the maintainer's approval before it can be merged.");
  if (s.branch && s.keep) {
    out.push(`- The branch \`${s.branch}\` is kept after merging. To have it deleted then, comment \`${DELETE_COMMAND}\`.`);
  } else if (s.branch) {
    out.push(`- Once merged, the branch \`${s.branch}\` is deleted automatically. To keep it, comment \`${KEEP_COMMAND}\`.`);
  }
  const when = now.toISOString().slice(0, 16).replace("T", " ");
  out.push("", `<sub>[How the checks work](${SERVER}/${REPO}/blob/main/CONTRIBUTING.md#before-you-open-a-pull-request) · updated ${when} UTC for ${s.head.slice(0, 7)}</sub>`);
  return out.join("\n") + "\n";
}

export function isExempt(author: string): boolean {
  return EXEMPT.has(author);
}

// What a comment says to the bot, or null when it does not start by mentioning the bot.
export function addressed(body: string): string | null {
  const start = body.trimStart();
  const mention = `@${BOT}`;
  if (start.slice(0, mention.length).toLowerCase() !== mention.toLowerCase()) return null;
  const rest = start.slice(mention.length);
  return rest === "" || /^[\s,:]/.test(rest) ? rest.replace(/^[\s,:]+/, "") : null;
}

export function termsReply(body: string): "agreed" | "declined" | null {
  const text = addressed(body);
  if (text === null) return null;
  const said = text.replaceAll("\r", "").replaceAll("’", "'").toLowerCase().trim().replace(/\.$/, "");
  if (said === PHRASE.toLowerCase()) return "agreed";
  if (said === DECLINE.toLowerCase() || said === "i don't agree to the ytktv contribution terms") return "declined";
  return null;
}

// The latest ledger entry for a person decides. Matched by account id, or by login for
// entries from before ids were recorded.
export function ledgerState(lines: string[], id: number, login: string): "agreed" | "declined" | "none" {
  let state: "agreed" | "declined" | "none" = "none";
  for (const line of lines) {
    const m = line.match(/^<!-- terms:(agreed|declined):(.*) -->$/);
    if (!m) continue;
    const who = m[2];
    if (who.startsWith(`id=${id}:`) || who === login) state = m[1] as "agreed" | "declined";
  }
  return state;
}

export function termsMarkdown(contributing: string): string {
  const out: string[] = [];
  let on = false;
  let skip = false;
  for (const line of contributing.split("\n")) {
    if (line.startsWith("## Contribution terms")) {
      on = true;
      continue;
    }
    if (line.startsWith("## ")) on = false;
    if (!on) continue;
    if (line.startsWith("On your first pull request")) skip = true;
    if (skip) {
      if (line.startsWith("you agree that:")) skip = false;
      continue;
    }
    out.push(line.replace(/\]\(([A-Za-z_]+(\.md)?)\)/g, `](${SERVER}/${REPO}/blob/main/$1)`));
  }
  return out.join("\n").trim();
}

export function branchCommand(body: string): "keep" | "delete" | null {
  const text = addressed(body);
  if (text === null) return null;
  const said = text.trim().toLowerCase();
  if (said === "/keep-branch") return "keep";
  if (said === "/delete-branch") return "delete";
  return null;
}
