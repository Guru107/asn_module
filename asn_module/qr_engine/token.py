import base64
import hashlib
import hmac
import json
from binascii import Error as BinasciiError

import frappe
from frappe.utils import now_datetime


class InvalidTokenError(Exception):
	pass


_REQUIRED_PAYLOAD_KEYS = (
	"action",
	"source_doctype",
	"source_name",
	"created_at",
	"created_by",
)


def _get_secret() -> str:
	secret = frappe.local.conf.get("secret_key")
	if not secret:
		raise InvalidTokenError("Site secret is not configured")

	return secret


def _sign(data: str) -> str:
	return hmac.new(_get_secret().encode(), data.encode(), digestmod=hashlib.sha512).hexdigest()


def create_token(action: str, source_doctype: str, source_name: str) -> str:
	payload = {
		"action": action,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"created_at": str(now_datetime()),
		"created_by": frappe.session.user,
	}
	data = json.dumps(payload, separators=(",", ":"))
	token = f"{data}.{_sign(data)}".encode()
	return base64.urlsafe_b64encode(token).decode()


def _validate_payload(payload: object) -> dict:
	if not isinstance(payload, dict):
		raise InvalidTokenError("Invalid token payload")

	missing_keys = [key for key in _REQUIRED_PAYLOAD_KEYS if key not in payload]
	if missing_keys:
		raise InvalidTokenError(f"Invalid token payload: missing {', '.join(missing_keys)}")

	invalid_keys = []
	for key in _REQUIRED_PAYLOAD_KEYS:
		value = payload[key]
		if not isinstance(value, str) or not value.strip():
			invalid_keys.append(key)

	if invalid_keys:
		raise InvalidTokenError(f"Invalid token payload: invalid {', '.join(invalid_keys)}")

	return payload


def verify_token(token: str) -> dict:
	try:
		decoded = base64.urlsafe_b64decode(token.encode()).decode()
		data, signature = decoded.rsplit(".", 1)
		if not hmac.compare_digest(signature, _sign(data)):
			raise InvalidTokenError("Token signature verification failed")

		return _validate_payload(json.loads(data))
	except InvalidTokenError:
		raise
	except (BinasciiError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
		raise InvalidTokenError("Invalid token format") from exc
