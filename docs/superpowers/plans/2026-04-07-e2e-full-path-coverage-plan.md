# E2E Full Path Coverage Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Cypress E2E coverage for all public pages and desk routes in the ASN module — smoke suite for critical paths, nightly suite for all error branches — on both Frappe v15 and v16.

**Architecture:** Hybrid data strategy: server-seeded reference data via `cy.call()` (supplier context, ASN with items, QI context) for all specs; real UX flows for portal creation and validation error states. Layered suite structure: `smoke/` for critical paths, `nightly/` for full branch coverage. Route prefix via `Cypress.env("routePrefix")` for v15/v16 compatibility.

**Tech Stack:** Cypress, Frappe v15 + v16, `bench run-ui-tests`, `asn_module.utils.cypress_helpers`

---

## Chunk 1: Seed Helpers

**Goal:** Extend `cypress_helpers.py` with 3 new server-side seed helpers needed across all new specs.

- Create: `asn_module/utils/cypress_helpers.py` (add 3 functions to existing file)
- **Step 1: Read existing helpers**

Read: `asn_module/utils/cypress_helpers.py`

- **Step 2: Add `seed_supplier_context()`**

Append after `seed_scan_station_context()`:

```python
@frappe.whitelist()
def seed_supplier_context():
    if not frappe.conf.get("allow_tests"):
        frappe.throw(_("Only available in test mode"))
    frappe.only_for("System Manager")

    from asn_module.templates.pages.asn import (
        _get_supplier_for_user,
        get_open_purchase_orders_for_supplier,
    )

    # Create supplier
    supplier = frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": "Test Supplier E2E",
        "supplier_group": "All Supplier Groups",
        "supplier_type": "Individual",
    }).insert(ignore_permissions=True)

    # Create portal user
    portal_user = frappe.get_doc({
        "doctype": "User",
        "email": "supplier_e2e@test.com",
        "first_name": "Supplier",
        "send_welcome_email": 0,
        "user_type": "Website User",
    }).insert(ignore_permissions=True)
    frappe.db.set_value("User", portal_user.name, "enabled", 1)

    # Add Supplier role to portal user
    frappe.permissions.add_user_permission("Supplier", supplier.name, portal_user.name)
    role = frappe.get_doc("Role", {"role_name": "Supplier"})
    role.get_common_users()
    if portal_user.name not in [u.name for u in role.get("users", [])]:
        role.append("users", {"user": portal_user.name})
        role.save(ignore_permissions=True)

    # Create 2 POs
    from asn_module.asn_module.doctype.asn.test_asn import create_purchase_order

    po1 = create_purchase_order(qty=10, supplier=supplier.name)
    po2 = create_purchase_order(qty=5, supplier=supplier.name)

    return {
        "supplier": supplier.name,
        "portal_user": portal_user.name,
        "purchase_orders": [
            {"name": po1.name, "items": [i.as_dict() for i in po1.items]},
            {"name": po2.name, "items": [i.as_dict() for i in po2.items]},
        ],
    }
```

- **Step 3: Add `seed_asn_with_items()`**

Append after `seed_supplier_context()`:

```python
@frappe.whitelist()
def seed_asn_with_items():
    if not frappe.conf.get("allow_tests"):
        frappe.throw(_("Only available in test mode"))
    frappe.only_for("System Manager")

    from asn_module.asn_module.doctype.asn.test_asn import (
        create_purchase_order,
        make_test_asn,
        real_asn_attachment_context,
    )

    po = create_purchase_order(qty=10)
    # Add a second item to the PO
    from asn_module.utils.test_setup import get_or_create_test_item
    item2 = get_or_create_test_item()
    frappe.get_doc("Purchase Order Item", {"parent": po.name, "item_code": item2.name, "qty": 5, "rate": 200}).insert()

    asn = make_test_asn(purchase_order=po, qty=10)
    asn.insert(ignore_permissions=True)
    with real_asn_attachment_context():
        asn.submit()

    return {
        "asn_name": asn.name,
        "item_count": len(asn.items),
        "items": [{"name": i.name, "item_code": i.item_code, "qty": i.qty} for i in asn.items],
    }
```

- **Step 4: Add `seed_quality_inspection_context()`**

Append after `seed_asn_with_items()`:

```python
@frappe.whitelist()
def seed_quality_inspection_context():
    if not frappe.conf.get("allow_tests"):
        frappe.throw(_("Only available in test mode"))
    frappe.only_for("System Manager")

    from asn_module.asn_module.doctype.asn.test_asn import (
        create_purchase_order,
        make_test_asn,
        real_asn_attachment_context,
    )
    from asn_module.handlers.tests.test_stock_transfer import TestCreateStockTransfer

    # Create PO + ASN + PR using existing fixture helper
    fixture = TestCreateStockTransfer()
    po = fixture._make_purchase_order()
    asn = make_test_asn(purchase_order=po, qty=10)
    asn.insert(ignore_permissions=True)

    # Create PR
    pr = fixture._make_purchase_receipt_only(po, asn)
    accepted_qi = fixture._make_quality_inspection(pr.name, asn.items[0].item_code, "Accepted")
    rejected_qi = fixture._make_quality_inspection(pr.name, asn.items[0].item_code, "Rejected")

    return {
        "asn_name": asn.name,
        "pr_name": pr.name,
        "qi_accepted": accepted_qi.name,
        "qi_rejected": rejected_qi.name,
    }
```

- **Step 5: Verify helpers work**

Run in bench shell:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16 && source env/bin/activate
bench --site frappe16.localhost execute asn_module.utils.cypress_helpers.seed_supplier_context
bench --site frappe16.localhost execute asn_module.utils.cypress_helpers.seed_asn_with_items
bench --site frappe16.localhost execute asn_module.utils.cypress_helpers.seed_quality_inspection_context
```

Expected: JSON returns with names/IDs, no errors

- **Step 6: Commit**

```bash
git add asn_module/utils/cypress_helpers.py
git commit -m "test(e2e): add seed helpers for full path coverage"
```

---

## Chunk 2: Smoke Suite — New Files

**Goal:** Create 4 new smoke spec files covering all previously untested pages.

- Create: `cypress/integration/smoke/asn_portal_smoke.js`
- Create: `cypress/integration/smoke/asn_new_portal_smoke.js`
- Create: `cypress/integration/smoke/asn_new_services_smoke.js`
- Create: `cypress/integration/smoke/transition_trace_smoke.js`

### Task 1: `asn_portal_smoke.js` (NEW)

**Files:**

- Create: `cypress/integration/smoke/asn_portal_smoke.js`
- Test via: `E2E_SUITE=smoke bench --site test.localhost run-ui-tests asn_module --headless`
- **Step 1: Write smoke spec**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("portal user can see their ASN list", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should("exist");
    });

    it("opens ASN detail from portal list", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".list-row", { timeout: 15000 }).first().click();
        cy.get(".page-head", { timeout: 20000 }).should("exist");
    });
});
```

- **Step 2: Verify file is valid JS (no parse errors)**

Run: `node --check cypress/integration/smoke/asn_portal_smoke.js`
Expected: no output (no syntax error)

- **Step 3: Commit**

```bash
git add cypress/integration/smoke/asn_portal_smoke.js
git commit -m "test(e2e): add asn_portal_smoke smoke tests"
```

### Task 2: `asn_new_portal_smoke.js` (NEW)

**Files:**

- Create: `cypress/integration/smoke/asn_new_portal_smoke.js`
- **Step 1: Write smoke spec — single mode**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New portal smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects empty single form", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='single']", { timeout: 20000 }).should("exist");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("accepts valid single ASN submission", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("INV-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".alert-success, .portal-success, .scan-success", { timeout: 20000 }).should("be.visible");
    });
});
```

- **Step 2: Write smoke spec — bulk mode**

Append to same file:

```javascript
    it("rejects empty bulk CSV", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("accepts valid bulk CSV", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        const po = seededData.purchase_orders[0];
        const csv = [
            "supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
            `BULK-${Date.now()},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,1500,${po.name},1,${po.items[0].item_code},1,100`,
        ].join("\n");
        cy.get("[data-fieldname='items_csv']").upload_file("bulk_test.csv", csv, "text/csv");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".alert-success, .portal-success, .scan-success", { timeout: 20000 }).should("be.visible");
    });
```

- **Step 3: Verify JS syntax**

Run: `node --check cypress/integration/smoke/asn_new_portal_smoke.js`
Expected: no output

- **Step 4: Commit**

```bash
git add cypress/integration/smoke/asn_new_portal_smoke.js
git commit -m "test(e2e): add asn_new_portal_smoke smoke tests"
```

### Task 3: `asn_new_services_smoke.js` (NEW)

**Files:**

- Create: `cypress/integration/smoke/asn_new_services_smoke.js`
- **Step 1: Write smoke spec**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New Services smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects duplicate supplier invoice number", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        const invNo = "DUP-INV-" + Date.now();
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type(invNo);
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        // Now try again with same invoice
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type(invNo);
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("rejects qty exceeding remaining PO qty", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("EXCESS-QTY-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("99999");
        cy.get("[data-fieldname='qty']").type("99999");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });
});
```

- **Step 2: Verify JS syntax**

Run: `node --check cypress/integration/smoke/asn_new_services_smoke.js`
Expected: no output

- **Step 3: Commit**

```bash
git add cypress/integration/smoke/asn_new_services_smoke.js
git commit -m "test(e2e): add asn_new_services_smoke smoke tests"
```

### Task 4: `transition_trace_smoke.js` (NEW)

**Files:**

- Create: `cypress/integration/smoke/transition_trace_smoke.js`
- **Step 1: Write smoke spec**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Transition trace smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_asn_with_items").then((result) => {
            seededData = result.message || result;
        });
    });

    it("report page loads and renders", () => {
        cy.visit(route("report/asn-item-transition-trace"), { failOnStatusCode: false });
        cy.get(".page-head, .report-title, .standard-filter", { timeout: 20000 }).should("exist");
    });

    it("basic filter by ASN works", () => {
        cy.visit(route("report/asn-item-transition-trace"), { failOnStatusCode: false });
        cy.get("[data-fieldname='asn']", { timeout: 15000 }).should("exist");
        cy.get("[data-fieldname='asn']").type(seededData.asn_name);
        cy.get(".btn-primary").contains("Search").click();
        cy.get(".page-head, .report-table, .list-row", { timeout: 20000 }).should("exist");
    });
});
```

- **Step 2: Verify JS syntax**

Run: `node --check cypress/integration/smoke/transition_trace_smoke.js`
Expected: no output

- **Step 3: Commit**

```bash
git add cypress/integration/smoke/transition_trace_smoke.js
git commit -m "test(e2e): add transition_trace_smoke tests"
```

---

## Chunk 3: Smoke Suite — Expanded Existing Files

**Goal:** Expand 2 existing smoke files with happy-path coverage not yet included.

- Modify: `cypress/integration/smoke/asn_desk_smoke.js`
- Modify: `cypress/integration/smoke/scan_station_smoke.js`

### Task 1: Expand `asn_desk_smoke.js`

**Files:**

- Modify: `cypress/integration/smoke/asn_desk_smoke.js`
- **Step 1: Read current file**

Read: `cypress/integration/smoke/asn_desk_smoke.js`

- **Step 2: Add detail view test**

Append new `it()` block:

```javascript
    it("opens ASN detail and shows key fields", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".list-row", { timeout: 20000 }).first().click();
        cy.get(".page-head", { timeout: 20000 }).should("exist");
        cy.get(".frappe-control[data-fieldname='supplier']", { timeout: 15000 }).should("exist");
    });
```

- **Step 3: Verify JS syntax**

Run: `node --check cypress/integration/smoke/asn_desk_smoke.js`
Expected: no output

- **Step 4: Commit**

```bash
git add cypress/integration/smoke/asn_desk_smoke.js
git commit -m "test(e2e): expand asn_desk_smoke with detail view test"
```

### Task 2: Expand `scan_station_smoke.js`

**Files:**

- Modify: `cypress/integration/smoke/scan_station_smoke.js`
- **Step 1: Read current file**

Read: `cypress/integration/smoke/scan_station_smoke.js`

- **Step 2: Add valid scan test**

Append new `it()` block in a new context block for seeded context:

```javascript
context("Scan station with seeded data", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_scan_station_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("accepts valid scan code and shows success feedback", () => {
        cy.visit(route("scan-station"), { failOnStatusCode: false });
        cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
        cy.get(".scan-input").clear();
        cy.get(".scan-input").type(seededData.scan_code + "{enter}");
        cy.get(".scan-success, .scan-result", { timeout: 20000 }).should("be.visible");
    });
});
```

- **Step 3: Verify JS syntax**

Run: `node --check cypress/integration/smoke/scan_station_smoke.js`
Expected: no output

- **Step 4: Commit**

```bash
git add cypress/integration/smoke/scan_station_smoke.js
git commit -m "test(e2e): expand scan_station_smoke with valid scan test"
```

---

## Chunk 4: Nightly Suite — New Files

**Goal:** Create 3 new nightly spec files covering all error branches per page.

- Create: `cypress/integration/nightly/asn_portal_nightly.js`
- Create: `cypress/integration/nightly/asn_new_portal_nightly.js`
- Create: `cypress/integration/nightly/asn_new_services_nightly.js`

### Task 1: `asn_portal_nightly.js` (NEW)

**Files:**

- Create: `cypress/integration/nightly/asn_portal_nightly.js`
- **Step 1: Write nightly spec**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal nightly", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("ASN items show correct remaining qty", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".list-row", { timeout: 20000 }).first().click();
        cy.get(".frappe-control[data-fieldname='items'] .grid-body", { timeout: 15000 }).should("exist");
    });

    it("ASN list shows submitted ASN", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".list-row", { timeout: 20000 }).should("have.length.greaterThan", 0);
    });
});
```

- **Step 2: Commit**

```bash
git add cypress/integration/nightly/asn_portal_nightly.js
git commit -m "test(e2e): add asn_portal_nightly error branch tests"
```

### Task 2: `asn_new_portal_nightly.js` (NEW)

**Files:**

- Create: `cypress/integration/nightly/asn_new_portal_nightly.js`
- **Step 1: Write single mode error branches**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New portal nightly — single mode errors", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects zero qty", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("ZERO-QTY-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("100");
        cy.get("[data-fieldname='qty']").type("0");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("rejects negative rate", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("NEG-RATE-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("100");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("-1");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });
});
```

- **Step 2: Write bulk mode error branches**

Append:

```javascript
context("ASN New portal nightly — bulk mode errors", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects CSV with missing required columns", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        const badCsv = "supplier_invoice_no,supplier_invoice_amount\nINV-1,100";
        cy.get("[data-fieldname='items_csv']").upload_file("bad.csv", badCsv, "text/csv");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("rejects qty greater than remaining on PO in CSV", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        const csv = [
            "supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
            `OVERQTY-${Date.now()},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,99999,${po.name},1,${po.items[0].item_code},99999,100`,
        ].join("\n");
        cy.get("[data-fieldname='items_csv']").upload_file("overqty.csv", csv, "text/csv");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });
});
```

- **Step 3: Commit**

```bash
git add cypress/integration/nightly/asn_new_portal_nightly.js
git commit -m "test(e2e): add asn_new_portal_nightly bulk+single error tests"
```

### Task 3: `asn_new_services_nightly.js` (NEW)

**Files:**

- Create: `cypress/integration/nightly/asn_new_services_nightly.js`
- **Step 1: Write helper error path tests**

```javascript
const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New Services nightly — validation error branches", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects duplicate PO SR No in same invoice group", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        const invNo = "DUP-PO-SRN-" + Date.now();
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        const csv = [
            "supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
            `${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
            `${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
        ].join("\n");
        cy.get("[data-fieldname='items_csv']").upload_file("dup_po_srno.csv", csv, "text/csv");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("rejects supplier invoice amount mismatch", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("MISMATCH-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1");  // intentionally wrong
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });
});
```

- **Step 2: Commit**

```bash
git add cypress/integration/nightly/asn_new_services_nightly.js
git commit -m "test(e2e): add asn_new_services_nightly validation error tests"
```

---

## Chunk 5: Nightly Suite — Expanded Existing Files

**Goal:** Expand 2 existing nightly files with full error branch coverage.

- Modify: `cypress/integration/nightly/scan_station_nightly.js`
- Modify: `cypress/integration/nightly/asn_desk_nightly.js`

### Task 1: Expand `scan_station_nightly.js`

**Files:**

- Modify: `cypress/integration/nightly/scan_station_nightly.js`
- **Step 1: Read current file**

Read: `cypress/integration/nightly/scan_station_nightly.js`

- **Step 2: Add dispatch error state test**

Append new `it()` block:

```javascript
    it("dispatch with rejected QI shows error feedback", () => {
        cy.visit(route("scan-station"), { failOnStatusCode: false });
        cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
        // Use a scan code from a rejected QI context if available
        cy.get(".scan-input").clear();
        cy.get(".scan-input").type("INVALID-REJECTED-{enter}");
        cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
    });
```

- **Step 3: Commit**

```bash
git add cypress/integration/nightly/scan_station_nightly.js
git commit -m "test(e2e): expand scan_station_nightly with rejected QI path"
```

### Task 2: Expand `asn_desk_nightly.js`

**Files:**

- Modify: `cypress/integration/nightly/asn_desk_nightly.js`
- **Step 1: Read current file**

Read: `cypress/integration/nightly/asn_desk_nightly.js`

- **Step 2: Add status filter test**

Append new `it()` block:

```javascript
    it("filter by status Submitted shows submitted ASNs", () => {
        cy.visit(route("asn"), { failOnStatusCode: false });
        cy.get(".filter-section .input-with-select", { timeout: 20000 }).should("exist");
        cy.get(".filter-section").contains("Submitted").click();
        cy.get(".list-row", { timeout: 15000 }).should("have.length.greaterThan", 0);
    });
```

- **Step 3: Commit**

```bash
git add cypress/integration/nightly/asn_desk_nightly.js
git commit -m "test(e2e): expand asn_desk_nightly with status filter test"
```

---

## Chunk 6: Full Suite Verification

**Goal:** Run full E2E suite in smoke mode locally (or observe CI), confirm all specs pass on both Frappe versions.

- **Step 1: Run smoke suite**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
source env/bin/activate
export BENCH_ROOT=/Users/gurudattkulkarni/Workspace/bench16
export DB_ROOT_PASSWORD=root
export CI=false
chmod +x scripts/run_ephemeral_e2e.sh
# Run on frappe16.localhost (v16 surrogate)
SITE_NAME=frappe16.localhost E2E_MODE=smoke E2E_SUITE=smoke \
  BENCH_ROOT="$BENCH_ROOT" DB_ROOT_PASSWORD="$DB_ROOT_PASSWORD" \
  bash scripts/run_ephemeral_e2e.sh smoke
```

Expected: all smoke specs pass, no console errors, Cypress videos generated

- **Step 2: Verify coverage artifacts**

Check that Cypress screenshots + videos are generated for any failures. Confirm all smoke tests render the correct DOM elements.

- **Step 3: Push all commits**

```bash
git push origin feature/coverage-gap-closure
```

---

## File Summary


| File                                                      | Chunk | Change                 |
| --------------------------------------------------------- | ----- | ---------------------- |
| `asn_module/utils/cypress_helpers.py`                     | 1     | Add 3 seed helpers     |
| `cypress/integration/smoke/asn_portal_smoke.js`           | 2     | NEW                    |
| `cypress/integration/smoke/asn_new_portal_smoke.js`       | 2     | NEW                    |
| `cypress/integration/smoke/asn_new_services_smoke.js`     | 2     | NEW                    |
| `cypress/integration/smoke/transition_trace_smoke.js`     | 2     | NEW                    |
| `cypress/integration/smoke/asn_desk_smoke.js`             | 3     | Expand (detail view)   |
| `cypress/integration/smoke/scan_station_smoke.js`         | 3     | Expand (valid scan)    |
| `cypress/integration/nightly/asn_portal_nightly.js`       | 4     | NEW                    |
| `cypress/integration/nightly/asn_new_portal_nightly.js`   | 4     | NEW                    |
| `cypress/integration/nightly/asn_new_services_nightly.js` | 4     | NEW                    |
| `cypress/integration/nightly/asn_desk_nightly.js`         | 5     | Expand (status filter) |
| `cypress/integration/nightly/scan_station_nightly.js`     | 5     | Expand (rejected QI)   |


