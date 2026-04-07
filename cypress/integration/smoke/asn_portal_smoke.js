const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN portal smoke", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("portal user can see their ASN list", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
	});

	it("opens ASN detail from portal list", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".list-row", { timeout: 15000 }).first().click();
		cy.get(".page-head", { timeout: 20000 }).should("exist");
	});
});
