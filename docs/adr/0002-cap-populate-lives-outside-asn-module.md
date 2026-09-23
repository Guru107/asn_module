# Cap Populate lives outside asn_module

The same decision is recorded in the `cap_populate` repo as ADR 0001.

Cap Populate is a Trikaya customization, same home as Schedule Upload. Both are Custom DocTypes on the company site. The formula runs in a Server Script, not in an app and not in `asn_module`. `asn_module` enforces Stock Cap from stored `ASN Item Branch Cap.max_qty` and does not know schedules. One confirmed button runs the script, the desk shows a Frappe loader until it returns, and a throw rolls back every Maximum Stock write from that call. The script saves ASN Item Branch Cap through that DocType. There is no new write method on `asn_module`.

## Considered Options

**Cap Populate DocType inside `asn_module`.** Rejected. Schedule Upload, Schedule Demand, Cover Days, and Buffer Percent are one company's plant-month planning. Putting them in `asn_module` would make every install depend on that schedule.

**A new company app that owns Cap Populate in Python.** Rejected. Schedule Upload is already a Trikaya Custom DocType with no app. Cap Populate stays beside it as another Custom DocType plus a Server Script.

**Moving Schedule Upload into a new app and putting Cap Populate beside it.** Rejected. That would migrate a live Custom DocType for a feature that only needs to read it.

**A Maximum Stock writer port on `asn_module`.** Rejected. Production would be the only adapter. The DocType save already is the write.

## Consequences

`asn_module` stays installable with no Schedule Upload. Deleting the Cap Populate Custom DocType leaves existing Maximum Stock rows and Stock Cap enforcement in place; nothing will refresh those rows from a schedule.

The formula, the skip-zero rule, and the working-days refusal live in the Server Script on the site. Stock Cap evaluate and fetch stay readers of the stored value.

The Custom DocType, Server Script, and Client Script are not committed inside `asn_module`. A separate repo named `cap_populate` holds a script that creates them through the ERPNext API on the site it is pointed at. A later run upserts those three definitions and does not delete Cap Populate documents or Maximum Stock rows. The script refuses to start if Schedule Upload is missing, if ASN Item Branch Cap is missing, or if the Stock Manager role is missing. The Sales Schedule link on Cap Populate lists only Sales schedules for that Branch. A Purchase schedule is refused. Schedule Demand sums every line on that document, Inhouse and Outsource together. Cap Populate documents are named `CP-.####`. The Branch field is unique, so a second instruction for the same Branch is refused. A Branch rename updates that link and leaves the document name alone. The repo does not embed a site URL or credentials, and it does not import `asn_module`.
