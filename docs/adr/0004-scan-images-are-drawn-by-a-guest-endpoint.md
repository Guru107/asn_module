# Scan images are drawn by a guest endpoint

The barcode and QR are a pure function of a Scan Code, yet every submit used to save them as File attachments, and a supplier who wanted the ASN barcode on their own invoice template could only get it from the attachment. A document now stores only its Scan Code, and one whitelisted, guest-accessible method in the QR engine draws the image on demand from a code and a kind (barcode or QR). A print format or a supplier's template points an image tag at it. The method checks only that the code is canonical, with no database lookup, so it stays cheap and needs no registry row. It returns a PNG with an immutable one-year public cache header, is rate limited at 120 requests a minute per IP, and answers a malformed code or unknown kind with a 400. The QR encodes the site's dispatch URL for the code; dispatch itself is unchanged and still validates the registry row.

The endpoint is public by design. Its output reveals nothing the code does not already carry, and a code is only useful to someone who can reach dispatch, which requires a login.

## Considered Options

**A Jinja-only helper.** Rejected. It would serve our own print formats but give a supplier's template, which is not rendered by this site, no way to fetch an image.

**An external QR service.** Rejected. Scan Codes would leave the site in every request URL, and printing would depend on a third party being up.

**Keep the attachments.** Rejected. Each submit writes extra files per document for images that can be recomputed, and the file list fills with them.

## Consequences

The attachment helpers, the backfill API and the registry-resolving generators are deleted, so nothing saves a scan image any more. Documents and files created before the change are not migrated. Putaway and the Quality Inspection actions were retired alongside (#97, #98), so a Purchase Receipt carries one Scan Code only.

Anyone can draw an image for any string that looks like a Scan Code. That reveals nothing: the endpoint never checks whether the code exists.

The QR payload comes from `frappe.utils.get_url()`, which honours the request Host header when `host_name` is not set in site config. Because the response is cached publicly for a year, a site must set `host_name` so a request with a foreign Host header cannot get a QR for the wrong domain cached.
