const fs = require("fs");
const path = require("path");

// Used only when cypress.config.cjs cannot find Frappe (e.g. misconfigured bench).
const candidates = [];
if (process.env.BENCH_ROOT) {
	candidates.push(
		path.join(process.env.BENCH_ROOT, "apps", "frappe", "cypress", "support", "e2e.js")
	);
}
candidates.push(path.join(__dirname, "..", "..", "..", "frappe", "cypress", "support", "e2e.js"));

const frappeSupport = candidates.find((p) => fs.existsSync(p));
if (!frappeSupport) {
	throw new Error(
		"Could not find Frappe cypress/support/e2e.js. Set BENCH_ROOT or install the app inside a bench (apps/<app>/cypress)."
	);
}
// eslint-disable-next-line import/no-dynamic-require, global-require
require(frappeSupport);
