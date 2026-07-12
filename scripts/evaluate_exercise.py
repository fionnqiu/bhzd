#!/usr/bin/env python3
"""Evaluate a curriculum exercise with deterministic, versioned rules."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


SUPPORTED_METHODS = {"exact_match", "ordered_exact_match", "allowed_answers"}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def serialize_result(result: dict[str, Any]) -> str:
    """Return the stable wire representation of an evaluation result."""
    return canonical_json(result)


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    return list(value)


def _require_unit_interval_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field} must be finite and within [0, 1]")
    return numeric


def _base_result(unit: dict[str, Any]) -> dict[str, Any]:
    exercise = unit.get("exercise")
    if not isinstance(exercise, dict):
        raise ValueError("unit.exercise must be an object")
    evaluation = exercise.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("unit.exercise.evaluation must be an object")
    return {
        "score": 0.0,
        "passed": False,
        "rule_refs": _require_string_list(unit.get("rule_refs"), "unit.rule_refs"),
        "capability_refs": _require_string_list(
            exercise.get("capability_refs"), "unit.exercise.capability_refs"
        ),
        "error_type": None,
        "feedback": "",
        "remediation": [],
        "manual_review_required": False,
        "data_version": _require_string(
            exercise.get("data_version"), "unit.exercise.data_version"
        ),
        "evaluation_version": _require_string(
            evaluation.get("version"), "unit.exercise.evaluation.version"
        ),
    }


def _incorrect_result(
    unit: dict[str, Any],
    result: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    error_types = _require_string_list(
        unit["exercise"].get("error_types"), "unit.exercise.error_types"
    )
    incorrect_feedback = evaluation.get("incorrect_feedback")
    if isinstance(incorrect_feedback, dict):
        error_type = incorrect_feedback.get(
            "error_type", evaluation.get("default_error_type", error_types[0])
        )
        feedback = _require_string(
            incorrect_feedback.get("feedback"),
            "unit.exercise.evaluation.incorrect_feedback.feedback",
        )
        remediation = _require_string_list(
            incorrect_feedback.get("remediation"),
            "unit.exercise.evaluation.incorrect_feedback.remediation",
        )
    else:
        error_type = evaluation.get("default_error_type", error_types[0])
        feedback = _require_string(
            incorrect_feedback, "unit.exercise.evaluation.incorrect_feedback"
        )
        remediation = _require_string_list(
            unit.get("remediation"), "unit.remediation"
        )
    if error_type not in error_types:
        raise ValueError("incorrect_feedback.error_type must be declared in error_types")
    result.update(
        {
            "error_type": error_type,
            "feedback": feedback,
            "remediation": remediation,
            "manual_review_required": bool(
                evaluation.get("manual_review_on_unmatched", False)
            ),
        }
    )
    return result


def _validate_allowed_answers(
    evaluation: dict[str, Any], error_types: list[str]
) -> list[dict[str, Any]]:
    allowed = evaluation.get("allowed_answers")
    if not isinstance(allowed, list) or not allowed:
        raise ValueError("allowed_answers evaluation requires at least one answer")
    canonical_answers: set[str] = set()
    for index, candidate in enumerate(allowed):
        if not isinstance(candidate, dict):
            raise ValueError(f"allowed_answers[{index}] must be an object")
        required = {
            "answer",
            "score",
            "manual_review_required",
            "error_type",
            "feedback",
            "remediation",
        }
        missing = sorted(required - candidate.keys())
        if missing:
            raise ValueError(
                f"allowed_answers[{index}] missing required field: {missing[0]}"
            )
        canonical = canonical_json(candidate["answer"])
        if canonical in canonical_answers:
            raise ValueError("allowed_answers contains duplicate canonical answers")
        canonical_answers.add(canonical)
        _require_unit_interval_number(
            candidate.get("score"), f"allowed_answers[{index}].score"
        )
        if not isinstance(candidate["manual_review_required"], bool):
            raise ValueError(
                f"allowed_answers[{index}].manual_review_required must be boolean"
            )
        error_type = candidate["error_type"]
        if error_type is not None and error_type not in error_types:
            raise ValueError(
                f"allowed_answers[{index}].error_type must be null or declared"
            )
        _require_string(candidate.get("feedback"), f"allowed_answers[{index}].feedback")
        _require_string_list(
            candidate["remediation"], f"allowed_answers[{index}].remediation"
        )
    return allowed


def _validate_diagnostic_rules(
    evaluation: dict[str, Any], error_types: list[str]
) -> list[dict[str, Any]]:
    rules = evaluation.get("diagnostic_rules", [])
    if not isinstance(rules, list):
        raise ValueError("diagnostic_rules must be a list")
    if rules:
        _require_string(
            evaluation.get("diagnostic_precedence"),
            "unit.exercise.evaluation.diagnostic_precedence",
        )
    canonical_submissions: set[str] = set()
    required = {"submission", "error_type", "feedback", "remediation"}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"diagnostic_rules[{index}] must be an object")
        missing = sorted(required - rule.keys())
        if missing:
            raise ValueError(
                f"diagnostic_rules[{index}] missing required field: {missing[0]}"
            )
        submission = canonical_json(rule["submission"])
        if submission in canonical_submissions:
            raise ValueError("diagnostic_rules contains duplicate canonical submissions")
        canonical_submissions.add(submission)
        if rule["error_type"] not in error_types:
            raise ValueError(
                f"diagnostic_rules[{index}].error_type must be declared in error_types"
            )
        _require_string(rule["feedback"], f"diagnostic_rules[{index}].feedback")
        _require_string_list(
            rule["remediation"], f"diagnostic_rules[{index}].remediation"
        )
        if "manual_review_required" in rule and not isinstance(
            rule["manual_review_required"], bool
        ):
            raise ValueError(
                f"diagnostic_rules[{index}].manual_review_required must be boolean"
            )
    return rules


def _diagnostic_result(
    result: dict[str, Any], rules: list[dict[str, Any]], submission: Any
) -> dict[str, Any] | None:
    submission_key = canonical_json(submission)
    for rule in rules:
        if canonical_json(rule["submission"]) != submission_key:
            continue
        diagnosed = dict(result)
        diagnosed.update(
            {
                "error_type": rule["error_type"],
                "feedback": rule["feedback"],
                "remediation": list(rule["remediation"]),
                "manual_review_required": rule.get(
                    "manual_review_required", False
                ),
            }
        )
        return diagnosed
    return None


def select_exercise(
    unit: dict[str, Any], exercise_id: str | None = None
) -> dict[str, Any]:
    """Return a unit view whose primary exercise is the requested variant."""
    primary = unit.get("exercise")
    if not isinstance(primary, dict):
        raise ValueError("unit.exercise must be an object")
    if exercise_id is None:
        return unit
    _require_string(exercise_id, "exercise_id")

    variants = unit.get("practice_variants", [])
    if not isinstance(variants, list) or any(
        not isinstance(variant, dict) for variant in variants
    ):
        raise ValueError("unit.practice_variants must be a list of objects")
    candidates = [primary, *variants]
    matches = [
        exercise
        for exercise in candidates
        if exercise.get("exercise_id") == exercise_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one exercise_id {exercise_id!r}, found {len(matches)}"
        )
    selected = dict(unit)
    selected["exercise"] = matches[0]
    return selected


def evaluate_unit(
    unit: dict[str, Any], submission: Any, exercise_id: str | None = None
) -> dict[str, Any]:
    """Evaluate one submission without time, randomness, I/O, or global state."""
    unit = select_exercise(unit, exercise_id)
    result = _base_result(unit)
    exercise = unit["exercise"]
    evaluation = exercise["evaluation"]
    method = evaluation.get("method")
    if method not in SUPPORTED_METHODS:
        raise ValueError(f"unsupported evaluation method: {method!r}")
    error_types = _require_string_list(
        exercise.get("error_types"), "unit.exercise.error_types"
    )
    diagnostic_rules = _validate_diagnostic_rules(evaluation, error_types)
    allowed_answers: list[dict[str, Any]] = []
    pass_score = 1.0
    if method == "allowed_answers":
        allowed_answers = _validate_allowed_answers(evaluation, error_types)
        pass_score = _require_unit_interval_number(
            evaluation.get("pass_score", 1.0),
            "unit.exercise.evaluation.pass_score",
        )

    diagnostic_keys = {
        canonical_json(rule["submission"]) for rule in diagnostic_rules
    }
    if method in {"exact_match", "ordered_exact_match"}:
        if "answer" not in exercise:
            raise ValueError("exact evaluation requires unit.exercise.answer")
        answer_keys = {canonical_json(exercise["answer"])}
    else:
        answer_keys = {
            canonical_json(candidate["answer"]) for candidate in allowed_answers
        }
    if diagnostic_keys & answer_keys:
        raise ValueError("diagnostic submission overlap with standard or allowed answer")

    diagnosed = _diagnostic_result(result, diagnostic_rules, submission)
    if diagnosed is not None:
        return diagnosed

    if method in {"exact_match", "ordered_exact_match"}:
        if canonical_json(submission) == canonical_json(exercise["answer"]):
            result.update(
                {
                    "score": 1.0,
                    "passed": True,
                    "feedback": evaluation.get("correct_feedback", "回答正确。"),
                }
            )
            return result
        return _incorrect_result(unit, result, evaluation)

    submission_key = canonical_json(submission)
    for candidate in allowed_answers:
        if canonical_json(candidate["answer"]) != submission_key:
            continue
        score = float(candidate["score"])
        manual_review = bool(candidate.get("manual_review_required", False))
        result.update(
            {
                "score": score,
                "passed": score >= pass_score and not manual_review,
                "error_type": candidate.get("error_type"),
                "feedback": candidate["feedback"],
                "remediation": list(candidate.get("remediation", [])),
                "manual_review_required": manual_review,
            }
        )
        return result
    return _incorrect_result(unit, result, evaluation)


def load_unit(path: Path, unit_id: str | None) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if "exercise" in document:
        if unit_id is not None and document.get("id") != unit_id:
            raise ValueError(f"unit {unit_id!r} was not found in {path}")
        return document
    units = document.get("units")
    if not isinstance(units, list):
        raise ValueError(f"{path} does not contain a unit or units array")
    if unit_id is None:
        raise ValueError("--unit-id is required for a teaching-unit collection")
    matches = [unit for unit in units if unit.get("id") == unit_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one unit {unit_id!r}, found {len(matches)}")
    return matches[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-file", type=Path, required=True)
    parser.add_argument("--unit-id")
    parser.add_argument("--exercise-id")
    parser.add_argument("--submission", required=True, help="Submission as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = load_unit(args.unit_file, args.unit_id)
    submission = json.loads(args.submission)
    output = serialize_result(
        evaluate_unit(unit, submission, exercise_id=args.exercise_id)
    )
    sys.stdout.buffer.write((output + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
