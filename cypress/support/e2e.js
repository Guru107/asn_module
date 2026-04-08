// Load Frappe's Cypress support first so commands like `cy.login()` are registered.
// This app is expected to run inside a bench at `apps/asn_module`.
// eslint-disable-next-line import/no-unresolved
require("../../../frappe/cypress/support/e2e.js");

Cypress.Commands.add("call_api", (method, args = {}) => {
	return cy.request({
		url: `/api/method/${method}`,
		method: "POST",
		body: args,
		form: true,
		headers: {
			Accept: "application/json",
		},
		failOnStatusCode: true,
	});
});
