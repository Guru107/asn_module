# This document details common coding conventions and best practices.

## Development Philosophy

- Test Driven Development is the holy grail of correctness and verification.
- Always start with tests before implementing any feature.
- Incase of user facing code, always write E2E Tests first.
- The test coverage should be above 95% at all times.
- Do not modify a feature or a test in order to suite an easy implementation or comfortable path that drifts from user requirement.
- Always ask in case of a doubt.
- Do not create superficial file paths that do not exist.
- Follow best coding practices of the language being used in the project.
- In case of database operations or query generation always look for the most optimum query plan. Use indexes where available or create new one if it is the most used read path.

---

## Testing Approach

### Unit Tests (Python)

- Extend `FrappeTestCase` from `frappe.tests.utils`.
- Helper `_ensure_loss_types()` creates Downtime Reason fixture data inside tests.
- Use `frappe.db.set_value()` for test cleanup — it bypasses validations.
- Avoid explicit `frappe.db.commit()` unless testing transaction isolation.
- Name tests `test_<what>_<expected_outcome>` (e.g., `test_overlap_validation_throws_for_same_time`).

### E2E Tests (Cypress)

- Location: `tests/e2e/specs/`
- Always add an E2E spec for every user-facing flow.
- Required scenarios per feature:
  - Happy path (success)
  - Validation path (user error → visible message)
  - Permission path (unauthorized user → blocked)

### Coverage

Run the full suite and check coverage before every PR:

```bash
bench --site development.localhost run-tests --app asn_module --with-coverage
```

Coverage must not drop below **95%**.

---

## JavaScript — Frappe Best Practices

### Every `frappe.call()` Must Have an `error:` Callback

Silent failures are unacceptable. Every API call must inform the user when something goes wrong:

```javascript
frappe.call({
	method: "...",
	args: { ... },
	callback(r) { /* success */ },
	error(err) {
		frappe.msgprint(__("Operation failed. Please retry or contact support."));
		console.error(err);
	},
});
```

### Debounce Repeated Triggers

When multiple field changes trigger the same server call, debounce to 300 ms to avoid
sending duplicate requests:

```javascript
let _timer = null;
function _my_handler(frm) {
	clearTimeout(_timer);
	_timer = setTimeout(() => _do_call(frm), 300);
}
```

### Last-Call-Wins for Rapid API Calls

When a user action can trigger multiple in-flight requests, use a request counter so stale
responses are discarded:

```javascript
let _reqId = 0;
function _fetch_metrics(frm) {
	const id = ++_reqId;
	frappe.call({
		...,
		callback(r) {
			if (id !== _reqId) return;   // stale — discard
			/* apply result */
		},
	});
}
```

### Animation Frame Cleanup

Always guard `requestAnimationFrame` loops with a `stopped` flag so orphaned frames cannot
re-queue themselves after a form unloads:

```javascript
const state = { stopped: false, animationFrame: null };

const animate = () => {
	if (state.stopped) return;   // checked first, every frame
	/* draw */
	state.animationFrame = requestAnimationFrame(animate);
};

// On cleanup:
state.stopped = true;
cancelAnimationFrame(state.animationFrame);
```

### i18n — All User-Visible Strings in `__()`

Every string a user can see must be wrapped in the translation function:

```javascript
// CORRECT
frappe.msgprint(__("Shift started successfully."));
ctx.fillText(__("No entries for this shift."), x, y);
`<th>${__("Workstation")}</th>`

// WRONG — hard-coded strings are not translatable
frappe.msgprint("Shift started successfully.");
```

Exceptions: CSS class names, HTML attribute names, API method paths, DocType names used as
identifiers (not displayed text), JS variable names.

### Monkey-Patching ERPNext Prototypes

When overriding a method on an ERPNext prototype (e.g., `erpnext.stock.StockEntry.prototype`),
always check that the original method exists and preserve a fallback:

```javascript
const _proto = erpnext.stock.StockEntry.prototype;
const _original = typeof _proto.some_method === "function" ? _proto.some_method : null;

_proto.some_method = function () {
	if (_should_override(this.frm.doc)) { /* custom logic */ return; }
	if (_original) return _original.call(this);
	console.warn("[production_entry_app] some_method original not found; ERPNext may have changed.");
};
```

Document the dependency with a comment referencing the ERPNext source file and version.

### HTML Construction

Prefer template literals over string concatenation. Always escape user-supplied values:

```javascript
const row = `
	<tr>
		<td>${frappe.utils.escape_html(entry.name)}</td>
		<td>${frappe.utils.escape_html(entry.workstation || "—")}</td>
	</tr>`;
```

---

## Technical Specification: DSA Engineering & Problem Solving

### 1. Algorithmic Mindset

- The "Identify First" Rule: Before writing a single line of code, explicitly understand the problem category (e.g., Divide & Conquer, Greedy, Backtracking with Pruning, or Monotonic Queue).
- Bottleneck Analysis: Identify the current complexity bottleneck. If the solution is $O(N^2)$, explain why $O(N \log N)$ or $O(N)$ is required based on typical competitive programming constraints ($N = 10^5$).
- Space-Time Tradeoffs: Always prefer a hash map ($O(N)$ space) to save time ($O(1)$ lookup) unless memory is the primary constraint.

### 2. Coding Standards

- Idiomatic Efficiency: Use language-specific optimizations (e.g., collections.deque for $O(1)$ pops in Python, or std::vector::reserve() in C++ to avoid reallocations).
- Modular Logic: Separate the "Core Algorithm" from "Helper Functions" (like a custom Comparator or Union-Find class) to maintain readability.
- In-Place Operations: When possible, perform transformations in-place to achieve $O(1)$ auxiliary space.

## MariaDB Best Practices

---

### Core Optimization Principles

1. I/O Minimization: The fastest query is the one that touches the fewest data pages.
2. Leftmost Index Rule: Composite indexes must be utilized from left to right to be effective.
3. Sargability: Always write predicates that allow the optimizer to use indexes (e.g., avoid functions on columns in WHERE clauses).
4. Buffer Pool Priority: Ensure the working set fits in memory to avoid costly disk reads.

### 1. Advanced Indexing Patterns

- Covering Indexes: Include all columns requested in the SELECT to avoid a "Bookmark Lookup" or "Row ID Scan".
  - Example: `INDEX(user_id, status, last_login) for SELECT last_login FROM users WHERE user_id = ? AND status = ?`.
- 
- Prefix Indexing: Use for long VARCHAR or TEXT columns to save space while maintaining selectivity.
  - Example: `CREATE INDEX idx_url ON links (url(20));`.
- Invisible/Ignored Indexes: Test the impact of removing an index without actually dropping it.
  - Syntax: `ALTER TABLE t1 ALTER INDEX idx_name INVISIBLE;`.

### 2. Query Execution Analysis

- EXPLAIN ANALYZE: Available in MariaDB 10.9+, this provides actual execution times and row counts vs. estimates.
- Query Profiling: Use
  ```sql
  SET profiling = 1;
  ```
  followed by
  ```sql
  SHOW PROFILE FOR QUERY N;
  ```
  to see detailed CPU and I/O breakdowns.
- Slow Query Log:
  - Configure to catch "time bombs"—fast queries that don't use indexes.
    ```sql
    SET GLOBAL slow_query_log = 'ON';
    SET GLOBAL long_query_time = 0.5; -- Catch anything > 500ms
    SET GLOBAL log_queries_not_using_indexes = ON;
    ```

### 3. Optimizer Control & Hints

- Condition Pushdown: MariaDB excels at pushing conditions into derived tables and even through window functions in newer versions.
- New-Style Hints: Use expanded hints introduced in MariaDB 10.x for more granular control over join orders and index selection.
- Example: `SELECT /*+ BKA(t1) NO_BKA(t2) */ ...` to control Batched Key Access.

### 4. System Tuning for Performance

- InnoDB Buffer Pool: Set innodb_buffer_pool_size to 70-80% of system RAM for dedicated DB servers.
- Thread Pool: Enable for high-concurrency OLTP workloads to reduce context-switching overhead.
- Config: thread_handling = pool-of-threads.
- I/O Capacity: Adjust innodb_io_capacity based on storage type (e.g., 200 for HDD, 2000+ for SSD).

---

## Example Optimization: From Full Scan to Index Scan

Sub-optimal Query:

```sql
-- Bad: Function on indexed column 'created_at' prevents index usage
SELECT id, amount FROM orders WHERE YEAR(created_at) = 2024;
```

Optimized Query:

```sql
-- Good: Sargable range allows MariaDB to use INDEX(created_at)
SELECT id, amount
FROM orders
WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01';
```

Expert Tip: Use pt-query-digest from the Percona Toolkit to aggregate slow query logs and identify the highest-impact bottlenecks.