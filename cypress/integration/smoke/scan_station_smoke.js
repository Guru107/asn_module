const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN scan station", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.seed_context("asn_module.utils.cypress_helpers.seed_scan_station_context").then(
			(result) => {
				seededData = result;
			}
		);
	});

	beforeEach(() => {
		// Cypress test isolation clears the session between tests.
		cy.login();
	});

	it("renders scan input and rejects URLs without code query parameter", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("https://example.com/api?token=old{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
		cy.get(".scan-error").should("contain", "missing the code query parameter");
	});

	it("successful scan stays on the station and links to the created document", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type(seededData.scan_code);
		cy.location("pathname", { timeout: 20000 }).should("include", "scan-station");
		// v15 renders show_alert as .alert.desk-alert; v16 renders a toast.
		// The created-document link is the version-neutral target.
		cy.get('a[href*="/purchase-receipt/"]', { timeout: 20000 })
			.should("be.visible")
			.and("have.attr", "href")
			.and("include", "/purchase-receipt/");
		cy.get(".scan-input").should("be.focused");
	});
});
