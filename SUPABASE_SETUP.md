# TrendRadar Supabase Setup Guide

This guide walks you through setting up Supabase as the storage backend for TrendRadar.

## Prerequisites

- A Supabase project ([supabase.com](https://supabase.com))
- `psql` or access to the Supabase SQL Editor (Dashboard → SQL Editor)
- Python 3.10+

---

## Step 1: Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) and sign in.
2. Click **New Project**.
3. Choose your organization and region.
4. Set a strong database password — save it somewhere safe.
5. Wait for the project to provision (~2 min).

---

## Step 2: Get Your Credentials

1. In your project dashboard, go to **Settings → API**.
2. Copy the following:
   - **Project URL** → `SUPABASE_URL`
   - **anon/public** key → `SUPABASE_KEY` (safe for client-side use)

---

## Step 3: Run the Schema Migration

### Option A: Supabase SQL Editor (Recommended)

1. In the Supabase dashboard, go to **SQL Editor**.
2. Click **New Query**.
3. Paste the contents of `supabase/migrations/001_trendradar_schema.sql`.
4. Click **Run**.

### Option B: Via `psql`

```bash
psql "postgresql://postgres:<YOUR_PASSWORD>@db.<YOUR_PROJECT_REF>.supabase.co:5432/postgres" \
  -f supabase/migrations/001_trendradar_schema.sql
```

Replace `<YOUR_PASSWORD>` and `<YOUR_PROJECT_REF>` with your values.

---

## Step 4: Configure Environment Variables

Add these to your `.env` file (or export them directly):

```bash
SUPABASE_URL=https://<YOUR_PROJECT_REF>.supabase.co
SUPABASE_KEY=<your-anon-key>
```

For local development, create or update `.env` in the project root:

```
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGc...
```

---

## Step 5: Install the Supabase Python Client

```bash
pip install supabase>=2.0.0
```

The dependency is already listed in `requirements.txt`.

---

## Step 6: Verify the Connection

From the project root, run:

```python
from storage.supabase_client import SupabaseClient

client = SupabaseClient()
print("Supabase available:", client.available)
```

If `available` is `True`, the client connected successfully.

---

## Step 7: (Optional) Migrate Existing JSON Data

If you have existing data in `data/trends.json` and want to backfill:

```python
import json
from pathlib import Path
from storage.supabase_client import SupabaseClient

client = SupabaseClient()
data = json.loads(Path("data/trends.json").read_text())

# Migrate snapshots
for source, snapshots in data.get("sources", {}).items():
    for snap in snapshots:
        client.save_snapshot(snap["source"], snap["data"])

# Migrate digests
for d in data.get("digests", []):
    client.save_digest(d)

print("Migration complete.")
```

**Note:** Run this only once. Duplicate runs will create duplicate records.

---

## Row Level Security (RLS)

The schema above creates tables without RLS policies. For production, add policies:

```sql
-- Allow authenticated inserts/reads (adjust as needed)
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE digests ENABLE ROW LEVEL SECURITY;
ALTER TABLE trend_history ENABLE ROW LEVEL SECURITY;

-- Example: public read/write for anon keys
CREATE POLICY "Public snapshots" ON snapshots
  FOR ALL USING (true) WITH CHECK (true);
```

For private data, scope policies to `auth.uid()`.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `SUPABASE_URL` not set | Add to `.env` and restart your app |
| `SUPABASE_KEY` not set | Use the anon key from Settings → API |
| Connection refused | Check your project status in Supabase dashboard |
| RLS blocked reads | Add or relax row level security policies |
| Duplicate migration errors | Safe to re-run — `CREATE TABLE IF NOT EXISTS` is idempotent |

---

## Files Reference

| File | Purpose |
|---|---|
| `supabase/migrations/001_trendradar_schema.sql` | Database schema |
| `storage/supabase_client.py` | Python client (drop-in replacement) |
| `storage/trends.py` | Original JSON storage (unchanged) |
| `requirements.txt` | Updated with `supabase>=2.0.0` |
