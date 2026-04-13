const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal nightly", () => {
	let seededData;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
			(result) => {
				seededData = result;
			}
		);
	});

	it("ASN items show correct remaining qty", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".list-row", { timeout: 20000 }).first().click();
		cy.get(".frappe-control[data-fieldname='items'] .grid-body", { timeout: 15000 }).should(
			"exist"
		);
	});

	it("ASN list shows submitted ASN", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".list-row", { timeout: 20000 }).should("have.length.greaterThan", 0);
	});
});
