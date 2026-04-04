const path = require("path");

// Prefer BENCH_ROOT (GitHub Actions: app is linked from GITHUB_WORKSPACE, so ../../../frappe is wrong).
// Local bench: apps/<this-app>/cypress/support → ../../../frappe/cypress/support
const frappeSupport = process.env.BENCH_ROOT
	? path.join(
			process.env.BENCH_ROOT,
			"apps",
			"frappe",
			"cypress",
			"support",
			"e2e.js"
		)
	: path.join(__dirname, "..", "..", "..", "frappe", "cypress", "support", "e2e.js");
// eslint-disable-next-line import/no-dynamic-require, global-require
require(frappeSupport);
