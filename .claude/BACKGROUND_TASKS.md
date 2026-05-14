# SmartLedger — Background Tasks & Async Processing

## 1. Overview

SmartLedger uses **ARQ** (Async Redis Queue) for background job processing. ARQ is lightweight, fully async, and integrates naturally with FastAPI's async model. Redis serves as both the job queue and result store.

---

## 2. ARQ Worker Setup

### Worker Entry Point
```
app/tasks/worker.py
```

### Configuration
```python
from arq import cron
from arq.connections import RedisSettings
from app.core.config import settings

class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10                  # Max concurrent jobs
    job_timeout = 300              # 5 minutes max per job
    keep_result = 3600             # Keep results for 1 hour
    retry_jobs = True
    max_tries = 3                  # Retry failed jobs up to 3 times

    functions = [
        send_due_invoice_notifications,
        check_low_stock,
        refresh_materialized_views,
        generate_report_export,
        dispatch_email_notification,
    ]

    cron_jobs = [
        cron(check_low_stock,                   hour=7,  minute=0),
        cron(send_due_invoice_notifications,    hour=8,  minute=0),
        cron(refresh_materialized_views,        hour=2,  minute=0),
    ]

    on_startup = startup
    on_shutdown = shutdown
```

### Running the Worker
```bash
# Development
arq app.tasks.worker.WorkerSettings

# Production (via Dockerfile/supervisor)
arq app.tasks.worker.WorkerSettings --watch app/
```

---

## 3. Scheduled (Cron) Jobs

### 3.1 `check_low_stock` — Daily at 07:00

**Purpose:** Identify all inventory items where `current_stock < reorder_level` and insert notification records.

**Steps:**
1. Query all active items where `current_stock < reorder_level AND reorder_level > 0`
2. For each item: check if a `low_stock` notification was already sent today (avoid duplicates)
3. If not: insert `Notification(type='low_stock', item_id=..., message=...)`
4. Log count of alerts generated

**Error Handling:**
- Wrap in try/except; log failures without crashing the worker
- Retry up to 3 times with 60-second backoff on DB errors

**Expected Runtime:** < 30 seconds for up to 10,000 items

---

### 3.2 `send_due_invoice_notifications` — Daily at 08:00

**Purpose:** Detect overdue and soon-to-be-due sales invoices and create notification records.

**Steps:**
1. Query `sale_invoices` where:
   - `status IN ('confirmed', 'partially_paid')`
   - `due_date IS NOT NULL`
   - `due_date <= CURRENT_DATE + 3` (due within 3 days) OR `due_date < CURRENT_DATE` (overdue)
2. For each invoice:
   - If `due_date < today` → notification type = `overdue`
   - If `due_date <= today + 3` → notification type = `due`
   - Skip if notification of same type already exists for this invoice today
3. Insert notifications in bulk
4. Optionally enqueue `dispatch_email_notification` jobs for each notification

**Error Handling:**
- Process in batches of 100 to avoid memory issues on large datasets
- Continue processing remaining invoices even if one batch fails

---

### 3.3 `refresh_materialized_views` — Nightly at 02:00

**Purpose:** Refresh PostgreSQL materialized views used for reports.

**Views refreshed (in order):**
1. `mv_stock_valuation` — stock quantities × purchase prices
2. `mv_supplier_balances` — aggregated supplier balances
3. `mv_customer_balances` — aggregated customer balances
4. `mv_profit_loss` — monthly P&L summary

**SQL executed:**
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_stock_valuation;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_supplier_balances;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_customer_balances;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_profit_loss;
```

`CONCURRENTLY` allows reads to continue during refresh (no table lock).

**Error Handling:**
- If one view fails, log error and continue with remaining views
- Alert admin via log if any view fails 3 nights in a row

**Expected Runtime:** 30 seconds to 5 minutes depending on data volume

---

## 4. On-Demand Jobs (Enqueued by API)

### 4.1 `generate_report_export`

**Purpose:** Generate large report exports (CSV/Excel) without blocking the API response.

**Trigger:** `POST /reports/{report_name}/export`

**Flow:**
```
1. API validates request params
2. API enqueues job: arq.enqueue_job('generate_report_export', report_name, params, user_id)
3. API returns immediately: { "job_id": "abc123", "status": "queued" }
4. Worker picks up job, executes report query, generates file
5. Worker stores result file in configured storage (local FS or S3)
6. Worker updates job status to "completed" with download URL

Client polls: GET /reports/exports/{job_id}
→ { "status": "completed", "download_url": "/reports/exports/abc123/download" }
→ { "status": "processing" }
→ { "status": "failed", "error": "..." }
```

**Supported Export Formats:**
- `?format=csv` — streaming CSV
- `?format=xlsx` — Excel workbook via `openpyxl`

**File Cleanup:** Exported files older than 24 hours are deleted by a cleanup cron job.

---

### 4.2 `dispatch_email_notification`

**Purpose:** Send email notifications for due invoices (optional, requires SMTP config).

**Input:** `notification_id`, `customer_email`, `message`, `invoice_id`

**Steps:**
1. Fetch notification details
2. Render email template
3. Send via SMTP (or SendGrid API if configured)
4. Mark notification as `sent_via_email = true`

**Error Handling:**
- Retry up to 3 times on SMTP failure
- After 3 failures: mark as `email_failed`, log error, continue (don't crash)
- Never retry if customer email is invalid (bounce)

---

## 5. Job Enqueuing from FastAPI

Jobs are enqueued using the ARQ Redis pool, created on application startup:

```python
# app/core/arq_pool.py
from arq import create_pool
from arq.connections import RedisSettings

arq_pool = None

async def get_arq_pool():
    global arq_pool
    if arq_pool is None:
        arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    return arq_pool
```

```python
# In a service, when a sale is confirmed:
pool = await get_arq_pool()
await pool.enqueue_job(
    'dispatch_email_notification',
    notification_id=notif.id,
    customer_email=customer.email,
    message=f"Invoice {invoice.invoice_no} is due on {invoice.due_date}",
    invoice_id=invoice.id,
)
```

---

## 6. Job Monitoring

| Endpoint | Description |
|----------|-------------|
| `GET /admin/jobs` | List recent job statuses (admin only) |
| `GET /admin/jobs/{job_id}` | Get specific job status/result |
| `GET /reports/exports/{job_id}` | Check export job status |
| `GET /reports/exports/{job_id}/download` | Download generated export file |

---

## 7. Redis Usage Summary

| Purpose | Key Pattern | TTL |
|---------|-------------|-----|
| Job queue | `arq:job:{job_id}` | Until processed |
| Job results | `arq:result:{job_id}` | 1 hour |
| Token blacklist | `blacklist:jti:{jti}` | Token remaining lifetime |
| Rate limit counters | `ratelimit:{ip}:{endpoint}` | 1 minute |
| Login attempt tracker | `login_attempts:{ip}` | 15 minutes |

---

## 8. Fault Tolerance

### Job Failure Recovery
- All jobs decorated with `max_tries=3` (ARQ built-in)
- Exponential backoff between retries: 30s → 120s → 480s
- Failed jobs after max tries: logged to `audit_logs` with error detail

### Worker Crash Recovery
- ARQ marks in-progress jobs as failed on worker restart
- Jobs are re-queued automatically (ARQ handles this)
- Use `supervisor` or `systemd` in production to auto-restart the worker process

### Data Consistency
- Background tasks that modify the database (e.g., inserting notifications) use their own DB session
- They never share a session with the web request that enqueued them
- If a notification job fails, the notification is not marked as sent — it will be retried or re-created next day

---

## 9. Environment Variables for Tasks

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | Yes | Redis DSN for ARQ |
| `SMTP_HOST` | No | SMTP server for email |
| `SMTP_PORT` | No | SMTP port (default: 587) |
| `SMTP_USER` | No | SMTP username |
| `SMTP_PASSWORD` | No | SMTP password |
| `SMTP_FROM_EMAIL` | No | Sender email address |
| `EXPORT_STORAGE_PATH` | No | Local path for export files (default: `/tmp/exports`) |
| `LOW_STOCK_NOTIFY_DAYS` | No | Days before due to notify (default: 3) |
