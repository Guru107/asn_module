import base64
import io
from urllib.parse import quote

import barcode
import frappe
import pyqrcode
from barcode.writer import ImageWriter
from frappe import _
from frappe.rate_limiter import rate_limit
from werkzeug.wrappers import Response

from asn_module.qr_engine.scan_codes import (
	format_scan_code_for_display,
	normalize_scan_code,
	resolve_scan_code_for_attachment,
)

# Printability: compact QR modules, barcode tuned for narrow invoice columns.
# ImageWriter paints text with anchor="md" (vertical center on ypos), so roughly half the
# glyph sits above ypos — keep text_distance large enough that the label clears the bars.
_QR_SCALE = 4
_BARCODE_OPTIONS = {
	"module_width": 0.22,
	"module_height": 12.0,
	"quiet_zone": 6.5,
	"font_size": 11,
	"text_distance": 6.5,
	"margin_bottom": 3.0,
}


def _build_dispatch_url(code: str) -> str:
	site_url = frappe.utils.get_url().rstrip("/")
	safe_code = quote(code, safe="")
	return f"{site_url}/api/method/asn_module.qr_engine.dispatch.dispatch?code={safe_code}"


def render_qr_png(code: str) -> bytes:
	"""PNG of the QR that encodes the site dispatch URL for ``code``. No registry access."""
	buffer = io.BytesIO()
	pyqrcode.create(_build_dispatch_url(code)).png(buffer, scale=_QR_SCALE)
	return buffer.getvalue()


def render_barcode_png(code: str) -> bytes:
	"""PNG of a Code 128 barcode with ``code`` as its human-readable label. No registry access."""
	buffer = io.BytesIO()
	code128 = barcode.get("code128", code, writer=ImageWriter())
	try:
		code128.write(buffer, options=_BARCODE_OPTIONS)
	except TypeError:
		code128.write(buffer)
	return buffer.getvalue()


class InvalidScanImageRequest(frappe.ValidationError):
	http_status_code = 400


_IMAGE_RENDERERS = {"barcode": render_barcode_png, "qr": render_qr_png}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=120, seconds=60)
def scan_image(code: str | None = None, kind: str | None = None) -> Response:
	"""Draw the barcode or QR PNG for a canonical Scan Code; touches no database row."""
	renderer = _IMAGE_RENDERERS.get(kind or "")
	if renderer is None:
		frappe.throw(_("Unknown image kind."), exc=InvalidScanImageRequest)
	canonical = normalize_scan_code(code)
	if not canonical:
		frappe.throw(_("Malformed scan code."), exc=InvalidScanImageRequest)

	return Response(
		renderer(canonical),
		mimetype="image/png",
		headers={"Cache-Control": "public, max-age=31536000, immutable"},
	)


def generate_qr(action: str, source_doctype: str, source_name: str) -> dict:
	code = resolve_scan_code_for_attachment(action, source_doctype, source_name)

	return {
		"url": _build_dispatch_url(code),
		"scan_code": code,
		"human_readable": format_scan_code_for_display(code),
		"image_base64": base64.b64encode(render_qr_png(code)).decode(),
	}


def generate_barcode(action: str, source_doctype: str, source_name: str) -> dict:
	code = resolve_scan_code_for_attachment(action, source_doctype, source_name)

	return {
		"scan_code": code,
		"human_readable": format_scan_code_for_display(code),
		"image_base64": base64.b64encode(render_barcode_png(code)).decode(),
	}
