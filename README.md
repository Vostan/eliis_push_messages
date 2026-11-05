# Eliis → Telegram

Forwards everything from the Eliis kindergarten app (inbox messages and both children's
diaries) to a private Telegram channel, translated Estonian → English with gpt-4o-mini.

| File | Role |
|---|---|
| `poll.py` | The scheduled job: new inbox messages + new diary content → Telegram |
| `weekly_digest.py` | Sunday evening summary of the week |
| `eliis.py` | Eliis API client, child ids |
| `tg.py` | Telegram sending with retries and fallbacks |
| `translator.py` | OpenAI calls; every call falls back to the untranslated text |
| `state.json` | What has been posted; committed by CI after every run |

## How diary detection works (and why)

Eliis diary ids are **not** ordered by date: an entry can be created days ahead as an
empty placeholder, so "post everything with id > last id" skips real entries. Teachers
also write the text first and upload photos minutes to hours later. `poll.py` therefore
remembers, per entry, the text hash and the image ids already posted, and posts only
the delta: new text, or new photos as an album. Entries older than 45 days are pruned.

## Running

Secrets (GitHub Actions secrets, or env vars locally): `ELIIS_CSRF_TOKEN` (the `eliis_csrf`
cookie JWT, valid ~1 year), `BOT_TOKEN`, `OPENAI_API_KEY`.

```
python poll.py --dry-run   # show what would be posted, send nothing
python poll.py
python weekly_digest.py
```

## Scheduling

GitHub drops most ticks of a frequent `schedule` cron; a `*/5` cron fired only 4–7
times a day in practice. The workflow also accepts `workflow_dispatch`, so for real
10-minute latency point any external cron (cron-job.org, a Mac launchd job, ...) at:

```
curl -X POST -H "Authorization: Bearer <fine-grained PAT with Actions: write>" \
  https://api.github.com/repos/Vostan/eliis_push_messages/actions/workflows/scheduled-job.yml/dispatches \
  -d '{"ref":"main"}'
```
