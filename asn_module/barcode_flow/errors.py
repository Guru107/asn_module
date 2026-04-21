import frappe


class BarcodeFlowResolutionError(frappe.ValidationError):
	"""Base exception for barcode flow resolution failures."""


class NoMatchingFlowError(BarcodeFlowResolutionError):
	"""Raised when no active scope can resolve a flow for a context."""


class AmbiguousFlowScopeError(BarcodeFlowResolutionError):
	"""Raised when multiple flow scopes tie after deterministic tie-breaks."""
