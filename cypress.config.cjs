const path = require("path");

module.exports = {
  e2e: {
    supportFile: path.join(__dirname, "cypress", "support", "e2e.js"),
    specPattern: "cypress/integration/**/*.js",
    video: true,
    screenshotOnRunFailure: true,
    env: {
      routePrefix:
        process.env.FRAPPE_ROUTE_PREFIX ||
        process.env.CYPRESS_FRAPPE_ROUTE_PREFIX ||
        "app",
    },
  },
};
