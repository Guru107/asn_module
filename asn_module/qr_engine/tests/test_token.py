import base64
import json
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from asn_module.qr_engine import token as token_module
from asn_module.qr_engine.token import InvalidTokenError, create_token, verify_token
from asn_module.tests.financial_year_dates import get_fiscal_year_test_dates


def _test_dates():
	cache_key = "_token_test_dates_cache"
	cached = getattr(frappe.local, cache_key, None)
	if cached is None:
		cached = get_fiscal_year_test_dates()
		setattr(frappe.local, cache_key, cached)
	return cached


class TestToken(UnitTestCase):
	def _create_token(self):
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			return create_token(
				action="create_purchase_receipt",
				source_doctype="ASN",
				source_name="ASN-00001",
			)

	def _verify_token(self, token):
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			return verify_token(token)

	def _make_signed_token(self, payload):
		data = json.dumps(payload, separators=(",", ":"))
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			signature = token_module._sign(data)
		return base64.urlsafe_b64encode(f"{data}.{signature}".encode()).decode()

	def test_create_token_returns_non_empty_string(self):
		token = self._create_token()
		self.assertIsInstance(token, str)
		self.assertTrue(token)

	def test_verify_token_returns_payload_fields(self):
		token = self._create_token()
		payload = self._verify_token(token)

		self.assertEqual(payload["action"], "create_purchase_receipt")
		self.assertEqual(payload["source_doctype"], "ASN")
		self.assertEqual(payload["source_name"], "ASN-00001")
		self.assertIn("created_at", payload)
		self.assertIn("created_by", payload)

	def test_tampered_token_raises_invalid_token_error(self):
		token = self._create_token()
		decoded = base64.urlsafe_b64decode(token.encode()).decode()
		data, signature = decoded.rsplit(".", 1)
		tampered_payload = data.replace("ASN-00001", "ASN-00002")
		tampered = base64.urlsafe_b64encode(f"{tampered_payload}.{signature}".encode()).decode()

		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			with self.assertRaises(InvalidTokenError):
				verify_token(tampered)

	def test_garbage_token_raises_invalid_token_error(self):
		with self.assertRaises(InvalidTokenError):
			verify_token("not-a-valid-token")

	def test_token_includes_created_by_as_current_user(self):
		token = self._create_token()
		payload = self._verify_token(token)

		self.assertEqual(payload["created_by"], frappe.session.user)

	def test_verify_token_rejects_non_dict_payload(self):
		token = self._make_signed_token(["action", "source_doctype"])

		with self.assertRaises(InvalidTokenError):
			verify_token(token)

	def test_verify_token_rejects_payload_missing_required_keys(self):
		token = self._make_signed_token(
			{
				"action": "create_purchase_receipt",
				"source_doctype": "ASN",
				"source_name": "ASN-00001",
				"created_at": _test_dates()["token_created_at"],
			}
		)

		with self.assertRaises(InvalidTokenError):
			verify_token(token)

	def test_verify_token_rejects_payload_with_blank_required_values(self):
		token = self._make_signed_token(
			{
				"action": " ",
				"source_doctype": "ASN",
				"source_name": "ASN-00001",
				"created_at": _test_dates()["token_created_at"],
				"created_by": "Administrator",
			}
		)

		with self.assertRaises(InvalidTokenError):
			verify_token(token)

	def test_create_token_raises_when_site_secret_missing(self):
		with patch.dict(frappe.local.conf, {}, clear=True):
			with patch.object(token_module, "get_encryption_key", return_value=""):
				with self.assertRaises(InvalidTokenError) as exc:
					create_token(
						action="create_purchase_receipt",
						source_doctype="ASN",
						source_name="ASN-00001",
					)

		self.assertEqual(str(exc.exception), "Site secret is not configured")

	def test_create_token_uses_encryption_key_when_secret_key_missing(self):
		with patch.dict(frappe.local.conf, {}, clear=True):
			with patch.object(token_module, "get_encryption_key", return_value="fallback-key"):
				token = create_token(
					action="create_purchase_receipt",
					source_doctype="ASN",
					source_name="ASN-00001",
				)

		self.assertIsInstance(token, str)
		self.assertTrue(token)
