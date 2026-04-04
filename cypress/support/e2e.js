const path = require("path");

// Bench layout: apps/<this-app>/cypress/support → apps/frappe/cypress/support
const frappeSupport = path.join(__dirname, "..", "..", "..", "frappe", "cypress", "support", "e2e.js");
// eslint-disable-next-line import/no-dynamic-require, global-require
require(frappeSupport);
