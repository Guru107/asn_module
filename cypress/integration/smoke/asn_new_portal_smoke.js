const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New portal smoke", () => {
	before(() => {
		cy.login();
	});

	it("renders single-mode form without errors", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		cy.get(".asn-new-page", { timeout: 20000 }).should("exist");
		cy.get("#single-pane.active form#single-asn-form", { timeout: 20000 }).should("exist");
		cy.get("form#single-asn-form input[name='supplier_invoice_no']", {
			timeout: 20000,
		}).should("exist");
	});

	it("renders bulk-mode form without errors", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		cy.get("#bulk-tab", { timeout: 20000 }).click();
		cy.get("#bulk-pane.active form#asn-bulk-upload-form", { timeout: 20000 }).should("exist");
		cy.get("form#asn-bulk-upload-form input#asn-bulk-file-input", { timeout: 20000 }).should(
			"exist"
		);
	});
});
