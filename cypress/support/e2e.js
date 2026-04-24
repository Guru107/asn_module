// Load Frappe's Cypress support first so commands like `cy.login()` are registered.
// This app is expected to run inside a bench at `apps/asn_module`.
// eslint-disable-next-line import/no-unresolved
require("../../../frappe/cypress/support/e2e.js");

// Frappe login expects password as string; Cypress may coerce numeric env vars to number.
Cypress.Commands.overwrite("login", (originalFn, email, password) => {
	const resolvedPassword =
		typeof password !== "undefined" && password !== null
			? password
			: Cypress.env("adminPassword");
	const normalizedPassword = String(resolvedPassword ?? "");
	return originalFn(email, normalizedPassword);
});

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
