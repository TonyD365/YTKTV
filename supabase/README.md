# PR assistant on Supabase Edge Functions

The same PR assistant as `.github/workflows/pr-assistant.yml` (status comment, labels,
contribution terms, auto-merge, welcome, thanks), run from GitHub webhooks instead of Actions.

It works out the state from GitHub on every event, so repeated or out-of-order webhooks are
harmless. Every write goes through one switch:

- `LIVE_PRS` empty: shadow mode. Writes are only logged.
- `LIVE_PRS=123,124`: only those pull requests.
- `LIVE_PRS=*`: all of them. Then disable (never delete) the old workflow, which stays the fallback.
  To go back, set `LIVE_PRS` empty first, then enable the workflow again.

Every interaction starts with `@TonyD365-Agent`, e.g. `@TonyD365-Agent I agree to the YTKTV
contribution terms`.

## Secrets (Edge Functions → Secrets, set by the maintainer, never pasted in chat)

| Name | What |
|---|---|
| `GITHUB_TOKEN` | TonyD365-Agent classic token, `public_repo` only, 90 days. When it expires the required check stops updating and nothing can merge: replace it beforehand. |
| `WEBHOOK_SECRET` | The repository webhook's secret. |
| `SWEEP_SECRET` | Signs the scheduled sweep (also in Vault as `sweep_secret`, and in the Actions secret `SUPABASE_SWEEP_SECRET`). |
| `LIVE_PRS` | See above. |

## Setup

1. `npx supabase login`, then `npx supabase functions deploy pr-assistant --project-ref <ref>`.
2. Repository webhook: `https://<ref>.supabase.co/functions/v1/pr-assistant`, content type
   JSON, the webhook secret, events: Pull requests, Pull request reviews, Issue comments,
   Workflow runs, Pushes.
3. Run `cron.sql` in the SQL editor for the 10-minute sweep (project `fqccljyubefeakscukpx`).
4. Repository variable `SUPABASE_SWEEP_URL` (the `/sweep` URL) and secret
   `SUPABASE_SWEEP_SECRET` for `supabase-keepalive.yml`, which stops a free project pausing.

Tests (an in-memory GitHub, no network): `cd supabase/functions/pr-assistant && LIVE_PRS='*' deno test --allow-env`.
