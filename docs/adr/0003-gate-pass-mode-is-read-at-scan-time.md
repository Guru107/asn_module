# Gate Pass Mode is read at scan time

Some sites record the vehicle at the gate before a receipt; others create the receipt straight from the ASN. The barcode and QR are printed when the ASN is submitted and keep a single action, so the same printed code has to follow whichever way the site works. Gate Pass Mode is a site-wide switch, off unless the site turns it on, and it is read when that code is scanned. When it is on, the scan saves a draft Gate Pass (Material against the Purchase Order, Job against the Subcontracting Order) and the existing Create action makes the receipt afterwards. When it is off, a Material ASN creates a draft Purchase Receipt and a Job ASN creates a draft Subcontracting Receipt. Codes that already live on a Subcontracting Order are outside the switch.

## Considered Options

**Always create a Gate Pass.** Rejected. A site with no gate must keep the receipt path it has now.

**Choose the action when the code is printed.** Rejected. Turning the switch would leave invoices in transit pointing at the old path until they were reprinted.

**A second scan action used only in Gate Pass Mode.** Rejected. Two codes for one notice would make the switch a reprint event, which is the same problem.

## Consequences

The ASN action stays usable after a successful scan, so a later scan reopens the Gate Pass or the draft receipt already created for that notice. An ASN cannot be saved without a vehicle number, because a Gate Pass requires one. A Job ASN is raised from the supplier portal against one Subcontracting Order. The Purchase Receipt created from the Gate Pass still carries the ASN, so the Purchase Invoice scan is unchanged.
