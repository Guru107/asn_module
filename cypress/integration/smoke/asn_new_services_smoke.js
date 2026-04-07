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
		cy.get("[data-fieldname='mode']", { timeout: 20000 }).should("exist");
	});
});
