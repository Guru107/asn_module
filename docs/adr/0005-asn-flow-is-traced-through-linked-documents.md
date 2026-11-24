# The ASN's flow is traced through its linked documents

Every document that follows an ASN links back to it with an `asn` field: Gate Pass, Purchase Receipt, Subcontracting Receipt and Purchase Invoice. The ASN form's Connections tab lists them, and each document's own timeline and Version history record who changed it and when. The ASN Transition Log, its ASN Item Transition Trace report, and the form's Traceability section are removed, and a patch drops the table. Gate Pass is listed in Connections only on sites that have the Gate Pass DocType.

## Considered Options

**Keep the log and add the missing Gate Pass states.** Rejected. The log copied facts the linked documents already hold, and it drifted from them. It recorded no Gate Pass at all until a separate fix, and no submitted Purchase Invoice. Each new step needed new logging code, and its Dynamic Link rows blocked deleting draft and cancelled documents unless every doctype had a cleanup hook. It also needed indexes that nothing else uses.

**Keep the log but stop showing it.** Rejected. An unused table still costs a write per ASN line at every step.

## Consequences

There is no per-line timeline across documents. Questions about a single line are answered from the receipts' item rows and the ASN Item's Received Qty. Existing trace rows are not kept.
