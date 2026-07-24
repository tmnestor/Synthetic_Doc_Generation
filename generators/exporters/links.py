"""Map the link ground truth to a FinBalance-style doc_refs convention.

Implements Mapping C of docs/GroundTruth_Export_Spec.md (section 6). No public
standard exists for cross-document links; this convention is defined by the spec.
"""

from generators.exporters.normalise import canonical_identifier, validate_identifier_form

QUAD_REF_KEYS: tuple[str, ...] = (
    "trust_return",
    "trust_income_schedule",
    "beneficiary_itr",
)

IDENTIFIER_LINK_FIELDS: frozenset[str] = frozenset({"trust_abn", "beneficiary_tfn"})


def transaction_links_to_doc_refs(data: dict, identifier_form: str) -> list[dict]:
    """Map transaction_links.yml to doc_refs records.

    Args:
        data: The parsed transaction_links.yml mapping. Each key is a source
            document image name; each value is a list of link dicts.
        identifier_form: 'spaced' or 'digits_only'. Transaction links carry no
            ABN or TFN, so this is never applied to any field here — but it is
            still validated unconditionally so a config typo fails fast on
            this path exactly as it already does on the trust-quad path,
            instead of being silently accepted.

    Returns:
        One record per link, flattened across sources.

    Raises:
        ValueError: If identifier_form is not a recognised identifier form.
    """
    validate_identifier_form(identifier_form)
    records = []
    for source_doc, links in data.items():
        for link in links:
            records.append(
                {
                    "link_type": "receipt_to_bank",
                    "source_doc": str(source_doc),
                    "target_doc": link["bank_statement"],
                    "match_keys": {
                        "supplier": link["supplier"],
                        "date": link["receipt_date"],
                        "amount": link["receipt_total"],
                    },
                    "target_evidence": {
                        "date": link["bank_date"],
                        "description": link["bank_description"],
                        "amount": link["bank_amount"],
                    },
                    "label": link["match_status"],
                    "difficulty": link["match_difficulty"],
                    "notes": link.get("notes", ""),
                }
            )
    return records


def trust_quads_to_doc_refs(data: dict, identifier_form: str, equality_form: str) -> list[dict]:
    """Map trust_distribution_links.yml to doc_refs records.

    The distribution statement is the anchor source_doc; the other three
    documents become the doc_refs list.

    Args:
        data: The parsed trust_distribution_links.yml mapping.
        identifier_form: 'spaced' or 'digits_only'. Applied to the ABN and TFN
            fields in `match_keys`, never to the amount fields.
        equality_form: 'spaced' or 'digits_only', from export_config.yml's
            abn_tfn_equality_form. Applied to a parallel
            `match_keys_equality` dict carrying only the two identifier
            fields (trust_abn, beneficiary_tfn), rendered in this form for
            downstream equality checks. Independent of identifier_form:
            `match_keys` keeps whatever human-readable form identifier_form
            selects, while `match_keys_equality` always uses equality_form.

    Returns:
        One record per quad. Each record carries both `match_keys` (all
        linking fields, ABN/TFN in identifier_form, amounts untouched) and
        `match_keys_equality` (ABN/TFN only, in equality_form).
    """
    records = []
    for source_doc, quad in data.items():
        match_keys = {}
        match_keys_equality = {}
        for key, value in quad["linking_fields"].items():
            text = str(value)
            if key in IDENTIFIER_LINK_FIELDS:
                match_keys[key] = canonical_identifier(text, identifier_form)
                match_keys_equality[key] = canonical_identifier(text, equality_form)
            else:
                match_keys[key] = text

        records.append(
            {
                "link_type": "trust_distribution_quad",
                "source_doc": str(source_doc),
                "doc_refs": [quad[key] for key in QUAD_REF_KEYS],
                "match_keys": match_keys,
                "match_keys_equality": match_keys_equality,
                "label": {
                    "compliance_status": quad["compliance_status"],
                    "discrepancy_type": quad["discrepancy_type"],
                    "discrepancy_details": quad["discrepancy_details"],
                    "match_status": quad["match_status"],
                },
            }
        )
    return records
