# NamEngine Business

Minimal Flask prototype for a premium business naming web app.

## Local run

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## Environment

- `OPENAI_API_KEY` - optional for live AI suggestions
- `OPENAI_MODEL` - optional, defaults to `gpt-4.1-mini`
- `OPENAI_ORIGINAL_MODEL` - optional model override for original-name generation, defaults to `OPENAI_MODEL`

Without an API key, the app uses a small curated fallback set so the product flow still works.

For local development, copy `.env.example` to `.env` and add the real key. `.env` is git-ignored and loaded automatically by the Flask app.

## Engine probe

```bash
python engine_probe.py
```

The probe prints curated prompt details and original-name outputs. It reports whether original-name generation used OpenAI or the fallback engine.

## Share links

Shortlists now create durable share snapshots in `share_store.json` by default so people can text or email themselves a stable link.

Optional environment variables:
- `SHARE_STORE_PATH` - override where share snapshots are stored
- `PUBLIC_BASE_URL` - force absolute share links for email/text sharing (for example your Render app URL)

## Feedback

Feedback is off by default. Set `FEEDBACK_ENABLED=true` to show feedback links and allow `/feedback`.

Preferred production storage is Google Sheets. JSON storage remains as a local fallback when Sheets credentials are not configured.

Optional environment variables:
- `FEEDBACK_ENABLED` - set to `true` to show feedback links and accept submissions
- `FEEDBACK_STORE_PATH` - override where local fallback feedback is stored
- `FEEDBACK_ADMIN_TOKEN` - required token for the fallback feedback responses page
- `GOOGLE_FEEDBACK_SHEET_ID` - spreadsheet ID for feedback rows
- `GOOGLE_SERVICE_ACCOUNT_JSON` - full service account JSON as a secret env var
- `GOOGLE_FEEDBACK_WORKSHEET` - worksheet tab name, defaults to `Feedback`

Before enabling production feedback, share the Google Sheet with the service account `client_email` as Editor.

## Smoke tests

The Business smoke harness writes a CSV backup by default:

```bash
python run_business_smoke_test_batch.py
```

To append the same rows directly to the grading Google Sheet:

```bash
python run_business_smoke_test_batch.py --append-to-sheets
```

To upload existing CSVs:

```bash
python append_business_smoke_csv_to_google_sheet.py namengine_business_smoke_test_YYYYMMDD-HHMMSS.csv
```

Optional environment variables:
- `GOOGLE_SMOKE_TEST_SHEET_ID` - spreadsheet ID for smoke-test grading rows
- `GOOGLE_SMOKE_TEST_WORKSHEET` - worksheet tab name, defaults to `Smoke Tests`
- `GOOGLE_SERVICE_ACCOUNT_JSON` - full service account JSON as a secret env var

Share the grading Google Sheet with the service account `client_email` as Editor before appending.

## Feature flags

- `LIVE_BRIEF_ENABLED` - defaults to `true`; set to `false` to hide the live Taste builder on the curated intake without removing the code.

## Deploy

This repo includes `render.yaml` for Render deployment.
