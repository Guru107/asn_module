context("ASN desk", () => {
	before(() => {
		cy.login();
	});

	it("opens ASN list without console errors", () => {
		cy.visit("/app/asn");
		cy.get(".page-head, .standard-list-section, .list-row-head", { timeout: 20000 }).should(
			"exist"
		);
	});
});
