context("Global scan shortcut", () => {
	beforeEach(() => {
		cy.login();
	});

	it("opens the Scan QR Code dialog on Ctrl+Shift+S", () => {
		cy.visit(`/${Cypress.env("routePrefix")}`);
		cy.window().its("frappe.ui.keys.handlers", { timeout: 20000 });
		cy.get("body").trigger("keydown", { keyCode: 83, ctrlKey: true, shiftKey: true });
		cy.contains(".modal.show .modal-title", "Scan QR Code", { timeout: 10000 }).should(
			"be.visible"
		);
		cy.contains(".modal.show", "Scan or paste code");
	});
});
