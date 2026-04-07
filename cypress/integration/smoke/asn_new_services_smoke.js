const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("ASN New Services smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_supplier_context").then((result) => {
            seededData = result.message || result;
        });
    });

    it("rejects duplicate supplier invoice number", () => {
        const po = seededData.purchase_orders[0];
        const invNo = "DUP-INV-" + Date.now();
        // First submission should succeed
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type(invNo);
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        // Now try again with same invoice - should fail
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type(invNo);
        cy.get("[data-fieldname='supplier_invoice_amount']").type("1000");
        cy.get("[data-fieldname='qty']").type("1");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });

    it("rejects qty exceeding remaining PO qty", () => {
        cy.visit(route("purchasing/asn-new"), { failOnStatusCode: false });
        const po = seededData.purchase_orders[0];
        cy.get("[data-fieldname='mode'][value='single']").click();
        cy.get("[data-fieldname='purchase_order']").select(po.name);
        cy.get("[data-fieldname='supplier_invoice_no']").type("EXCESS-QTY-" + Date.now());
        cy.get("[data-fieldname='supplier_invoice_amount']").type("99999");
        cy.get("[data-fieldname='qty']").type("99999");
        cy.get("[data-fieldname='rate']").type("100");
        cy.get(".btn-primary").contains("Submit").click();
        cy.get(".portal-error, .error-message, .alert-error", { timeout: 15000 }).should("be.visible");
    });
});
