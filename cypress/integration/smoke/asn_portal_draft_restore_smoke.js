context("Portal draft restore when the picker hides the fully shipped PO line", () => {
	let seeded;

	before(() => {
		cy.seed_context(
			"asn_module.utils.cypress_helpers.seed_portal_draft_hidden_line_context"
		).then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("renders the stored row and surfaces the over-qty error on Save", () => {
		cy.intercept("GET", /search_purchase_order_items/).as("poItems");
		cy.visit(`/asn_new?asn_name=${encodeURIComponent(seeded.draft_name)}`, {
			failOnStatusCode: false,
		});
		cy.get("form#single-asn-form", { timeout: 20000 }).should("exist");
		cy.get("form#single-asn-form input[name='asn_name']").should(
			"have.value",
			seeded.draft_name
		);
		cy.wait("@poItems");

		// The picker omits the line (Remaining Qty 0 after the other notice shipped all
		// 10). The stored draft row must still render instead of being dropped.
		cy.get("#single-item-picker-list .asn-item-picker-empty", { timeout: 20000 }).should(
			"contain",
			"No items found"
		);
		cy.get("#single-manual-rows .single-row", { timeout: 20000 }).should("have.length", 1);
		cy.get("#single-manual-rows input[name='single_manual_purchase_order']")
			.first()
			.should("have.value", seeded.purchase_order);
		cy.get("#single-manual-rows input[name='single_manual_sr_no']")
			.first()
			.should("have.value", "1");

		// Saving over the shipped line must surface the server's per-row over-qty error
		// and keep the row, not delete it silently.
		cy.get("#single-manual-rows input[name='single_manual_qty']").first().clear().type("6");
		cy.fill_portal_asn_vehicle();
		cy.get("button[form='single-asn-form']").click();
		cy.get("#single-pane .alert.alert-danger", { timeout: 20000 }).should(
			"contain",
			"exceeds remaining"
		);
		cy.get("#single-manual-rows .single-row", { timeout: 20000 }).should("have.length", 1);
	});
});
