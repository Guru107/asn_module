context("ASN New portal smoke", () => {
	let portalUser;
	let portalPassword;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
			(seededData) => {
				portalUser = seededData.portal_user;
				portalPassword = seededData.portal_password;
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
