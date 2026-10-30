const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

// testIsolation: false -- the third test deliberately continues on the exact draft the
// second test saved (no navigation, no newAsnWithQty call), so this suite needs the
// browser's page/session state to carry over between tests. Cypress's default
// testIsolation resets to about:blank and clears storage before every test, which would
// otherwise strand test 3 on a blank page before it can find its buttons.
context("ASN stock cap", { testIsolation: false }, () => {
	let seeded;

	before(() => {
		cy.login();
		cy.seed_context("asn_module.utils.cypress_helpers.seed_stock_cap_context").then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login();
	});

	// Saving a breach can surface more than one stock cap warning dialog in quick
	// succession (e.g. a client-side check and the server's own _server_messages
	// landing a moment apart), so closing "the" modal once isn't reliable -- keep
	// closing until none are left rather than asserting a fixed count.
	const closeAllVisibleModals = () => {
		cy.get("body").then(($body) => {
			const $closeBtn = $body
				.find(".modal:visible .modal-header .btn-modal-close:visible")
				.first();
			if ($closeBtn.length) {
				cy.wrap($closeBtn).click();
				cy.wait(300);
				closeAllVisibleModals();
			}
		});
	};

	const clickVisibleModalYes = () => {
		cy.get(".modal:visible .modal-footer", { timeout: 15000 })
			.contains("button", /^Yes$/)
			.click({ force: true });
	};

	const clickPrimaryAction = (label) => {
		const re = new RegExp(`^${label}$`);
		cy.get("body").then(($body) => {
			const $match = $body
				.find(
					".page-head .primary-action:visible, .page-head button.primary-action:visible"
				)
				.filter((_, el) => {
					const clone = Cypress.$(el).clone();
					clone.find(".es-button__loading-label").remove();
					return re.test(clone.text().trim().replace(/\s+/g, " "));
				});
			expect($match.length, `toolbar action ${label}`).to.be.greaterThan(0);
			cy.wrap($match.first()).click({ force: true });
		});
	};

	const waitForDeskUnfrozen = () => {
		cy.window().then((win) => {
			const frappe = win.frappe;
			if (!frappe?.dom?.unfreeze) {
				return;
			}
			for (let i = 0; i < 10 && frappe.dom.freeze_count > 0; i += 1) {
				frappe.dom.unfreeze();
			}
		});
		cy.get("body", { timeout: 60000 }).should(($body) => {
			expect($body.find(".freeze-message-container:visible").length).to.eq(0);
		});
	};

	const expectDraftDoc = () => {
		cy.window().its("cur_frm.doc.docstatus", { timeout: 20000 }).should("eq", 0);
	};

	const expectSubmittedDoc = () => {
		cy.window().its("cur_frm.doc.docstatus", { timeout: 20000 }).should("eq", 1);
	};

	const dismissSupplierClearConfirm = () => {
		cy.get("body").then(($body) => {
			if (!$body.find(".modal:visible").length) {
				return;
			}
			cy.get(".modal:visible", { timeout: 15000 }).should(
				"contain",
				"Changing supplier will clear all items"
			);
			clickVisibleModalYes();
			cy.get(".modal:visible").should("not.exist");
			cy.window().its("cur_frm.doc.supplier").should("eq", seeded.supplier);
		});
	};

	const newAsnWithQty = (qty) => {
		cy.visit(route("Form/ASN/new"), { failOnStatusCode: false });
		cy.get(".form-layout", { timeout: 20000 }).should("exist");
		cy.fill_field("supplier", seeded.supplier, "Link");
		// The Link field's value lands on the DOM input synchronously, but the commit
		// into frm.doc is a server round-trip (validate_link_and_fetch): force the
		// field to blur/commit and wait for the model to actually reflect it.
		cy.get('[data-fieldname="supplier"] input').focus().blur();
		cy.window().its("cur_frm.doc.supplier", { timeout: 15000 }).should("eq", seeded.supplier);
		// Every new ASN starts with one empty row already in the "items" table: it is
		// a mandatory (reqd) Table field, and Frappe seeds mandatory child tables with
		// a blank row for every new document (frappe.model.create_mandatory_children,
		// see apps/frappe/frappe/public/js/frappe/model/create_new.js). Because of that
		// placeholder row, asn.js's `supplier(frm)` handler (asn.js:41-58) pops its
		// "Changing supplier will clear all items. Continue?" confirm the first time
		// supplier is set on a new document too, not just on a genuine re-selection.
		// The trigger that opens it is queued via frappe.run_serially, so it can land a
		// tick or two after `cur_frm.doc.supplier` above already reads correctly. Handle
		// it if/when it shows up: there is nothing real to lose, since the only row is
		// the untouched placeholder. Accepting clears the table, so re-add a fresh row.
		// Give the deferred trigger a moment to actually run before checking for it.
		cy.wait(800);
		dismissSupplierClearConfirm();
		waitForDeskUnfrozen();
		cy.get('[data-fieldname="items"] .grid-add-row', { timeout: 20000 }).click();
		cy.get('[data-fieldname="purchase_order"]:visible input', { timeout: 20000 })
			.first()
			.type(`${seeded.purchase_order}{enter}`, { delay: 50, force: true });
		cy.get('[data-fieldname="qty"]:visible').first().clear({ force: true }).type(String(qty), {
			force: true,
		});
		// Adding a row opens it directly in the full "Editing Row" grid-form overlay
		// (grid_row_form.js), which covers the form's own Save/Submit buttons. Collapse
		// it back to the compact grid view before interacting with the page toolbar.
		cy.get(".grid-collapse-row:visible").click();
		cy.get(".form-in-grid:visible").should("not.exist");
		// Supplier Invoice No/Amount are mandatory fields on the ASN doctype itself
		// (asn.json), unrelated to the stock cap feature, but Save fails validation
		// without them. Supplier Invoice No must also be unique per supplier, so give
		// each document its own value rather than reusing one across tests.
		cy.fill_field("supplier_invoice_no", `SINV-E2E-${Date.now()}`, "Data");
		cy.fill_field("supplier_invoice_amount", "100", "Currency");
		cy.fill_field("vehicle_number", "MH12AB1234", "Data");
	};

	it("submits when projected stock stays within the cap", () => {
		newAsnWithQty(seeded.passing_qty);
		clickPrimaryAction("Save");
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		clickPrimaryAction("Submit");
		clickVisibleModalYes();
		expectSubmittedDoc();
	});

	it("warns on save but still saves when the cap is breached", () => {
		newAsnWithQty(seeded.breaching_qty);
		clickPrimaryAction("Save");
		cy.get(".modal", { timeout: 20000 }).should("contain", seeded.item_code);
		closeAllVisibleModals();
		cy.get(".modal:visible").should("not.exist");
		expectDraftDoc();
	});

	it("blocks submit and leaves the ASN in draft when the cap is breached", () => {
		// The previous test's own modal(s) can still be open/mid fade-out here
		// (testIsolation is off for this suite so the page carries over directly from
		// that test's last assertion), which would otherwise cover the Submit button.
		closeAllVisibleModals();
		cy.get(".modal:visible").should("not.exist");
		clickPrimaryAction("Submit");
		clickVisibleModalYes();
		cy.get(".modal", { timeout: 20000 }).should("contain", "exceeds maximum");
		closeAllVisibleModals();
		cy.get(".modal:visible").should("not.exist");
		expectDraftDoc();
	});
});
