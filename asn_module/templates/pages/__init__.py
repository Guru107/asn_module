"""Template page module aliases for case-variant imports."""

import sys

from asn_module.templates.pages import asn as _asn_page

# Ensure ``import asn_module.templates.pages.ASN`` resolves to ``asn`` module.
sys.modules[__name__ + ".ASN"] = _asn_page

