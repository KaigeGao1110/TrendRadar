# Cloud Scheduler Setup - TrendRadar

## Jobs Created (all ENABLED)

| Job ID | Schedule (CT) | HTTP Method | Endpoint |
|--------|--------------|-------------|----------|
| `trend-radar-daily-fetch` | 0 7 * * * (7 AM CT) | GET | `/trends` |
| `trend-radar-daily-digest` | 0 8 * * * (8 AM CT) | POST | `/digest/daily` |
| `trend-radar-yc` | 0 */6 * * * (every 6h) | GET | `/sources/ycombinator` |
| `trend-radar-hn` | 0 */6 * * * (every 6h) | GET | `/sources/hackernews` |

## Notes
- OIDC/service account auth was skipped — `deployer@testforcureforge.iam.gserviceaccount.com` lacks `iam.serviceAccounts.actAs` permission on itself.
- Jobs run with default App Engine service account (the `Compute Engine default service account`).
- All jobs target: `https://trend-radar-594674305905.us-central1.run.app`
- Manual trigger of `trend-radar-daily-fetch` succeeded (lastAttemptTime: 2026-03-31T23:38:58Z, status: {}).

## Commands
```bash
# List all jobs
gcloud scheduler jobs list --location=us-central1

# Trigger manually
gcloud scheduler jobs run trend-radar-daily-fetch --location=us-central1

# Delete a job
gcloud scheduler jobs delete trend-radar-daily-fetch --location=us-central1
```
