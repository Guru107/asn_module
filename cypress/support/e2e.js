// Load Frappe's Cypress support first so commands like `cy.login()` are registered.
// This app is expected to run inside a bench at `apps/asn_module`.
// eslint-disable-next-line import/no-unresolved
require("../../../frappe/cypress/support/e2e.js");

Cypress.Commands.add("call_api", (method, args = {}) => {
	const hasArgs = Object.keys(args || {}).length > 0;
	return cy
		.request({
			url: `/api/method/${method}`,
			method: hasArgs ? "POST" : "GET",
			body: hasArgs ? args : undefined,
			form: hasArgs,
			headers: { Accept: "application/json" },
			failOnStatusCode: true,
		})
		.then((response) => {
			// Keep specs simple: return method payload directly.
			return response.body && response.body.message ? response.body.message : response.body;
		});
});

/** Vehicle Number is mandatory on ASN validate(); portal nightly specs must set it before Save. */
Cypress.Commands.add("fill_portal_asn_vehicle", () => {
	cy.get("form#single-asn-form input[name='vehicle_number']", { timeout: 20000 })
		.clear()
		.type("MH12AB1234");
});

Cypress.Commands.add("seed_context", (method, args = {}) => {
	const routePrefix = (Cypress.env("routePrefix") || "app").replace(/^\/+/, "") || "app";
	return cy
		.login()
		.visit(`/${routePrefix}`, { failOnStatusCode: false })
		.window()
		.its("frappe.csrf_token")
		.should("be.a", "string")
		.then(() => cy.call(method, args))
		.then((result) => (result && result.message ? result.message : result));
});
