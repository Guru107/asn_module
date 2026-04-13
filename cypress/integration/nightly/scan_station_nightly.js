const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Scan Station nightly", () => {
	let seededData;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_scan_station_context").then(
			(result) => {
				seededData = result;
			}
		);
	});

	it("renders scan input", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
	});

	it("accepts scan code and shows success or expected feedback", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type(seededData.scan_code + "{enter}");
		cy.get(".scan-result, .scan-success, .scan-error", { timeout: 20000 }).should(
			"be.visible"
		);
	});

	it("dispatch with rejected QI shows error feedback", () => {
		cy.visit(route("scan-station"), { failOnStatusCode: false });
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("INVALID-REJECTED{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
	});
});
