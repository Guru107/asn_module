context("ASN New portal smoke", () => {
	before(() => {
		cy.login();
		cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			const seededData = result.message || result;
			cy.login(seededData.portal_user, seededData.portal_password);
		});
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
		cy.get("#bulk-tab", { timeout: 20000 }).click();
		cy.get("#bulk-pane.active form#asn-bulk-upload-form", { timeout: 20000 }).should("exist");
		cy.get("form#asn-bulk-upload-form input#asn-bulk-file-input", { timeout: 20000 }).should(
			"exist"
		);
	});
});
