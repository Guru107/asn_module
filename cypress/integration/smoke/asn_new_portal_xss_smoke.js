context("ASN New portal XSS smoke", () => {
	let portalUser;
	let portalPassword;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_supplier_context").then(
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

	it("renders typed markup in the PO field as inert chip text", () => {
		const payload = '<img src=x onerror="window.__asnXss=1">';
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("#single-po-input", { timeout: 20000 }).clear().type(payload);
		cy.get("#add-po-btn").click();

		// The chip shows the typed value as text, not parsed markup.
		cy.get("#selected-po-chip .asn-selected-po-chip", { timeout: 20000 })
			.should("have.text", payload)
			.then(($chip) => {
				expect($chip.children().length, "injected elements inside chip").to.eq(0);
			});
		cy.get("#selected-po-chip").find("img").should("not.exist");
		cy.window().its("__asnXss").should("be.undefined");

		// The hidden form value round-trips the raw string unchanged.
		cy.get("input[name='selected_purchase_orders']").should("have.value", payload);

		// No manual row may be built from typed markup either.
		cy.get("#single-manual-rows").find("img").should("not.exist");
	});
});
