context("Barcode Process Flow nightly — standard handler coverage", () => {
	let matrix;

	before(() => {
		cy.seed_context("asn_module.utils.cypress_helpers.seed_standard_handler_dispatch_matrix").then(
			(result) => {
				matrix = result;
			}
		);
	});

	it("executes all supported standard handlers through scan dispatch", () => {
		expect(matrix).to.have.property("cases");
		expect(matrix.cases).to.be.an("array");
		expect(matrix.cases.length).to.be.greaterThan(0);

		cy.wrap(matrix.cases).each((handlerCase) => {
			cy.call("asn_module.qr_engine.dispatch.dispatch", {
				code: handlerCase.scan_code,
				device_info: "Cypress",
			}).then((response) => {
				const payload = response && response.message ? response.message : response;
				expect(payload.success).to.eq(true);
				expect(payload.action).to.eq(handlerCase.scan_action_key);
				expect(payload.step_name).to.be.a("string").and.not.be.empty;
				expect(payload.doctype).to.eq(handlerCase.expected_doctype);
				expect(payload.name).to.be.a("string").and.not.be.empty;
				expect(payload.url).to.be.a("string").and.include("/app/");
			});
		});
	});

	it("covers version-gated handler visibility", () => {
		expect(matrix).to.have.property("erp_major");
		expect(matrix.version_checks).to.be.an("object");
		if (matrix.erp_major >= 16) {
			expect(matrix.version_checks.mr_subcontracting_to_po_supported).to.eq(true);
		} else {
			expect(matrix.version_checks.mr_subcontracting_to_po_supported).to.eq(false);
		}
	});

	it("fails dispatch when a step condition is false", () => {
		expect(matrix.negative_cases).to.be.an("array").and.have.length.greaterThan(0);
		const negativeCase = matrix.negative_cases[0];

		cy.seed_context("asn_module.utils.cypress_helpers.dispatch_scan_for_test", {
			code: negativeCase.scan_code,
			device_info: "Cypress",
		}).then((payload) => {
			expect(payload.ok).to.eq(false);
			expect(payload.error).to.include("No eligible Barcode Process Flow step matched scan action");
		});
	});
});
