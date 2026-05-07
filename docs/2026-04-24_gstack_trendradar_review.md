# GSTACK TrendRadar Database & Pipeline Review
## Date: 2026-04-24
## Mode: HOLD SCOPE
### Overall Score: 7/10

## 1. Architecture Review Findings
### Current 3-Layer Design
| Layer | Design | Risks | Fixes |
|-------|--------|-------|-------|
| S3 Raw | `trendradar-raw` bucket, private, SSL only | ✅ Good design | Add lifecycle policy to archive raw data to Glacier after 30 days |
| DynamoDB Standardized | `events` table + `event-sources` table | ⚠️ PK hotspot risk (same date/type events in same partition)<br>⚠️ `event-sources` table redundant<br>⚠️ No TTL for old data | Fix PK to `first_seen_date#event_type` to spread load<br>Drop `event-sources` table, add `raw_signal_ids` array to `events` table<br>Add TTL field to auto-delete events after 90 days |
| Supabase Business | `snapshots` + `digests` + `trend_history` tables | ⚠️ No GIN index on JSONB `data` field<br>⚠️ No uniqueness constraint, duplicate snapshots<br>⚠️ No composite index for date range queries | Add GIN index to `snapshots.data` for fast search<br>Add unique constraint on `source + created_at_hour` to avoid duplicates<br>Add composite index `(source, metric_name, recorded_at)` to `trend_history` |

### Pipeline Gaps
Current: `Crawl 4 sources → Local JSON → Digest generation → CLI output`
Missing:
- S3 write logic (risk of data loss)
- DynamoDB deduplication/normalization logic
- Scoring/push logic
- Retry/dead letter queue

Fix: Add simple orchestration layer:
`Scheduler → Parallel crawl → S3 write → DynamoDB normalize/dedupe → LLM scoring (≥70 push) → Supabase store → Telegram push`

---
## 2. Database & State Management Findings
### Key Risks
1. **Redundant storage**: S3 and Supabase both store raw snapshots, doubles cost
   > Fix: Drop `snapshots` table, store only structured data in Supabase, raw data only in S3
2. **No global deduplication**: Same event from multiple sources is processed multiple times
   > Fix: Generate global `event_id = md5(source + url + title)`, check DynamoDB existence before processing
3. **No incremental update for FundBat**: Full crawl of 791 companies every run wastes resources
   > Fix: Add hash comparison, only save changed companies
4. **Insufficient backup strategy**: Only DynamoDB has point-in-time recovery, no S3 versioning/Supabase backups
   > Fix: Enable S3 versioning, enable daily Supabase backups (retention 30 days)

### Scalability Estimate (10x load)
- S3: ~10MB/day, ~3.6GB/year → $0.02/month, no issues
- DynamoDB: ~1,000 events/day, 360k/year → ~$1/month, no issues
- Supabase: Fully covered by free tier, no issues

---
## 3. Next Steps Priority
### High (Must Do)
- Fix DynamoDB PK hotspot issue + add TTL
- Implement S3 write + DynamoDB normalization layer with global deduplication
- Add missing Supabase indexes
### Medium (Should Do)
- Drop redundant `snapshots` table
- Add pipeline dead letter queue + alerts
- Enable S3 versioning + Supabase backups
### Low (Can Do Later)
- FundBat incremental update logic
- Cold data auto-archiving

## Status: DONE
