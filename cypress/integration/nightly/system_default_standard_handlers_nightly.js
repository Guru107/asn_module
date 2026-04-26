context("System default flow nightly — standard handler submit generation", () => {
	let contextData;

	before(() => {
		cy.seed_context(
			"asn_module.utils.cypress_helpers.seed_default_standard_handler_submit_context"
		).then((result) => {
			contextData = result;
		});
	});

	it("uses System::Default::StandardHandlers and generates MR scan codes on submit", () => {
		expect(contextData.flow_name).to.eq("System::Default::StandardHandlers");
		expect(contextData.material_request).to.be.a("string").and.not.be.empty;
		expect(contextData.scan_codes).to.be.an("array").and.have.length.greaterThan(0);
		expect(contextData.action_keys).to.include("mr_purchase_to_po");
	});
});
