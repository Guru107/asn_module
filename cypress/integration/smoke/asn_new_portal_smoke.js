const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New portal smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects empty single form", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='single']", { timeout: 20000 }).should("exist");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("accepts valid single ASN submission", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("INV-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".alert-success, .portal-success, .scan-success", { timeout: 20000 }).should("be.visible");
    });

    it("rejects empty bulk CSV", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("accepts valid bulk CSV", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='bulk']").click();
        const po = seededData.purchase_orders[0];
        const csv = [
            "supplier_invoice_no,supplier_invoice_date,expected_delivery_date,lr_no,lr_date,transporter_name,vehicle_number,driver_contact,supplier_invoice_amount,purchase_order,sr_no,item_code,qty,rate",
            `BULK-${Date.now()},2026-04-01,2026-04-10,,,Transporter,KA01AB1234,,1500,${po.name},1,${po.items[0].item_code},1,100`,
        ].join("\n");
        cy.get("[data-fieldname='items_csv']").upload_file("bulk_test.csv", csv, "text/csv");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".alert-success, .portal-success, .scan-success", { timeout: 20000 }).should("be.visible");
    });
});
