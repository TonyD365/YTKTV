// The whole assistant against an in-memory GitHub: real code, no network.
import { route } from "./index.ts";
import { sweep } from "./assistant.ts";
import { DECLINE_REPLY, PHRASE, REPLY, REPO } from "./logic.ts";

// deno-lint-ignore no-explicit-any
type Any = any;
const BOT = "TonyD365-Agent";
const repository = { full_name: REPO };

function world(over: Record<string, unknown> = {}) {
  const w: Any = {
    pr: {
      number: 50, id: "PR_50", head: "abcdef1234567", author: "alice", authorId: 11,
      state: "OPEN", draft: false, review: "REVIEW_REQUIRED", mergeable: "MERGEABLE",
      labels: [], auto: false, ...over,
    },
    comments: [], ledger: [], ledgerIssue: null as number | null, statuses: [],
    checks: [{ name: "Tests", status: "completed", conclusion: "success", html_url: "u", started_at: "1", check_suite: { id: 1 } }],
    runs: [], reviews: [], nextId: 100, writes: 0,
  };
  const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  // deno-lint-ignore require-await
  globalThis.fetch = (async (input: string, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    const p = url.pathname.replace(`/repos/${REPO}`, "");
    if (method !== "GET" && p !== "/graphql") w.writes++;
    if (url.hostname === "raw.githubusercontent.com") {
      return new Response("## Contribution terms\nOn your first pull request\nyou agree that:\n- Term one\n## End\n");
    }
    if (p === "/graphql") {
      if (body.query.includes("enablePullRequestAutoMerge")) { w.pr.auto = true; w.writes++; return json({ data: {} }); }
      if (body.query.includes("mergePullRequest(")) { w.pr.state = "MERGED"; w.merged = true; w.writes++; return json({ data: {} }); }
      if (body.query.includes("disablePullRequestAutoMerge")) { w.pr.auto = false; w.writes++; return json({ data: {} }); }
      return json({ data: { repository: { pullRequest: {
        id: w.pr.id, state: w.pr.state, isDraft: w.pr.draft, reviewDecision: w.pr.review,
        mergeable: w.pr.mergeable, mergeStateStatus: w.pr.mergeState ?? "BLOCKED", headRefOid: w.pr.head, headRefName: "feature", isCrossRepository: !!w.pr.fork,
        labels: { nodes: w.pr.labels.map((name: string) => ({ name })) },
        autoMergeRequest: w.pr.auto ? { enabledAt: "x" } : null,
      } } } });
    }
    if (method === "GET" && p === "/pulls") return json(w.pr.state === "OPEN" ? [{ number: 50, head: { sha: w.pr.head } }] : []);
    if (method === "GET" && p === "/pulls/50") return json({ user: { login: w.pr.author, id: w.pr.authorId } });
    if (method === "GET" && p === "/pulls/50/files") return json([]);
    if (method === "GET" && p === "/issues/50") return json({ labels: [] });
    if (method === "GET" && p === "/pulls/50/reviews") return json(w.reviews);
    if (method === "GET" && p.endsWith("/check-runs")) return json({ check_runs: w.checks });
    if (method === "GET" && p === "/actions/runs") return json({ workflow_runs: w.runs });
    if (method === "GET" && p === "/issues") return json(w.ledgerIssue ? [{ number: w.ledgerIssue }] : []);
    if (method === "GET" && p === "/issues/50/comments") return json(w.comments);
    if (method === "GET" && p === `/issues/${w.ledgerIssue}/comments`) return json(w.ledger);
    if (method === "POST" && p === "/labels") return json({}, w.pr.labels.includes(body.name) ? 422 : 201);
    if (method === "POST" && p === "/issues/50/labels") { w.pr.labels.push(...body.labels); return json({}); }
    let m = p.match(/^\/issues\/50\/labels\/(.+)$/);
    if (method === "DELETE" && m) { w.pr.labels = w.pr.labels.filter((l: string) => l !== decodeURIComponent(m![1])); return json({}); }
    if (method === "POST" && p === "/issues/50/comments") {
      const c = { id: w.nextId++, body: body.body, user: { login: BOT } };
      w.comments.push(c);
      return json(c, 201);
    }
    m = p.match(/^\/issues\/comments\/(\d+)$/);
    if (m) {
      const id = Number(m[1]);
      if (method === "DELETE") { w.comments = w.comments.filter((c: Any) => c.id !== id); return new Response(null, { status: 204 }); }
      if (method === "PATCH") { w.comments.find((c: Any) => c.id === id).body = body.body; return json({}); }
    }
    if (method === "POST" && p === "/issues") { w.ledgerIssue = 900; w.locked = false; return json({ number: 900 }, 201); }
    if (method === "PUT" && p === "/issues/900/lock") { w.locked = true; return new Response(null, { status: 204 }); }
    if (method === "PATCH" && p === "/issues/900") { w.closed = true; return json({}); }
    if (method === "POST" && p === `/issues/${w.ledgerIssue}/comments`) {
      w.ledger.push({ body: body.body, user: { login: BOT } });
      return json({}, 201);
    }
    if (method === "DELETE" && p.startsWith("/git/refs/heads/")) { w.deleted = decodeURIComponent(p.slice(16)); return new Response(null, { status: 204 }); }
    if (method === "POST" && p.startsWith("/statuses/")) { w.statuses.push(body); return json({}, 201); }
    throw new Error(`unexpected ${method} ${p}`);
  }) as typeof fetch;
  return w;
}

const status = (w: Any, context = "YTKTV checks") => w.statuses.filter((s: Any) => s.context === context).at(-1)?.state;
const assistantComments = (w: Any) => w.comments.filter((c: Any) => c.body.startsWith("<!-- ytktv-pr-assistant"));
const has = (w: Any, tag: string) => w.comments.filter((c: Any) => c.body.startsWith(tag)).length;
const pull = (w: Any, action: string, extra = {}) => ({
  action, repository,
  pull_request: { number: 50, merged: false, author_association: "FIRST_TIME_CONTRIBUTOR", user: { login: w.pr.author, id: w.pr.authorId, type: "User" }, ...extra },
});
const say = (w: Any, text: string, user = { login: w.pr.author, id: w.pr.authorId }) => ({
  action: "created", repository,
  issue: { number: 50, pull_request: {}, user: { id: w.pr.authorId, login: w.pr.author } },
  comment: { body: text, html_url: "c", user },
});
function ok(cond: unknown, what: string) { if (!cond) throw new Error(what); }
function eq(a: unknown, b: unknown, what = "") { if (a !== b) throw new Error(`${what}: ${a} != ${b}`); }

Deno.env.set("LIVE_PRS", "*");
Deno.env.set("GITHUB_TOKEN", "test");

Deno.test("first pull request: welcome and terms, once, and it cannot pass", async () => {
  const w = world();
  await route("pull_request", pull(w, "opened"));
  await route("pull_request", pull(w, "opened"));
  eq(has(w, "<!-- ytktv-welcome"), 1, "welcome");
  eq(has(w, "<!-- ytktv-terms-ask"), 1, "terms ask");
  ok(w.comments.find((c: Any) => c.body.includes("Term one")), "terms text");
  eq(status(w), "failure");
  eq(status(w, "Contribution terms"), "failure");
  ok(w.pr.labels.includes("Needs-Terms-Agreement"), "label");
  eq(assistantComments(w).length, 1, "status comments");
});

Deno.test("agree: ledger, green check; repeat is recorded once", async () => {
  const w = world();
  await route("pull_request", pull(w, "opened"));
  await route("issue_comment", say(w, REPLY));
  await route("issue_comment", say(w, REPLY));
  eq(w.ledger.length, 1, "ledger");
  ok(w.locked && w.closed, "ledger locked and closed");
  eq(has(w, "<!-- ytktv-terms-ok"), 1, "reply");
  eq(status(w), "success");
  eq(status(w, "Contribution terms"), "success");
  ok(w.pr.labels.includes("Terms-Agreed") && !w.pr.labels.includes("Needs-Terms-Agreement"), "labels");
});

Deno.test("withdraw turns it red again", async () => {
  const w = world();
  await route("pull_request", pull(w, "opened"));
  await route("issue_comment", say(w, REPLY));
  await route("issue_comment", say(w, DECLINE_REPLY));
  eq(status(w), "failure");
  ok(w.pr.labels.includes("Terms-Declined"), "label");
  ok(!w.pr.labels.includes("Terms-Agreed"), "old label");
});

Deno.test("a comment without the mention does nothing", async () => {
  const w = world();
  await route("issue_comment", say(w, PHRASE));
  eq(w.writes, 0, "writes");
  eq(w.ledger.length, 0, "ledger");
});

Deno.test("someone else cannot agree for the author", async () => {
  const w = world();
  await route("pull_request", pull(w, "opened"));
  await route("issue_comment", say(w, REPLY, { login: "mallory", id: 66 }));
  eq(w.ledger.length, 0, "ledger");
  eq(status(w), "failure");
});

Deno.test("the bot's own comment does nothing", async () => {
  const w = world({ author: "TonyD365" });
  await route("issue_comment", say(w, REPLY, { login: BOT, id: 1 }));
  eq(w.writes, 0, "writes");
});

Deno.test("another repository is ignored", async () => {
  const w = world();
  await route("pull_request", { ...pull(w, "opened"), repository: { full_name: "evil/repo" } });
  eq(w.writes, 0, "writes");
});

Deno.test("failed, then fixed: one comment, right labels", async () => {
  const w = world({ author: "TonyD365" });
  w.checks = [{ ...w.checks[0], conclusion: "failure" }];
  await route("pull_request", pull(w, "synchronize"));
  eq(status(w), "failure");
  ok(assistantComments(w)[0].body.includes("A test failed"), "hint");
  ok(w.pr.labels.includes("Checks-Failed"), "failed label");
  w.checks = [{ ...w.checks[0], conclusion: "success" }];
  await route("pull_request", pull(w, "synchronize"));
  eq(status(w), "success");
  ok(!w.pr.labels.includes("Checks-Failed") && w.pr.labels.includes("Checks-Passed"), "labels");
  eq(assistantComments(w).length, 1, "status comments");
  ok(assistantComments(w)[0].body.includes("All 1 checks passed"), "text");
});

Deno.test("running stays pending", async () => {
  const w = world({ author: "TonyD365" });
  w.checks = [{ ...w.checks[0], status: "in_progress", conclusion: null }];
  await route("pull_request", pull(w, "synchronize"));
  eq(status(w), "pending");
  ok(w.pr.labels.includes("Checks-Running"), "label");
});

Deno.test("merge conflict is explained and labelled", async () => {
  const w = world({ author: "TonyD365", mergeable: "CONFLICTING" });
  await route("pull_request", pull(w, "synchronize"));
  ok(w.pr.labels.includes("Merge-Conflict") && w.pr.labels.includes("Needs-Author-Action"), "labels");
  ok(assistantComments(w)[0].body.includes("**Merge conflict:**"), "text");
});

Deno.test("a push to main finds new conflicts", async () => {
  const w = world({ author: "TonyD365", mergeable: "CONFLICTING" });
  await route("push", { ref: "refs/heads/main", repository });
  ok(w.pr.labels.includes("Merge-Conflict"), "label");
});

Deno.test("approval turns auto-merge on; requested changes turn it off", async () => {
  const w = world({ author: "TonyD365", review: "APPROVED" });
  await route("pull_request_review", { action: "submitted", repository, pull_request: { number: 50 } });
  eq(w.pr.auto, true, "on");
  ok(w.pr.labels.includes("Maintainer-Approved"), "label");
  w.pr.review = "CHANGES_REQUESTED";
  w.reviews = [{ state: "CHANGES_REQUESTED", user: { login: "TonyD365" }, html_url: "r" }];
  await route("pull_request_review", { action: "submitted", repository, pull_request: { number: 50 } });
  eq(w.pr.auto, false, "off");
  ok(w.pr.labels.includes("Changes-Requested"), "label");
});

Deno.test("a draft never gets auto-merge", async () => {
  const w = world({ author: "TonyD365", review: "APPROVED", draft: true });
  await route("pull_request", pull(w, "edited"));
  eq(w.pr.auto, false, "auto");
});

Deno.test("merged: thanks once, bots without a mention", async () => {
  const w = world({ state: "MERGED" });
  await route("pull_request", pull(w, "closed", { merged: true }));
  await route("pull_request", pull(w, "closed", { merged: true }));
  eq(has(w, "<!-- ytktv-thanks"), 1, "thanks");
  ok(w.comments[0].body.includes("@alice"), "mention");
  const b = world({ state: "MERGED", author: "dependabot[bot]" });
  await route("pull_request", pull(b, "closed", { merged: true, user: { login: "dependabot[bot]", type: "Bot" } }));
  ok(!b.comments[0].body.includes("@dependabot"), "no mention");
});

Deno.test("closed without merging gets no thanks", async () => {
  const w = world({ state: "CLOSED" });
  await route("pull_request", pull(w, "closed"));
  eq(w.comments.length, 0, "comments");
});

Deno.test("a finished workflow updates only the matching commit", async () => {
  const w = world({ author: "TonyD365" });
  await route("workflow_run", { action: "completed", repository, workflow_run: { head_sha: "other", check_suite_id: 1, conclusion: "success" } });
  eq(w.writes, 0, "other commit");
  w.checks = [{ ...w.checks[0], status: "in_progress", conclusion: null }];
  await route("workflow_run", { action: "completed", repository, workflow_run: { head_sha: w.pr.head, check_suite_id: 1, conclusion: "success" } });
  eq(status(w), "success");
});

Deno.test("two webhooks at once leave one status comment", async () => {
  const w = world({ author: "TonyD365" });
  await Promise.all([route("pull_request", pull(w, "synchronize")), route("pull_request", pull(w, "synchronize"))]);
  eq(assistantComments(w).length, 1, "status comments");
});

Deno.test("sweep with nothing changed rewrites no comment", async () => {
  const w = world({ author: "TonyD365" });
  await sweep();
  const before = assistantComments(w)[0].body;
  await sweep();
  eq(assistantComments(w)[0].body, before, "comment");
});

Deno.test("shadow mode sends no writes", async () => {
  Deno.env.set("LIVE_PRS", "");
  try {
    const w = world();
    await route("pull_request", pull(w, "opened"));
    await route("issue_comment", say(w, REPLY));
    eq(w.writes, 0, "writes");
  } finally {
    Deno.env.set("LIVE_PRS", "*");
  }
});

Deno.test("approved and every check passed: merged at once", async () => {
  const w = world({ author: "TonyD365", review: "APPROVED", mergeState: "CLEAN" });
  await route("pull_request", pull(w, "edited"));
  eq(w.merged, true, "merged");
});

Deno.test("approved while checks run: auto-merge only", async () => {
  const w = world({ author: "TonyD365", review: "APPROVED", mergeState: "CLEAN" });
  w.checks = [{ ...w.checks[0], status: "in_progress", conclusion: null }];
  await route("pull_request", pull(w, "edited"));
  eq(w.merged, undefined, "merged");
  eq(w.pr.auto, true, "auto");
});

const merged = (w: Any, extra = {}) => pull(w, "closed", {
  merged: true, head: { ref: "feature", repo: { full_name: w.pr.fork ? "bob/YTKTV" : REPO } },
  base: { repo: { default_branch: "main" } }, labels: w.pr.labels.map((name: string) => ({ name })), ...extra,
});

Deno.test("merged: the branch is deleted by default, and the status comment says so", async () => {
  const w = world({ author: "TonyD365" });
  await route("pull_request", pull(w, "edited"));
  ok(assistantComments(w)[0].body.includes("`feature` is deleted automatically"), "hint");
  ok(assistantComments(w)[0].body.includes("@TonyD365-Agent /keep-branch"), "command");
  w.pr.state = "MERGED";
  await route("pull_request", merged(w));
  eq(w.deleted, "feature", "deleted");
});

Deno.test("/keep-branch keeps it; /delete-branch undoes that", async () => {
  const w = world({ author: "TonyD365" });
  await route("issue_comment", say(w, "@TonyD365-Agent /keep-branch"));
  ok(w.pr.labels.includes("Keep-Branch"), "label");
  ok(assistantComments(w).at(-1).body.includes("is kept after merging"), "status");
  w.pr.state = "MERGED";
  await route("pull_request", merged(w));
  eq(w.deleted, undefined, "kept");
  w.pr.state = "OPEN";
  await route("issue_comment", say(w, "@TonyD365-Agent /delete-branch"));
  ok(!w.pr.labels.includes("Keep-Branch"), "label removed");
});

Deno.test("only the author or a maintainer can keep the branch", async () => {
  const w = world({ author: "TonyD365" });
  await route("issue_comment", say(w, "@TonyD365-Agent /keep-branch", { login: "mallory", id: 99 } as Any));
  ok(!w.pr.labels.includes("Keep-Branch"), "no label");
});

Deno.test("a fork's branch is never deleted", async () => {
  const w = world({ author: "TonyD365", fork: true });
  await route("pull_request", pull(w, "edited"));
  ok(!assistantComments(w)[0].body.includes("deleted automatically"), "no hint");
  w.pr.state = "MERGED";
  await route("pull_request", merged(w));
  eq(w.deleted, undefined, "fork");
});
