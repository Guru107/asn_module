const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New portal nightly — single mode errors", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call_api("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("rejects zero qty", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		const po = seededData.purchase_orders[0];
		cy.get("[data-fieldname='mode'][value='single']").click();
		cy.get("[data-fieldname='purchase_order']").select(po.name);
		cy.get("[data-fieldname='supplier_invoice_no']").type("ZERO-QTY-" + Date.now());
		cy.get("[data-fieldname='supplier_invoice_amount']").type("100");
		cy.get("[data-fieldname='qty']").type("0");
		cy.get("[data-fieldname='rate']").type("100");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});

	it("rejects negative rate", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		const po = seededData.purchase_orders[0];
		cy.get("[data-fieldname='mode'][value='single']").click();
		cy.get("[data-fieldname='purchase_order']").select(po.name);
		cy.get("[data-fieldname='supplier_invoice_no']").type("NEG-RATE-" + Date.now());
		cy.get("[data-fieldname='supplier_invoice_amount']").type("100");
		cy.get("[data-fieldname='qty']").type("1");
		cy.get("[data-fieldname='rate']").type("-1");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});
});

context("ASN New portal nightly — bulk mode errors", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call_api("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("rejects CSV with missing required columns", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		cy.get("[data-fieldname='mode'][value='bulk']").click();
		const badCsv = "supplier_invoice_no,supplier_invoice_amount\nINV-1,100";
		cy.get("[data-fieldname='items_csv']").upload_file("bad.csv", badCsv, "text/csv");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});

	it("rejects qty greater than remaining on PO in CSV", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		const po = seededData.purchase_orders[0];
		cy.get("[data-fieldname='mode'][value='bulk']").click();
		const csv = [
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
			`OVERQTY-${Date.now()},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,99999,${
				po.name
			},1,${po.items[0].item_code},99999,100`,
		].join("\n");
		cy.get("[data-fieldname='items_csv']").upload_file("overqty.csv", csv, "text/csv");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});
});
