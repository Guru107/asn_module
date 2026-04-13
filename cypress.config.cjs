const path = require("path");

module.exports = {
  e2e: {
    // Always load app support so custom commands (e.g. cy.call_api) are registered.
    // App support itself requires Frappe's support file first.
    supportFile: path.join(__dirname, "cypress", "support", "e2e.js"),
    specPattern: (() => {
      const suite = process.env.E2E_SUITE || "smoke";
      if (suite === "nightly") return "cypress/integration/nightly/**/*.js";
      if (suite === "all") return "cypress/integration/**/*.js";
      return "cypress/integration/smoke/**/*.js";
    })(),
    video: true,
    screenshotOnRunFailure: true,
    env: {
      routePrefix:
        process.env.FRAPPE_ROUTE_PREFIX ||
        process.env.CYPRESS_FRAPPE_ROUTE_PREFIX ||
        "app",
      // Frappe cy.login() uses this; must match bench new-site --admin-password (see run_ephemeral_e2e.sh).
      adminPassword:
        process.env.CYPRESS_adminPassword ||
        process.env.EPHEMERAL_ADMIN_PASSWORD ||
        "admin",
    },
  },
};
