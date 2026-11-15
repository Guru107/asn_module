/* Shared helpers for the ASN supplier portal pages (list page + detail page). */
window.asnPortal =
	window.asnPortal ||
	(() => {
		function escapeHtmlText(s) {
			const d = document.createElement("div");
			d.textContent = s;
			return d.innerHTML;
		}

		/** Prefer Frappe msgprint modal on portal; fall back to alert if frappe-web bundle is not loaded. */
		function showPortalError(message, title) {
			const text = (message || "").trim();
			if (!text) return;
			if (window.frappe && typeof frappe.msgprint === "function") {
				frappe.msgprint({
					title: title,
					indicator: "red",
					message: `<p class="mb-0" style="white-space: pre-wrap;">${escapeHtmlText(
						text
					)}</p>`,
				});
				return;
			}
			window.alert(text);
		}

		function plainTextForAlert(raw) {
			if (raw == null || raw === "") return null;
			// DOMParser builds an inert document: no scripts run and no <img onerror> fires.
			const doc = new DOMParser().parseFromString(String(raw), "text/html");
			const t = (doc.body.textContent || "").replace(/\s+/g, " ").trim();
			return t || null;
		}

		/** First server message as plain text; the caller's fallback for bare failure payloads (exc_type/exception). */
		function parseServerError(data, fallback) {
			if (data) {
				if (data._server_messages) {
					try {
						const arr = JSON.parse(data._server_messages);
						for (const row of arr) {
							const o = typeof row === "string" ? JSON.parse(row) : row;
							if (o && o.message) return plainTextForAlert(o.message);
						}
					} catch (e) {
						/* ignore */
					}
				}
				if (typeof data.message === "string" && data.message.trim()) {
					return plainTextForAlert(data.message);
				}
			}
			return fallback || null;
		}

		/** Shared confirm → POST → error-or-redirect flow behind the cancel/delete buttons. */
		async function postAction(opts) {
			if (!opts.asnName || !confirm(opts.confirmMsg)) return;
			try {
				const res = await fetch(opts.path, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Accept: "application/json",
						"X-Frappe-CSRF-Token": opts.csrf,
					},
					credentials: "same-origin",
					body: JSON.stringify({ asn_name: opts.asnName }),
				});
				const data = await res.json();
				const inner = data.message !== undefined ? data.message : data;
				if (!res.ok || data.exc || (inner && inner.exc)) {
					showPortalError(parseServerError(data, opts.errorMsg), opts.errorTitle);
					return;
				}
				const redirect =
					typeof inner === "object" && inner.redirect
						? inner.redirect
						: opts.defaultRedirect;
				window.location.href = redirect;
			} catch (e) {
				showPortalError(opts.errorMsg, opts.errorTitle);
			}
		}

		/** Wire every button matching selector into the shared POST flow; opts carry the per-page messages. */
		function wireButtons(selector, opts) {
			document.querySelectorAll(selector).forEach((btn) => {
				btn.addEventListener("click", (ev) => {
					ev.preventDefault();
					ev.stopPropagation();
					void postAction(
						Object.assign({ asnName: btn.getAttribute("data-asn-name") || "" }, opts)
					);
				});
			});
		}

		return { escapeHtmlText, showPortalError, parseServerError, postAction, wireButtons };
	})();
