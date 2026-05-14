# SmartLedger Architecture — Feedback & Required Improvements

**Overall:** Plan approved. Solid work — the ledger-first design, atomic transaction boundaries, and strict layering are exactly right. Please address the following before we start implementation.

---

## 🛑 Must-fix (Clarity Issues)

### 1. Resolve the real-time inventory vs. nightly refresh contradiction
Section 1 advertises "real-time inventory tracking," but materialized views refresh nightly at 02:00. Separate the two concerns explicitly in the document:
- **Operational stock queries** (current on-hand quantity) → served real-time from the underlying tables.
- **Reporting queries** (stock valuation, P&L, aging) → served from materialized views, up to 24 hours stale.

> [!IMPORTANT]
> Make this distinction clear so there's no ambiguity about which reads go where.

### 2. Make the current-stock read strategy explicit
The doc states "current stock is derived, never set directly," but doesn't specify how it's read efficiently. Running `SUM(stock_movements)` on every read will not scale. Pick one approach and document it:
- A cached `current_stock` column on the item table, updated in the same transaction as the movement insert.
- A per-item running-total materialized view or summary table.

Either is fine, but the choice needs to be explicit.

### 3. Pick one RBAC model — static or dynamic
The document currently describes both: three hardcoded roles (admin, manager, staff) and a `roles_permissions` table that implies dynamic role management. Commit to one:
- **Static enum** → remove the `roles_permissions` table.
- **Dynamic roles** → keep the table and drop the hardcoded role references.

Don't straddle both designs.

---

## ➕ Add These Missing Sections

### 4. Failure modes
Add a short section covering operational failure scenarios:
- **Redis unavailable** → what happens to JWT blacklist checks and rate limiting? Fail-open or fail-closed? Document the decision.
- **PostgreSQL unavailable** → expected API behavior and client-facing error contract.
- **ARQ worker crashes mid-job** → retry logic is already described; add dead-letter queue handling and how failed jobs surface to operators.
- **Failed background jobs** → how does the operator find out? Logging alone isn't enough; specify the alerting path.

### 5. Operations & deployment
Add a brief section covering:
- **Alembic migration strategy** in production (zero-downtime approach, rollback plan).
- **Database backup strategy** — frequency, retention, restore testing.
- **Monitoring and alerting** — Prometheus metrics are mentioned, but where do alerts go, and what are the key SLOs?

### 6. Justify the connection pool sizing
"Pool size 20" is the SQLAlchemy default, not a considered decision. With multiple uvicorn workers, you'll hit PostgreSQL's default `max_connections` (100) quickly. Either:
- Add **PgBouncer** (or equivalent pooler) to the stack, or
- Explicitly note that the default is provisional and will be tuned based on load testing.

---

## ✅ Conclusion
Once these are addressed, the plan is final. The core design decisions — immutable ledgers, atomic cross-module transactions, stateless API — are correct and should not change.
