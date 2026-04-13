context("ASN New portal smoke", () => {
	let portalUser;
	let portalPassword;
	let purchaseOrders;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
			(seededData) => {
				portalUser = seededData.portal_user;
				portalPassword = seededData.portal_password;
				purchaseOrders = seededData.purchase_orders || [];
			}
		);
	});

	beforeEach(() => {
		cy.login(portalUser, portalPassword);
		cy.request("/api/method/frappe.auth.get_logged_user")
			.its("body.message")
			.should("eq", portalUser);
	});

	it("renders single-mode form without errors", () => {
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get(".asn-new-page", { timeout: 20000 }).should("exist");
		cy.get("#single-pane.active form#single-asn-form", { timeout: 20000 }).should("exist");
		cy.get("form#single-asn-form input[name='supplier_invoice_no']", {
			timeout: 20000,
		}).should("exist");
	});

	it("selects items and auto-populates manual rows", () => {
		const poName = purchaseOrders[0].name;
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#single-po-input", { timeout: 20000 }).clear().type(poName);
		cy.get("#add-po-btn").click();
		cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
		cy.get("#single-item-picker-list input[type='checkbox']", { timeout: 20000 })
			.first()
			.check({ force: true });
		cy.get("#single-manual-rows .single-row", { timeout: 20000 }).should("have.length", 1);
		cy.get("#single-manual-rows input[name='single_manual_purchase_order']")
			.first()
			.should("have.value", poName);
		cy.get("#single-item-picker-list input[type='checkbox']").first().uncheck({ force: true });
		cy.get("#single-manual-rows .single-row", { timeout: 20000 }).should("have.length", 0);
	});

	it("renders bulk-mode form without errors", () => {
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get(".asn-new-page", { timeout: 20000 }).should("exist");
		cy.get(".nav-link[aria-controls='bulk-pane']", { timeout: 20000 })
			.should("have.attr", "href", "#bulk")
			.click();
		cy.location("hash", { timeout: 20000 }).should("eq", "#bulk");
		cy.get("form#asn-bulk-upload-form", { timeout: 20000 }).should("exist");
		cy.get("form#asn-bulk-upload-form input#asn-bulk-file-input", {
			timeout: 20000,
		}).should("exist");
	});
});
