const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal smoke", () => {
	before(() => {
		cy.login();
	});

	it("portal user can see ASN list page without errors", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
	});
});
