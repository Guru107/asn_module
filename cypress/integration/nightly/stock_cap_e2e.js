const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN stock cap", () => {
	let seeded;

	before(() => {
		cy.login();
		cy.seed_context("asn_module.utils.cypress_helpers.seed_stock_cap_context").then((data) => {
			seeded = data;
		});
	});

	beforeEach(() => {
		cy.login();
	});

	const newAsnWithQty = (qty) => {
		cy.visit(route("asn/new"), { failOnStatusCode: false });
		cy.get(".form-layout", { timeout: 20000 }).should("exist");
		cy.fill_field("supplier", seeded.supplier, "Link");
		cy.get('[data-fieldname="items"] .grid-add-row').click();
		cy.get('[data-fieldname="purchase_order"]:visible')
			.first()
			.type(`${seeded.purchase_order}{enter}`, { delay: 30 });
		cy.get('[data-fieldname="qty"]:visible').first().clear().type(String(qty));
	};

	it("submits when projected stock stays within the cap", () => {
		newAsnWithQty(seeded.passing_qty);
		cy.get(".primary-action").contains("Save").click();
		cy.get(".page-head", { timeout: 20000 }).should("exist");
		cy.get(".primary-action").contains("Submit").click();
		cy.get(".modal-footer .btn-primary:visible").click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("not.contain", "Draft");
	});

	it("warns on save but still saves when the cap is breached", () => {
		newAsnWithQty(seeded.breaching_qty);
		cy.get(".primary-action").contains("Save").click();
		cy.get(".modal", { timeout: 20000 }).should("contain", seeded.item_code);
		cy.get(".modal-header .btn-modal-close:visible").first().click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("contain", "Draft");
	});

	it("blocks submit and leaves the ASN in draft when the cap is breached", () => {
		cy.get(".primary-action").contains("Submit").click();
		cy.get(".modal-footer .btn-primary:visible").click();
		cy.get(".modal", { timeout: 20000 }).should("contain", "exceeds maximum");
		cy.get(".modal-header .btn-modal-close:visible").first().click();
		cy.get(".indicator-pill", { timeout: 20000 }).should("contain", "Draft");
	});
});
