# ASN Module

Advance Shipping Notices: a supplier declares what is being shipped against a Purchase Order before the goods arrive, and that declaration drives receipt, traceability, and stock guardrails.

## Language

### Shipment

**ASN**:
A supplier's declaration of goods dispatched against one Purchase Order or one Subcontracting Order, submitted before the goods physically arrive. It carries the vehicle that will bring the goods.
_Avoid_: Advance Ship Notice, shipping notice, dispatch note, notice

**Material ASN**:
An ASN whose lines reference one Purchase Order.
_Avoid_: Purchase ASN

**Job ASN**:
An ASN whose lines reference one Subcontracting Order.
_Avoid_: Subcontract ASN, SCO ASN

**ASN Line**:
One item row on an ASN, traceable to one Purchase Order Item or one Subcontracting Order Item.
_Avoid_: ASN row, line item, item

**Gate Pass Mode**:
A site-wide switch, off unless the site turns it on. It is read when the ASN barcode or QR is scanned. When it is on, that scan creates a draft Gate Pass. When it is off, a Material ASN scan creates a draft Purchase Receipt and a Job ASN scan creates a draft Subcontracting Receipt.
_Avoid_: a per-ASN flag, a Gate Pass Type

**Gate Pass**:
The security record of the vehicle at the gate. In Gate Pass Mode the supplier-invoice barcode opens it as a draft, with the Purchase Order or Subcontracting Order as its reference. Its own barcode, attached on submit, opens the receipt: a Purchase Receipt for Material, a Subcontracting Receipt for Job.
_Avoid_: treating the scan as the receipt

**Scan Chain**:
The rule that every document in the flow carries the code that creates its successor: the ASN opens the Gate Pass, the Gate Pass opens its receipt, a Subcontracting Receipt opens its Purchase Receipt, and every Purchase Receipt opens a Purchase Invoice. A Purchase Invoice is raised from a Purchase Receipt only, never from a Subcontracting Receipt.
_Avoid_: manual Create buttons between scanned steps, billing a Subcontracting Receipt directly

**Shipped Qty**:
The quantity declared on an ASN Line, expressed in the Purchase Order line's purchase UOM.
_Avoid_: ASN qty, declared qty

**Received Qty**:
The portion of a Shipped Qty that has physically arrived and been receipted, expressed in the same purchase UOM as the Shipped Qty.
_Avoid_: delivered qty, accepted qty

**In Transit Qty**:
Shipped Qty minus Received Qty on submitted ASNs that are neither fully Received nor Closed. Stock that is promised but not yet on hand.
_Avoid_: pending qty, open qty, outstanding qty

**Closed**:
An ASN that is finished and will take no further receipt, whether or not Received Qty covers Shipped Qty.
_Avoid_: cancelled, fully received

**Remaining Qty**:
The further Shipped Qty that may be declared against a Purchase Order Item. It matches what a Purchase Receipt could still post on the line within the over-receipt allowance, after Shipped Qty declared but not yet received on ASNs that are not Closed or Cancelled. A supplier and a desk user get the same figure.
_Avoid_: open qty, pending qty, allowed qty, headroom

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
The per-branch ceiling for an item, held in `ASN Item Branch Cap.max_qty`, keyed by (item, branch), and expressed in the item's stock UOM. Stock Cap always compares Projected Stock to this stored value. Cap Populate may overwrite `max_qty` from a Sales Schedule; rows it does not write stay manually maintained. Zero or an absent row means the item is uncapped. The company-wide total across branches is deliberately uncapped.
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

### Cap Populate

**Cap Populate**:
The instruction, owned outside this module, that may overwrite a Branch's Maximum Stock from a Sales Schedule. Stock Cap never reads that instruction. The terms it uses are defined in the `cap_populate` glossary.
_Avoid_: sync caps, generate limits, import caps

**Sales Schedule**:
The plant-month demand document Cap Populate reads when it writes Maximum Stock. This module does not read it.
_Avoid_: schedule (unqualified), forecast, plan, Purchase schedule, Selling schedule
