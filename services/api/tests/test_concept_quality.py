import pytest
from pydantic import ValidationError

from app.domain.assessment_types import ConceptQuestion
from tests.integration.test_concept_check import candidate


@pytest.mark.parametrize(
    "options",
    [
        {"A": "继续执行符号合并。", "B": "继续 执行符号合并！", "C": "停止执行符号合并。"},
        {
            "A": "The merge process stops",
            "B": "The merge process does not stop",
            "C": "All of the above",
        },
    ],
)
def test_obvious_duplicate_or_meta_options_are_rejected(options: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ConceptQuestion.model_validate({**candidate(), "options": options})


def test_direct_negation_is_flagged_for_human_review_without_claiming_proof() -> None:
    from app.domain.assessment_types import ChoiceOptions, option_quality_notice

    notice = option_quality_notice(
        ChoiceOptions(A="合并过程停止", B="合并过程不停止", C="重新分配预算")
    )
    assert "直接否定" in notice and "未经独立语义验证" in notice


def test_unpaired_negation_is_not_reported_as_a_detected_contradiction() -> None:
    from app.domain.assessment_types import ChoiceOptions, option_quality_notice

    notice = option_quality_notice(
        ChoiceOptions(A="并不包含当前符号", B="根据频率选择符号", C="重新分配合并预算")
    )
    assert "检测到直接否定" not in notice


def test_punctuation_only_option_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ConceptQuestion.model_validate(
            {**candidate(), "options": {"A": "！！！！", "B": "停止执行合并", "C": "继续执行合并"}}
        )
