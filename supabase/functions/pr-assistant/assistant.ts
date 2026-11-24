// Reads the pull request from GitHub and applies what logic.ts decides. Every run works out
// the state again from GitHub, so repeated or out-of-order webhooks are harmless.
import {
  aggregate,
  BOT,
  type Check,
  COLOURS,
  counts,
  isExempt,
  latestChecks,
  ledgerState,
  marker,
  DECLINE_REPLY,
  REPLY,
  renderStatus,
  REPO,
  SERVER,
  type State,
  type Terms,
  termsMarkdown,
  termsReply,
  wantedLabels,
  withoutTimestamp,
} from "./logic.ts";

const API = "https://api.github.com";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// LIVE_PRS: "" (shadow: log writes, send none), "42,43" (only these), or "*" (all).
function isLive(number: number): boolean {
  const live = (Deno.env.get("LIVE_PRS") ?? "").trim();
  return live === "*" || live.split(",").map((s) => s.trim()).includes(String(number));
}

export async function request(method: string, path: string, body?: unknown): Promise<Response> {
  const res = await fetch(path.startsWith("http") ? path : `${API}${path}`, {
    method,
    headers: {
      authorization: `Bearer ${Deno.env.get("GITHUB_TOKEN")}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "ytktv-pr-assistant",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok && res.status !== 404 && res.status !== 422) {
    throw new Error(`${method} ${path}: HTTP ${res.status}`);
  }
  return res;
}

// deno-lint-ignore no-explicit-any
export async function get(path: string): Promise<any> {
  const res = await request("GET", path);
  return res.ok ? await res.json() : null;
}

// deno-lint-ignore no-explicit-any
export async function getAll(path: string): Promise<any[]> {
  // deno-lint-ignore no-explicit-any
  const items: any[] = [];
  let url: string | null = `${path}${path.includes("?") ? "&" : "?"}per_page=100`;
  while (url) {
    const res: Response = await request("GET", url);
    if (!res.ok) break;
    items.push(...await res.json());
    url = res.headers.get("link")?.match(/<([^>]+)>;\s*rel="next"/)?.[1] ?? null;
  }
  return items;
}

export async function graphql(query: string, variables: Record<string, unknown>) {
  const res = await request("POST", "/graphql", { query, variables });
  const json = await res.json();
  if (json.errors) throw new Error(json.errors[0]?.message ?? "GraphQL error");
  return json.data;
}

class Writer {
  constructor(readonly number: number, readonly live = isLive(number)) {}

  async send(method: string, path: string, body?: unknown): Promise<unknown> {
    if (!this.live) {
      const summary = body && typeof body === "object" && "state" in body
        ? JSON.stringify(body)
        : body && typeof body === "object" && "labels" in body
        ? JSON.stringify(body)
        : "";
      console.log(`shadow pr=${this.number} ${method} ${path} ${summary}`);
      return null;
    }
    const res = await request(method, path, body);
    return res.status === 204 || !res.ok ? null : await res.json();
  }

  comment(body: string) {
    return this.send("POST", `/repos/${REPO}/issues/${this.number}/comments`, { body });
  }

  // GitHub refuses auto-merge on a pull request that can already be merged (CLEAN): merge it.
  async autoMerge(on: boolean, id: string, enabled: boolean, mergeNow = false) {
    if (on && mergeNow) {
      if (!this.live) return console.log(`shadow pr=${this.number} merge now`);
      await graphql(
        "mutation($id:ID!){mergePullRequest(input:{pullRequestId:$id,mergeMethod:MERGE}){clientMutationId}}",
        { id },
      ).catch((e) => console.error(`merge pr=${this.number}: ${e}`));
      return;
    }
    if (on === enabled) return;
    if (!this.live) return console.log(`shadow pr=${this.number} auto-merge=${on}`);
    const mutation = on
      ? "mutation($id:ID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:MERGE}){clientMutationId}}"
      : "mutation($id:ID!){disablePullRequestAutoMerge(input:{pullRequestId:$id}){clientMutationId}}";
    await graphql(mutation, { id }).catch((e) => console.error(`auto-merge pr=${this.number}: ${e}`));
  }
}

const PR_QUERY = `query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){
  id state isDraft reviewDecision mergeable mergeStateStatus headRefOid
  labels(first:50){nodes{name}} autoMergeRequest{enabledAt}}}}`;

async function pullRequest(number: number) {
  const [owner, name] = REPO.split("/");
  for (let i = 0;; i++) {
    const data = await graphql(PR_QUERY, { o: owner, n: name, p: number });
    const pr = data.repository.pullRequest;
    if (pr.mergeable !== "UNKNOWN" || i >= 4) return pr;
    await sleep(4000);
  }
}

async function ledgerNumber(): Promise<number | null> {
  const issues = await get(`/repos/${REPO}/issues?state=all&labels=terms-ledger&per_page=1`);
  return issues?.[0]?.number ?? null;
}

async function ledgerLines(ledger: number | null): Promise<string[]> {
  if (!ledger) return [];
  const comments = await getAll(`/repos/${REPO}/issues/${ledger}/comments`);
  return comments.filter((c) => c.user.login === BOT).map((c) => c.body.split("\n")[0]);
}

async function termsFor(author: string, id: number): Promise<Terms> {
  if (isExempt(author)) return "exempt";
  const state = ledgerState(await ledgerLines(await ledgerNumber()), id, author);
  return state === "agreed" ? "yes" : state === "declined" ? "declined" : "no";
}

async function askTerms(w: Writer, author: string, comments: { body: string }[]) {
  if (comments.some((c) => c.body.startsWith("<!-- ytktv-terms-ask"))) return;
  const res = await fetch(`https://raw.githubusercontent.com/${REPO}/main/CONTRIBUTING.md`);
  if (!res.ok) throw new Error(`CONTRIBUTING.md: HTTP ${res.status}`);
  await w.comment([
    "<!-- ytktv-terms-ask -->",
    "### 📝 Contribution terms",
    "",
    `Thank you for your contribution, @${author}! Before it can be merged, please read the terms below and reply to agree.`,
    "",
    termsMarkdown(await res.text()),
    "",
    "---",
    "",
    "**If you agree, reply to this pull request with a comment that says exactly:**",
    "",
    "```",
    REPLY,
    "```",
    "",
    "Agreeing once covers your later pull requests to YTKTV too, until you withdraw it by replying `@TonyD365-Agent I do not agree to the YTKTV contribution terms`. If you do not agree, the pull request cannot be merged.",
  ].join("\n"));
}

async function syncLabels(w: Writer, have: string[], want: string[]) {
  for (const label of Object.keys(COLOURS)) {
    const wanted = want.includes(label);
    if (wanted && !have.includes(label)) {
      await w.send("POST", `/repos/${REPO}/labels`, { name: label, color: COLOURS[label] });
      await w.send("POST", `/repos/${REPO}/issues/${w.number}/labels`, { labels: [label] });
    } else if (!wanted && have.includes(label)) {
      await w.send("DELETE", `/repos/${REPO}/issues/${w.number}/labels/${encodeURIComponent(label)}`);
    }
  }
}

async function writeStatusComment(w: Writer, body: string, first: string) {
  const comments = (await getAll(`/repos/${REPO}/issues/${w.number}/comments`))
    .filter((c) => c.body.startsWith("<!-- ytktv-pr-assistant"));
  const last = comments.at(-1);
  if (last && last.user.login === BOT && last.body.split("\n")[0] === first) {
    if (withoutTimestamp(last.body) !== withoutTimestamp(body)) {
      await w.send("PATCH", `/repos/${REPO}/issues/comments/${last.id}`, { body });
    }
  } else {
    if (last) await w.send("DELETE", `/repos/${REPO}/issues/comments/${last.id}`);
    await w.comment(body);
  }
  if (!w.live) return;
  // Two webhooks at once can each post a comment: keep only the newest.
  const now = (await getAll(`/repos/${REPO}/issues/${w.number}/comments`))
    .filter((c) => c.user.login === BOT && c.body.startsWith("<!-- ytktv-pr-assistant"));
  for (const extra of now.slice(0, -1)) {
    await w.send("DELETE", `/repos/${REPO}/issues/comments/${extra.id}`);
  }
}

export async function refresh(number: number, doneSuite = 0, doneConclusion = "") {
  const w = new Writer(number);
  const pr = await pullRequest(number);
  if (!pr || pr.state !== "OPEN") return;
  const head: string = pr.headRefOid;
  const rest = await get(`/repos/${REPO}/pulls/${number}`);
  const author: string = rest.user.login;
  const checkRuns = await get(`/repos/${REPO}/commits/${head}/check-runs?per_page=100`);
  const checks: Check[] = latestChecks(checkRuns?.check_runs ?? [], doneSuite, doneConclusion);
  const prRuns = await get(`/repos/${REPO}/actions/runs?head_sha=${head}&event=pull_request&per_page=100`);
  // deno-lint-ignore no-explicit-any
  const busy = (prRuns?.workflow_runs ?? []).filter((r: any) => r.status !== "completed").length;
  const allRuns = await get(`/repos/${REPO}/actions/runs?head_sha=${head}&per_page=100`);
  const waiting: string[] = [
    // deno-lint-ignore no-explicit-any
    ...new Set<string>((allRuns?.workflow_runs ?? []).filter((r: any) => r.conclusion === "action_required").map((r: any) => r.name)),
  ];
  const terms = await termsFor(author, rest.user.id);
  const issueComments = await getAll(`/repos/${REPO}/issues/${number}/comments`);
  if (terms === "no") await askTerms(w, author, issueComments);
  const agreed = terms === "yes" || terms === "exempt";
  await w.send("POST", `/repos/${REPO}/statuses/${head}`, {
    state: agreed ? "success" : "failure",
    context: "Contribution terms",
    description: agreed ? (terms === "exempt" ? "Not needed for the maintainer" : "Agreed") : `Reply: ${REPLY}`,
    target_url: `${SERVER}/${REPO}/blob/main/CONTRIBUTING.md#contribution-terms`,
  });

  const state: State = {
    number,
    head,
    author,
    draft: pr.isDraft,
    review: pr.reviewDecision ?? "",
    conflict: pr.mergeable === "CONFLICTING",
    checks,
    busy: counts({ checks, busy: 0 } as unknown as State).running ? 0 : busy,
    waiting,
    terms,
  };
  if (state.review === "CHANGES_REQUESTED") {
    const reviews = await getAll(`/repos/${REPO}/pulls/${number}/reviews`);
    const asked = reviews.filter((r) => r.state === "CHANGES_REQUESTED").at(-1);
    state.askedBy = asked?.user?.login;
    state.askedUrl = asked?.html_url;
  }

  const have: string[] = pr.labels.nodes.map((l: { name: string }) => l.name);
  const want = wantedLabels(state);
  await syncLabels(w, have, want);
  const result = aggregate(state);
  await w.send("POST", `/repos/${REPO}/statuses/${head}`, {
    ...result,
    context: "YTKTV checks",
    target_url: `${SERVER}/${REPO}/pull/${number}`,
  });
  await w.autoMerge(
    state.review === "APPROVED" && !state.draft,
    pr.id,
    pr.autoMergeRequest !== null,
    result.state === "success" && pr.mergeStateStatus === "CLEAN",
  );
  const shown = [...have.filter((l) => !(l in COLOURS)), ...want];
  await writeStatusComment(w, renderStatus(state, shown, new Date()), marker(state));
  console.log(`pr=${number} live=${w.live} result=${result.state} labels=${want.join(",")}`);
}

export async function answerTerms(number: number, c: {
  body: string;
  html_url: string;
  user: { login: string; id: number };
}, authorId: number) {
  const what = termsReply(c.body);
  if (!what || c.user.id !== authorId) return;
  const w = new Writer(number);
  let ledger = await ledgerNumber();
  if (ledgerState(await ledgerLines(ledger), c.user.id, c.user.login) === what) return;
  if (!ledger) {
    if (!w.live) return console.log(`shadow pr=${number} would create the terms ledger`);
    await w.send("POST", `/repos/${REPO}/labels`, { name: "terms-ledger", color: "ededed" });
    const issue = await w.send("POST", `/repos/${REPO}/issues`, {
      title: "Contribution terms: agreements (kept by the bot)",
      labels: ["terms-ledger"],
      body: `This issue is the record of who agreed to the [contribution terms](${SERVER}/${REPO}/blob/main/CONTRIBUTING.md#contribution-terms). The bot keeps it; it is closed and locked so it stays out of the way.\n\n- **To agree**, reply on your pull request: \`${REPLY}\`\n- **To withdraw**, reply on any of your pull requests: \`${DECLINE_REPLY}\`\n\nOne entry per answer, newest last. A person's latest entry counts; people are matched by their account number, so a renamed account keeps its agreement.`,
    }) as { number: number };
    ledger = issue.number;
    await w.send("PUT", `/repos/${REPO}/issues/${ledger}/lock`, { lock_reason: "resolved" });
    await w.send("PATCH", `/repos/${REPO}/issues/${ledger}`, { state: "closed" });
  }
  const when = new Date().toISOString().slice(0, 16).replace("T", " ");
  const mark = what === "agreed" ? "✅ **Agreed**" : "❌ **Withdrawn**";
  await w.send("POST", `/repos/${REPO}/issues/${ledger}/comments`, {
    body: `<!-- terms:${what}:id=${c.user.id}:${c.user.login} -->\n${mark} · \`${c.user.login}\` (account ${c.user.id}) · PR #${number} · [their comment](${c.html_url}) · ${when} UTC`,
  });
  await w.comment(what === "agreed"
    ? `<!-- ytktv-terms-ok -->\n✅ Thank you, @${c.user.login}: your agreement to the contribution terms is recorded. It covers your later pull requests too, until you reply \`${DECLINE_REPLY}\`.`
    : `<!-- ytktv-terms-declined -->\nNoted, @${c.user.login}: you do not agree to the contribution terms, so this pull request cannot be merged. If you change your mind, reply \`${REPLY}\`.`);
}

async function once(number: number, tag: string, body: string) {
  const comments = await getAll(`/repos/${REPO}/issues/${number}/comments`);
  if (!comments.some((c) => c.body.startsWith(tag))) await new Writer(number).comment(`${tag}\n${body}`);
}

export function welcome(number: number, author: string) {
  const base = `${SERVER}/${REPO}/blob/main`;
  return once(number, "<!-- ytktv-welcome -->", [
    `### 🎤 Welcome, @${author}, and thank you for your first pull request to YTKTV!`,
    "",
    "A few things that help it go in quickly:",
    "",
    "- **Check it locally** before pushing (the same as CI, all without opening a window):",
    "  ```bash",
    '  pip install -e ".[dev]"',
    "  ruff check . && ruff format --check .",
    "  mypy src",
    "  QT_QPA_PLATFORM=offscreen pytest",
    "  ```",
    `- **The rules:** English in the code, comments and commits; tests need no network, sound card or window; one topic per pull request. See [CONTRIBUTING.md](${base}/CONTRIBUTING.md) and the [code of conduct](${base}/CODE_OF_CONDUCT.md).`,
    "- **Contribution terms:** I will post them in a moment; reply to agree, once, and it counts for your later pull requests too.",
    "- **The checks** run after a maintainer approves running them for a first-time contributor. My status comment below says what passed, what failed and what usually fixes it. Comment `@TonyD365-Agent /help` for the commands, e.g. `@TonyD365-Agent /retest`.",
    "- **Questions** are welcome right here, in English or Chinese.",
  ].join("\n"));
}

export function thanks(number: number, author: string, type: string) {
  const who = type === "Bot" ? author : `@${author}`;
  return once(number, "<!-- ytktv-thanks -->", [
    `### 🎉 Merged! Thank you for your contribution, ${who}!`,
    "",
    "Your change is now on `main` and will ship in the next YTKTV release.",
    "Ideas, bug reports and more pull requests are always welcome. 🎤",
  ].join("\n"));
}

export async function openNumbers(sha?: string): Promise<number[]> {
  const prs = await getAll(`/repos/${REPO}/pulls?state=open`);
  return prs.filter((p) => !sha || p.head.sha === sha).map((p) => p.number);
}

export async function sweep() {
  for (const number of await openNumbers()) {
    try {
      await refresh(number);
    } catch (e) {
      console.error(`sweep pr=${number}: ${e}`);
    }
  }
}
