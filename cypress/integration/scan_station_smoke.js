context("ASN scan station", () => {
	before(() => {
		cy.login();
	});

	it("renders scan input", () => {
		cy.visit("/app/scan-station");
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
	});

	it("rejects legacy token URLs with a clear message", () => {
		cy.visit("/app/scan-station");
		cy.get(".scan-input", { timeout: 20000 }).should("be.visible");
		cy.get(".scan-input").clear();
		cy.get(".scan-input").type("https://example.com/api?token=old{enter}");
		cy.get(".scan-error", { timeout: 15000 }).should("be.visible");
		cy.get(".scan-error").should("contain", "old token");
	});
});
