import base64
import io

import barcode
import frappe
import pyqrcode
from barcode.writer import ImageWriter

from asn_module.qr_engine.token import create_token


def _build_dispatch_url(token: str) -> str:
	site_url = frappe.utils.get_url().rstrip("/")
	return f"{site_url}/api/method/asn_module.qr_engine.dispatch.dispatch?token={token}"


def generate_qr(action: str, source_doctype: str, source_name: str) -> dict:
	token = create_token(action, source_doctype, source_name)
	url = _build_dispatch_url(token)

	buffer = io.BytesIO()
	pyqrcode.create(url).png(buffer, scale=5)

	return {
		"url": url,
		"token": token,
		"image_base64": base64.b64encode(buffer.getvalue()).decode(),
	}


def generate_barcode(action: str, source_doctype: str, source_name: str) -> dict:
	token = create_token(action, source_doctype, source_name)

	buffer = io.BytesIO()
	barcode.get("code128", token, writer=ImageWriter()).write(buffer)

	return {
		"token": token,
		"image_base64": base64.b64encode(buffer.getvalue()).decode(),
	}
