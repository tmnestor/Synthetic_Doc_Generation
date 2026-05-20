"""Transaction link validator — scores predictions against ground truth.

Computes precision, recall, F1 at each difficulty level.
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


def validate_links(
    ground_truth: dict,
    predictions: dict[str, dict],
) -> LinkScore:
    """Score linking predictions against ground truth.

    Args:
        ground_truth: Dict of link entries from transaction_links.yml.
        predictions: Dict mapping source_id -> {target_id, target_transaction_index}.

    Returns:
        LinkScore with overall and per-difficulty metrics.
    """
    score = LinkScore()

    gt_lookup: dict[str, tuple[str, int, str]] = {}
    for _link_id, link in ground_truth.items():
        src = link["source_id"]
        gt_lookup[src] = (
            link["target_id"],
            link["target_transaction_index"],
            link.get("match_difficulty", "unknown"),
        )

    for src, (gt_target, gt_idx, difficulty) in gt_lookup.items():
        if difficulty not in score.by_difficulty:
            score.by_difficulty[difficulty] = DifficultyScore()

        pred = predictions.get(src)
        if pred and pred["target_id"] == gt_target and pred["target_transaction_index"] == gt_idx:
            score.true_positives += 1
            score.by_difficulty[difficulty].true_positives += 1
        else:
            score.false_negatives += 1
            score.by_difficulty[difficulty].false_negatives += 1

    for src in predictions:
        if src not in gt_lookup:
            score.false_positives += 1

    return score
