# ASN Module

Advance Shipping Notices: a supplier declares what is being shipped against a Purchase Order before the goods arrive, and that declaration drives receipt, traceability, and stock guardrails.

## Language

### Shipment

**ASN**:
A supplier's declaration of goods dispatched against one or more Purchase Orders, submitted before the goods physically arrive.
_Avoid_: Advance Ship Notice, shipping notice, dispatch note, notice

**ASN Line**:
One item row on an ASN, always traceable to a specific Purchase Order Item.
_Avoid_: ASN row, line item, item

**Shipped Qty**:
The quantity declared on an ASN Line, expressed in the Purchase Order line's purchase UOM.
_Avoid_: ASN qty, declared qty

**Received Qty**:
The portion of a Shipped Qty that has physically arrived and been receipted, expressed in the same purchase UOM as the Shipped Qty.
_Avoid_: delivered qty, accepted qty

**In Transit Qty**:
Shipped Qty minus Received Qty on submitted ASNs that are neither fully Received nor Closed. Stock that is promised but not yet on hand.
_Avoid_: pending qty, open qty, outstanding qty

### Stock Cap

**Stock Cap**:
The rule that refuses an ASN submission when the stock it will land pushes an item above its permitted maximum for the destination branch.
_Avoid_: max stock check, stock limit, ceiling rule

**Branch**:
The organisational unit that owns a set of warehouses. Resolved from the Purchase Order header, never from the ASN.
_Avoid_: site, location, plant

**Cap Warehouses**:
The warehouses configured against a Branch whose stock counts toward that branch's Stock Cap. Always leaf warehouses, never groups, and each belongs to exactly one Branch. Warehouses outside this set are invisible to the rule.
_Avoid_: selected warehouses, configured warehouses

**Maximum Stock**:
The per-branch ceiling for an item, held in `ASN Item Branch Cap.max_qty`, keyed by (item, branch), and expressed in the item's stock UOM. A single branch may hold up to this quantity; the company-wide total across branches is deliberately uncapped. Zero or an absent row means the item is uncapped.
_Avoid_: max stock, stock limit, cap (unqualified), `Item.custom_max_stock` (retired)

**Projected Stock**:
On Hand plus In Transit Qty plus the quantity of the ASN under evaluation, summed over a branch's Cap Warehouses and expressed in stock UOM. The figure compared against Maximum Stock.
_Avoid_: future stock, expected stock, projected qty (which is an ERPNext Bin field with a different formula)

**On Hand**:
Sum of `Bin.actual_qty` across a branch's Cap Warehouses, in stock UOM.
_Avoid_: current stock, available stock, actual qty

**Breach**:
A single (branch, item) pair whose Projected Stock exceeds its Maximum Stock. Breaches warn on save and block on submit.
_Avoid_: violation, error, cap failure

**Consumed Headroom**:
Cap capacity already claimed by earlier ASNs within the same bulk upload, carried forward so one upload cannot drive an item past its Maximum Stock across several ASNs.
_Avoid_: running total, reserved capacity

**Allowed Qty**:
The largest additional quantity a line may declare without causing a Breach. The only cap-derived figure disclosed to suppliers; On Hand, In Transit Qty, and Maximum Stock are never shown outside the desk.
_Avoid_: headroom, remaining capacity, available qty
