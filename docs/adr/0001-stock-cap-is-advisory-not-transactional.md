# Stock Cap is advisory, not transactional

The Stock Cap refuses ASN and Purchase Receipt submissions that would push an item above its Maximum Stock for a branch, but it reads stock levels without locking them. Two submissions for the same item in overlapping requests can both observe the same pre-commit figures, both pass, and together exceed the cap. We accepted this rather than serialising the check.

## Considered Options

**`SELECT ... FOR UPDATE` on Bin rows.** Rejected. Those are the same rows ERPNext locks when posting stock ledger entries, so the cap check would contend with stock posting on the submit path. That is a live deadlock and timeout risk under load, traded for a window measured in milliseconds where the overshoot is bounded by a single shipment.

**Advisory lock keyed on `(branch, item_code)`.** Rejected for this iteration. It scopes contention to this feature instead of the stock ledger, but it only protects paths that take the lock, so it buys a partial guarantee at the cost of a lock acquisition per item per submit. Worth revisiting if real overshoot is ever observed.

## Consequences

No code may treat "stock is at or below Maximum Stock" as an invariant. Reorder logic, storage capacity planning, and allocation must tolerate an item sitting above its cap.

This is invisible from the outside. The feature presents as a hard limit, and a reader inspecting only the enforcement code would reasonably conclude the invariant holds. That is the whole reason this decision is recorded.

Stock movements outside the ASN and Purchase Receipt paths - Stock Entry, Stock Reconciliation, transfers between Cap Warehouses, and a Purchase Invoice with update_stock (receipts are expected to go through the Purchase Receipt, so the cap does not check them) - are unguarded entirely and can carry an item above Maximum Stock regardless of concurrency.
