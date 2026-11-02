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

	beforeEach(() => {
		cy.login();
	});

	it("renders scan input", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
	});

	it("accepts scan code, stays on the station and links to the created document", () => {
		cy.visit(route("scan-station"));
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		expect(seededData.scan_code).to.have.length(16);
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type(seededData.scan_code);
		cy.location("pathname", { timeout: 20000 }).should("include", "scan-station");
		cy.url().should("not.include", "/login");
		// v15 renders show_alert as .alert.desk-alert; v16 renders a toast.
		// The created-document link is the version-neutral target.
		cy.get('a[href*="/purchase-receipt/"]', { timeout: 20000 })
			.should("be.visible")
			.and("have.attr", "href")
			.and("include", "/purchase-receipt/");
		cy.get(".scan-input").should("be.focused");
	});

	it("malformed code shows error feedback", () => {
		cy.visit(route("scan-station"), { failOnStatusCode: false });
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("TOO-SHORT{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("ABCD-EFGH-JKLM-NPQR{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
	});
});
