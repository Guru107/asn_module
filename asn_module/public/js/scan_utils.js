/* global asn_module */
frappe.provide("asn_module");

asn_module.parse_scan_input = function (value, copy) {
	const messages = Object.assign(
		{
			empty: __("Please scan or paste a scan code or Scan Station URL."),
			file: __(
				"You pasted an image file URL. Scan the QR or barcode so the scanner sends the code or URL."
			),
			missing_code: __(
				"Scanned URL is missing the code query parameter (expected ...scan-station?code=...)."
			),
		},
		copy || {}
	);
	const input = (value || "").trim();
	if (!input) {
		return { error: messages.empty };
	}

	try {
		const parsed = new URL(input, window.location.origin);
		const code_param = parsed.searchParams.get("code");
		if (code_param) {
			return { code: decodeURIComponent(code_param).trim() };
		}

		if (parsed.pathname && parsed.pathname.startsWith("/files/")) {
			return { error: messages.file };
		}

		if (/^https?:\/\//i.test(input)) {
			return { error: messages.missing_code };
		}
	} catch (e) {
		// Not a URL. Treat as raw scan code.
	}

	return { code: input.replace(/\s/g, "") };
};

asn_module.load_scan_code_length = function (apply_length) {
	frappe.call({
		method: "asn_module.qr_engine.scan_codes.get_scan_code_length",
		callback(r) {
			const value = Number(r.message);
			if (Number.isInteger(value) && value > 0) {
				apply_length(value);
			}
		},
		error(err) {
			apply_length(16);
			frappe.msgprint(__("Operation failed. Please retry or contact support."));
			console.error(err);
		},
	});
};
