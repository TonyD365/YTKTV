import { validSignature } from "./index.ts";
import {
  aggregate, type Check, kind, latestChecks, ledgerState, renderStatus, type State,
  termsMarkdown, termsReply, wantedLabels, withoutTimestamp,
} from "./logic.ts";

function eq(a: unknown, b: unknown) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${JSON.stringify(a)} != ${JSON.stringify(b)}`);
}
const pass: Check = { name: "Tests", status: "completed", conclusion: "success", html_url: "u" };
const fail: Check = { ...pass, name: "Tests", conclusion: "failure" };
const base: State = {
  number: 7, head: "abcdef1234", author: "someone", draft: false, review: "REVIEW_REQUIRED",
  conflict: false, checks: [pass], busy: 0, waiting: [], terms: "exempt",
};

Deno.test("all checks passed", () => {
  eq(aggregate(base).state, "success");
  eq(kind(base), "passed-REVIEW_REQUIRED");
  eq(wantedLabels(base), ["Checks-Passed", "Needs-Review"]);
});
Deno.test("no checks yet is pending, never success", () => eq(aggregate({ ...base, checks: [] }).state, "pending"));
Deno.test("an unfinished workflow run keeps it pending", () => eq(aggregate({ ...base, busy: 1 }).state, "pending"));
Deno.test("a failed check fails", () => {
  eq(aggregate({ ...base, checks: [fail] }).state, "failure");
  eq(wantedLabels({ ...base, checks: [fail] }).includes("Needs-Author-Action"), true);
});
Deno.test("cancelled is an internal failure", () => {
  const s = { ...base, checks: [{ ...pass, conclusion: "cancelled" }] };
  eq(aggregate(s).state, "failure");
  eq(wantedLabels(s).includes("Internal-Error"), true);
});
Deno.test("terms not agreed or declined block success", () => {
  eq(aggregate({ ...base, terms: "no" }).state, "failure");
  eq(aggregate({ ...base, terms: "declined" }).state, "failure");
});
Deno.test("waiting workflows stay pending", () => eq(aggregate({ ...base, waiting: ["CI"] }).state, "pending"));
Deno.test("a re-run replaces the older result", () => {
  const old = { ...fail, started_at: "2026-01-01" };
  const again = { ...pass, started_at: "2026-01-02" };
  eq(latestChecks([again, old]).map((c) => c.conclusion), ["success"]);
});
Deno.test("the finished suite counts as completed", () => {
  const c = { ...pass, status: "in_progress", conclusion: null, check_suite: { id: 5 } };
  eq(latestChecks([c], 5, "success")[0].status, "completed");
});
Deno.test("terms replies are exact", () => {
  eq(termsReply(" @TonyD365-Agent I agree to the YTKTV contribution terms. "), "agreed");
  eq(termsReply("@tonyd365-agent, I agree to the YTKTV contribution terms"), "agreed");
  eq(termsReply("@TonyD365-Agent I don’t agree to the YTKTV contribution terms"), "declined");
  eq(termsReply("@TonyD365-Agent I agree to the YTKTV contribution terms, but"), null);
  eq(termsReply("I agree to the YTKTV contribution terms"), null);
  eq(termsReply("@TonyD365-Agent2 I agree to the YTKTV contribution terms"), null);
  eq(termsReply("Thanks @TonyD365-Agent I agree to the YTKTV contribution terms"), null);
});
Deno.test("the latest ledger entry decides", () => {
  const lines = ["<!-- terms:agreed:id=9:a -->", "<!-- terms:declined:id=8:b -->", "<!-- terms:declined:id=9:renamed -->"];
  eq(ledgerState(lines, 9, "a"), "declined");
  eq(ledgerState(lines, 7, "c"), "none");
});
Deno.test("terms section is extracted", () => {
  const md = "# x\n## Contribution terms\nOn your first pull request\nblah\nyou agree that:\n- one [L](LICENSE)\n## Next\nno";
  eq(termsMarkdown(md), "- one [L](https://github.com/TonyD365/YTKTV/blob/main/LICENSE)");
});
Deno.test("only the timestamp may differ between same comments", () => {
  const a = renderStatus(base, [], new Date("2026-01-01T00:00:00Z"));
  const b = renderStatus(base, [], new Date("2026-01-02T00:00:00Z"));
  eq(a === b, false);
  eq(withoutTimestamp(a), withoutTimestamp(b));
});
Deno.test("webhook signatures are verified", async () => {
  const body = new TextEncoder().encode("{}");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode("s"), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, body));
  const hex = [...sig].map((b) => b.toString(16).padStart(2, "0")).join("");
  eq(await validSignature("s", body, `sha256=${hex}`), true);
  eq(await validSignature("wrong", body, `sha256=${hex}`), false);
  eq(await validSignature("s", body, "sha256=zz"), false);
  eq(await validSignature("", body, `sha256=${hex}`), false);
});
