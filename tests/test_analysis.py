from datetime import date

import pandas as pd

from rwe.analysis import t2dm


def test_small_counts_are_suppressed_but_zero_is_not():
    assert t2dm.count(3, 5) == "<5"
    assert t2dm.count(0, 5) == "0"
    assert t2dm.count(5, 5) == "5"
    assert t2dm.n_pct(4, 19, 5) == "<5"
    assert t2dm.n_pct(10, 20, 5) == "10 (50%)"
    assert t2dm.count(1, 0) == "1"  # min_cell_count 0 switches suppression off


def test_median_iqr_hides_statistics_from_too_few_people():
    assert t2dm.median_iqr(pd.Series([1, 2, 3]), 5) == "n<5, not shown"
    assert t2dm.median_iqr(pd.Series([1, 2, 3, 4, 5]), 5) == "3.0 [2.0, 4.0] (n=5)"
    assert t2dm.median_iqr(pd.Series([], dtype=float), 5) == "no data"


def hba1c_row(pid, value, plausible):
    return {
        "person_id": pid,
        "hba1c_pct": value,
        "plausible": plausible,
        "window_label": "1 baseline (-365 to 0 d)",
        "days_from_index": -30,
    }


def test_primary_excludes_implausible_and_sensitivity_keeps_them():
    # five people with plausible values, a sixth whose only value is implausible
    values = pd.DataFrame(
        [hba1c_row(pid, 7.0, True) for pid in range(1, 6)] + [hba1c_row(6, 2.5, False)]
    )
    primary = t2dm.hba1c_windows(values, plausible_only=True, min_cell=5)
    sensitivity = t2dm.hba1c_windows(values, plausible_only=False, min_cell=5)
    assert (primary.loc[0, "Persons"], primary.loc[0, "Values"]) == ("5", "5")
    assert (sensitivity.loc[0, "Persons"], sensitivity.loc[0, "Values"]) == ("6", "6")
    assert primary.loc[0, "Per-person mean HbA1c %, median [IQR]"] == "7.00 [7.00, 7.00] (n=5)"


def test_windows_on_an_empty_cohort_do_not_crash():
    empty = pd.DataFrame(
        columns=["person_id", "hba1c_pct", "plausible", "window_label", "days_from_index"]
    )
    assert len(t2dm.hba1c_windows(empty, plausible_only=True, min_cell=5)) == 0


def test_metformin_summary_counts_post_index_eras_only():
    base = pd.DataFrame(
        {
            "person_id": [1, 2, 3, 4, 5, 6],
            "index_date": [date(2020, 1, 1)] * 6,
            "exit_date": [date(2024, 1, 1)] * 6,
            "rx_metformin": [False] * 6,
        }
    )
    eras = pd.DataFrame(
        {
            "person_id": [1, 1, 2, 3, 4, 5, 6],
            "era_number": [1, 2, 1, 1, 1, 1, 1],
            "era_start_date": [
                date(2019, 6, 1),
                date(2020, 3, 1),
                date(2020, 1, 1),
                date(2021, 1, 1),
                date(2020, 2, 1),
                date(2020, 6, 1),
                date(2025, 1, 1),
            ],  # p6: after exit
            "era_end_date": [
                date(2019, 6, 30),
                date(2020, 3, 30),
                date(2020, 1, 30),
                date(2021, 1, 30),
                date(2020, 3, 1),
                date(2020, 6, 30),
                date(2025, 1, 30),
            ],
        }
    )
    summary = dict(t2dm.metformin_summary(base, eras, min_cell=5).values)
    assert summary["Started a metformin era on or after index (during follow-up)"] == "5 (83%)"
    assert summary["... of whom within 365 days of index"] == "<5"


def test_table1_handles_an_empty_cohort():
    empty = pd.DataFrame(columns=["person_id", "age_at_index"])
    assert t2dm.table1(empty, 5).values.tolist() == [["Persons", "0", ""]]
