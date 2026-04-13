const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Transition trace smoke", () => {
	before(() => {
		cy.login();
	});

	it("report page loads and renders", () => {
		cy.visit(route("query-report/ASN%20Item%20Transition%20Trace"), {
			failOnStatusCode: false,
		});
		cy.location("pathname", { timeout: 20000 }).should(
			"include",
			"/query-report/ASN%20Item%20Transition%20Trace"
		);
		cy.get(".query-report, .report-wrapper, .page-form", { timeout: 20000 }).should("exist");
	});
});
