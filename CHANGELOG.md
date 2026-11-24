# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-11-24

### Added

- Per-branch stock caps: a ceiling per item and branch in ASN Item Branch Cap, with Data Import and Version history.
- Saving an ASN warns on a stock cap breach. Submitting the ASN, bulk upload and Purchase Receipt submit are blocked. Suppliers see the message without the stock figures.
- Stock caps cover Job ASNs and Subcontracting Receipts, and compare lines in stock UOM.
- The supplier portal lists open Subcontracting Orders, so a supplier can raise a Job ASN against one.
- Scanning opens a Material or Job Gate Pass, then leads on to the Purchase Receipt or Subcontracting Receipt and the Purchase Invoice.
- Gate Pass Mode, a site switch read at scan time.
- A Subcontracting Receipt updates its Job ASN's received qty and status.
- Incomplete ASN drafts can be saved, and rate differences against the order are reported.
- Scan Code barcodes on the Purchase Receipt and Gate Pass print formats, drawn on demand by a scan image endpoint.
- Ctrl+Shift+S opens the scan dialog.

### Changed

- Documents store their Scan Code instead of attached QR and barcode images.
- Putaway and the Quality Inspection scan chain are retired. A Purchase Receipt carries one Scan Code.
- `Item.custom_max_stock` is retired in favour of per-branch caps.
- A vehicle number is required before an ASN can be saved.
- Portal bulk ASN creation runs in the background.
- Scan dispatch is POST-only and rate-limited, and every whitelisted API declares its HTTP methods.
- Scan Logs are cleared after 180 days.
- The ASN Discrepancy and stale QC notifications are dropped.

### Fixed

- Single-use scan codes are claimed atomically, and concurrent scans reopen one draft.
- A failed scan handler rolls back its partial writes.
- Scan dispatch and receipt creation check document permissions, and the Cypress seed endpoints are locked down.
- Server text in portal error lists and Scan Station alerts is escaped.
- Every ASN order line is checked against its order, supplier, item and UOM.
- An ASN closes when its linked receipt is submitted short. A second booking document is refused once the ASN is fully booked.
- A double submit no longer creates the same bulk ASNs twice.
- Gate Pass rows link to ASN lines, so a PO item shipped as several lines keeps each row's qty.
- A Subcontracting Receipt receives its Job ASN's invoice and transport references.
- `/asn/<name>` answers 404, not 500, when the caller may not view the ASN.
- The Open Full Trace View button shows on saved ASN forms.
- The remaining raw SQL uses the query builder, and hot-path filter fields are indexed.

## [1.0.0] - 2026-10-09

### Added

- Supplier portal: create one ASN, or upload many, against open Purchase Orders. A submitted ASN opens at `/asn/<name>`.
- Desk: upload ASNs from a spreadsheet, with validation before anything is created. Vehicle details are copied onto the Purchase Receipt.
- Scan actions: QR and 16-character plain scan codes dispatch role-gated actions and write a Scan Log. Scanning a used code reopens the document it created.
- Scan handlers for Purchase Receipt, Quality Inspection, stock transfer, purchase return, and subcontracting dispatch and receipt.

[Unreleased]: https://github.com/Guru107/asn_module/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Guru107/asn_module/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Guru107/asn_module/releases/tag/v1.0.0
