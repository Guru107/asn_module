const route = (path) => {
	const p = path.replace(/^\//, "");
	return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New Services nightly — validation error branches", () => {
	let seededData;

	before(() => {
		cy.login();
		cy.call_api("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
			seededData = result.message || result;
		});
	});

	it("rejects duplicate PO SR No in same invoice group", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		const po = seededData.purchase_orders[0];
		const invNo = "DUP-PO-SRN-" + Date.now();
		cy.get("[data-fieldname='mode'][value='bulk']").click();
		const csv = [
			"supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
			`${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
			`${invNo},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,200,${po.name},1,${po.items[0].item_code},1,100`,
		].join("\n");
		cy.get("[data-fieldname='items_csv']").upload_file("dup_po_srno.csv", csv, "text/csv");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});

	it("rejects supplier invoice amount mismatch", () => {
		cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
		const po = seededData.purchase_orders[0];
		cy.get("[data-fieldname='mode'][value='single']").click();
		cy.get("[data-fieldname='purchase_order']").select(po.name);
		cy.get("[data-fieldname='supplier_invoice_no']").type("MISMATCH-" + Date.now());
		cy.get("[data-fieldname='supplier_invoice_amount']").type("1");
		cy.get("[data-fieldname='qty']").type("1");
		cy.get("[data-fieldname='rate']").type("100");
		cy.get(".btn-primary").contains("Submit").click();
		cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should(
			"be.visible"
		);
	});
});
