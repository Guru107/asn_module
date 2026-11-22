const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN form trace button smoke", () => {
	let asnName;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_minimal_asn").then((result) => {
			asnName = result.asn_name;
		});
	});

	beforeEach(() => {
		cy.login();
	});

	it("opens the trace report filtered on the saved ASN", () => {
		cy.visit(route("asn/" + asnName));
		cy.contains(".page-actions button", "Open Full Trace View", { timeout: 20000 }).should(
			"be.visible"
		);
		cy.reload();
		cy.contains(".page-actions button", "Open Full Trace View", { timeout: 20000 })
			.should("be.visible")
			.click();
		cy.location("pathname", { timeout: 20000 }).should(
			"include",
			"/query-report/ASN%20Item%20Transition%20Trace"
		);
		cy.window()
			.its("frappe.query_report", { timeout: 20000 })
			.should((report) => {
				expect(report.get_filter_value("asn")).to.equal(asnName);
				// Submitting the seeded ASN logs an ASN_GENERATED row per item.
				expect(report.data).to.have.length.greaterThan(0);
			});
	});

	it("hides the button on a new ASN", () => {
		cy.visit(route("asn/new"));
		// The status pill is set in the same refresh that would add the button.
		cy.contains(".page-head:visible", "Not Saved", { timeout: 20000 });
		cy.contains(".page-actions button", "Open Full Trace View").should("not.exist");
	});
});
