const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New Services smoke", () => {
	before(() => {
		cy.login();
	});

	it("asn-new page renders without errors", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
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
