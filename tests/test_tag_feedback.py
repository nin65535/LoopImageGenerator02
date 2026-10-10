import copy
import json
from dataclasses import asdict

import pytest

from backend.tag_feedback import update_tag_weights
from backend.tagging import parse_tags


def test_multiple_images_frequency_and_half_inheritance():
    result = update_tag_weights(
        {"liked": 0.2, "disliked": 0.2, "common": 0.8, "unseen": -0.6},
        liked=[{"liked": None, "common": None}, {"common": None}],
        disliked=[{"disliked": None, "common": None}, {"disliked": None}],
    )
    assert result.liked_frequency == {"common": 1, "liked": 0.5}
    assert result.disliked_frequency == {"common": 0.5, "disliked": 1}
    assert result.common_tags == ("common",)
    assert result.weights == pytest.approx(
        {"liked": 0.35, "disliked": -0.4, "common": 0.8, "unseen": -0.3}
    )
    assert result.positive == pytest.approx({"common": 0.8, "liked": 0.35})
    assert result.negative == pytest.approx({"disliked": 0.4, "unseen": 0.3})
    assert json.loads(json.dumps(asdict(result)))["inheritance_rate"] == 0.5


def test_disliked_only_removes_then_moves_to_negative():
    first = update_tag_weights({"cat": 1}, liked=[], disliked=[{"cat": None}])
    assert first.weights == first.positive == first.negative == {}
    second = update_tag_weights(first.weights, liked=[], disliked=[{"cat": None}])
    assert second.negative == {"cat": 0.5}


def test_liked_only_can_reverse_negative():
    result = update_tag_weights({"cat": -0.2}, liked=[{"cat": None}], disliked=[])
    assert result.positive == {"cat": 0.4}


def test_common_tags_preserve_prior_and_defer_new_tags():
    result = update_tag_weights(
        {"cat": -0.6},
        liked=[{"cat": None, "solo": None}],
        disliked=[{"cat": None, "solo": None}],
    )
    assert result.weights == {"cat": -0.6}
    assert result.common_tags == ("cat", "solo")


def test_empty_tags_count_in_denominator_and_confidence_is_ignored():
    result = update_tag_weights({}, liked=[{"cat": 0.01}, {}], disliked=[{}])
    assert result.liked_frequency == {"cat": 0.5}
    assert result.positive == {"cat": 0.25}
    assert update_tag_weights({"cat": 1}, liked=[{}], disliked=[]).weights == {"cat": 0.5}


def test_tagger_output_integration_and_input_snapshots():
    prior = {"red_hair": 0.2}
    liked = [parse_tags({"2": {"tags": ["solo, red_hair, solo"]}})]
    disliked = [parse_tags({"2": {"tags": ["blue_hair"]}})]
    snapshot = copy.deepcopy((prior, liked, disliked))
    result = update_tag_weights(prior, liked=liked, disliked=disliked)
    assert result.weights == {"blue_hair": -0.5, "red_hair": 0.6, "solo": 0.5}
    assert (prior, liked, disliked) == snapshot
    assert update_tag_weights(prior, liked=liked, disliked=disliked) == result


def test_no_selection_is_invalid():
    with pytest.raises(ValueError, match="At least one"):
        update_tag_weights({}, liked=[], disliked=[])


@pytest.mark.parametrize("weight", [True, None, "0.5", float("nan"), float("inf"), -1.1, 1.1])
def test_invalid_previous_weights(weight):
    with pytest.raises(ValueError, match="weights"):
        update_tag_weights({"cat": weight}, liked=[{}], disliked=[])


@pytest.mark.parametrize("tag", ["", " ", " cat", 1])
def test_invalid_tag_names(tag):
    with pytest.raises(ValueError, match="Tag names"):
        update_tag_weights({}, liked=[{tag: None}], disliked=[])
    with pytest.raises(ValueError, match="Tag names"):
        update_tag_weights({tag: 0.5}, liked=[{}], disliked=[])


def test_invalid_image_tags():
    with pytest.raises(ValueError, match="mapping"):
        update_tag_weights({}, liked=[None], disliked=[])
