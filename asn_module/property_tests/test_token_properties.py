import base64
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from asn_module.qr_engine import token as token_module
from asn_module.qr_engine.token import InvalidTokenError, create_token, verify_token
from asn_module.tests.compat import UnitTestCase

_ACTION = st.from_regex(r"[a-z][a-z_]{2,39}", fullmatch=True)
_SOURCE_DOCTYPE = st.from_regex(r"[A-Za-z][A-Za-z ]{2,39}", fullmatch=True)
_SOURCE_NAME = st.from_regex(r"[A-Z0-9][A-Z0-9\-]{0,39}", fullmatch=True)


class TestTokenProperties(UnitTestCase):
	def _create_token(self, action: str, source_doctype: str, source_name: str) -> str:
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			return create_token(
				action=action,
				source_doctype=source_doctype,
				source_name=source_name,
			)

	def _verify_token(self, token: str) -> dict:
		with patch.object(token_module, "_get_secret", return_value="test-secret"):
			return verify_token(token)

	@given(action=_ACTION, source_doctype=_SOURCE_DOCTYPE, source_name=_SOURCE_NAME)
	def test_create_verify_round_trip_preserves_token_fields(
		self,
		action,
		source_doctype,
		source_name,
	):
		token = self._create_token(action, source_doctype, source_name)
		payload = self._verify_token(token)

		self.assertEqual(payload["action"], action)
		self.assertEqual(payload["source_doctype"], source_doctype)
		self.assertEqual(payload["source_name"], source_name)

	@given(action=_ACTION, source_doctype=_SOURCE_DOCTYPE, source_name=_SOURCE_NAME)
	def test_tampered_token_is_rejected(self, action, source_doctype, source_name):
		token = self._create_token(action, source_doctype, source_name)
		decoded = base64.urlsafe_b64decode(token.encode()).decode()
		data, signature = decoded.rsplit(".", 1)
		tampered_data = data.replace(source_name, f"{source_name}X", 1)
		tampered = base64.urlsafe_b64encode(f"{tampered_data}.{signature}".encode()).decode()

		with self.assertRaises(InvalidTokenError):
			self._verify_token(tampered)
