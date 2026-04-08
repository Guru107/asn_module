context("ASN New Services smoke", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call_api("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			seededData = result.message || result;
			cy.request("POST", "/api/method/login", {
				usr: seededData.portal_user,
				pwd: seededData.portal_password,
			})
				.its("status")
				.should("eq", 200);
		});
	});

	it("asn-new page renders without errors", () => {
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get(".asn-new-page", { timeout: 20000 }).should("exist");
		cy.get("#single-tab", { timeout: 20000 }).should("be.visible");
		cy.get("#bulk-tab", { timeout: 20000 }).should("be.visible");
		cy.get("form#single-asn-form input[name='mode'][value='single']", {
			timeout: 20000,
		}).should("exist");
		cy.get("form#asn-bulk-upload-form input[name='mode'][value='bulk']", {
			timeout: 20000,
		}).should("exist");
	});
});
