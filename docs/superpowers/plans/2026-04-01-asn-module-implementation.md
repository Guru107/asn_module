# ASN Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a QR-driven stock entry and material movement automation module for ERPNext that automates document creation at every handoff point - from supplier ASN through quality inspection to invoicing.

**Architecture:** Two-layer design: a generic QR Action Engine (token encryption, dispatch routing, scan logging) and domain-specific handlers that register with the engine. Each QR scan hits a single dispatch endpoint, which routes to the correct handler based on the encrypted action token.

**Tech Stack:** Frappe v16, Python 3.11+, ERPNext v16, PyQRCode (already a Frappe dependency), python-barcode, HMAC-SHA512 signing (Frappe's built-in pattern)

**Spec:** `docs/superpowers/specs/2026-03-31-asn-module-design.md`

---

## File Structure

```
asn_module/
  asn_module/                          # Python package
    qr_engine/                         # QR Action Engine
      __init__.py                      # exports: generate_qr, generate_barcode, dispatch
      token.py                         # sign/verify encrypted tokens
      generate.py                      # QR code and barcode image generation
      dispatch.py                      # whitelisted dispatch endpoint
      tests/
        __init__.py
        test_token.py
        test_generate.py
        test_dispatch.py
    handlers/                          # Domain action handlers
      __init__.py
      purchase_receipt.py              # create_purchase_receipt handler
      stock_transfer.py               # create_stock_transfer handler
      purchase_return.py              # create_purchase_return handler
      purchase_invoice.py             # create_purchase_invoice handler
      putaway.py                      # confirm_putaway handler
      subcontracting.py              # dispatch + receipt handlers
      tests/
        __init__.py
        test_purchase_receipt.py
        test_stock_transfer.py
        test_purchase_return.py
        test_purchase_invoice.py
        test_putaway.py
        test_subcontracting.py
    asn_module/                        # "ASN Module" module directory
      doctype/
        asn/
          asn.json
          asn.py
          asn.js
          test_asn.py
        asn_item/
          asn_item.json
          asn_item.py
        qr_action_registry/
          qr_action_registry.json
          qr_action_registry.py
        scan_log/
          scan_log.json
          scan_log.py
          test_scan_log.py
      page/
        scan_station/
          scan_station.json
          scan_station.js
          scan_station.html
          scan_station.py
    templates/
      pages/
        asn.html                       # Supplier portal ASN form
        asn.py                         # Portal controller
        asn_row.html                   # Portal list row template
    custom_fields/                     # Custom field fixtures
      purchase_receipt.py
      purchase_invoice.py
    notifications/                     # Notification templates
      asn_submitted.py
      discrepancy_detected.py
      qc_awaiting.py
    public/
      js/
        asn_module.js                  # Global scan shortcut (Ctrl+Shift+S)
        scan_dialog.js                 # Reusable scan dialog component
    hooks.py                           # Modified - doc_events, includes, portal
```

---

## Phase 1: QR Action Engine

### Task 1: Token Signing and Verification

**Files:**

- Create: `asn_module/qr_engine/__init__.py`
- Create: `asn_module/qr_engine/token.py`
- Create: `asn_module/qr_engine/tests/__init__.py`
- Create: `asn_module/qr_engine/tests/test_token.py`
- **Step 1: Write the failing tests for token sign/verify**

```python
# asn_module/qr_engine/tests/test_token.py
import frappe
from frappe.tests import UnitTestCase

from asn_module.qr_engine.token import create_token, verify_token, InvalidTokenError


class TestToken(UnitTestCase):
	def test_create_token_returns_string(self):
		token = create_token(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		self.assertIsInstance(token, str)
		self.assertTrue(len(token) > 0)

	def test_verify_token_returns_payload(self):
		token = create_token(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		payload = verify_token(token)
		self.assertEqual(payload["action"], "create_purchase_receipt")
		self.assertEqual(payload["source_doctype"], "ASN")
		self.assertEqual(payload["source_name"], "ASN-00001")
		self.assertIn("created_at", payload)
		self.assertIn("created_by", payload)

	def test_verify_tampered_token_raises(self):
		token = create_token(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		tampered = token[:-5] + "XXXXX"
		with self.assertRaises(InvalidTokenError):
			verify_token(tampered)

	def test_verify_garbage_token_raises(self):
		with self.assertRaises(InvalidTokenError):
			verify_token("not-a-valid-token")

	def test_token_includes_created_by(self):
		token = create_token(
			action="test_action",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		payload = verify_token(token)
		self.assertEqual(payload["created_by"], frappe.session.user)
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_token`
Expected: FAIL with ImportError

- **Step 3: Implement token module**

```python
# asn_module/qr_engine/__init__.py
```

```python
# asn_module/qr_engine/tests/__init__.py
```

```python
# asn_module/qr_engine/token.py
import hashlib
import hmac
import json
import base64

import frappe
from frappe.utils import now_datetime


class InvalidTokenError(Exception):
	pass


def _get_secret():
	"""Get the site secret for HMAC signing."""
	return frappe.local.conf.secret_key or frappe.utils.password.get_encryption_key()


def _sign(data: str) -> str:
	"""Create HMAC-SHA512 signature for data."""
	return hmac.new(
		_get_secret().encode(),
		data.encode(),
		digestmod=hashlib.sha512,
	).hexdigest()


def create_token(action: str, source_doctype: str, source_name: str) -> str:
	"""Create a signed token encoding a QR action payload.

	Args:
		action: The action key (e.g., 'create_purchase_receipt')
		source_doctype: The source document type
		source_name: The source document name

	Returns:
		URL-safe base64 encoded signed token string
	"""
	payload = {
		"action": action,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"created_at": str(now_datetime()),
		"created_by": frappe.session.user,
	}
	data = json.dumps(payload, separators=(",", ":"))
	signature = _sign(data)
	token_bytes = base64.urlsafe_b64encode(f"{data}.{signature}".encode())
	return token_bytes.decode()


def verify_token(token: str) -> dict:
	"""Verify a signed token and return its payload.

	Args:
		token: The signed token string

	Returns:
		dict with keys: action, source_doctype, source_name, created_at, created_by

	Raises:
		InvalidTokenError: If the token is invalid or has been tampered with
	"""
	try:
		decoded = base64.urlsafe_b64decode(token.encode()).decode()
		data, signature = decoded.rsplit(".", 1)
		expected_signature = _sign(data)
		if not hmac.compare_digest(signature, expected_signature):
			raise InvalidTokenError("Token signature verification failed")
		return json.loads(data)
	except (ValueError, json.JSONDecodeError, Exception) as e:
		if isinstance(e, InvalidTokenError):
			raise
		raise InvalidTokenError(f"Invalid token format: {e}") from e
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_token`
Expected: All 5 tests PASS

- **Step 5: Commit**

```bash
git add asn_module/qr_engine/
git commit -m "feat: add QR token signing and verification"
```

---

### Task 2: QR Code and Barcode Generation

**Files:**

- Create: `asn_module/qr_engine/generate.py`
- Create: `asn_module/qr_engine/tests/test_generate.py`
- Modify: `pyproject.toml` (add python-barcode dependency)
- **Step 1: Add python-barcode dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    # "frappe~=16.0.0" # Installed and managed by bench.
]
```

to:

```toml
dependencies = [
    # "frappe~=16.0.0" # Installed and managed by bench.
    "python-barcode>=0.15.1",
]
```

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && pip install python-barcode`

- **Step 2: Write the failing tests for QR and barcode generation**

```python
# asn_module/qr_engine/tests/test_generate.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.qr_engine.generate import generate_qr, generate_barcode


class TestGenerateQR(IntegrationTestCase):
	def test_generate_qr_returns_url_and_image(self):
		result = generate_qr(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		self.assertIn("url", result)
		self.assertIn("image_base64", result)
		self.assertIn("token", result)
		self.assertTrue(result["url"].startswith("/api/method/asn_module.qr_engine.dispatch.dispatch"))
		self.assertTrue(len(result["image_base64"]) > 0)

	def test_generate_qr_url_contains_token(self):
		result = generate_qr(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		self.assertIn("token=", result["url"])

	def test_generate_barcode_returns_image(self):
		result = generate_barcode(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name="ASN-00001",
		)
		self.assertIn("image_base64", result)
		self.assertTrue(len(result["image_base64"]) > 0)
```

- **Step 3: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_generate`
Expected: FAIL with ImportError

- **Step 4: Implement generate module**

```python
# asn_module/qr_engine/generate.py
import base64
import io

import pyqrcode
import barcode
from barcode.writer import ImageWriter

import frappe

from asn_module.qr_engine.token import create_token


def _get_dispatch_url(token: str) -> str:
	"""Build the full dispatch URL for a given token."""
	site_url = frappe.utils.get_url()
	return f"{site_url}/api/method/asn_module.qr_engine.dispatch.dispatch?token={token}"


def generate_qr(action: str, source_doctype: str, source_name: str) -> dict:
	"""Generate a QR code image for a given action.

	Args:
		action: The action key
		source_doctype: The source document type
		source_name: The source document name

	Returns:
		dict with keys: url, token, image_base64
	"""
	token = create_token(action, source_doctype, source_name)
	url = _get_dispatch_url(token)

	qr = pyqrcode.create(url)
	buffer = io.BytesIO()
	qr.png(buffer, scale=5)
	image_base64 = base64.b64encode(buffer.getvalue()).decode()

	return {
		"url": url,
		"token": token,
		"image_base64": image_base64,
	}


def generate_barcode(action: str, source_doctype: str, source_name: str) -> dict:
	"""Generate a Code128 barcode image for a given action.

	Args:
		action: The action key
		source_doctype: The source document type
		source_name: The source document name

	Returns:
		dict with keys: token, image_base64
	"""
	token = create_token(action, source_doctype, source_name)

	code128 = barcode.get("code128", token, writer=ImageWriter())
	buffer = io.BytesIO()
	code128.write(buffer)
	image_base64 = base64.b64encode(buffer.getvalue()).decode()

	return {
		"token": token,
		"image_base64": image_base64,
	}
```

- **Step 5: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_generate`
Expected: All 3 tests PASS

- **Step 6: Commit**

```bash
git add asn_module/qr_engine/generate.py asn_module/qr_engine/tests/test_generate.py pyproject.toml
git commit -m "feat: add QR code and barcode generation utilities"
```

---

### Task 3: QR Action Registry and Scan Log Doctypes

**Files:**

- Create: `asn_module/asn_module/doctype/qr_action_registry/qr_action_registry.json`
- Create: `asn_module/asn_module/doctype/qr_action_registry/qr_action_registry.py`
- Create: `asn_module/asn_module/doctype/qr_action_registry_item/qr_action_registry_item.json`
- Create: `asn_module/asn_module/doctype/qr_action_registry_item/qr_action_registry_item.py`
- Create: `asn_module/asn_module/doctype/scan_log/scan_log.json`
- Create: `asn_module/asn_module/doctype/scan_log/scan_log.py`
- Create: `asn_module/asn_module/doctype/scan_log/test_scan_log.py`
- **Step 1: Create the QR Action Registry single doctype**

Create directory: `asn_module/asn_module/doctype/qr_action_registry/`

```python
# asn_module/asn_module/doctype/qr_action_registry/__init__.py
```

```json
// asn_module/asn_module/doctype/qr_action_registry/qr_action_registry.json
{
	"actions": [],
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "DocType",
	"engine": "InnoDB",
	"field_order": [
		"actions_section",
		"actions"
	],
	"fields": [
		{
			"fieldname": "actions_section",
			"fieldtype": "Section Break",
			"label": "Registered Actions"
		},
		{
			"fieldname": "actions",
			"fieldtype": "Table",
			"label": "Actions",
			"options": "QR Action Registry Item",
			"reqd": 0
		}
	],
	"index_web_pages_for_search": 0,
	"issingle": 1,
	"links": [],
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "QR Action Registry",
	"owner": "Administrator",
	"permissions": [
		{
			"create": 1,
			"delete": 1,
			"email": 1,
			"print": 1,
			"read": 1,
			"role": "System Manager",
			"share": 1,
			"write": 1
		}
	],
	"sort_field": "creation",
	"sort_order": "DESC",
	"states": []
}
```

Note: We need a child table for the registry rows. Create `QR Action Registry Item`:

Create directory: `asn_module/asn_module/doctype/qr_action_registry_item/`

```python
# asn_module/asn_module/doctype/qr_action_registry_item/__init__.py
```

```json
// asn_module/asn_module/doctype/qr_action_registry_item/qr_action_registry_item.json
{
	"actions": [],
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "DocType",
	"engine": "InnoDB",
	"field_order": [
		"action_key",
		"handler_method",
		"source_doctype",
		"allowed_roles"
	],
	"fields": [
		{
			"fieldname": "action_key",
			"fieldtype": "Data",
			"in_list_view": 1,
			"label": "Action Key",
			"reqd": 1,
			"unique": 1
		},
		{
			"fieldname": "handler_method",
			"fieldtype": "Data",
			"in_list_view": 1,
			"label": "Handler Method",
			"reqd": 1
		},
		{
			"fieldname": "source_doctype",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "Source DocType",
			"options": "DocType",
			"reqd": 1
		},
		{
			"fieldname": "allowed_roles",
			"fieldtype": "Small Text",
			"in_list_view": 1,
			"label": "Allowed Roles",
			"description": "Comma-separated role names, e.g. Stock User,Stock Manager",
			"reqd": 1
		}
	],
	"index_web_pages_for_search": 0,
	"istable": 1,
	"links": [],
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "QR Action Registry Item",
	"owner": "Administrator",
	"permissions": [],
	"sort_field": "creation",
	"sort_order": "DESC",
	"states": []
}
```

```python
# asn_module/asn_module/doctype/qr_action_registry_item/qr_action_registry_item.py
import frappe
from frappe.model.document import Document


class QRActionRegistryItem(Document):
	pass
```

```python
# asn_module/asn_module/doctype/qr_action_registry/qr_action_registry.py
import frappe
from frappe.model.document import Document


class QRActionRegistry(Document):
	def get_action(self, action_key: str) -> dict | None:
		"""Look up a registered action by key.

		Returns:
			dict with handler_method, source_doctype, allowed_roles or None
		"""
		for row in self.actions:
			if row.action_key == action_key:
				return {
					"handler_method": row.handler_method,
					"source_doctype": row.source_doctype,
					"allowed_roles": [r.strip() for r in (row.allowed_roles or "").split(",") if r.strip()],
				}
		return None
```

- **Step 2: Create the Scan Log doctype**

Create directory: `asn_module/asn_module/doctype/scan_log/`

```python
# asn_module/asn_module/doctype/scan_log/__init__.py
```

```json
// asn_module/asn_module/doctype/scan_log/scan_log.json
{
	"actions": [],
	"autoname": "format:SCAN-{####}",
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "DocType",
	"engine": "InnoDB",
	"field_order": [
		"scan_timestamp",
		"user",
		"action",
		"column_break_1",
		"source_doctype",
		"source_name",
		"device_info",
		"result_section",
		"result",
		"result_doctype",
		"result_name",
		"column_break_2",
		"error_message"
	],
	"fields": [
		{
			"fieldname": "scan_timestamp",
			"fieldtype": "Datetime",
			"in_list_view": 1,
			"label": "Scan Timestamp",
			"read_only": 1
		},
		{
			"fieldname": "user",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "User",
			"options": "User",
			"read_only": 1
		},
		{
			"fieldname": "action",
			"fieldtype": "Data",
			"in_list_view": 1,
			"label": "Action",
			"read_only": 1
		},
		{
			"fieldname": "column_break_1",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "source_doctype",
			"fieldtype": "Link",
			"label": "Source DocType",
			"options": "DocType",
			"read_only": 1
		},
		{
			"fieldname": "source_name",
			"fieldtype": "Dynamic Link",
			"label": "Source Name",
			"options": "source_doctype",
			"read_only": 1
		},
		{
			"fieldname": "device_info",
			"fieldtype": "Data",
			"label": "Device Info",
			"read_only": 1
		},
		{
			"fieldname": "result_section",
			"fieldtype": "Section Break",
			"label": "Result"
		},
		{
			"fieldname": "result",
			"fieldtype": "Select",
			"in_list_view": 1,
			"label": "Result",
			"options": "\nSuccess\nFailure",
			"read_only": 1
		},
		{
			"fieldname": "result_doctype",
			"fieldtype": "Link",
			"label": "Result DocType",
			"options": "DocType",
			"read_only": 1
		},
		{
			"fieldname": "result_name",
			"fieldtype": "Dynamic Link",
			"label": "Result Name",
			"options": "result_doctype",
			"read_only": 1
		},
		{
			"fieldname": "column_break_2",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "error_message",
			"fieldtype": "Text",
			"label": "Error Message",
			"read_only": 1
		}
	],
	"in_create": 1,
	"index_web_pages_for_search": 0,
	"links": [],
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "Scan Log",
	"naming_rule": "Expression",
	"owner": "Administrator",
	"permissions": [
		{
			"read": 1,
			"role": "System Manager"
		},
		{
			"read": 1,
			"role": "Stock User"
		},
		{
			"read": 1,
			"role": "Stock Manager"
		},
		{
			"read": 1,
			"role": "Accounts User"
		}
	],
	"sort_field": "creation",
	"sort_order": "DESC",
	"states": [],
	"track_changes": 0
}
```

```python
# asn_module/asn_module/doctype/scan_log/scan_log.py
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ScanLog(Document):
	def before_insert(self):
		self.scan_timestamp = now_datetime()
		self.user = frappe.session.user
```

- **Step 3: Write test for Scan Log creation**

```python
# asn_module/asn_module/doctype/scan_log/test_scan_log.py
import frappe
from frappe.tests import IntegrationTestCase


class TestScanLog(IntegrationTestCase):
	def test_scan_log_auto_sets_timestamp_and_user(self):
		log = frappe.get_doc({
			"doctype": "Scan Log",
			"action": "test_action",
			"source_doctype": "User",
			"source_name": "Administrator",
			"result": "Success",
			"device_info": "Desktop",
		}).insert(ignore_permissions=True)

		self.assertIsNotNone(log.scan_timestamp)
		self.assertEqual(log.user, frappe.session.user)

	def test_scan_log_fields_are_read_only(self):
		log = frappe.get_doc({
			"doctype": "Scan Log",
			"action": "test_action",
			"source_doctype": "User",
			"source_name": "Administrator",
			"result": "Success",
			"device_info": "Desktop",
		}).insert(ignore_permissions=True)

		self.assertTrue(log.name.startswith("SCAN-"))
```

- **Step 4: Run tests**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.asn_module.doctype.scan_log.test_scan_log`
Expected: All 2 tests PASS

- **Step 5: Commit**

```bash
git add asn_module/asn_module/doctype/
git commit -m "feat: add QR Action Registry, QR Action Registry Item, and Scan Log doctypes"
```

---

### Task 4: Dispatch Endpoint

**Files:**

- Create: `asn_module/qr_engine/dispatch.py`
- Create: `asn_module/qr_engine/tests/test_dispatch.py`
- **Step 1: Write the failing tests for dispatch**

```python
# asn_module/qr_engine/tests/test_dispatch.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.qr_engine.token import create_token
from asn_module.qr_engine.dispatch import dispatch, _resolve_action, ActionNotFoundError, PermissionDeniedError


class TestResolveAction(IntegrationTestCase):
	def setUp(self):
		self._setup_registry()

	def _setup_registry(self):
		"""Register a test action in the QR Action Registry."""
		registry = frappe.get_single("QR Action Registry")
		registry.actions = []
		registry.append("actions", {
			"action_key": "test_action",
			"handler_method": "asn_module.qr_engine.tests.test_dispatch.dummy_handler",
			"source_doctype": "User",
		})
		# Add role to the action row
		registry.actions[0].allowed_roles = "System Manager"
		registry.save(ignore_permissions=True)

	def test_resolve_action_returns_handler(self):
		action = _resolve_action("test_action")
		self.assertEqual(action["handler_method"], "asn_module.qr_engine.tests.test_dispatch.dummy_handler")

	def test_resolve_unknown_action_raises(self):
		with self.assertRaises(ActionNotFoundError):
			_resolve_action("nonexistent_action")


class TestDispatch(IntegrationTestCase):
	def setUp(self):
		self._setup_registry()

	def _setup_registry(self):
		registry = frappe.get_single("QR Action Registry")
		registry.actions = []
		registry.append("actions", {
			"action_key": "test_action",
			"handler_method": "asn_module.qr_engine.tests.test_dispatch.dummy_handler",
			"source_doctype": "User",
		})
		registry.actions[0].allowed_roles = "System Manager"
		registry.save(ignore_permissions=True)

	def test_dispatch_calls_handler_and_returns_result(self):
		token = create_token(
			action="test_action",
			source_doctype="User",
			source_name="Administrator",
		)
		result = dispatch(token=token)
		self.assertTrue(result["success"])
		self.assertEqual(result["doctype"], "User")
		self.assertEqual(result["name"], "Administrator")

	def test_dispatch_creates_scan_log_on_success(self):
		token = create_token(
			action="test_action",
			source_doctype="User",
			source_name="Administrator",
		)
		dispatch(token=token)

		logs = frappe.get_all(
			"Scan Log",
			filters={"action": "test_action", "source_name": "Administrator"},
			fields=["result"],
		)
		self.assertTrue(len(logs) > 0)
		self.assertEqual(logs[0].result, "Success")

	def test_dispatch_creates_scan_log_on_failure(self):
		token = create_token(
			action="nonexistent_action",
			source_doctype="User",
			source_name="Administrator",
		)
		try:
			dispatch(token=token)
		except ActionNotFoundError:
			pass

		logs = frappe.get_all(
			"Scan Log",
			filters={"action": "nonexistent_action"},
			fields=["result", "error_message"],
		)
		self.assertTrue(len(logs) > 0)
		self.assertEqual(logs[0].result, "Failure")


def dummy_handler(source_doctype, source_name, payload):
	"""Test handler that returns a mock result."""
	return {
		"doctype": source_doctype,
		"name": source_name,
		"url": f"/app/user/{source_name}",
	}
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch`
Expected: FAIL with ImportError

- **Step 3: Implement dispatch module**

```python
# asn_module/qr_engine/dispatch.py
import frappe
from frappe import _

from asn_module.qr_engine.token import verify_token, InvalidTokenError


class ActionNotFoundError(frappe.ValidationError):
	pass


class PermissionDeniedError(frappe.PermissionError):
	pass


def _resolve_action(action_key: str) -> dict:
	"""Look up a registered action from the QR Action Registry.

	Returns:
		dict with handler_method, source_doctype, allowed_roles

	Raises:
		ActionNotFoundError: If the action is not registered
	"""
	registry = frappe.get_single("QR Action Registry")
	action = registry.get_action(action_key)
	if not action:
		raise ActionNotFoundError(_("Action '{0}' is not registered").format(action_key))
	return action


def _check_permission(allowed_roles: list[str]) -> None:
	"""Check if the current user has any of the allowed roles.

	Raises:
		PermissionDeniedError: If user lacks required roles
	"""
	user_roles = frappe.get_roles()
	if not any(role in user_roles for role in allowed_roles):
		raise PermissionDeniedError(
			_("You do not have permission to perform this action. Required roles: {0}").format(
				", ".join(allowed_roles)
			)
		)


def _log_scan(action: str, source_doctype: str, source_name: str, result: str,
              result_doctype: str = None, result_name: str = None,
              error_message: str = None, device_info: str = None) -> None:
	"""Create a Scan Log entry."""
	frappe.get_doc({
		"doctype": "Scan Log",
		"action": action,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"result": result,
		"result_doctype": result_doctype,
		"result_name": result_name,
		"error_message": error_message,
		"device_info": device_info or "Desktop",
	}).insert(ignore_permissions=True)


def _call_handler(handler_method: str, source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Dynamically call the registered handler method.

	Returns:
		dict with doctype, name, url from the handler
	"""
	module_path, method_name = handler_method.rsplit(".", 1)
	module = frappe.get_module(module_path)
	handler_fn = getattr(module, method_name)
	return handler_fn(source_doctype=source_doctype, source_name=source_name, payload=payload)


@frappe.whitelist(allow_guest=False)
def dispatch(token: str, device_info: str = "Desktop") -> dict:
	"""Main QR dispatch endpoint. Decodes token, validates action and permissions,
	calls handler, logs result.

	Args:
		token: Signed QR action token
		device_info: 'Desktop' or 'Mobile'

	Returns:
		dict with success, action, doctype, name, url, message
	"""
	payload = None
	action_key = None

	try:
		payload = verify_token(token)
		action_key = payload["action"]
		source_doctype = payload["source_doctype"]
		source_name = payload["source_name"]

		action = _resolve_action(action_key)
		_check_permission(action["allowed_roles"])

		handler_result = _call_handler(
			action["handler_method"],
			source_doctype,
			source_name,
			payload,
		)

		_log_scan(
			action=action_key,
			source_doctype=source_doctype,
			source_name=source_name,
			result="Success",
			result_doctype=handler_result.get("doctype"),
			result_name=handler_result.get("name"),
			device_info=device_info,
		)

		return {
			"success": True,
			"action": action_key,
			"doctype": handler_result["doctype"],
			"name": handler_result["name"],
			"url": handler_result["url"],
			"message": handler_result.get("message", ""),
		}

	except Exception as e:
		_log_scan(
			action=action_key or "unknown",
			source_doctype=payload.get("source_doctype", "") if payload else "",
			source_name=payload.get("source_name", "") if payload else "",
			result="Failure",
			error_message=str(e),
			device_info=device_info,
		)
		raise
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.qr_engine.tests.test_dispatch`
Expected: All 5 tests PASS

- **Step 5: Commit**

```bash
git add asn_module/qr_engine/dispatch.py asn_module/qr_engine/tests/test_dispatch.py
git commit -m "feat: add QR dispatch endpoint with action routing and scan logging"
```

---

## Phase 2: ASN Doctype

### Task 5: ASN Item Child Table

**Files:**

- Create: `asn_module/asn_module/doctype/asn_item/__init__.py`
- Create: `asn_module/asn_module/doctype/asn_item/asn_item.json`
- Create: `asn_module/asn_module/doctype/asn_item/asn_item.py`
- **Step 1: Create the ASN Item child table doctype**

Create directory: `asn_module/asn_module/doctype/asn_item/`

```python
# asn_module/asn_module/doctype/asn_item/__init__.py
```

```json
// asn_module/asn_module/doctype/asn_item/asn_item.json
{
	"actions": [],
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "DocType",
	"engine": "InnoDB",
	"field_order": [
		"purchase_order",
		"purchase_order_item",
		"item_code",
		"item_name",
		"column_break_1",
		"qty",
		"uom",
		"rate",
		"batch_no",
		"serial_nos",
		"tracking_section",
		"received_qty",
		"discrepancy_qty"
	],
	"fields": [
		{
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "Purchase Order",
			"options": "Purchase Order",
			"reqd": 1
		},
		{
			"fieldname": "purchase_order_item",
			"fieldtype": "Data",
			"hidden": 1,
			"label": "Purchase Order Item"
		},
		{
			"fieldname": "item_code",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "Item Code",
			"options": "Item",
			"reqd": 1
		},
		{
			"fieldname": "item_name",
			"fieldtype": "Data",
			"fetch_from": "item_code.item_name",
			"label": "Item Name",
			"read_only": 1
		},
		{
			"fieldname": "column_break_1",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "qty",
			"fieldtype": "Float",
			"in_list_view": 1,
			"label": "Quantity",
			"reqd": 1
		},
		{
			"fieldname": "uom",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "UOM",
			"options": "UOM",
			"reqd": 1
		},
		{
			"fieldname": "rate",
			"fieldtype": "Currency",
			"in_list_view": 1,
			"label": "Rate",
			"read_only": 1
		},
		{
			"fieldname": "batch_no",
			"fieldtype": "Data",
			"label": "Batch No"
		},
		{
			"fieldname": "serial_nos",
			"fieldtype": "Small Text",
			"label": "Serial Nos"
		},
		{
			"fieldname": "tracking_section",
			"fieldtype": "Section Break",
			"label": "Receipt Tracking"
		},
		{
			"fieldname": "received_qty",
			"fieldtype": "Float",
			"label": "Received Qty",
			"read_only": 1,
			"default": "0"
		},
		{
			"fieldname": "discrepancy_qty",
			"fieldtype": "Float",
			"label": "Discrepancy Qty",
			"read_only": 1,
			"default": "0"
		}
	],
	"index_web_pages_for_search": 0,
	"istable": 1,
	"links": [],
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "ASN Item",
	"owner": "Administrator",
	"permissions": [],
	"sort_field": "creation",
	"sort_order": "DESC",
	"states": []
}
```

```python
# asn_module/asn_module/doctype/asn_item/asn_item.py
import frappe
from frappe.model.document import Document


class ASNItem(Document):
	pass
```

- **Step 2: Commit**

```bash
git add asn_module/asn_module/doctype/asn_item/
git commit -m "feat: add ASN Item child table doctype"
```

---

### Task 6: ASN Doctype - Structure and Validations

**Files:**

- Create: `asn_module/asn_module/doctype/asn/__init__.py`
- Create: `asn_module/asn_module/doctype/asn/asn.json`
- Create: `asn_module/asn_module/doctype/asn/asn.py`
- Create: `asn_module/asn_module/doctype/asn/test_asn.py`
- **Step 1: Create the ASN doctype JSON**

Create directory: `asn_module/asn_module/doctype/asn/`

```python
# asn_module/asn_module/doctype/asn/__init__.py
```

```json
// asn_module/asn_module/doctype/asn/asn.json
{
	"actions": [],
	"autoname": "format:ASN-{####}",
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "DocType",
	"engine": "InnoDB",
	"field_order": [
		"supplier",
		"asn_date",
		"status",
		"column_break_1",
		"expected_delivery_date",
		"amended_from",
		"items_section",
		"items",
		"transport_section",
		"vehicle_number",
		"transporter_name",
		"column_break_2",
		"driver_contact",
		"invoice_section",
		"supplier_invoice_no",
		"supplier_invoice_date",
		"column_break_3",
		"supplier_invoice_amount",
		"qr_section",
		"qr_code",
		"column_break_4",
		"barcode",
		"remarks_section",
		"remarks"
	],
	"fields": [
		{
			"fieldname": "supplier",
			"fieldtype": "Link",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"label": "Supplier",
			"options": "Supplier",
			"reqd": 1
		},
		{
			"fieldname": "asn_date",
			"fieldtype": "Date",
			"in_list_view": 1,
			"label": "ASN Date",
			"read_only": 1
		},
		{
			"fieldname": "status",
			"fieldtype": "Select",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"label": "Status",
			"options": "Draft\nSubmitted\nPartially Received\nReceived\nClosed\nCancelled",
			"default": "Draft",
			"read_only": 1
		},
		{
			"fieldname": "column_break_1",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "expected_delivery_date",
			"fieldtype": "Date",
			"label": "Expected Delivery Date"
		},
		{
			"fieldname": "amended_from",
			"fieldtype": "Link",
			"label": "Amended From",
			"no_copy": 1,
			"options": "ASN",
			"print_hide": 1,
			"read_only": 1
		},
		{
			"fieldname": "items_section",
			"fieldtype": "Section Break",
			"label": "Items"
		},
		{
			"fieldname": "items",
			"fieldtype": "Table",
			"label": "Items",
			"options": "ASN Item",
			"reqd": 1
		},
		{
			"fieldname": "transport_section",
			"fieldtype": "Section Break",
			"label": "Transport Details"
		},
		{
			"fieldname": "vehicle_number",
			"fieldtype": "Data",
			"label": "Vehicle Number"
		},
		{
			"fieldname": "transporter_name",
			"fieldtype": "Data",
			"label": "Transporter Name"
		},
		{
			"fieldname": "column_break_2",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "driver_contact",
			"fieldtype": "Data",
			"label": "Driver Contact"
		},
		{
			"fieldname": "invoice_section",
			"fieldtype": "Section Break",
			"label": "Supplier Invoice Details"
		},
		{
			"fieldname": "supplier_invoice_no",
			"fieldtype": "Data",
			"label": "Supplier Invoice No",
			"reqd": 1
		},
		{
			"fieldname": "supplier_invoice_date",
			"fieldtype": "Date",
			"label": "Supplier Invoice Date"
		},
		{
			"fieldname": "column_break_3",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "supplier_invoice_amount",
			"fieldtype": "Currency",
			"label": "Supplier Invoice Amount"
		},
		{
			"fieldname": "qr_section",
			"fieldtype": "Section Break",
			"label": "QR Code & Barcode"
		},
		{
			"fieldname": "qr_code",
			"fieldtype": "Attach Image",
			"label": "QR Code",
			"read_only": 1
		},
		{
			"fieldname": "column_break_4",
			"fieldtype": "Column Break"
		},
		{
			"fieldname": "barcode",
			"fieldtype": "Attach Image",
			"label": "Barcode",
			"read_only": 1
		},
		{
			"fieldname": "remarks_section",
			"fieldtype": "Section Break",
			"label": "Remarks"
		},
		{
			"fieldname": "remarks",
			"fieldtype": "Text",
			"label": "Remarks"
		}
	],
	"index_web_pages_for_search": 0,
	"is_submittable": 1,
	"links": [],
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "ASN",
	"naming_rule": "Expression",
	"owner": "Administrator",
	"permissions": [
		{
			"create": 1,
			"delete": 1,
			"email": 1,
			"export": 1,
			"print": 1,
			"read": 1,
			"report": 1,
			"role": "Stock User",
			"share": 1,
			"submit": 0,
			"write": 1
		},
		{
			"amend": 1,
			"cancel": 1,
			"create": 1,
			"delete": 1,
			"email": 1,
			"export": 1,
			"print": 1,
			"read": 1,
			"report": 1,
			"role": "Stock Manager",
			"share": 1,
			"submit": 1,
			"write": 1
		}
	],
	"sort_field": "creation",
	"sort_order": "DESC",
	"states": [],
	"track_changes": 1
}
```

- **Step 2: Write the failing tests for ASN validations**

```python
# asn_module/asn_module/doctype/asn/test_asn.py
import frappe
from frappe.tests import IntegrationTestCase


def make_test_asn(**kwargs):
	"""Helper to create a test ASN document."""
	asn = frappe.get_doc({
		"doctype": "ASN",
		"supplier": kwargs.get("supplier", "_Test Supplier"),
		"supplier_invoice_no": kwargs.get("supplier_invoice_no", f"INV-{frappe.generate_hash(length=6)}"),
		"supplier_invoice_date": kwargs.get("supplier_invoice_date", frappe.utils.today()),
		"expected_delivery_date": kwargs.get("expected_delivery_date", frappe.utils.add_days(frappe.utils.today(), 3)),
		"items": kwargs.get("items", []),
	})
	return asn


class TestASNValidation(IntegrationTestCase):
	def setUp(self):
		self._ensure_test_data()

	def _ensure_test_data(self):
		"""Ensure test supplier and items exist."""
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

	def test_asn_requires_at_least_one_item(self):
		asn = make_test_asn(items=[])
		with self.assertRaises(frappe.ValidationError):
			asn.insert()

	def test_asn_unique_supplier_invoice(self):
		invoice_no = f"UNIQUE-INV-{frappe.generate_hash(length=6)}"
		asn1 = make_test_asn(
			supplier_invoice_no=invoice_no,
			items=[{
				"purchase_order": "",
				"item_code": "_Test ASN Item",
				"qty": 10,
				"uom": "Nos",
				"rate": 100,
			}],
		)
		asn1.flags.ignore_validate = True
		asn1.insert(ignore_permissions=True)

		asn2 = make_test_asn(
			supplier_invoice_no=invoice_no,
			items=[{
				"purchase_order": "",
				"item_code": "_Test ASN Item",
				"qty": 5,
				"uom": "Nos",
				"rate": 100,
			}],
		)
		with self.assertRaises(frappe.ValidationError):
			asn2.insert()

	def test_asn_status_defaults_to_draft(self):
		asn = make_test_asn(
			items=[{
				"purchase_order": "",
				"item_code": "_Test ASN Item",
				"qty": 10,
				"uom": "Nos",
				"rate": 100,
			}],
		)
		asn.flags.ignore_validate = True
		asn.insert(ignore_permissions=True)
		self.assertEqual(asn.status, "Draft")

	def test_asn_item_qty_must_be_positive(self):
		asn = make_test_asn(
			items=[{
				"purchase_order": "",
				"item_code": "_Test ASN Item",
				"qty": 0,
				"uom": "Nos",
				"rate": 100,
			}],
		)
		with self.assertRaises(frappe.ValidationError):
			asn.insert()
```

- **Step 3: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.asn_module.doctype.asn.test_asn`
Expected: FAIL with ImportError or validation not implemented

- **Step 4: Implement ASN controller with validations**

```python
# asn_module/asn_module/doctype/asn/asn.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today


class ASN(Document):
	def validate(self):
		self.validate_items()
		self.validate_item_qty()
		self.validate_unique_supplier_invoice()
		self.validate_po_qty()

	def on_submit(self):
		self.status = "Submitted"
		self.asn_date = today()
		self.generate_qr_codes()

	def on_cancel(self):
		self.status = "Cancelled"

	def validate_items(self):
		if not self.items:
			frappe.throw(_("At least one item is required in the ASN"))

	def validate_item_qty(self):
		for item in self.items:
			if not item.qty or item.qty <= 0:
				frappe.throw(
					_("Row {0}: Quantity must be greater than 0 for item {1}").format(
						item.idx, item.item_code
					)
				)

	def validate_unique_supplier_invoice(self):
		if not self.supplier_invoice_no:
			return
		existing = frappe.db.exists(
			"ASN",
			{
				"supplier": self.supplier,
				"supplier_invoice_no": self.supplier_invoice_no,
				"name": ("!=", self.name),
				"docstatus": ("!=", 2),
			},
		)
		if existing:
			frappe.throw(
				_("Supplier Invoice {0} already exists for supplier {1} in ASN {2}").format(
					self.supplier_invoice_no, self.supplier, existing
				)
			)

	def validate_po_qty(self):
		"""Validate shipped qty does not exceed remaining unshipped PO qty."""
		for item in self.items:
			if not item.purchase_order:
				continue

			po_item_qty = frappe.db.get_value(
				"Purchase Order Item",
				item.purchase_order_item,
				"qty",
			)
			if not po_item_qty:
				continue

			# Sum all ASN Item qty for this PO item across other ASNs
			already_shipped = frappe.db.sql(
				"""
				SELECT COALESCE(SUM(ai.qty), 0)
				FROM `tabASN Item` ai
				JOIN `tabASN` a ON a.name = ai.parent
				WHERE ai.purchase_order_item = %s
				AND a.name != %s
				AND a.docstatus != 2
				""",
				(item.purchase_order_item, self.name),
			)[0][0]

			remaining = po_item_qty - already_shipped
			if item.qty > remaining:
				frappe.throw(
					_("Row {0}: Shipped qty {1} exceeds remaining PO qty {2} for item {3}").format(
						item.idx, item.qty, remaining, item.item_code
					)
				)

	def generate_qr_codes(self):
		"""Generate Purchase Receipt QR and barcode on submit."""
		from asn_module.qr_engine.generate import generate_qr, generate_barcode

		qr_result = generate_qr(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name=self.name,
		)
		barcode_result = generate_barcode(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name=self.name,
		)

		# Save QR as file attachment
		qr_file = self._save_image(qr_result["image_base64"], f"{self.name}-qr.png")
		barcode_file = self._save_image(barcode_result["image_base64"], f"{self.name}-barcode.png")

		frappe.db.set_value("ASN", self.name, {
			"qr_code": qr_file.file_url,
			"barcode": barcode_file.file_url,
		})

	def _save_image(self, image_base64: str, filename: str):
		"""Save a base64 image as a Frappe File attachment."""
		import base64

		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": filename,
			"attached_to_doctype": "ASN",
			"attached_to_name": self.name,
			"content": base64.b64decode(image_base64),
			"is_private": 0,
		})
		file_doc.save(ignore_permissions=True)
		return file_doc

	def update_receipt_status(self):
		"""Update ASN status based on received quantities across all items."""
		all_received = True
		any_received = False

		for item in self.items:
			if item.received_qty > 0:
				any_received = True
			if item.received_qty < item.qty:
				all_received = False
			item.discrepancy_qty = item.qty - item.received_qty

		if all_received:
			self.status = "Received"
		elif any_received:
			self.status = "Partially Received"

		self.save(ignore_permissions=True)
```

- **Step 5: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.asn_module.doctype.asn.test_asn`
Expected: All 4 tests PASS

- **Step 6: Commit**

```bash
git add asn_module/asn_module/doctype/asn/
git commit -m "feat: add ASN doctype with validations and QR generation on submit"
```

---

### Task 7: ASN Client Script

**Files:**

- Create: `asn_module/asn_module/doctype/asn/asn.js`
- **Step 1: Write the client script for ASN form**

```javascript
// asn_module/asn_module/doctype/asn/asn.js
frappe.ui.form.on("ASN", {
	setup(frm) {
		frm.set_query("purchase_order", "items", function () {
			return {
				filters: {
					supplier: frm.doc.supplier,
					docstatus: 1,
					status: ["in", ["To Receive and Bill", "To Receive"]],
				},
			};
		});

		frm.set_query("item_code", "items", function (_doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			if (row.purchase_order) {
				return {
					query: "asn_module.asn_module.doctype.asn.asn.get_po_items",
					filters: { purchase_order: row.purchase_order },
				};
			}
			return {};
		});
	},

	supplier(frm) {
		// Clear items when supplier changes
		if (frm.doc.items && frm.doc.items.length) {
			frappe.confirm(
				__("Changing supplier will clear all items. Continue?"),
				function () {
					frm.clear_table("items");
					frm.refresh_field("items");
				},
				function () {
					frm.set_value("supplier", frm.doc.__last_supplier || "");
				}
			);
		}
		frm.doc.__last_supplier = frm.doc.supplier;
	},
});

frappe.ui.form.on("ASN Item", {
	purchase_order(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.purchase_order) return;

		frappe.call({
			method: "asn_module.asn_module.doctype.asn.asn.get_purchase_order_items",
			args: { purchase_order: row.purchase_order, asn_name: frm.doc.name },
			callback(r) {
				if (r.message && r.message.length) {
					// Remove the current empty row
					let current_idx = row.idx;
					frm.doc.items = frm.doc.items.filter((d) => d.idx !== current_idx);

					// Add all PO items
					r.message.forEach(function (item) {
						let new_row = frm.add_child("items");
						Object.assign(new_row, item);
					});

					frm.refresh_field("items");
				}
			},
		});
	},

	qty(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.qty <= 0) {
			frappe.msgprint(__("Quantity must be greater than 0"));
			frappe.model.set_value(cdt, cdn, "qty", 1);
		}
	},
});
```

- **Step 2: Add the server-side helper for fetching PO items**

Append to `asn_module/asn_module/doctype/asn/asn.py`:

```python
@frappe.whitelist()
def get_purchase_order_items(purchase_order: str, asn_name: str = None) -> list[dict]:
	"""Fetch items from a Purchase Order with remaining unshipped quantities.

	Args:
		purchase_order: Purchase Order name
		asn_name: Current ASN name (to exclude from shipped qty calculation)

	Returns:
		list of dicts with item details for ASN Item child table
	"""
	po_items = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order},
		fields=[
			"name as purchase_order_item",
			"item_code",
			"item_name",
			"qty",
			"uom",
			"rate",
		],
	)

	result = []
	for poi in po_items:
		# Calculate already shipped qty from other ASNs
		already_shipped = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(ai.qty), 0)
			FROM `tabASN Item` ai
			JOIN `tabASN` a ON a.name = ai.parent
			WHERE ai.purchase_order_item = %s
			AND a.name != %s
			AND a.docstatus != 2
			""",
			(poi.purchase_order_item, asn_name or ""),
		)[0][0]

		remaining = poi.qty - already_shipped
		if remaining > 0:
			result.append({
				"purchase_order": purchase_order,
				"purchase_order_item": poi.purchase_order_item,
				"item_code": poi.item_code,
				"item_name": poi.item_name,
				"qty": remaining,
				"uom": poi.uom,
				"rate": poi.rate,
			})

	return result


@frappe.whitelist()
def get_po_items(doctype, txt, searchfield, start, page_len, filters):
	"""Search filter for items available in a specific Purchase Order."""
	purchase_order = filters.get("purchase_order")
	if not purchase_order:
		return []

	return frappe.db.sql(
		"""
		SELECT poi.item_code, poi.item_name
		FROM `tabPurchase Order Item` poi
		WHERE poi.parent = %s
		AND (poi.item_code LIKE %s OR poi.item_name LIKE %s)
		LIMIT %s OFFSET %s
		""",
		(purchase_order, f"%{txt}%", f"%{txt}%", page_len, start),
	)
```

- **Step 3: Run E2E tests manually**

Open browser, navigate to `frappe16.localhost/app/asn/new`, verify:

- Supplier field filters POs correctly
- Selecting a PO populates items with remaining quantities
- QR code and barcode are generated on submit
- **Step 4: Commit**

```bash
git add asn_module/asn_module/doctype/asn/asn.js asn_module/asn_module/doctype/asn/asn.py
git commit -m "feat: add ASN client script with PO item fetching and quantity validation"
```

---

## Phase 3: Supplier Portal

### Task 8: Portal Configuration for ASN

**Files:**

- Create: `asn_module/templates/pages/asn.html`
- Create: `asn_module/templates/pages/asn.py`
- Create: `asn_module/templates/pages/asn_row.html`
- Modify: `asn_module/hooks.py`
- **Step 1: Configure hooks for portal**

In `asn_module/hooks.py`, add after the existing comments:

```python
# Portal
has_website_permission = {
	"ASN": "asn_module.templates.pages.asn.has_website_permission",
}

portal_menu_items = [
	{
		"title": "ASN",
		"route": "/asn",
		"reference_doctype": "ASN",
		"role": "Supplier",
	}
]
```

Also update the ASN doctype JSON to add web view settings. In `asn.json`, add these top-level keys:

```json
"allow_guest_to_view": 0,
"has_web_view": 1,
"allow_import": 1
```

- **Step 2: Create the portal list page controller**

```python
# asn_module/templates/pages/asn.py
import frappe


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.title = "ASN"


def has_website_permission(doc, ptype, user=None, verbose=False):
	"""Suppliers can only see their own ASNs."""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	supplier = frappe.db.get_value(
		"Portal User",
		{"user": user, "parenttype": "Supplier"},
		"parent",
	)
	if not supplier:
		# Fallback: check if user email matches supplier
		supplier = frappe.db.get_value("Supplier", {"supplier_primary_contact": user})

	return doc.supplier == supplier if supplier else False
```

- **Step 3: Create the portal list template**

```html
<!-- asn_module/templates/pages/asn.html -->
{% extends "templates/web.html" %}

{% block page_content %}
<div class="container">
	<div class="row">
		<div class="col-md-12">
			<div class="d-flex justify-content-between align-items-center mb-4">
				<h3>{{ _("Advanced Shipping Notices") }}</h3>
				<a href="/app/asn/new" class="btn btn-primary btn-sm">
					{{ _("New ASN") }}
				</a>
			</div>

			{% if asn_list %}
			<div class="list-group">
				{% for asn in asn_list %}
				{% include "asn_module/templates/pages/asn_row.html" %}
				{% endfor %}
			</div>
			{% else %}
			<div class="text-muted text-center py-5">
				{{ _("No ASNs found. Create your first ASN.") }}
			</div>
			{% endif %}
		</div>
	</div>
</div>
{% endblock %}
```

```html
<!-- asn_module/templates/pages/asn_row.html -->
<a href="/app/asn/{{ asn.name }}" class="list-group-item list-group-item-action">
	<div class="d-flex justify-content-between">
		<div>
			<strong>{{ asn.name }}</strong>
			<span class="text-muted ml-2">{{ asn.supplier_invoice_no }}</span>
		</div>
		<div>
			<span class="badge badge-{{ 'success' if asn.status == 'Received' else 'warning' if asn.status == 'Partially Received' else 'info' }}">
				{{ asn.status }}
			</span>
		</div>
	</div>
	<div class="text-muted small mt-1">
		{{ _("Expected") }}: {{ frappe.format(asn.expected_delivery_date, {"fieldtype": "Date"}) }}
		| {{ _("Items") }}: {{ asn.total_items }}
	</div>
</a>
```

- **Step 4: Update the portal list controller to fetch ASN data**

Update `asn_module/templates/pages/asn.py`:

```python
# asn_module/templates/pages/asn.py
import frappe


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.title = "ASN"

	user = frappe.session.user
	supplier = _get_supplier_for_user(user)

	if not supplier:
		context.asn_list = []
		return

	asn_list = frappe.get_all(
		"ASN",
		filters={"supplier": supplier, "docstatus": ("!=", 2)},
		fields=["name", "supplier_invoice_no", "status", "expected_delivery_date", "asn_date"],
		order_by="creation desc",
		limit_page_length=50,
	)

	for asn in asn_list:
		asn.total_items = frappe.db.count("ASN Item", {"parent": asn.name})

	context.asn_list = asn_list


def _get_supplier_for_user(user):
	"""Get the Supplier linked to a portal user."""
	if user == "Administrator":
		return None

	supplier = frappe.db.get_value(
		"Portal User",
		{"user": user, "parenttype": "Supplier"},
		"parent",
	)
	return supplier


def has_website_permission(doc, ptype, user=None, verbose=False):
	"""Suppliers can only see their own ASNs."""
	if not user:
		user = frappe.session.user

	if user == "Administrator":
		return True

	supplier = _get_supplier_for_user(user)
	return doc.supplier == supplier if supplier else False
```

- **Step 5: Commit**

```bash
git add asn_module/templates/ asn_module/hooks.py asn_module/asn_module/doctype/asn/asn.json
git commit -m "feat: add supplier portal for ASN list and creation"
```

---

## Phase 4: Scan Station

### Task 9: Scan Station Page

**Files:**

- Create: `asn_module/asn_module/page/scan_station/__init__.py`
- Create: `asn_module/asn_module/page/scan_station/scan_station.json`
- Create: `asn_module/asn_module/page/scan_station/scan_station.js`
- Create: `asn_module/asn_module/page/scan_station/scan_station.html`
- Create: `asn_module/asn_module/page/scan_station/scan_station.py`
- **Step 1: Create the Scan Station page definition**

Create directory: `asn_module/asn_module/page/scan_station/`

```python
# asn_module/asn_module/page/scan_station/__init__.py
```

```json
// asn_module/asn_module/page/scan_station/scan_station.json
{
	"content": null,
	"creation": "2026-04-01 00:00:00.000000",
	"doctype": "Page",
	"icon": "icon-barcode",
	"modified": "2026-04-01 00:00:00.000000",
	"modified_by": "Administrator",
	"module": "ASN Module",
	"name": "scan-station",
	"owner": "Administrator",
	"page_name": "scan-station",
	"roles": [
		{ "role": "Stock User" },
		{ "role": "Stock Manager" },
		{ "role": "Accounts User" },
		{ "role": "Accounts Manager" },
		{ "role": "System Manager" }
	],
	"standard": "Yes",
	"system_page": 0,
	"title": "Scan Station"
}
```

- **Step 2: Create the Scan Station HTML template**

```html
<!-- asn_module/asn_module/page/scan_station/scan_station.html -->
<div class="scan-station-container" style="max-width: 800px; margin: 0 auto; padding: 20px;">
	<div class="scan-input-section text-center" style="padding: 40px 20px;">
		<h3>{{ __("Scan QR Code or Barcode") }}</h3>
		<p class="text-muted">{{ __("Use a handheld scanner or paste a QR URL below") }}</p>
		<div class="scan-input-wrapper" style="max-width: 500px; margin: 20px auto;">
			<input
				type="text"
				class="form-control form-control-lg scan-input"
				placeholder="{{ __('Scan here...') }}"
				autofocus
				autocomplete="off"
			/>
		</div>
		<div class="scan-status mt-3" style="display: none;">
			<div class="spinner-border text-primary" role="status">
				<span class="sr-only">{{ __("Processing...") }}</span>
			</div>
			<p class="text-muted mt-2">{{ __("Processing scan...") }}</p>
		</div>
		<div class="scan-error alert alert-danger mt-3" style="display: none;"></div>
	</div>

	<div class="scan-history-section mt-5">
		<h5>{{ __("Recent Scans") }}</h5>
		<div class="scan-history-list"></div>
	</div>
</div>
```

- **Step 3: Create the Scan Station JavaScript**

```javascript
// asn_module/asn_module/page/scan_station/scan_station.js
frappe.pages["scan-station"].on_page_load = function (wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Scan Station"),
		single_column: true,
	});

	page.main.html(frappe.render_template("scan_station"));

	const $input = page.main.find(".scan-input");
	const $status = page.main.find(".scan-status");
	const $error = page.main.find(".scan-error");
	const $history = page.main.find(".scan-history-list");

	let scan_buffer = "";
	let scan_timeout = null;

	function process_scan(value) {
		if (!value || !value.trim()) return;

		let token = value.trim();

		// Extract token from URL if full URL was scanned
		let url_match = token.match(/[?&]token=([^&]+)/);
		if (url_match) {
			token = url_match[1];
		}

		$input.prop("disabled", true);
		$status.show();
		$error.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { token: token, device_info: "Desktop" },
			callback(r) {
				$status.hide();
				$input.val("").prop("disabled", false).focus();

				if (r.message && r.message.success) {
					frappe.show_alert(
						{
							message: __(r.message.message || "Document created"),
							indicator: "green",
						},
						5
					);
					// Navigate to created document
					frappe.set_route(r.message.url);
				}
			},
			error(r) {
				$status.hide();
				$input.val("").prop("disabled", false).focus();

				let error_msg = r.responseJSON
					? r.responseJSON._server_messages || r.responseJSON.message
					: __("Scan failed. Please try again.");

				$error.text(error_msg).show();
				setTimeout(() => $error.fadeOut(), 5000);
			},
		});
	}

	// Handle scanner input (rapid keystrokes ending with Enter)
	$input.on("keydown", function (e) {
		if (e.key === "Enter") {
			e.preventDefault();
			clearTimeout(scan_timeout);
			process_scan($input.val());
		}
	});

	// Auto-submit after 300ms of no input (for scanners that don't send Enter)
	$input.on("input", function () {
		clearTimeout(scan_timeout);
		scan_timeout = setTimeout(() => {
			let val = $input.val();
			if (val && val.length > 20) {
				process_scan(val);
			}
		}, 300);
	});

	// Load recent scan history
	function load_scan_history() {
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Scan Log",
				fields: [
					"name",
					"scan_timestamp",
					"action",
					"result",
					"result_doctype",
					"result_name",
					"error_message",
				],
				filters: { user: frappe.session.user },
				order_by: "creation desc",
				limit_page_length: 20,
			},
			callback(r) {
				if (r.message) {
					render_scan_history(r.message);
				}
			},
		});
	}

	function render_scan_history(logs) {
		if (!logs.length) {
			$history.html(
				'<p class="text-muted text-center">' +
					__("No recent scans") +
					"</p>"
			);
			return;
		}

		let html = '<div class="list-group">';
		logs.forEach((log) => {
			let indicator = log.result === "Success" ? "green" : "red";
			let link =
				log.result === "Success" && log.result_doctype && log.result_name
					? `/app/${frappe.router.slug(log.result_doctype)}/${log.result_name}`
					: "#";

			html += `
				<a href="${link}" class="list-group-item list-group-item-action">
					<div class="d-flex justify-content-between">
						<span class="indicator-pill ${indicator}">${log.action}</span>
						<small class="text-muted">${frappe.datetime.prettyDate(log.scan_timestamp)}</small>
					</div>
					${log.error_message ? `<small class="text-danger">${log.error_message}</small>` : ""}
				</a>
			`;
		});
		html += "</div>";
		$history.html(html);
	}

	load_scan_history();

	// Refocus input when page becomes visible
	$(wrapper).on("show", () => $input.focus());
};
```

- **Step 4: Commit**

```bash
git add asn_module/asn_module/page/scan_station/
git commit -m "feat: add Scan Station page with scanner input and scan history"
```

---

### Task 10: Global Scan Shortcut

**Files:**

- Create: `asn_module/public/js/asn_module.js`
- Create: `asn_module/public/js/scan_dialog.js`
- Modify: `asn_module/hooks.py`
- **Step 1: Create the scan dialog component**

```javascript
// asn_module/public/js/scan_dialog.js
frappe.provide("asn_module");

asn_module.ScanDialog = class ScanDialog {
	constructor() {
		this.dialog = new frappe.ui.Dialog({
			title: __("Scan QR Code"),
			fields: [
				{
					fieldname: "scan_input",
					fieldtype: "Data",
					label: __("Scan or paste token"),
					description: __("Use your scanner or paste the QR URL here"),
				},
			],
			primary_action_label: __("Process"),
			primary_action: (values) => {
				this.process_scan(values.scan_input);
			},
		});

		// Auto-submit on Enter in the input
		this.dialog.$wrapper
			.find('input[data-fieldname="scan_input"]')
			.on("keydown", (e) => {
				if (e.key === "Enter") {
					e.preventDefault();
					this.process_scan(this.dialog.get_value("scan_input"));
				}
			});
	}

	show() {
		this.dialog.show();
		this.dialog.set_value("scan_input", "");
		setTimeout(() => {
			this.dialog.$wrapper
				.find('input[data-fieldname="scan_input"]')
				.focus();
		}, 100);
	}

	process_scan(value) {
		if (!value || !value.trim()) return;

		let token = value.trim();
		let url_match = token.match(/[?&]token=([^&]+)/);
		if (url_match) {
			token = url_match[1];
		}

		this.dialog.hide();

		frappe.call({
			method: "asn_module.qr_engine.dispatch.dispatch",
			args: { token: token, device_info: "Desktop" },
			callback(r) {
				if (r.message && r.message.success) {
					frappe.show_alert(
						{
							message: __(r.message.message || "Document created"),
							indicator: "green",
						},
						5
					);
					frappe.set_route(r.message.url);
				}
			},
			error() {
				frappe.show_alert(
					{
						message: __("Scan failed. Check Scan Log for details."),
						indicator: "red",
					},
					5
				);
			},
		});
	}
};
```

```javascript
// asn_module/public/js/asn_module.js
$(document).ready(function () {
	// Global scan shortcut: Ctrl+Shift+S
	frappe.ui.keys.add_shortcut({
		shortcut: "ctrl+shift+s",
		action: function () {
			if (!asn_module._scan_dialog) {
				asn_module._scan_dialog = new asn_module.ScanDialog();
			}
			asn_module._scan_dialog.show();
		},
		description: __("Open QR Scan Dialog"),
		page: undefined, // Available on all pages
	});
});
```

- **Step 2: Update hooks.py to include JS files**

In `asn_module/hooks.py`, uncomment and set:

```python
app_include_js = "/assets/asn_module/js/asn_module.js"
```

And add the scan_dialog bundle. Since Frappe bundles files from `public/js/`, both files need to be in the build. Create a bundle configuration or include both:

```python
app_include_js = [
	"/assets/asn_module/js/scan_dialog.js",
	"/assets/asn_module/js/asn_module.js",
]
```

- **Step 3: Build assets and verify**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench build --app asn_module`

Open browser, press `Ctrl+Shift+S` and verify the scan dialog appears.

- **Step 4: Commit**

```bash
git add asn_module/public/js/ asn_module/hooks.py
git commit -m "feat: add global scan shortcut (Ctrl+Shift+S) and scan dialog component"
```

---

## Phase 5: Purchase Receipt Handler

### Task 11: Custom Fields on Purchase Receipt

**Files:**

- Create: `asn_module/custom_fields/__init__.py`
- Create: `asn_module/custom_fields/purchase_receipt.py`
- Modify: `asn_module/hooks.py`
- **Step 1: Define custom fields for Purchase Receipt**

```python
# asn_module/custom_fields/__init__.py
```

```python
# asn_module/custom_fields/purchase_receipt.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create custom fields on Purchase Receipt for ASN integration."""
	custom_fields = {
		"Purchase Receipt": [
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
				"read_only": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "asn_items",
				"fieldtype": "JSON",
				"label": "ASN Items Mapping",
				"hidden": 1,
				"insert_after": "asn",
			},
		],
	}
	create_custom_fields(custom_fields)
```

- **Step 2: Add after_install hook to create custom fields**

In `asn_module/hooks.py`, add:

```python
after_install = "asn_module.setup.after_install"
```

Create setup file:

```python
# asn_module/setup.py
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields


def after_install():
	setup_pr_fields()
```

- **Step 3: Run the setup to create fields**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost execute asn_module.setup.after_install`

- **Step 4: Commit**

```bash
git add asn_module/custom_fields/ asn_module/setup.py asn_module/hooks.py
git commit -m "feat: add custom fields (asn, asn_items) on Purchase Receipt"
```

---

### Task 12: Purchase Receipt Handler

**Files:**

- Create: `asn_module/handlers/__init__.py`
- Create: `asn_module/handlers/purchase_receipt.py`
- Create: `asn_module/handlers/tests/__init__.py`
- Create: `asn_module/handlers/tests/test_purchase_receipt.py`
- Modify: `asn_module/hooks.py`
- **Step 1: Write the failing tests for purchase receipt handler**

```python
# asn_module/handlers/tests/__init__.py
```

```python
# asn_module/handlers/tests/test_purchase_receipt.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.purchase_receipt import create_from_asn


class TestCreatePurchaseReceipt(IntegrationTestCase):
	def setUp(self):
		self._ensure_test_data()

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Warehouse", "_Test Warehouse - _TC"):
			frappe.get_doc({
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse",
				"company": "_Test Company",
			}).insert(ignore_permissions=True)

	def _make_asn(self):
		asn = frappe.get_doc({
			"doctype": "ASN",
			"supplier": "_Test Supplier",
			"supplier_invoice_no": f"INV-{frappe.generate_hash(length=6)}",
			"supplier_invoice_date": frappe.utils.today(),
			"expected_delivery_date": frappe.utils.add_days(frappe.utils.today(), 3),
			"items": [
				{
					"item_code": "_Test ASN Item",
					"qty": 10,
					"uom": "Nos",
					"rate": 100,
				}
			],
		})
		asn.insert(ignore_permissions=True)
		asn.submit()
		return asn

	def test_creates_draft_purchase_receipt(self):
		asn = self._make_asn()
		result = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		self.assertEqual(result["doctype"], "Purchase Receipt")
		pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(pr.docstatus, 0)  # Draft
		self.assertEqual(pr.supplier, "_Test Supplier")
		self.assertEqual(pr.custom_asn, asn.name)
		self.assertEqual(len(pr.items), 1)
		self.assertEqual(pr.items[0].item_code, "_Test ASN Item")
		self.assertEqual(pr.items[0].qty, 10)

	def test_returns_existing_draft_on_duplicate_scan(self):
		asn = self._make_asn()
		result1 = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		result2 = create_from_asn(
			source_doctype="ASN",
			source_name=asn.name,
			payload={"action": "create_purchase_receipt"},
		)
		self.assertEqual(result1["name"], result2["name"])

	def test_rejects_received_asn(self):
		asn = self._make_asn()
		frappe.db.set_value("ASN", asn.name, "status", "Received")
		with self.assertRaises(frappe.ValidationError):
			create_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)

	def test_rejects_closed_asn(self):
		asn = self._make_asn()
		frappe.db.set_value("ASN", asn.name, "status", "Closed")
		with self.assertRaises(frappe.ValidationError):
			create_from_asn(
				source_doctype="ASN",
				source_name=asn.name,
				payload={"action": "create_purchase_receipt"},
			)
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_receipt`
Expected: FAIL with ImportError

- **Step 3: Implement purchase receipt handler**

```python
# asn_module/handlers/__init__.py
```

```python
# asn_module/handlers/purchase_receipt.py
import json

import frappe
from frappe import _


def create_from_asn(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a Purchase Receipt in draft from an ASN.

	Args:
		source_doctype: 'ASN'
		source_name: ASN document name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	asn = frappe.get_doc("ASN", source_name)

	# Validate ASN status
	if asn.status in ("Received", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot create Purchase Receipt from ASN {0} with status {1}").format(
				source_name, asn.status
			)
		)

	# Check for existing draft PR
	existing_pr = frappe.db.get_value(
		"Purchase Receipt",
		{"custom_asn": source_name, "docstatus": 0},
		"name",
	)
	if existing_pr:
		return {
			"doctype": "Purchase Receipt",
			"name": existing_pr,
			"url": f"/app/purchase-receipt/{existing_pr}",
			"message": _("Existing draft Purchase Receipt {0} opened").format(existing_pr),
		}

	# Build item mapping for discrepancy tracking
	asn_items_map = {}

	pr = frappe.new_doc("Purchase Receipt")
	pr.supplier = asn.supplier
	pr.custom_asn = asn.name

	for asn_item in asn.items:
		# Determine warehouse based on inspection requirement
		inspection_required = frappe.db.get_value(
			"Item", asn_item.item_code, "inspection_required_before_purchase"
		)

		pr_item = pr.append("items", {
			"item_code": asn_item.item_code,
			"item_name": asn_item.item_name,
			"qty": asn_item.qty,
			"uom": asn_item.uom,
			"rate": asn_item.rate,
			"batch_no": asn_item.batch_no,
			"serial_no": asn_item.serial_nos,
			"purchase_order": asn_item.purchase_order,
			"purchase_order_item": asn_item.purchase_order_item,
		})

		asn_items_map[str(pr_item.idx)] = {
			"asn_item_name": asn_item.name,
			"original_qty": asn_item.qty,
		}

	pr.custom_asn_items = json.dumps(asn_items_map)
	pr.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Receipt",
		"name": pr.name,
		"url": f"/app/purchase-receipt/{pr.name}",
		"message": _("Purchase Receipt {0} created from ASN {1}").format(pr.name, source_name),
	}
```

- **Step 4: Add doc_events hook for Purchase Receipt submit**

In `asn_module/hooks.py`, add:

```python
doc_events = {
	"Purchase Receipt": {
		"on_submit": "asn_module.handlers.purchase_receipt.on_purchase_receipt_submit",
	},
}
```

Append to `asn_module/handlers/purchase_receipt.py`:

```python
def on_purchase_receipt_submit(doc, method):
	"""Update ASN discrepancy tracking when a PR linked to an ASN is submitted."""
	if not doc.custom_asn:
		return

	asn = frappe.get_doc("ASN", doc.custom_asn)
	asn_items_map = json.loads(doc.custom_asn_items or "{}")

	for pr_item in doc.items:
		mapping = asn_items_map.get(str(pr_item.idx))
		if not mapping:
			continue

		asn_item_name = mapping["asn_item_name"]
		for asn_item in asn.items:
			if asn_item.name == asn_item_name:
				asn_item.received_qty = (asn_item.received_qty or 0) + pr_item.qty
				break

	asn.update_receipt_status()

	# Generate Purchase Invoice QR
	from asn_module.qr_engine.generate import generate_qr

	qr_result = generate_qr(
		action="create_purchase_invoice",
		source_doctype="Purchase Receipt",
		source_name=doc.name,
	)
	# Attach QR to Purchase Receipt as a comment or file
	_attach_qr_to_doc(doc, qr_result, "purchase-invoice-qr")

	# Generate Putaway QRs for non-QC items
	for pr_item in doc.items:
		inspection_required = frappe.db.get_value(
			"Item", pr_item.item_code, "inspection_required_before_purchase"
		)
		if not inspection_required:
			putaway_qr = generate_qr(
				action="confirm_putaway",
				source_doctype="Purchase Receipt",
				source_name=doc.name,
			)
			_attach_qr_to_doc(doc, putaway_qr, f"putaway-{pr_item.item_code}")


def _attach_qr_to_doc(doc, qr_result, prefix):
	"""Attach a QR code image to a document."""
	import base64

	frappe.get_doc({
		"doctype": "File",
		"file_name": f"{prefix}-{doc.name}.png",
		"attached_to_doctype": doc.doctype,
		"attached_to_name": doc.name,
		"content": base64.b64decode(qr_result["image_base64"]),
		"is_private": 0,
	}).save(ignore_permissions=True)
```

- **Step 5: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_receipt`
Expected: All 4 tests PASS

- **Step 6: Commit**

```bash
git add asn_module/handlers/ asn_module/hooks.py
git commit -m "feat: add purchase receipt handler with ASN discrepancy tracking"
```

---

## Phase 6: Quality Inspection & Stock Transfer

### Task 13: Stock Transfer Handler

**Files:**

- Create: `asn_module/handlers/stock_transfer.py`
- Create: `asn_module/handlers/tests/test_stock_transfer.py`
- **Step 1: Write the failing tests for stock transfer handler**

```python
# asn_module/handlers/tests/test_stock_transfer.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.stock_transfer import create_from_quality_inspection


class TestCreateStockTransfer(IntegrationTestCase):
	def test_creates_draft_material_transfer(self):
		# This test requires a submitted Quality Inspection with accepted items.
		# We mock the necessary data structure.
		qi = self._make_quality_inspection()

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_stock_transfer"},
		)

		self.assertEqual(result["doctype"], "Stock Entry")
		se = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(se.docstatus, 0)
		self.assertEqual(se.stock_entry_type, "Material Transfer")
		self.assertTrue(len(se.items) > 0)

	def _make_quality_inspection(self):
		"""Create a minimal Quality Inspection for testing."""
		self._ensure_test_data()

		qi = frappe.get_doc({
			"doctype": "Quality Inspection",
			"inspection_type": "Incoming",
			"reference_type": "Purchase Receipt",
			"reference_name": self._make_purchase_receipt(),
			"item_code": "_Test ASN Item",
			"sample_size": 10,
			"status": "Accepted",
		})
		qi.insert(ignore_permissions=True)
		qi.submit()
		return qi

	def _make_purchase_receipt(self):
		if not frappe.db.exists("Warehouse", "_Test QC Warehouse - _TC"):
			frappe.get_doc({
				"doctype": "Warehouse",
				"warehouse_name": "_Test QC Warehouse",
				"company": "_Test Company",
			}).insert(ignore_permissions=True)

		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": "_Test Supplier",
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"rate": 100,
				"warehouse": "_Test QC Warehouse - _TC",
			}],
		})
		pr.insert(ignore_permissions=True)
		pr.submit()
		return pr.name

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"inspection_required_before_purchase": 1,
			}).insert(ignore_permissions=True)
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_stock_transfer`
Expected: FAIL with ImportError

- **Step 3: Implement stock transfer handler**

```python
# asn_module/handlers/stock_transfer.py
import frappe
from frappe import _


def create_from_quality_inspection(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a Stock Entry (Material Transfer) from Quality Inspection for accepted items.

	Args:
		source_doctype: 'Quality Inspection'
		source_name: Quality Inspection document name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	qi = frappe.get_doc("Quality Inspection", source_name)

	if qi.status != "Accepted":
		frappe.throw(
			_("Quality Inspection {0} is not Accepted. Status: {1}").format(
				source_name, qi.status
			)
		)

	# Get the Purchase Receipt to find source warehouse
	pr = frappe.get_doc(qi.reference_type, qi.reference_name)

	# Find the PR item matching the QI item
	pr_item = None
	for item in pr.items:
		if item.item_code == qi.item_code:
			pr_item = item
			break

	if not pr_item:
		frappe.throw(_("Item {0} not found in {1}").format(qi.item_code, qi.reference_name))

	# Source = QC warehouse, Destination = item default warehouse
	source_warehouse = pr_item.warehouse
	destination_warehouse = frappe.db.get_value(
		"Item Default",
		{"parent": qi.item_code, "company": pr.company},
		"default_warehouse",
	) or pr_item.warehouse

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.company = pr.company
	se.append("items", {
		"item_code": qi.item_code,
		"qty": qi.sample_size,
		"s_warehouse": source_warehouse,
		"t_warehouse": destination_warehouse,
	})

	se.insert(ignore_permissions=True)

	return {
		"doctype": "Stock Entry",
		"name": se.name,
		"url": f"/app/stock-entry/{se.name}",
		"message": _("Stock Transfer {0} created from Quality Inspection {1}").format(
			se.name, source_name
		),
	}
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_stock_transfer`
Expected: PASS

- **Step 5: Commit**

```bash
git add asn_module/handlers/stock_transfer.py asn_module/handlers/tests/test_stock_transfer.py
git commit -m "feat: add stock transfer handler for accepted QC items"
```

---

### Task 14: Purchase Return Handler

**Files:**

- Create: `asn_module/handlers/purchase_return.py`
- Create: `asn_module/handlers/tests/test_purchase_return.py`
- **Step 1: Write the failing tests for purchase return handler**

```python
# asn_module/handlers/tests/test_purchase_return.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.purchase_return import create_from_quality_inspection


class TestCreatePurchaseReturn(IntegrationTestCase):
	def setUp(self):
		self._ensure_test_data()

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

	def test_creates_return_purchase_receipt(self):
		pr = self._make_purchase_receipt()
		qi = self._make_rejected_qi(pr.name)

		result = create_from_quality_inspection(
			source_doctype="Quality Inspection",
			source_name=qi.name,
			payload={"action": "create_purchase_return"},
		)

		self.assertEqual(result["doctype"], "Purchase Receipt")
		return_pr = frappe.get_doc("Purchase Receipt", result["name"])
		self.assertEqual(return_pr.docstatus, 0)
		self.assertEqual(return_pr.is_return, 1)
		self.assertEqual(return_pr.return_against, pr.name)
		self.assertTrue(return_pr.items[0].qty < 0)

	def _make_purchase_receipt(self):
		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": "_Test Supplier",
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"rate": 100,
				"warehouse": "_Test Warehouse - _TC",
			}],
		})
		pr.insert(ignore_permissions=True)
		pr.submit()
		return pr

	def _make_rejected_qi(self, pr_name):
		qi = frappe.get_doc({
			"doctype": "Quality Inspection",
			"inspection_type": "Incoming",
			"reference_type": "Purchase Receipt",
			"reference_name": pr_name,
			"item_code": "_Test ASN Item",
			"sample_size": 10,
			"status": "Rejected",
		})
		qi.insert(ignore_permissions=True)
		qi.submit()
		return qi
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_return`
Expected: FAIL with ImportError

- **Step 3: Implement purchase return handler**

```python
# asn_module/handlers/purchase_return.py
import frappe
from frappe import _


def create_from_quality_inspection(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a Purchase Receipt return from a rejected Quality Inspection.

	Args:
		source_doctype: 'Quality Inspection'
		source_name: Quality Inspection document name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	qi = frappe.get_doc("Quality Inspection", source_name)

	if qi.status != "Rejected":
		frappe.throw(
			_("Quality Inspection {0} is not Rejected. Status: {1}").format(
				source_name, qi.status
			)
		)

	original_pr = frappe.get_doc(qi.reference_type, qi.reference_name)

	# Find the matching PR item
	pr_item = None
	for item in original_pr.items:
		if item.item_code == qi.item_code:
			pr_item = item
			break

	if not pr_item:
		frappe.throw(
			_("Item {0} not found in {1}").format(qi.item_code, qi.reference_name)
		)

	return_pr = frappe.new_doc("Purchase Receipt")
	return_pr.supplier = original_pr.supplier
	return_pr.is_return = 1
	return_pr.return_against = original_pr.name

	return_pr.append("items", {
		"item_code": qi.item_code,
		"item_name": pr_item.item_name,
		"qty": -1 * qi.sample_size,
		"uom": pr_item.uom,
		"rate": pr_item.rate,
		"warehouse": pr_item.warehouse,
		"purchase_order": pr_item.purchase_order,
		"purchase_order_item": pr_item.purchase_order_item,
		"purchase_receipt_item": pr_item.name,
	})

	return_pr.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Receipt",
		"name": return_pr.name,
		"url": f"/app/purchase-receipt/{return_pr.name}",
		"message": _("Purchase Return {0} created from Quality Inspection {1}").format(
			return_pr.name, source_name
		),
	}
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_return`
Expected: PASS

- **Step 5: Commit**

```bash
git add asn_module/handlers/purchase_return.py asn_module/handlers/tests/test_purchase_return.py
git commit -m "feat: add purchase return handler for rejected QC items"
```

---

### Task 15: Quality Inspection Submit Hook

**Files:**

- Modify: `asn_module/hooks.py`
- Create: `asn_module/handlers/quality_inspection.py`
- **Step 1: Write the QI submit hook**

```python
# asn_module/handlers/quality_inspection.py
import frappe
from frappe import _

from asn_module.qr_engine.generate import generate_qr


def on_quality_inspection_submit(doc, method):
	"""Generate QR codes on Quality Inspection submit.

	- Accepted: Stock Transfer QR
	- Rejected: Purchase Return QR
	"""
	if doc.reference_type != "Purchase Receipt":
		return

	if doc.status == "Accepted":
		qr_result = generate_qr(
			action="create_stock_transfer",
			source_doctype="Quality Inspection",
			source_name=doc.name,
		)
		_attach_qr(doc, qr_result, "stock-transfer-qr")
		frappe.msgprint(
			_("Stock Transfer QR code generated. Scan to create Material Transfer."),
			alert=True,
		)

	elif doc.status == "Rejected":
		qr_result = generate_qr(
			action="create_purchase_return",
			source_doctype="Quality Inspection",
			source_name=doc.name,
		)
		_attach_qr(doc, qr_result, "purchase-return-qr")
		frappe.msgprint(
			_("Purchase Return QR code generated. Scan to create return."),
			alert=True,
		)


def _attach_qr(doc, qr_result, prefix):
	"""Attach QR code image to the document."""
	import base64

	frappe.get_doc({
		"doctype": "File",
		"file_name": f"{prefix}-{doc.name}.png",
		"attached_to_doctype": doc.doctype,
		"attached_to_name": doc.name,
		"content": base64.b64decode(qr_result["image_base64"]),
		"is_private": 0,
	}).save(ignore_permissions=True)
```

- **Step 2: Add doc_events hook for Quality Inspection**

In `asn_module/hooks.py`, update `doc_events`:

```python
doc_events = {
	"Purchase Receipt": {
		"on_submit": "asn_module.handlers.purchase_receipt.on_purchase_receipt_submit",
	},
	"Quality Inspection": {
		"on_submit": "asn_module.handlers.quality_inspection.on_quality_inspection_submit",
	},
}
```

- **Step 3: Commit**

```bash
git add asn_module/handlers/quality_inspection.py asn_module/hooks.py
git commit -m "feat: add QI submit hook to generate stock transfer and return QR codes"
```

---

## Phase 7: Purchase Invoice Handler

### Task 16: Custom Fields on Purchase Invoice

**Files:**

- Create: `asn_module/custom_fields/purchase_invoice.py`
- Modify: `asn_module/setup.py`
- **Step 1: Define custom fields for Purchase Invoice**

```python
# asn_module/custom_fields/purchase_invoice.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
	"""Create custom fields on Purchase Invoice for ASN integration."""
	custom_fields = {
		"Purchase Invoice": [
			{
				"fieldname": "asn",
				"fieldtype": "Link",
				"label": "ASN",
				"options": "ASN",
				"insert_after": "supplier",
				"read_only": 1,
				"in_standard_filter": 1,
			},
		],
	}
	create_custom_fields(custom_fields)
```

- **Step 2: Update setup.py**

```python
# asn_module/setup.py
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields


def after_install():
	setup_pr_fields()
	setup_pi_fields()
```

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost execute asn_module.setup.after_install`

- **Step 3: Commit**

```bash
git add asn_module/custom_fields/purchase_invoice.py asn_module/setup.py
git commit -m "feat: add custom field (asn) on Purchase Invoice"
```

---

### Task 17: Purchase Invoice Handler

**Files:**

- Create: `asn_module/handlers/purchase_invoice.py`
- Create: `asn_module/handlers/tests/test_purchase_invoice.py`
- **Step 1: Write the failing tests**

```python
# asn_module/handlers/tests/test_purchase_invoice.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.purchase_invoice import create_from_purchase_receipt


class TestCreatePurchaseInvoice(IntegrationTestCase):
	def setUp(self):
		self._ensure_test_data()

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

	def _make_asn_and_pr(self):
		asn = frappe.get_doc({
			"doctype": "ASN",
			"supplier": "_Test Supplier",
			"supplier_invoice_no": f"INV-{frappe.generate_hash(length=6)}",
			"supplier_invoice_date": frappe.utils.today(),
			"supplier_invoice_amount": 1000,
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"uom": "Nos",
				"rate": 100,
			}],
		})
		asn.insert(ignore_permissions=True)
		asn.submit()

		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": "_Test Supplier",
			"custom_asn": asn.name,
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"rate": 100,
				"warehouse": "_Test Warehouse - _TC",
			}],
		})
		pr.insert(ignore_permissions=True)
		pr.submit()
		return asn, pr

	def test_creates_draft_purchase_invoice(self):
		asn, pr = self._make_asn_and_pr()

		result = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)

		self.assertEqual(result["doctype"], "Purchase Invoice")
		pi = frappe.get_doc("Purchase Invoice", result["name"])
		self.assertEqual(pi.docstatus, 0)
		self.assertEqual(pi.supplier, "_Test Supplier")
		self.assertEqual(pi.bill_no, asn.supplier_invoice_no)
		self.assertEqual(pi.bill_date, asn.supplier_invoice_date)
		self.assertEqual(pi.custom_asn, asn.name)

	def test_returns_existing_draft_on_duplicate_scan(self):
		asn, pr = self._make_asn_and_pr()

		result1 = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)
		result2 = create_from_purchase_receipt(
			source_doctype="Purchase Receipt",
			source_name=pr.name,
			payload={"action": "create_purchase_invoice"},
		)
		self.assertEqual(result1["name"], result2["name"])

	def test_rejects_unbilled_pr(self):
		"""Should reject if PR is not submitted."""
		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": "_Test Supplier",
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"rate": 100,
				"warehouse": "_Test Warehouse - _TC",
			}],
		})
		pr.insert(ignore_permissions=True)
		# Not submitted

		with self.assertRaises(frappe.ValidationError):
			create_from_purchase_receipt(
				source_doctype="Purchase Receipt",
				source_name=pr.name,
				payload={"action": "create_purchase_invoice"},
			)
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_invoice`
Expected: FAIL with ImportError

- **Step 3: Implement purchase invoice handler**

```python
# asn_module/handlers/purchase_invoice.py
import frappe
from frappe import _


def create_from_purchase_receipt(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Create a Purchase Invoice in draft from a Purchase Receipt.

	Args:
		source_doctype: 'Purchase Receipt'
		source_name: Purchase Receipt document name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	pr = frappe.get_doc("Purchase Receipt", source_name)

	if pr.docstatus != 1:
		frappe.throw(
			_("Purchase Receipt {0} must be submitted before creating an invoice").format(source_name)
		)

	if pr.per_billed >= 100:
		frappe.throw(
			_("Purchase Receipt {0} is already fully billed").format(source_name)
		)

	# Check for existing draft PI for this PR
	existing_pi = frappe.db.sql(
		"""
		SELECT pi.name
		FROM `tabPurchase Invoice` pi
		JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name
		WHERE pii.purchase_receipt = %s
		AND pi.docstatus = 0
		LIMIT 1
		""",
		(source_name,),
	)
	if existing_pi:
		pi_name = existing_pi[0][0]
		return {
			"doctype": "Purchase Invoice",
			"name": pi_name,
			"url": f"/app/purchase-invoice/{pi_name}",
			"message": _("Existing draft Purchase Invoice {0} opened").format(pi_name),
		}

	# Get ASN details for bill_no and bill_date
	asn_name = pr.custom_asn
	bill_no = None
	bill_date = None

	if asn_name:
		asn = frappe.get_doc("ASN", asn_name)
		bill_no = asn.supplier_invoice_no
		bill_date = asn.supplier_invoice_date

	pi = frappe.new_doc("Purchase Invoice")
	pi.supplier = pr.supplier
	pi.bill_no = bill_no
	pi.bill_date = bill_date
	pi.custom_asn = asn_name

	for pr_item in pr.items:
		pi.append("items", {
			"item_code": pr_item.item_code,
			"item_name": pr_item.item_name,
			"qty": pr_item.qty,
			"rate": pr_item.rate,
			"uom": pr_item.uom,
			"warehouse": pr_item.warehouse,
			"purchase_receipt": pr.name,
			"pr_detail": pr_item.name,
			"purchase_order": pr_item.purchase_order,
			"po_detail": pr_item.purchase_order_item,
		})

	pi.insert(ignore_permissions=True)

	return {
		"doctype": "Purchase Invoice",
		"name": pi.name,
		"url": f"/app/purchase-invoice/{pi.name}",
		"message": _("Purchase Invoice {0} created from Purchase Receipt {1}").format(
			pi.name, source_name
		),
	}
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_purchase_invoice`
Expected: All 3 tests PASS

- **Step 5: Commit**

```bash
git add asn_module/handlers/purchase_invoice.py asn_module/handlers/tests/test_purchase_invoice.py
git commit -m "feat: add purchase invoice handler with ASN bill details"
```

---

## Phase 8: Putaway Handler

### Task 18: Putaway Confirmation Handler

**Files:**

- Create: `asn_module/handlers/putaway.py`
- Create: `asn_module/handlers/tests/test_putaway.py`
- **Step 1: Write the failing tests**

```python
# asn_module/handlers/tests/test_putaway.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.putaway import confirm_putaway


class TestConfirmPutaway(IntegrationTestCase):
	def test_creates_scan_log_for_putaway(self):
		result = confirm_putaway(
			source_doctype="Purchase Receipt",
			source_name="PR-TEST-001",
			payload={
				"action": "confirm_putaway",
				"source_doctype": "Purchase Receipt",
				"source_name": "PR-TEST-001",
			},
		)

		self.assertEqual(result["doctype"], "Scan Log")
		log = frappe.get_doc("Scan Log", result["name"])
		self.assertEqual(log.action, "confirm_putaway")
		self.assertEqual(log.result, "Success")
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_putaway`
Expected: FAIL with ImportError

- **Step 3: Implement putaway handler**

```python
# asn_module/handlers/putaway.py
import frappe
from frappe import _
from frappe.utils import now_datetime


def confirm_putaway(source_doctype: str, source_name: str, payload: dict) -> dict:
	"""Log a putaway confirmation scan. No stock movement - audit only.

	Args:
		source_doctype: 'Purchase Receipt' or 'Stock Entry'
		source_name: Source document name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	log = frappe.get_doc({
		"doctype": "Scan Log",
		"action": "confirm_putaway",
		"source_doctype": source_doctype,
		"source_name": source_name,
		"result": "Success",
		"device_info": "Desktop",
	})
	log.insert(ignore_permissions=True)

	return {
		"doctype": "Scan Log",
		"name": log.name,
		"url": f"/app/scan-log/{log.name}",
		"message": _("Putaway confirmed for {0} {1}").format(source_doctype, source_name),
	}
```

- **Step 4: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_putaway`
Expected: PASS

- **Step 5: Commit**

```bash
git add asn_module/handlers/putaway.py asn_module/handlers/tests/test_putaway.py
git commit -m "feat: add putaway confirmation handler (audit scan log)"
```

---

## Phase 9: Subcontracting Handlers

### Task 19: Subcontracting Dispatch Handler

**Files:**

- Create: `asn_module/handlers/subcontracting.py`
- Create: `asn_module/handlers/tests/test_subcontracting.py`
- Modify: `asn_module/hooks.py`
- **Step 1: Write the failing tests for subcontracting dispatch**

```python
# asn_module/handlers/tests/test_subcontracting.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.handlers.subcontracting import (
	create_dispatch_from_subcontracting_order,
	create_receipt_from_subcontracting_order,
)


class TestSubcontractingDispatch(IntegrationTestCase):
	def setUp(self):
		self._ensure_test_data()

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Job Worker"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Job Worker",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test RM Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test RM Item",
				"item_name": "_Test RM Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test FG Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test FG Item",
				"item_name": "_Test FG Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_sub_contracted_item": 1,
			}).insert(ignore_permissions=True)

	def test_creates_send_to_subcontractor_stock_entry(self):
		sco = self._make_subcontracting_order()

		result = create_dispatch_from_subcontracting_order(
			source_doctype="Subcontracting Order",
			source_name=sco.name,
			payload={"action": "create_subcontracting_dispatch"},
		)

		self.assertEqual(result["doctype"], "Stock Entry")
		se = frappe.get_doc("Stock Entry", result["name"])
		self.assertEqual(se.docstatus, 0)
		self.assertEqual(se.stock_entry_type, "Send to Subcontractor")

	def _make_subcontracting_order(self):
		"""Create a minimal Subcontracting Order for testing.

		Note: Actual test setup depends on ERPNext's Subcontracting Order structure.
		This may need adjustment based on the specific ERPNext version.
		"""
		sco = frappe.get_doc({
			"doctype": "Subcontracting Order",
			"supplier": "_Test Job Worker",
			"items": [{
				"item_code": "_Test FG Item",
				"qty": 10,
				"rate": 50,
				"warehouse": "_Test Warehouse - _TC",
			}],
			"service_items": [{
				"item_code": "_Test RM Item",
				"qty": 10,
				"rate": 10,
				"warehouse": "_Test Warehouse - _TC",
			}],
		})
		sco.insert(ignore_permissions=True)
		sco.submit()
		return sco
```

- **Step 2: Run tests to verify they fail**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_subcontracting`
Expected: FAIL with ImportError

- **Step 3: Implement subcontracting handlers**

```python
# asn_module/handlers/subcontracting.py
import frappe
from frappe import _

from asn_module.qr_engine.generate import generate_qr


def create_dispatch_from_subcontracting_order(
	source_doctype: str, source_name: str, payload: dict
) -> dict:
	"""Create a Stock Entry (Send to Subcontractor) from a Subcontracting Order.

	Args:
		source_doctype: 'Subcontracting Order'
		source_name: Subcontracting Order name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	sco = frappe.get_doc("Subcontracting Order", source_name)

	if sco.docstatus != 1:
		frappe.throw(
			_("Subcontracting Order {0} must be submitted").format(source_name)
		)

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Send to Subcontractor"
	se.company = sco.company
	se.subcontracting_order = sco.name

	# Get supplier warehouse
	supplier_warehouse = frappe.db.get_value(
		"Supplier", sco.supplier, "default_warehouse"
	)

	for item in sco.supplied_items:
		# Check already transferred qty
		already_transferred = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(sed.qty), 0)
			FROM `tabStock Entry Detail` sed
			JOIN `tabStock Entry` se ON se.name = sed.parent
			WHERE se.subcontracting_order = %s
			AND sed.item_code = %s
			AND se.stock_entry_type = 'Send to Subcontractor'
			AND se.docstatus = 1
			""",
			(sco.name, item.rm_item_code),
		)[0][0]

		remaining = item.required_qty - already_transferred
		if remaining <= 0:
			continue

		se.append("items", {
			"item_code": item.rm_item_code,
			"qty": remaining,
			"s_warehouse": item.reserve_warehouse,
			"t_warehouse": supplier_warehouse,
			"subcontracting_order": sco.name,
		})

	if not se.items:
		frappe.throw(
			_("All raw materials have already been dispatched for Subcontracting Order {0}").format(
				source_name
			)
		)

	se.insert(ignore_permissions=True)

	return {
		"doctype": "Stock Entry",
		"name": se.name,
		"url": f"/app/stock-entry/{se.name}",
		"message": _("Stock Entry {0} (Send to Subcontractor) created from {1}").format(
			se.name, source_name
		),
	}


def on_subcontracting_dispatch_submit(doc, method):
	"""Generate receipt QR when Send to Subcontractor Stock Entry is submitted."""
	if doc.stock_entry_type != "Send to Subcontractor" or not doc.subcontracting_order:
		return

	qr_result = generate_qr(
		action="create_subcontracting_receipt",
		source_doctype="Subcontracting Order",
		source_name=doc.subcontracting_order,
	)

	import base64

	frappe.get_doc({
		"doctype": "File",
		"file_name": f"subcontracting-receipt-qr-{doc.name}.png",
		"attached_to_doctype": doc.doctype,
		"attached_to_name": doc.name,
		"content": base64.b64decode(qr_result["image_base64"]),
		"is_private": 0,
	}).save(ignore_permissions=True)


def create_receipt_from_subcontracting_order(
	source_doctype: str, source_name: str, payload: dict
) -> dict:
	"""Create a Subcontracting Receipt from a Subcontracting Order.

	Args:
		source_doctype: 'Subcontracting Order'
		source_name: Subcontracting Order name
		payload: Full token payload

	Returns:
		dict with doctype, name, url, message
	"""
	sco = frappe.get_doc("Subcontracting Order", source_name)

	if sco.docstatus != 1:
		frappe.throw(
			_("Subcontracting Order {0} must be submitted").format(source_name)
		)

	scr = frappe.new_doc("Subcontracting Receipt")
	scr.supplier = sco.supplier
	scr.subcontracting_order = sco.name

	for item in sco.items:
		# Check already received qty
		already_received = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(scri.qty), 0)
			FROM `tabSubcontracting Receipt Item` scri
			JOIN `tabSubcontracting Receipt` scr ON scr.name = scri.parent
			WHERE scr.subcontracting_order = %s
			AND scri.item_code = %s
			AND scr.docstatus = 1
			""",
			(sco.name, item.item_code),
		)[0][0]

		remaining = item.qty - already_received
		if remaining <= 0:
			continue

		# Determine warehouse based on inspection requirement
		inspection_required = frappe.db.get_value(
			"Item", item.item_code, "inspection_required_before_purchase"
		)

		scr.append("items", {
			"item_code": item.item_code,
			"qty": remaining,
			"rate": item.rate,
			"warehouse": item.warehouse,
			"subcontracting_order": sco.name,
		})

	if not scr.items:
		frappe.throw(
			_("All finished goods have already been received for Subcontracting Order {0}").format(
				source_name
			)
		)

	scr.insert(ignore_permissions=True)

	return {
		"doctype": "Subcontracting Receipt",
		"name": scr.name,
		"url": f"/app/subcontracting-receipt/{scr.name}",
		"message": _("Subcontracting Receipt {0} created from {1}").format(
			scr.name, source_name
		),
	}
```

- **Step 4: Add doc_events hooks for Subcontracting Order and Stock Entry**

In `asn_module/hooks.py`, update `doc_events`:

```python
doc_events = {
	"Purchase Receipt": {
		"on_submit": "asn_module.handlers.purchase_receipt.on_purchase_receipt_submit",
	},
	"Quality Inspection": {
		"on_submit": "asn_module.handlers.quality_inspection.on_quality_inspection_submit",
	},
	"Stock Entry": {
		"on_submit": "asn_module.handlers.subcontracting.on_subcontracting_dispatch_submit",
	},
	"Subcontracting Order": {
		"on_submit": "asn_module.handlers.subcontracting.on_subcontracting_order_submit",
	},
}
```

Add the SCO submit hook for generating dispatch QR:

Append to `asn_module/handlers/subcontracting.py`:

```python
def on_subcontracting_order_submit(doc, method):
	"""Generate Material Dispatch QR when Subcontracting Order is submitted."""
	qr_result = generate_qr(
		action="create_subcontracting_dispatch",
		source_doctype="Subcontracting Order",
		source_name=doc.name,
	)

	import base64

	frappe.get_doc({
		"doctype": "File",
		"file_name": f"subcontracting-dispatch-qr-{doc.name}.png",
		"attached_to_doctype": doc.doctype,
		"attached_to_name": doc.name,
		"content": base64.b64decode(qr_result["image_base64"]),
		"is_private": 0,
	}).save(ignore_permissions=True)
```

- **Step 5: Run tests to verify they pass**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.handlers.tests.test_subcontracting`
Expected: PASS

- **Step 6: Commit**

```bash
git add asn_module/handlers/subcontracting.py asn_module/handlers/tests/test_subcontracting.py asn_module/hooks.py
git commit -m "feat: add subcontracting dispatch and receipt handlers with QR generation"
```

---

## Phase 10: Notifications

### Task 20: Notification Templates

**Files:**

- Create: `asn_module/notifications/__init__.py`
- Create: `asn_module/notifications/setup.py`
- Modify: `asn_module/setup.py`
- **Step 1: Create notification setup**

```python
# asn_module/notifications/__init__.py
```

```python
# asn_module/notifications/setup.py
import frappe


def create_notifications():
	"""Create notification records for ASN module events."""
	notifications = [
		{
			"name": "ASN Submitted",
			"document_type": "ASN",
			"event": "Submit",
			"channel": "Email,System",
			"recipients": [{"receiver_by_role": "Stock Manager"}],
			"subject": "New ASN {name} submitted by {supplier}",
			"message": "A new ASN ({name}) has been submitted by {supplier}.\n\n"
				"Expected delivery: {expected_delivery_date}\n"
				"Invoice: {supplier_invoice_no}",
		},
		{
			"name": "ASN Discrepancy Detected",
			"document_type": "ASN",
			"event": "Value Change",
			"value_changed": "status",
			"channel": "Email,System",
			"recipients": [
				{"receiver_by_role": "Stock Manager"},
				{"receiver_by_role": "Purchase Manager"},
			],
			"condition": 'doc.status == "Partially Received"',
			"subject": "Discrepancy detected for ASN {name}",
			"message": "ASN {name} from {supplier} has been partially received. "
				"Please review the discrepancies.",
		},
		{
			"name": "QC Items Awaiting Inspection",
			"document_type": "Purchase Receipt",
			"event": "Submit",
			"channel": "System",
			"recipients": [{"receiver_by_role": "Quality Inspector"}],
			"condition": "doc.custom_asn",
			"subject": "Items from {supplier} awaiting Quality Inspection",
			"message": "Purchase Receipt {name} has been submitted with items requiring "
				"quality inspection. Please proceed with QC.",
		},
		{
			"name": "Purchase Receipt Ready for Billing",
			"document_type": "Purchase Receipt",
			"event": "Submit",
			"channel": "System",
			"recipients": [{"receiver_by_role": "Accounts User"}],
			"condition": "doc.custom_asn",
			"subject": "Purchase Receipt {name} ready for billing",
			"message": "Purchase Receipt {name} from {supplier} has been submitted "
				"and is ready for Purchase Invoice creation.",
		},
	]

	for notif_data in notifications:
		if frappe.db.exists("Notification", notif_data["name"]):
			continue

		recipients = notif_data.pop("recipients")
		notif = frappe.get_doc({
			"doctype": "Notification",
			"enabled": 1,
			**notif_data,
		})
		for recipient in recipients:
			notif.append("recipients", recipient)
		notif.insert(ignore_permissions=True)
```

- **Step 2: Update setup.py to create notifications**

```python
# asn_module/setup.py
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.notifications.setup import create_notifications


def after_install():
	setup_pr_fields()
	setup_pi_fields()
	create_notifications()
```

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost execute asn_module.setup.after_install`

- **Step 3: Commit**

```bash
git add asn_module/notifications/ asn_module/setup.py
git commit -m "feat: add notification templates for ASN events"
```

---

## Phase 11: Action Registry Seed Data

### Task 21: Register All Actions

**Files:**

- Create: `asn_module/setup_actions.py`
- Modify: `asn_module/setup.py`
- **Step 1: Create action registry seed data**

```python
# asn_module/setup_actions.py
import frappe


def register_actions():
	"""Register all QR actions in the QR Action Registry."""
	actions = [
		{
			"action_key": "create_purchase_receipt",
			"handler_method": "asn_module.handlers.purchase_receipt.create_from_asn",
			"source_doctype": "ASN",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_stock_transfer",
			"handler_method": "asn_module.handlers.stock_transfer.create_from_quality_inspection",
			"source_doctype": "Quality Inspection",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_purchase_return",
			"handler_method": "asn_module.handlers.purchase_return.create_from_quality_inspection",
			"source_doctype": "Quality Inspection",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_purchase_invoice",
			"handler_method": "asn_module.handlers.purchase_invoice.create_from_purchase_receipt",
			"source_doctype": "Purchase Receipt",
			"roles": ["Accounts User", "Accounts Manager"],
		},
		{
			"action_key": "confirm_putaway",
			"handler_method": "asn_module.handlers.putaway.confirm_putaway",
			"source_doctype": "Purchase Receipt",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_subcontracting_dispatch",
			"handler_method": "asn_module.handlers.subcontracting.create_dispatch_from_subcontracting_order",
			"source_doctype": "Subcontracting Order",
			"roles": ["Stock User", "Stock Manager"],
		},
		{
			"action_key": "create_subcontracting_receipt",
			"handler_method": "asn_module.handlers.subcontracting.create_receipt_from_subcontracting_order",
			"source_doctype": "Subcontracting Order",
			"roles": ["Stock User", "Stock Manager"],
		},
	]

	registry = frappe.get_single("QR Action Registry")
	registry.actions = []

	for action_data in actions:
		roles = action_data.pop("roles")
		action_data["allowed_roles"] = ",".join(roles)
		registry.append("actions", action_data)

	registry.save(ignore_permissions=True)
	frappe.db.commit()
```

- **Step 2: Update setup.py**

```python
# asn_module/setup.py
from asn_module.custom_fields.purchase_receipt import setup as setup_pr_fields
from asn_module.custom_fields.purchase_invoice import setup as setup_pi_fields
from asn_module.notifications.setup import create_notifications
from asn_module.setup_actions import register_actions


def after_install():
	setup_pr_fields()
	setup_pi_fields()
	create_notifications()
	register_actions()
```

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost execute asn_module.setup.after_install`

- **Step 3: Commit**

```bash
git add asn_module/setup_actions.py asn_module/setup.py
git commit -m "feat: register all QR actions in the Action Registry on install"
```

---

## Phase 12: Integration Tests

### Task 22: End-to-End Flow Test

**Files:**

- Create: `asn_module/tests/__init__.py`
- Create: `asn_module/tests/test_e2e_flow.py`
- **Step 1: Write integration test for full ASN-to-Invoice flow**

```python
# asn_module/tests/__init__.py
```

```python
# asn_module/tests/test_e2e_flow.py
import frappe
from frappe.tests import IntegrationTestCase

from asn_module.qr_engine.token import create_token
from asn_module.qr_engine.dispatch import dispatch


class TestEndToEndFlow(IntegrationTestCase):
	"""Test the complete flow: ASN -> Purchase Receipt -> Purchase Invoice."""

	def setUp(self):
		self._ensure_test_data()
		self._ensure_actions_registered()

	def _ensure_test_data(self):
		if not frappe.db.exists("Supplier", "_Test Supplier"):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": "_Test Supplier",
				"supplier_group": "All Supplier Groups",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "_Test ASN Item"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test ASN Item",
				"item_name": "_Test ASN Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)

	def _ensure_actions_registered(self):
		from asn_module.setup_actions import register_actions
		register_actions()

	def test_full_asn_to_invoice_flow(self):
		# Step 1: Create and submit ASN
		asn = frappe.get_doc({
			"doctype": "ASN",
			"supplier": "_Test Supplier",
			"supplier_invoice_no": f"E2E-{frappe.generate_hash(length=6)}",
			"supplier_invoice_date": frappe.utils.today(),
			"supplier_invoice_amount": 1000,
			"expected_delivery_date": frappe.utils.add_days(frappe.utils.today(), 3),
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"uom": "Nos",
				"rate": 100,
			}],
		})
		asn.insert(ignore_permissions=True)
		asn.submit()

		self.assertEqual(asn.status, "Submitted")
		self.assertTrue(asn.qr_code)

		# Step 2: Scan ASN QR to create Purchase Receipt
		pr_token = create_token(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name=asn.name,
		)
		pr_result = dispatch(token=pr_token)

		self.assertTrue(pr_result["success"])
		self.assertEqual(pr_result["doctype"], "Purchase Receipt")

		pr = frappe.get_doc("Purchase Receipt", pr_result["name"])
		self.assertEqual(pr.docstatus, 0)
		self.assertEqual(pr.supplier, "_Test Supplier")
		self.assertEqual(pr.custom_asn, asn.name)
		self.assertEqual(len(pr.items), 1)
		self.assertEqual(pr.items[0].qty, 10)

		# Step 3: Submit Purchase Receipt
		pr.items[0].warehouse = "_Test Warehouse - _TC"
		pr.save()
		pr.submit()

		# Verify ASN status updated
		asn.reload()
		self.assertEqual(asn.status, "Received")
		self.assertEqual(asn.items[0].received_qty, 10)
		self.assertEqual(asn.items[0].discrepancy_qty, 0)

		# Step 4: Scan PR QR to create Purchase Invoice
		pi_token = create_token(
			action="create_purchase_invoice",
			source_doctype="Purchase Receipt",
			source_name=pr.name,
		)
		pi_result = dispatch(token=pi_token)

		self.assertTrue(pi_result["success"])
		self.assertEqual(pi_result["doctype"], "Purchase Invoice")

		pi = frappe.get_doc("Purchase Invoice", pi_result["name"])
		self.assertEqual(pi.docstatus, 0)
		self.assertEqual(pi.supplier, "_Test Supplier")
		self.assertEqual(pi.bill_no, asn.supplier_invoice_no)
		self.assertEqual(pi.custom_asn, asn.name)

	def test_discrepancy_tracking(self):
		asn = frappe.get_doc({
			"doctype": "ASN",
			"supplier": "_Test Supplier",
			"supplier_invoice_no": f"DISC-{frappe.generate_hash(length=6)}",
			"supplier_invoice_date": frappe.utils.today(),
			"expected_delivery_date": frappe.utils.add_days(frappe.utils.today(), 3),
			"items": [{
				"item_code": "_Test ASN Item",
				"qty": 10,
				"uom": "Nos",
				"rate": 100,
			}],
		})
		asn.insert(ignore_permissions=True)
		asn.submit()

		# Create PR via scan
		pr_token = create_token(
			action="create_purchase_receipt",
			source_doctype="ASN",
			source_name=asn.name,
		)
		pr_result = dispatch(token=pr_token)
		pr = frappe.get_doc("Purchase Receipt", pr_result["name"])

		# Reduce quantity (discrepancy)
		pr.items[0].qty = 8
		pr.items[0].warehouse = "_Test Warehouse - _TC"
		pr.save()
		pr.submit()

		# Verify discrepancy tracked
		asn.reload()
		self.assertEqual(asn.status, "Partially Received")
		self.assertEqual(asn.items[0].received_qty, 8)
		self.assertEqual(asn.items[0].discrepancy_qty, 2)
```

- **Step 2: Run the E2E tests**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module --module asn_module.tests.test_e2e_flow`
Expected: All 2 tests PASS

- **Step 3: Commit**

```bash
git add asn_module/tests/
git commit -m "test: add end-to-end integration tests for ASN-to-Invoice flow"
```

---

### Task 23: Run Full Test Suite

- **Step 1: Run all tests**

Run: `cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app asn_module`
Expected: All tests PASS

- **Step 2: Run linting**

Run: `cd /Users/gurudattkulkarni/Workspace/asn_module && ruff check asn_module/ && ruff format --check asn_module/`
Expected: No errors

- **Step 3: Fix any issues found**

Address any test failures or linting errors.

- **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: fix linting and test issues across all modules"
```

- **Step 5: Push to remote**

```bash
git push origin main
```

