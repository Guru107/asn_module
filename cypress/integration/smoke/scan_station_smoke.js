const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN scan station", () => {
	before(() => {
		cy.login();
	});

	// Single visit: Frappe desk often does not re-run page boot on a second cy.visit to the same route,
	// which left the second spec without .scan-input in CI (Frappe 15 + 16).
	it("renders scan input and rejects legacy token URLs", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("https://example.com/api?token=old{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
		cy.get(".scan-error").should("contain", "old token");
	});
});

context("Scan station with seeded data", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call("asn_module.utils.cypress_helpers.seed_scan_station_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("accepts valid scan code and shows success feedback", () => {
		cy.visit(route("scan-station"), { failOnStatusCode: false });
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type(seededData.scan_code + "{enter}");
		cy.get(".scan-success, .scan-result", { timeout: 20000 }).should("be.visible");
	});
});
