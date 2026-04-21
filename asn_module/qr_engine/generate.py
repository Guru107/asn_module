import base64
import io
from urllib.parse import quote

import barcode
import frappe
import pyqrcode
from barcode.writer import ImageWriter

from asn_module.qr_engine.scan_codes import format_scan_code_for_display, get_or_create_scan_code

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


def build_scan_code_metadata(
	*, action_key: str, source_doctype: str, source_name: str, generation_mode: str
) -> dict:
	"""Create scan-code metadata for downstream display/dispatch payloads."""
	scan_code = get_or_create_scan_code(action_key, source_doctype, source_name)
	return {
		"action_key": action_key,
		"scan_code": scan_code,
		"human_readable": format_scan_code_for_display(scan_code),
		"generation_mode": (generation_mode or "").strip().lower(),
	}


def generate_qr(action: str, source_doctype: str, source_name: str) -> dict:
	code = get_or_create_scan_code(action, source_doctype, source_name)
	url = _build_dispatch_url(code)

	buffer = io.BytesIO()
	pyqrcode.create(url).png(buffer, scale=_QR_SCALE)

	return {
		"url": url,
		"scan_code": code,
		"human_readable": format_scan_code_for_display(code),
		"image_base64": base64.b64encode(buffer.getvalue()).decode(),
	}


def generate_barcode(action: str, source_doctype: str, source_name: str) -> dict:
	code = get_or_create_scan_code(action, source_doctype, source_name)

	buffer = io.BytesIO()
	code128 = barcode.get("code128", code, writer=ImageWriter())
	try:
		code128.write(buffer, options=_BARCODE_OPTIONS)
	except TypeError:
		code128.write(buffer)

	return {
		"scan_code": code,
		"human_readable": format_scan_code_for_display(code),
		"image_base64": base64.b64encode(buffer.getvalue()).decode(),
	}
