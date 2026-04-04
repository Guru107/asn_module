const path = require("path");

module.exports = {
	e2e: {
		supportFile: path.join(__dirname, "cypress", "support", "e2e.js"),
		specPattern: "cypress/integration/**/*.js",
		video: true,
		screenshotOnRunFailure: true,
	},
};
