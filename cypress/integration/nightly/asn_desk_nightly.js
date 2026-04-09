const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN desk nightly", () => {
	let seededData;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_minimal_asn").then((result) => {
			seededData = result;
		});
	});

	it("shows seeded ASN in the ASN list view", () => {
		cy.visit(route("asn"));
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
		cy.get(".list-row", { timeout: 15000 }).should("contain.text", seededData.asn_name);
	});

	it("opens ASN detail and shows key fields", () => {
		cy.visit(route("Form/ASN/" + seededData.asn_name));
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		cy.get(".frappe-control[data-fieldname='supplier']", { timeout: 15000 }).should("exist");
	});

	it("filter by status Submitted shows submitted ASNs", () => {
		cy.visit(route("asn"), { failOnStatusCode: false });
		cy.get(".filter-section .input-with-select", { timeout: 20000 }).should("exist");
		cy.get(".filter-section").contains("Submitted").click();
		cy.get(".list-row", { timeout: 15000 }).should("have.length.greaterThan", 0);
	});
});
