context("ASN New Services smoke", () => {
	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
			(seededData) => {
				cy.login(seededData.portal_user, seededData.portal_password);
				cy.request("/api/method/frappe.auth.get_logged_user")
					.its("body.message")
					.should("eq", seededData.portal_user);
			}
		);
	});

	it("asn-new page renders without errors", () => {
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get(".asn-new-page", { timeout: 20000 }).should("exist");
		cy.get("#single-tab", { timeout: 20000 }).should("be.visible");
		cy.get("#bulk-tab", { timeout: 20000 }).should("be.visible");
		cy.get("form#single-asn-form input[name='mode'][value='single']", {
			timeout: 20000,
		}).should("exist");
		cy.get("form#asn-bulk-upload-form input[name='mode'][value='bulk']", {
			timeout: 20000,
		}).should("exist");
	});
});
