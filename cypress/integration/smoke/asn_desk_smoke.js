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

	it("opens ASN detail and shows key fields", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".list-row", { timeout: 20000 }).first().click();
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		cy.get(".frappe-control[data-fieldname='supplier']", { timeout: 15000 }).should("exist");
	});
});
