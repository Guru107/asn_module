const fs = require("fs");
const path = require("path");

function resolveSupportFile() {
  const candidates = [];
  if (process.env.BENCH_ROOT) {
    candidates.push(
      path.join(
        process.env.BENCH_ROOT,
        "apps",
        "frappe",
        "cypress",
        "support",
        "e2e.js"
      )
    );
  }
  // Repo root is the app dir under bench/apps/<app>/ — frappe is ../frappe
  candidates.push(
    path.join(__dirname, "..", "frappe", "cypress", "support", "e2e.js")
  );

  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      return p;
    }
  }
  return path.join(__dirname, "cypress", "support", "e2e.js");
}

module.exports = {
  e2e: {
    supportFile: resolveSupportFile(),
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
