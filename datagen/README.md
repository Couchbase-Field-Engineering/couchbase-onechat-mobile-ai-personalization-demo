# The nightly export

OneChat personalizes from one dataset, `onechat_people`: a nightly export with
one JSON Lines row per person the company chatbot serves.

| Audience | Comes from (in production) | What the row carries |
|---|---|---|
| `customer` | Commerce platform + CDP | Rewards tier, recent orders with shipments, open cart, saved address, store, propensity scores |
| `lead` | CRM | Company, role, team size, interest, lead status and score |
| `employee` | HRIS + ITSM | Role, department, manager, start date, open IT tickets, onboarding tasks, benefits window, time-off balance |

## Layout

```
data/onechat-export/
  exportTime=20261113/
    part-00000.json      JSON Lines, one person per line
    part-00001.json
    _manifest.json       dataset, schema version, row counts per audience
    _SUCCESS             written last; the loader ignores a partition without it
```

The backend loads the newest complete partition on startup and looks for a
newer one every `EXPORT_POLL_SECONDS`. Point whatever delivers your real export
(object storage sync, an ETL job) at the folder mounted as `EXPORT_DIR`.

## Generating a mock export

```bash
python3 datagen/generate_mock_export.py                       # 24 MiB, 2 parts, today's date
python3 datagen/generate_mock_export.py --export-date 2026-11-13 --target-mb 8 --parts 1
```

* About 480 people per MiB, split roughly 75% customers, 12% prospects, 13% team members across the 12 groups in `backend/app/catalog.py`.
* Deterministic for a given `--seed` on a given Python version.
* The three demo personas (Maya Chen, Daniel Okafor, Sofia Alvarez) are always the first rows, with dates relative to the export date, so the demo reads the same whenever it is run.
* The Helm chart ships the same script (`helm/onechat-app/files/generate_mock_export.py`); keep the two copies identical.

## Live lookups

The export is a day old by design. When the assistant builds context for a
personal question it also asks the system of record for the current profile
(`backend/app/sources.py`): set `SOR_PROFILE_API_URL` / `SOR_API_TOKEN` to call a
real one, or leave them blank and the backend answers from the loaded row after
a simulated `SOR_MOCK_LATENCY_MS` delay. Help Center and Team Handbook articles
come from `CMS_KB_ENDPOINT` when set, otherwise from the bundled articles in
`backend/app/knowledge.py`.
