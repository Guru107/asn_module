const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal nightly", () => {
	let seededData;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_minimal_asn").then((result) => {
			seededData = result;
		});
	});

	beforeEach(() => {
		cy.login();
	});

	it("ASN list shows rows", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".list-row", { timeout: 20000 }).should("have.length.greaterThan", 0);
	});

	it("ASN detail shows items grid", () => {
		cy.visit(route("Form/ASN/" + seededData.asn_name), { failOnStatusCode: false });
		cy.get(".frappe-control[data-fieldname='items'] .grid-body", { timeout: 20000 }).should(
			"exist"
		);
	});
});
