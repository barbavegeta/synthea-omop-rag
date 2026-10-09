import pandas as pd
import pytest

from rwe.evaluation import metrics

CHUNK = "Outpatient note, 2024-04-27:\nPMH: Viral sinusitis, diagnosed 2024-04-27; HbA1c 7.1 %."


@pytest.mark.parametrize(
    "item, expected",
    [
        (
            {"value": "Viral sinusitis first diagnosed", "date": "2024-04-27"},
            True,
        ),  # paraphrase + date
        ({"value": "7.1 %", "date": ""}, True),  # number stated
        ({"value": "Course completed", "date": ""}, False),  # not in this chunk
        ({"value": "HbA1c 8.4 %", "date": ""}, False),  # wrong number
        ({"value": "Viral sinusitis", "date": "2023-01-01"}, False),  # right words, wrong date
        ({"value": "Viral sinusitis", "date": ""}, True),  # words alone, no date claimed
        ({"value": "Asthma", "date": "2024-05-01"}, False),  # wrong both
    ],
)
def test_support_rule_accepts_paraphrase_but_rejects_unstated_claims(item, expected):
    assert metrics._supported(item, CHUNK) is expected


def test_grounding_maps_labels_to_the_chunks_shown():
    answers = pd.DataFrame(
        [
            {
                "run_name": "r",
                "question_id": "q",
                "person_id": 1,
                "shown_chunks": ["a", "b"],
                "response": {
                    "status": "answered",
                    "items": [
                        {
                            "value": "7.1 %",
                            "date": "",
                            "cited_chunks": ["C2"],
                        },  # cites b: supported
                        {
                            "value": "7.1 %",
                            "date": "",
                            "cited_chunks": ["C1"],
                        },  # cites a: not supported
                    ],
                },
            }
        ]
    )
    g = metrics.grounding(answers, {"a": "nothing relevant", "b": CHUNK})
    assert g["grounded"].tolist() == [1.0, 0.0]


def test_clustered_ci_resamples_patients_not_questions():
    # one patient with 9 correct answers, nine patients with 1 wrong each
    df = pd.DataFrame({"person_id": [0] * 9 + list(range(1, 10)), "correct": [1.0] * 9 + [0.0] * 9})
    mean, lo, hi = metrics.clustered_ci(df, "correct")
    assert mean == 0.5
    assert hi - lo > 0.5  # wide: effectively ten clusters, not eighteen independent answers


def test_abstention_counts_both_error_kinds():
    df = pd.DataFrame(
        {"gold_nd": [True, True, False, False], "abstained": [True, False, True, False]}
    )
    a = metrics.abstention(df)
    assert (a["precision"], a["recall"]) == (0.5, 0.5)
    assert (a["over_abstentions"], a["answered_unanswerable"]) == (1, 1)


def test_failure_classifier_order() -> None:
    from types import SimpleNamespace

    from rwe.evaluation.report import classify

    def row(**kw):
        base = dict(
            correct=0.0,
            response={"status": "answered"},
            gold_nd=False,
            abstained=False,
            evidence_shown=True,
            template="latest_lab",
        )
        return SimpleNamespace(**{**base, **kw})

    assert classify(row(correct=1.0)) is None
    assert classify(row(response=None)) == "no_valid_response"
    assert classify(row(gold_nd=True)) == "answered_unanswerable"
    assert classify(row(abstained=True)) == "over_abstention"
    assert classify(row(abstained=True, evidence_shown=False)) == "retrieval_miss"
    assert classify(row(evidence_shown=False, template="negation_trap")) == "retrieval_miss"
    assert classify(row(template="negation_trap")) == "negation_error"
    assert classify(row(template="family_trap")) == "family_attribution"
    assert classify(row(template="latest_lab")) == "temporal_error"
    assert classify(row(template="dx_date")) == "other"


def test_grounding_agreement_kappa(tmp_path) -> None:
    from rwe.evaluation.report import grounding_agreement

    assert grounding_agreement(tmp_path) is None
    col = "supported_by_excerpts (yes/no)"
    ids = ["c1", "c2", "c3", "c4", "c5"]
    pd.DataFrame({"claim_id": ids, col: ["yes", "Yes ", "no", "no", ""]}).to_csv(
        tmp_path / "grounding_sample_TO_LABEL.csv", index=False
    )
    pd.DataFrame({"claim_id": ids, "auto_grounded": [1, 1, 1, 0, 1]}).to_csv(
        tmp_path / "grounding_sample_auto_labels.csv", index=False
    )
    msg = grounding_agreement(tmp_path)  # c5 unlabelled -> ignored; 3 of 4 agree
    assert msg.startswith("- human") and "4 claims" in msg
    assert "agreement 0.75" in msg and "kappa 0.50" in msg and "disagreements: c3" in msg
