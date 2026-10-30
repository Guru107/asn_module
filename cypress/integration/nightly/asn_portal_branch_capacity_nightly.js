function fillAndSubmit(purchaseOrder, qty) {
	cy.intercept("GET", /search_purchase_order_items/).as("poItems");
	cy.visit("/asn_new", { failOnStatusCode: false });
	cy.get("#single-po-input", { timeout: 20000 }).clear().type(purchaseOrder);
	cy.get("#add-po-btn").click();
	cy.wait("@poItems", { timeout: 20000 });
	cy.get("#single-item-picker", { timeout: 20000 }).should("be.visible");
	cy.get("#single-item-picker-list input[type='checkbox']", { timeout: 20000 })
		.first()
		.check({ force: true });
	cy.get("form#single-asn-form input[name='supplier_invoice_no']")
		.clear()
		.type(`CAP-E2E-${Date.now()}`);
	cy.fill_portal_asn_vehicle();
	cy.get("input[name='single_manual_qty']").first().clear().type(String(qty));
	cy.get("input[name='single_manual_rate']").first().clear().type("100");
	cy.get("button[form='single-asn-form']").click();
}

context("A user who is not a supplier cannot open the create page", () => {
	it("shows the portal permission error", () => {
		cy.login();
		cy.visit("/asn_new", { failOnStatusCode: false });
		cy.get("body", { timeout: 20000 }).should("contain", "Only supplier portal users");
	});
});

context("Portal message when the branch cannot take any more", () => {
	let seeded;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_portal_branch_capacity_context", {
			already_full: 1,
		}).then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("says the branch already has as much as it can take", () => {
		fillAndSubmit(seeded.purchase_order, 1);
		cy.get("#single-pane .alert.alert-danger", { timeout: 20000 })
			.should("contain", "as much of this item as it can take")
			.and("contain", "cannot declare any more")
			.and("not.contain", "Stock Cap");
	});
});

context("Portal message when the branch can still take some", () => {
	let seeded;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_portal_branch_capacity_context", {
			already_full: 0,
		}).then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("says how much the branch can still take", () => {
		fillAndSubmit(seeded.purchase_order, 10);
		cy.get("#single-pane .alert.alert-danger", { timeout: 20000 })
			.should("contain", "cannot take this quantity")
			.and("contain", "at most 4.")
			.and("not.contain", "Stock Cap");
	});
});

context("Portal accepts a quantity the branch can take", () => {
	let seeded;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_portal_branch_capacity_context", {
			already_full: 0,
		}).then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login(seeded.portal_user, seeded.portal_password);
	});

	it("submits a quantity inside the branch limit", () => {
		fillAndSubmit(seeded.purchase_order, 1);
		cy.location("pathname", { timeout: 20000 }).should("match", /\/asn-/);
	});
});
