# Alen Security Weekly Google Ads Brief

Read-only weekly Google Ads brief for Alen Security (customer 4563394098,
MCC 1614121172), delivered to Telegram every Monday 07:30 US Eastern.

Ported from the Hermes cron job `cb332bc38726` (Nov 2026 handoff).

## Layout
```
apps/worker/src/worker/
  entrypoints/worker.py        worker entrypoint (workflow discovery + run)
  workflows/alen_weekly_brief.py  workflow: pull -> brief agent -> telegram
  ads_pull.py                   Google Ads API pull (read-only), credentials from env
  brief_prompt.py               report rules (verbatim from the Hermes prompt) + dataset embedding
  telegram_delivery.py          chunked sendMessage / sendDocument delivery
deploy/docker/Dockerfile.worker  managed-deployment worker image
```

## Workspace secrets (bind at deploy)
- `google_ads_sa_json`    -> GOOGLE_ADS_SA_JSON   (service account key file contents)
- `google_ads_dev_token`  -> GOOGLE_ADS_DEV_TOKEN
- `telegram_bot_token`    -> TELEGRAM_BOT_TOKEN

Environmental defaults (override via env vars):
- GOOGLE_ADS_MCC_ID=1614121172, GOOGLE_ADS_CID=4563394098
- TELEGRAM_CHAT_ID=8355020994
- BRIEF_MODEL=mistral-large-latest

## Safety rules carried over from Hermes
- The job is READ-ONLY against the Google Ads account. No mutation, ever.
- Model is pinned explicitly; delivery target is explicit.
- Negative-change proposals only; the human (Mike) approves and owns UI changes.

## Deploy
From a Mistral workspace with pay-as-you-go enabled, deploy from this repo,
branch main, Dockerfile path `deploy/docker/Dockerfile.worker`, binding the
three secrets above. Then execute the `alen-weekly-brief` workflow with
`{"dry_run": true}` to test before scheduling `30 7 * * 1` in America/New_York.
