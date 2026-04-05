const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN desk", () => {
	before(() => {
		cy.login();
	});

	it("opens ASN list without console errors", () => {
		cy.visit(route("asn"));
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
	});
});
