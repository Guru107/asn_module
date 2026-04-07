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
		cy.get("[data-fieldname='mode'][value='single']", { timeout: 20000 }).should("exist");
	});

	it("renders bulk-mode form without errors", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		cy.get("[data-fieldname='mode'][value='bulk']", { timeout: 20000 }).should("exist");
	});
});
