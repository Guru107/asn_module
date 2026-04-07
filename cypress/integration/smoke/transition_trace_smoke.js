const route = (path) => {
    const p = path.replace(/^\//, "");
    return `/${Cypress.env("routePrefix")}/${p}`;
};

context("Transition trace smoke", () => {
    let seededData;

    before(() => {
        cy.login();
        cy.call("asn_module.utils.cypress_helpers.seed_asn_with_items").then((result) => {
            seededData = result.message || result;
        });
    });

    it("report page loads and renders", () => {
        cy.visit(route("report/asn-item-transition-trace"), { failOnStatusCode: false });
        cy.get(".page-head, .report-title, .standard-filter", { timeout: 20000 }).should("exist");
    });

    it("basic filter by ASN works", () => {
        cy.visit(route("report/asn-item-transition-trace"), { failOnStatusCode: false });
        cy.get("[data-fieldname='asn']", { timeout: 15000 }).should("exist");
        cy.get("[data-fieldname='asn']").type(seededData.asn_name);
        cy.get(".btn-primary").contains("Search").click();
        cy.get(".page-head, .report-table, .list-row", { timeout: 20000 }).should("exist");
    });
});
