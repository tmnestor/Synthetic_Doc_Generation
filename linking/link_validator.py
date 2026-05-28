"""Transaction link validator — scores predictions against ground truth.

Computes precision, recall, F1 at each difficulty level.

Ground truth format (transaction_links.yml):
    receipt_filename.png:
    - bank_statement: bank_filename.png
      bank_amount: "34.16"
      match_difficulty: easy
      ...

Prediction format:
    {receipt_filename: {"bank_statement": ..., "bank_amount": ...}}
"""

from dataclasses import dataclass, field


@dataclass
class DifficultyScore:
    """Scores for a single difficulty level."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class LinkScore:
    """Overall and per-difficulty linking scores."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    by_difficulty: dict[str, DifficultyScore] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class ComplianceScore:
    """Scores for trust distribution compliance detection."""

    total_compliant: int = 0
    total_non_compliant: int = 0
    true_compliant: int = 0
    true_non_compliant: int = 0
    false_positive_compliance: int = 0
    false_negative_compliance: int = 0
    correct_discrepancy_type: int = 0
    total_discrepancy_typed: int = 0

    @property
    def detection_rate(self) -> float:
        """Fraction of non-compliant cases correctly flagged."""
        return self.true_non_compliant / self.total_non_compliant if self.total_non_compliant > 0 else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Fraction of compliant cases incorrectly flagged."""
        return self.false_positive_compliance / self.total_compliant if self.total_compliant > 0 else 0.0

    @property
    def classification_accuracy(self) -> float:
        """Fraction of detected non-compliant cases with correct type."""
        return (
            self.correct_discrepancy_type / self.total_discrepancy_typed
            if self.total_discrepancy_typed > 0
            else 0.0
        )


@dataclass
class TrustDistributionScore:
    """Overall linking + compliance scores for trust distribution quads."""

    link_accuracy: float = 0.0
    total_quads: int = 0
    correct_quads: int = 0
    compliance: ComplianceScore = field(default_factory=ComplianceScore)


def validate_trust_distribution_links(
    ground_truth: dict,
    predictions: dict[str, dict],
) -> TrustDistributionScore:
    """Score trust distribution quad linking and compliance detection.

    Args:
        ground_truth: Dict from trust_distribution_links.yml, keyed by
            distribution statement filename.
        predictions: Dict mapping distribution_statement_filename ->
            {trust_return, trust_income_schedule, beneficiary_itr,
             linking_fields: {trust_abn, beneficiary_tfn, share_of_net_income,
                              franking_credit, capital_gain_component},
             compliance_status, discrepancy_type}.

    Returns:
        TrustDistributionScore with linking and compliance metrics.
    """
    score = TrustDistributionScore(total_quads=len(ground_truth))

    for ds_filename, gt_record in ground_truth.items():
        gt_compliance = gt_record.get("compliance_status", "compliant")
        gt_discrepancy = gt_record.get("discrepancy_type")

        if gt_compliance == "compliant":
            score.compliance.total_compliant += 1
        else:
            score.compliance.total_non_compliant += 1

        pred = predictions.get(ds_filename)
        if not pred:
            if gt_compliance == "non_compliant":
                score.compliance.false_negative_compliance += 1
            continue

        # Check quad linking (all 4 documents correctly identified)
        gt_linking = gt_record.get("linking_fields", {})
        pred_linking = pred.get("linking_fields", {})

        all_fields_match = True
        for key in (
            "trust_abn",
            "beneficiary_tfn",
            "share_of_net_income",
            "franking_credit",
            "capital_gain_component",
        ):
            gt_val = str(gt_linking.get(key, "")).replace(" ", "")
            pred_val = str(pred_linking.get(key, "")).replace(" ", "")
            if gt_val != pred_val:
                all_fields_match = False
                break

        docs_match = (
            pred.get("trust_return") == gt_record.get("trust_return")
            and pred.get("trust_income_schedule") == gt_record.get("trust_income_schedule")
            and pred.get("beneficiary_itr") == gt_record.get("beneficiary_itr")
        )

        if all_fields_match and docs_match:
            score.correct_quads += 1

        # Check compliance detection
        pred_compliance = pred.get("compliance_status", "compliant")
        pred_discrepancy = pred.get("discrepancy_type")

        if gt_compliance == "compliant":
            if pred_compliance == "compliant":
                score.compliance.true_compliant += 1
            else:
                score.compliance.false_positive_compliance += 1
        else:
            if pred_compliance == "non_compliant":
                score.compliance.true_non_compliant += 1
                score.compliance.total_discrepancy_typed += 1
                if pred_discrepancy == gt_discrepancy:
                    score.compliance.correct_discrepancy_type += 1
            else:
                score.compliance.false_negative_compliance += 1

    score.link_accuracy = score.correct_quads / score.total_quads if score.total_quads > 0 else 0.0
    return score


def validate_links(
    ground_truth: dict,
    predictions: dict[str, dict],
) -> LinkScore:
    """Score linking predictions against ground truth.

    Args:
        ground_truth: Dict keyed by receipt filename from transaction_links.yml.
            Each value is a list of link records with 'bank_statement',
            'bank_amount', and 'match_difficulty' fields.
        predictions: Dict mapping receipt_filename -> {bank_statement, bank_amount}.

    Returns:
        LinkScore with overall and per-difficulty metrics.
    """
    score = LinkScore()

    # Build lookup: receipt_filename -> (bank_statement, bank_amount, difficulty)
    gt_lookup: dict[str, tuple[str, str, str]] = {}
    for receipt_filename, link_list in ground_truth.items():
        link = link_list[0]
        gt_lookup[receipt_filename] = (
            link["bank_statement"],
            str(link["bank_amount"]),
            link.get("match_difficulty", "unknown"),
        )

    for receipt_filename, (gt_bank, gt_amount, difficulty) in gt_lookup.items():
        if difficulty not in score.by_difficulty:
            score.by_difficulty[difficulty] = DifficultyScore()

        pred = predictions.get(receipt_filename)
        if pred and pred["bank_statement"] == gt_bank and str(pred["bank_amount"]) == gt_amount:
            score.true_positives += 1
            score.by_difficulty[difficulty].true_positives += 1
        else:
            score.false_negatives += 1
            score.by_difficulty[difficulty].false_negatives += 1

    for receipt_filename in predictions:
        if receipt_filename not in gt_lookup:
            score.false_positives += 1

    return score
