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

// Ephemeral E2E sites set ignore_csrf=1 (run_ephemeral_e2e.sh). Use cy.call (in-browser) after
// one Desk visit so seeding shares the logged-in session; skip the csrf_token wait.
Cypress.Commands.add("seed_context", (method, args = {}) => {
	const routePrefix = (Cypress.env("routePrefix") || "app").replace(/^\/+/, "") || "app";
	return cy
		.login()
		.visit(`/${routePrefix}`, { failOnStatusCode: false })
		.then(() => cy.call(method, args))
		.then((result) => (result && result.message ? result.message : result));
});
