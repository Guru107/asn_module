function openPurchaseOrder(poName) {
	cy.intercept("GET", "**/search_purchase_order_items*").as("poItems");
	cy.get("#single-po-input", { timeout: 20000 }).clear().type(poName);
	cy.get("#add-po-btn").click();
	cy.wait("@poItems").its("request.url").should("include", `purchase_order=${encodeURIComponent(poName)}`);
	cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
}

function expectRemaining(qty) {
	const amount = String(qty);
	cy.get("#single-item-picker-list .asn-item-picker-meta", { timeout: 20000 })
		.invoke("text")
		.should("match", new RegExp(`Remaining: ${amount}(?:\\.0+)?(?:\\D|$)`));
}

function visitCreatePage(asnName) {
	const query = asnName ? `?asn_name=${encodeURIComponent(asnName)}` : "";
	cy.visit(`/asn_new${query}`, { failOnStatusCode: false });
	cy.get("form#single-asn-form", { timeout: 20000 }).should("exist");
}

context("Portal Remaining Qty while editing a draft", () => {
	let seeded;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_portal_draft_remaining_context").then(
			(data) => {
				seeded = data;
			}
		);
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("offers the draft's quantity back while that draft is being edited", () => {
		visitCreatePage(seeded.draft_name);
		cy.get("form#single-asn-form input[name='asn_name']").should("have.value", seeded.draft_name);
		openPurchaseOrder(seeded.purchase_order);
		// Ordered 10, this draft declares 6. Leaving it out offers 10.
		expectRemaining(10);
	});

	it("counts the draft when the page is a new notice", () => {
		visitCreatePage();
		cy.get("form#single-asn-form input[name='asn_name']").should("have.value", "");
		openPurchaseOrder(seeded.purchase_order);
		expectRemaining(4);
	});

	it("counts the draft when the name belongs to another supplier", () => {
		visitCreatePage(seeded.other_draft_name);
		cy.get("form#single-asn-form input[name='asn_name']").should("have.value", "");
		openPurchaseOrder(seeded.purchase_order);
		expectRemaining(4);
	});

	it("still counts a submitted notice, and still counts the draft, when that name is passed", () => {
		visitCreatePage(seeded.submitted_asn_name);
		cy.get("form#single-asn-form input[name='asn_name']").should("have.value", "");
		// This order's only shipment is the submitted notice of 6. Leaving it out would offer 10.
		openPurchaseOrder(seeded.submitted_purchase_order);
		expectRemaining(4);
		// The draft of 6 on the other order stays in the count. A submitted name is not this draft.
		openPurchaseOrder(seeded.purchase_order);
		expectRemaining(4);
	});

	it("refuses a new notice for the quantity only the draft could claim", () => {
		visitCreatePage();
		openPurchaseOrder(seeded.purchase_order);
		cy.get("#single-item-picker-list input[type='checkbox']").first().check({ force: true });
		cy.get("form#single-asn-form input[name='supplier_invoice_no']")
			.clear()
			.type(`OVER-E2E-${Date.now()}`);
		cy.get("form#single-asn-form input[name='supplier_invoice_amount']").clear().type("1000");
		cy.get("input[name='single_manual_qty']").first().clear().type("10");
		cy.get("input[name='single_manual_rate']").first().clear().type("100");
		cy.get("form#single-asn-form button[type='submit']").click();
		cy.get("#single-pane .alert.alert-danger", { timeout: 20000 }).should(
			"contain",
			"exceeds remaining"
		);
	});
});

context("A user who is not a supplier cannot open the create page", () => {
	it("shows the portal permission error", () => {
		cy.login();
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("body", { timeout: 20000 }).should("contain", "Only supplier portal users");
	});
});

context("Portal submit updates the draft being edited", () => {
	let seeded;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_portal_draft_remaining_context").then(
			(data) => {
				seeded = data;
			}
		);
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("saves the edited draft instead of opening a second notice", () => {
		const invoiceNo = `DRAFT-E2E-${Date.now()}`;
		visitCreatePage(seeded.draft_name);
		openPurchaseOrder(seeded.purchase_order);
		cy.get("#single-item-picker-list input[type='checkbox']").first().check({ force: true });
		cy.get("form#single-asn-form input[name='supplier_invoice_no']").clear().type(invoiceNo);
		cy.get("form#single-asn-form input[name='supplier_invoice_amount']").clear().type("1000");
		cy.get("input[name='single_manual_qty']").first().clear().type("10");
		cy.get("input[name='single_manual_rate']").first().clear().type("100");
		cy.get("form#single-asn-form button[type='submit']").click();
		cy.location("pathname", { timeout: 20000 }).should(
			"include",
			seeded.draft_name.toLowerCase()
		);
		cy.visit("/asn");
		cy.contains(".asn-portal-row-link", seeded.draft_name, { timeout: 20000 }).should(
			"contain",
			invoiceNo
		);
		cy.get(".asn-portal-row-link").filter(`:contains(${invoiceNo})`).should("have.length", 1);
	});
});
