"""Provisional tag feedback arithmetic, independent of generation and persistence."""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

INHERITANCE_RATE = 0.5


@dataclass(frozen=True)
class TagFeedback:
    liked_frequency: dict[str, float]
    disliked_frequency: dict[str, float]
    common_tags: tuple[str, ...]
    weights: dict[str, float]
    positive: dict[str, float]
    negative: dict[str, float]
    inheritance_rate: float = INHERITANCE_RATE


def _frequency(images: Sequence[Mapping[str, float | None]]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for tags in images:
        if not isinstance(tags, Mapping):
            raise ValueError("Image tags must be a mapping")
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip() or tag != tag.strip():
                raise ValueError("Tag names must be non-empty and trimmed")
        # Presence per image, not tagger confidence, determines frequency.
        counts.update(tags.keys())
    return {tag: counts[tag] / len(images) for tag in sorted(counts)}


def update_tag_weights(
    previous: Mapping[str, float],
    *,
    liked: Sequence[Mapping[str, float | None]],
    disliked: Sequence[Mapping[str, float | None]],
) -> TagFeedback:
    """Blend signed weights in [-1, 1] with per-group presence frequencies.

    Common tags retain their prior weight (new common tags remain undecided).
    Unobserved prior tags receive half their old weight. Negative output uses
    positive magnitudes. Empty tag maps count as images; no selection is invalid.
    Inputs are snapshots and are never modified. Image-ID validation belongs to
    the generation/save boundary, not this arithmetic layer.
    """
    if not liked and not disliked:
        raise ValueError("At least one liked or disliked image is required")
    prior = dict(previous)
    for tag, weight in prior.items():
        if not isinstance(tag, str) or not tag.strip() or tag != tag.strip():
            raise ValueError("Tag names must be non-empty and trimmed")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or not -1 <= weight <= 1
        ):
            raise ValueError("Previous tag weights must be finite numbers between -1 and 1")
    likes = _frequency(liked)
    dislikes = _frequency(disliked)
    common = likes.keys() & dislikes.keys()
    weights = {}
    for tag in sorted(prior.keys() | likes.keys() | dislikes.keys()):
        old = prior.get(tag, 0.0)
        evidence = old if tag in common else likes.get(tag, 0.0) - dislikes.get(tag, 0.0)
        weight = INHERITANCE_RATE * old + (1 - INHERITANCE_RATE) * evidence
        if weight != 0:
            weights[tag] = weight
    return TagFeedback(
        liked_frequency=likes,
        disliked_frequency=dislikes,
        common_tags=tuple(sorted(common)),
        weights=weights,
        positive={tag: weight for tag, weight in weights.items() if weight > 0},
        negative={tag: -weight for tag, weight in weights.items() if weight < 0},
    )
