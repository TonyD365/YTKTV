# The bot on Supabase Edge Functions

Everything TonyD365-Agent does on pull requests and issues, run from GitHub webhooks instead of
Actions: the status comment, labels, contribution terms, auto-merge, welcome and thanks
(`assistant.ts`), and the commands, issue triage, fixed and released notices, file labels,
reminders and stale pull requests (`bots.ts`). The old workflows (`pr-assistant`,
`review-noted`, `pr-commands`, `issue-assistant`, `labeler`, `label-apply`) are disabled, not
deleted: they are the fallback.

It works out the state from GitHub on every event, so repeated or out-of-order webhooks are
harmless. Every write goes through one switch:

- `LIVE_PRS` empty: shadow mode. Writes are only logged.
- `LIVE_PRS=123,124`: only those pull requests.
- `LIVE_PRS=*`: all of them.
- `BOTS_LIVE=1`: the commands and the rest of `bots.ts` write too (anything else only logs).

To go back, set `LIVE_PRS` empty and `BOTS_LIVE` to 0 first, then enable the old workflows;
otherwise both write.

Every interaction starts with `@TonyD365-Agent`, e.g. `@TonyD365-Agent I agree to the YTKTV
contribution terms`.

After a merge the head branch is deleted (never a fork's, the default branch, or the base of
another open pull request). `@TonyD365-Agent /keep-branch` keeps it (label `Keep-Branch`);
`@TonyD365-Agent /delete-branch` undoes that. Only the author or a maintainer can use them.

## Secrets (Edge Functions → Secrets, set by the maintainer, never pasted in chat)

| Name | What |
|---|---|
| `GITHUB_TOKEN` | TonyD365-Agent classic token, `public_repo` only, 90 days (the current one expires around 2027-02-22). When it expires the required check stops updating and nothing can merge: replace it beforehand. |
| `WEBHOOK_SECRET` | The repository webhook's secret. |
| `SWEEP_SECRET` | Signs the scheduled sweep (also in Vault as `sweep_secret`, and in the Actions secret `SUPABASE_SWEEP_SECRET`). |
| `LIVE_PRS`, `BOTS_LIVE` | See above. |

## Setup

1. `npx supabase login`, then `npx supabase functions deploy pr-assistant --project-ref <ref>`.
2. Repository webhook: `https://<ref>.supabase.co/functions/v1/pr-assistant`, content type
   JSON, the webhook secret, events: Pull requests, Pull request reviews, Issue comments,
   Issues, Releases, Workflow runs, Pushes.
3. Run `cron.sql` in the SQL editor for the sweep, reminders and stale checks (project `fqccljyubefeakscukpx`).
4. Repository variable `SUPABASE_SWEEP_URL` (the `/sweep` URL) and secret
   `SUPABASE_SWEEP_SECRET` for `supabase-keepalive.yml`, which stops a free project pausing.

Tests (an in-memory GitHub, no network): `cd supabase/functions/pr-assistant && LIVE_PRS='*' deno test --allow-env`.
