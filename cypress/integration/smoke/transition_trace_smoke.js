const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Transition trace smoke", () => {
	before(() => {
		cy.login();
	});

	it("report page loads and renders", () => {
		cy.visit(route("report/asn-item-transition-trace"), { failOnStatusCode: false });
		cy.get(".page-head, .page-content, .report-page", { timeout: 20000 }).should("exist");
	});
});
