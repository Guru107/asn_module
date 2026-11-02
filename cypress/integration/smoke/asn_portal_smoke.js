context("ASN portal smoke", () => {
	let portalUser;
	let portalPassword;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_asn_context").then(
			(seededData) => {
				portalUser = seededData.portal_user;
				portalPassword = seededData.portal_password;
			}
		);
	});

	beforeEach(() => {
		cy.login(portalUser, portalPassword);
		cy.request("/api/method/frappe.auth.get_logged_user")
			.its("body.message")
			.should("eq", portalUser);
	});

	it("portal user sees their ASN list with at least one row", () => {
		cy.visit("/asn", { failOnStatusCode: false });
		cy.get(".list-group .list-group-item", { timeout: 20000 }).should(
			"have.length.greaterThan",
			0
		);
	});
});
