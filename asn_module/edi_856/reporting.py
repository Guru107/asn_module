from asn_module.edi_856.validator import ComplianceFinding, ComplianceResult


def compliance_result_to_dict(result: ComplianceResult) -> dict:
	return {
		"is_compliant": result.is_compliant,
		"errors": [finding_to_dict(finding) for finding in result.errors],
		"warnings": [finding_to_dict(finding) for finding in result.warnings],
		"computed_metrics": dict(result.computed_metrics),
	}


def compliance_result_to_text(result: ComplianceResult) -> str:
	lines = [f"compliant={result.is_compliant}"]
	for label, findings in (("errors", result.errors), ("warnings", result.warnings)):
		for finding in findings:
			lines.append(
				f"{label}: {finding.rule_id} {finding.segment_tag}[{finding.segment_index}]"
				f" element={finding.element_index} {finding.message}"
			)
	return "\n".join(lines)


def finding_to_dict(finding: ComplianceFinding) -> dict:
	return {
		"rule_id": finding.rule_id,
		"severity": finding.severity,
		"message": finding.message,
		"segment_tag": finding.segment_tag,
		"segment_index": finding.segment_index,
		"element_index": finding.element_index,
		"fix_hint": finding.fix_hint,
	}
