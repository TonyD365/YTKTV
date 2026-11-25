// Commands, issue triage, fixed notices, file labels, reminders and stale pull requests.
// BOTS_LIVE=1 sends writes; anything else only logs them.
import { get, getAll, graphql, request } from "./assistant.ts";
import {
  fileLabels, fixedIssues, isMaintainer, labelNames, missingInfo, parseCommand, reminderNote,
  remindSeconds, staleAction, triageLabels,
} from "./bots_logic.ts";
import { BOT, DECLINE_REPLY, REPLY, REPO } from "./logic.ts";

const M = `@${BOT}`;
const live = () => Deno.env.get("BOTS_LIVE") === "1";

async function act(method: string, path: string, body?: unknown): Promise<Response | null> {
  if (!live()) {
    console.log(`shadow bots ${method} ${path}`);
    return null;
  }
  return await request(method, path, body);
}

const say = (n: number, body: string) => act("POST", `/repos/${REPO}/issues/${n}/comments`, { body });
const addLabel = (n: number, label: string) => act("POST", `/repos/${REPO}/issues/${n}/labels`, { labels: [label] });
const dropLabel = (n: number, label: string) => act("DELETE", `/repos/${REPO}/issues/${n}/labels/${encodeURIComponent(label)}`);
const makeLabel = (name: string, color: string, description = "") => act("POST", `/repos/${REPO}/labels`, { name, color, description });

// deno-lint-ignore no-explicit-any
export async function command(p: any) {
  const parsed = parseCommand(p.comment.body);
  if (!parsed) return;
  const { cmd, arg, rest } = parsed;
  const n: number = p.issue.number;
  const isPr = Boolean(p.issue.pull_request);
  const who: string = p.comment.user.login;
  const maintainer = isMaintainer(p.comment.author_association);
  const allowed = p.comment.user.id === p.issue.user.id || maintainer;
  const shown = `\`${M} ${cmd}\``;
  const react = (content: string) => act("POST", `/repos/${REPO}/issues/comments/${p.comment.id}/reactions`, { content });
  const deny = async (text: string) => {
    await react("confused");
    await say(n, `Sorry @${who}, ${text}`);
  };
  const needAuthor = async () => {
    if (allowed) return true;
    await deny(isPr
      ? `only the pull request's author or a maintainer can use ${shown}.`
      : `${shown} is for whoever opened the issue, or a maintainer.`);
    return false;
  };

  if (cmd === "/help") {
    await react("eyes");
    await say(n, isPr ? [
      `Commands for this pull request (start a comment with ${M}, as shown):`, "",
      `- \`${M} /retest\`: re-run the checks that failed or were cancelled (the author or a maintainer).`,
      `- \`${M} /benchmark\`: compare the speed with \`main\` again, e.g. after a slowdown that may be a busy runner (author or maintainer).`,
      `- \`${M} /ready\`: mark a draft as ready for review (author or maintainer).`,
      `- \`${M} /close\`, \`${M} /reopen\`: close or reopen this pull request (author or maintainer).`,
      `- \`${M} /update\`: bring this branch up to date with \`main\` (author or maintainer; maintainers only on a fork).`,
      `- \`${M} /remind 3d\` (or \`12h\`, up to \`30d\`), optionally with a note: the bot reminds you here then.`,
      `- \`${M} /run packaging\`, \`${M} /run installer\`, \`${M} /run desk\`, \`${M} /run separation\`: run that part's heavier tests (maintainers).`,
      `- \`${M} /label name ...\`, \`${M} /unlabel name ...\`: add or remove labels (maintainers).`,
      `- \`${M} /keep-branch\`, \`${M} /delete-branch\`: keep the branch after merging, or have it deleted (the default; author or maintainer).`,
      `- \`${M} /help\`: this list.`, "",
      `Other things the bot answers: \`${REPLY}\` and \`${DECLINE_REPLY}\`.`,
    ].join("\n") : [
      `Commands for this issue (start a comment with ${M}, as shown):`, "",
      `- \`${M} /close\`, \`${M} /reopen\`: close or reopen it (whoever opened it, or a maintainer).`,
      `- \`${M} /label name ...\`, \`${M} /unlabel name ...\`: add or remove labels (maintainers).`,
      `- \`${M} /help\`: this list.`,
    ].join("\n"));
  } else if (cmd === "/close" || cmd === "/reopen") {
    if (!await needAuthor()) return;
    await act("PATCH", `/repos/${REPO}/issues/${n}`, { state: cmd === "/close" ? "closed" : "open" });
    await react("+1");
    if (isPr) {
      await say(n, cmd === "/close"
        ? `Closed on request of @${who}. Comment \`${M} /reopen\` to open it again.`
        : `Reopened on request of @${who}.`);
    }
  } else if (cmd === "/label" || cmd === "/unlabel") {
    if (!maintainer) return await deny(`${shown} is for maintainers (the repository's owner and collaborators).`);
    const names = labelNames(rest);
    if (!names.length) return void await say(n, `Usage: \`${M} ${cmd} name\` (several names separated by spaces or commas).`);
    const done: string[] = [];
    for (const name of names) {
      if (cmd === "/label") await makeLabel(name, "ededed");
      const res = cmd === "/label" ? await addLabel(n, name) : await dropLabel(n, name);
      if (res?.ok) done.push(`\`${name}\``);
    }
    await react("+1");
    await say(n, `${cmd === "/label" ? "Added" : "Removed"}: ${done.join(" ") || "nothing"}`);
  } else if (isPr) {
    await prCommand({ cmd, arg, rest, n, who, maintainer, react, deny, needAuthor });
  }
}

async function prCommand(c: {
  cmd: string; arg: string; rest: string; n: number; who: string; maintainer: boolean;
  react: (s: string) => Promise<unknown>; deny: (s: string) => Promise<void>; needAuthor: () => Promise<boolean>;
}) {
  const { cmd, arg, rest, n, who, maintainer, react, deny, needAuthor } = c;
  if (cmd === "/retest") {
    if (!await needAuthor()) return;
    await react("eyes");
    const pr = await get(`/repos/${REPO}/pulls/${n}`);
    const runs = (await get(`/repos/${REPO}/actions/runs?head_sha=${pr.head.sha}&per_page=100`))?.workflow_runs ?? [];
    let again = 0;
    let waiting = 0;
    for (const run of runs) {
      if (["failure", "cancelled", "timed_out", "startup_failure"].includes(run.conclusion)) {
        const res = await act("POST", `/repos/${REPO}/actions/runs/${run.id}/rerun-failed-jobs`).catch(() => null);
        if (res?.ok) again++;
      } else if (run.conclusion === "action_required") waiting++;
    }
    let msg = again ? `🔁 Re-running ${again} workflow run(s) with failed or cancelled checks.` : "Nothing to re-run: no check has failed or been cancelled on the latest commit.";
    if (waiting) msg += ` ${waiting} run(s) wait for a maintainer to approve them first (Approve and run workflows).`;
    await say(n, msg);
  } else if (cmd === "/benchmark") {
    if (!await needAuthor()) return;
    await react("eyes");
    const pr = await get(`/repos/${REPO}/pulls/${n}`);
    const runs = (await get(`/repos/${REPO}/actions/workflows/benchmark.yml/runs?head_sha=${pr.head.sha}&per_page=1`))?.workflow_runs ?? [];
    if (!runs.length) return void await say(n, "No benchmark run found for the latest commit.");
    await act("POST", `/repos/${REPO}/actions/runs/${runs[0].id}/rerun`);
    await say(n, "🔁 Measuring again: the benchmark comment updates when it is done.");
  } else if (cmd === "/run") {
    if (!maintainer) return await deny(`\`${M} /run\` is for maintainers (it uses the project's CI minutes).`);
    if (!["packaging", "installer", "desk", "separation"].includes(arg)) {
      await react("confused");
      return void await say(n, `Usage: \`${M} /run packaging\`, \`${M} /run installer\`, \`${M} /run desk\` or \`${M} /run separation\`.`);
    }
    await react("rocket");
    // The area workflows start on this label being added (removed first, so it is "added" again).
    await dropLabel(n, arg).catch(() => null);
    await makeLabel(arg, "ededed");
    await addLabel(n, arg);
    await say(n, `🚀 Starting the \`${arg}\` tests for this pull request (they show among its checks).`);
  } else if (cmd === "/ready") {
    if (!await needAuthor()) return;
    const pr = await get(`/repos/${REPO}/pulls/${n}`);
    if (!pr.draft) return void await say(n, "This pull request is not a draft.");
    if (live()) {
      await graphql("mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){clientMutationId}}", { id: pr.node_id });
    }
    await react("+1");
    await say(n, "✅ Marked ready for review.");
  } else if (cmd === "/update") {
    if (!await needAuthor()) return;
    const pr = await get(`/repos/${REPO}/pulls/${n}`);
    if (!maintainer && pr.head.repo?.full_name !== REPO) {
      return await deny(`on a pull request from a fork only a maintainer can use \`${M} /update\`. Merge \`main\` into your branch yourself, or ask a maintainer.`);
    }
    const res = await act("PUT", `/repos/${REPO}/pulls/${n}/update-branch`, { expected_head_sha: pr.head.sha }).catch(() => null);
    if (!live() || res?.ok) {
      await react("+1");
      await say(n, "🔄 Merging `main` into this branch; the checks run again on the new commit.");
    } else {
      await react("confused");
      await say(n, "Could not update the branch. This happens when it is already up to date, when merging `main` conflicts (fix it locally), or when a fork does not allow edits by maintainers.");
    }
  } else if (cmd === "/remind") {
    const seconds = remindSeconds(arg);
    if (seconds === null) {
      await react("confused");
      return void await say(n, `Usage: \`${M} /remind 3d\` or \`${M} /remind 12h\` (up to 30 days), optionally followed by a note.`);
    }
    const at = Math.floor(Date.now() / 1000) + seconds;
    const note = reminderNote(rest);
    const when = new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ");
    await react("+1");
    await say(n, [`<!-- ytktv-remind at=${at} who=${who} -->`, `⏰ OK @${who}, I will remind you here on ${when} UTC (within an hour of it).`, ...(note ? ["", `> ${note}`] : [])].join("\n"));
  }
}

// deno-lint-ignore no-explicit-any
export async function triage(issue: any) {
  if (issue.user.login === BOT) return;
  const n: number = issue.number;
  const title: string = issue.title ?? "";
  const body: string = issue.body ?? "";
  for (const label of triageLabels(title, body)) await addLabel(n, label).catch(() => null);
  // deno-lint-ignore no-explicit-any
  if (!(issue.labels ?? []).some((l: any) => l.name === "bug")) return;
  const missing = missingInfo(title, body);
  if (!missing.length) return void await dropLabel(n, "needs-info").catch(() => null);
  await makeLabel("needs-info", "d4c5f9", "Waiting for details from the reporter");
  await addLabel(n, "needs-info");
  const comments = await getAll(`/repos/${REPO}/issues/${n}/comments`);
  if (comments.some((c) => c.body.startsWith("<!-- ytktv-needs-info -->"))) return;
  await say(n, ["<!-- ytktv-needs-info -->", `Thank you for the report, @${issue.user.login}! To look into it, please add (edit the issue, or reply):`, "", ...missing.map((m) => `- ${m}`), "", "The `needs-info` label goes away by itself once they are there."].join("\n"));
}

// deno-lint-ignore no-explicit-any
export async function announceFixed(pr: any) {
  const issues = fixedIssues(pr.title ?? "", pr.body ?? "");
  if (issues.length) await makeLabel("fixed-in-next-release", "0e8a16", "Fixed on main; ships in the next release");
  for (const n of issues) {
    const issue = await get(`/repos/${REPO}/issues/${n}`);
    if (!issue || issue.pull_request) continue;
    await addLabel(n, "fixed-in-next-release");
    await say(n, `<!-- ytktv-fixed -->\n✅ Fixed by #${pr.number}, now on \`main\`. It ships in the next release; I will say here which version has it.`);
  }
}

// deno-lint-ignore no-explicit-any
export async function announceReleased(release: any) {
  if (release.prerelease) return;
  const issues = await getAll(`/repos/${REPO}/issues?state=all&labels=fixed-in-next-release`);
  for (const issue of issues) {
    if (issue.pull_request) continue;
    await say(issue.number, `<!-- ytktv-released -->\n🎉 The fix is in **YTKTV ${release.tag_name}** (${release.html_url}). YTKTV and YTKTV Desk update themselves (Settings → Updates).`);
    await dropLabel(issue.number, "fixed-in-next-release");
  }
}

export async function labelByFiles(number: number) {
  const files = await getAll(`/repos/${REPO}/pulls/${number}/files`);
  const pr = await get(`/repos/${REPO}/issues/${number}`);
  // deno-lint-ignore no-explicit-any
  const have = (pr?.labels ?? []).map((l: any) => l.name);
  for (const label of fileLabels(files.map((f) => f.filename))) {
    if (!have.includes(label)) await addLabel(number, label).catch(() => null);
  }
}

export async function reminders() {
  const now = Math.floor(Date.now() / 1000);
  for (const pr of await getAll(`/repos/${REPO}/pulls?state=open`)) {
    for (const c of await getAll(`/repos/${REPO}/issues/${pr.number}/comments`)) {
      if (c.user.login !== BOT || !c.body.startsWith("<!-- ytktv-remind ")) continue;
      const m = c.body.split("\n")[0].match(/ at=([0-9]+) who=([A-Za-z0-9-]+) /);
      if (!m || Number(m[1]) > now) continue;
      const note = c.body.split("\n").find((l: string) => l.startsWith("> "));
      await say(pr.number, [`⏰ @${m[2]}, here is the reminder you asked for (${c.html_url}).`, ...(note ? ["", note] : [])].join("\n"));
      await act("PATCH", `/repos/${REPO}/issues/comments/${c.id}`, { body: c.body.replace("<!-- ytktv-remind ", "<!-- ytktv-remind-done ") });
    }
  }
}

export async function stale() {
  await makeLabel("Stale", "cfd3d7", "Waiting on the author for 30 days");
  const now = Date.now();
  for (const pr of await getAll(`/repos/${REPO}/pulls?state=open`)) {
    const author: string = pr.user.login;
    const comments = await getAll(`/repos/${REPO}/issues/${pr.number}/comments`);
    const commits = await getAll(`/repos/${REPO}/pulls/${pr.number}/commits`);
    const times = [
      Date.parse(pr.created_at),
      ...commits.map((c) => Date.parse(c.commit.committer.date)),
      ...comments.filter((c) => c.user.login === author).map((c) => Date.parse(c.created_at)),
    ];
    const notes = comments.filter((c) => c.body.startsWith("<!-- ytktv-stale -->")).map((c) => Date.parse(c.created_at));
    const action = staleAction({
      // deno-lint-ignore no-explicit-any
      labels: pr.labels.map((l: any) => l.name),
      lastActivity: Math.max(...times),
      staleNote: notes.length ? Math.max(...notes) : null,
      now,
    });
    if (action === "unmark") await dropLabel(pr.number, "Stale");
    if (action === "mark") {
      await addLabel(pr.number, "Stale");
      await say(pr.number, `<!-- ytktv-stale -->\n👋 @${author}, this pull request has been waiting for you for 30 days (see the status comment for what is needed). If nothing happens in the next 30 days it will be closed; you can reopen it at any time. A push or a comment keeps it open.`);
    }
    if (action === "close") {
      await say(pr.number, `<!-- ytktv-stale-closed -->\nClosing this pull request after 60 days without a reply. Thank you for it, @${author}: reopen it whenever you want to go on.`);
      await act("PATCH", `/repos/${REPO}/pulls/${pr.number}`, { state: "closed" });
    }
  }
}
