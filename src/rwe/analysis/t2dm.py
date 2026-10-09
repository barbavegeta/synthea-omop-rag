"""Incident type 2 diabetes cohort: characterisation, metformin exposure, HbA1c over time.

The cohort and every feature are defined in SQL on the CDM (dbt models in the `results`
schema, ADR-0010). This module only summarises, applies small-cell suppression, plots
and writes the report. Output is deterministic (no timestamps), so reruns diff cleanly.

SYNTHETIC DATA: nothing here supports a clinical conclusion. The report says why.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402

# Chart tokens: reference palette of the dataviz method (light surface).
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SERIES_1, SERIES_2 = "#e1e0d9", "#c3c2b7", "#2a78d6", "#eb6834"

HISTORY = {
    "hx_hypertension": "Hypertension",
    "hx_dyslipidaemia": "Dyslipidaemia",
    "hx_obesity": "Obesity",
    "hx_prediabetes": "Prediabetes",
    "hx_ischaemic_heart_disease": "Ischaemic heart disease",
    "hx_chronic_kidney_disease": "Chronic kidney disease",
    "hx_diabetic_complication": "Diabetic kidney/eye/nerve complication",
}
DRUGS = {
    "rx_metformin": "Metformin",
    "rx_atc_a10_diabetes_drugs": "Any diabetes drug (ATC A10)",
    "rx_atc_c10_lipid_modifying": "Lipid-modifying agent (ATC C10)",
    "rx_atc_c09_ras_agents": "Renin-angiotensin agent (ATC C09)",
    "rx_atc_c07_beta_blockers": "Beta blocker (ATC C07)",
}


def fetch(conn: psycopg.Connection, query: str) -> pd.DataFrame:
    cur = conn.execute(query)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


# ---- formatting with small-cell suppression ----------------------------------------------


def count(n: int, min_cell: int) -> str:
    return f"<{min_cell}" if 0 < n < min_cell else str(n)


def n_pct(n: int, denom: int, min_cell: int) -> str:
    if 0 < n < min_cell:
        return f"<{min_cell}"
    return f"{n} ({100 * n / denom:.0f}%)" if denom else "0"


def median_iqr(values: pd.Series, min_cell: int, digits: int = 1) -> str:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) == 0:
        return "no data"
    if len(values) < min_cell:
        return f"n<{min_cell}, not shown"
    q1, med, q3 = values.quantile([0.25, 0.5, 0.75])
    return f"{med:.{digits}f} [{q1:.{digits}f}, {q3:.{digits}f}] (n={len(values)})"


# ---- tables -------------------------------------------------------------------------------


def table1(base: pd.DataFrame, min_cell: int) -> pd.DataFrame:
    n = len(base)
    rows = [("Persons", str(n), "")]
    if n == 0:
        return pd.DataFrame(rows, columns=["Characteristic", "Value", "Section"])
    age = pd.to_numeric(base["age_at_index"])
    rows += [
        ("Age at index, mean (SD)", f"{age.mean():.1f} ({age.std():.1f})", "Demographics"),
        ("Age at index, median [IQR]", median_iqr(age, min_cell, 0), "Demographics"),
    ]
    for col, label in (("sex", "Sex"), ("race", "Race"), ("ethnicity", "Ethnicity")):
        for level, k in base[col].value_counts().sort_index().items():
            rows.append((f"{label}: {level}", n_pct(int(k), n, min_cell), "Demographics"))
    for col, label in HISTORY.items():
        rows.append((label, n_pct(int(base[col].sum()), n, min_cell), "History on or before index"))
    for col, label in DRUGS.items():
        rows.append(
            (label, n_pct(int(base[col].sum()), n, min_cell), "Drugs in 365 days before index")
        )
    rows += [
        (
            "BMI, kg/m2",
            median_iqr(base["baseline_bmi"], min_cell),
            "Last value in 365 days before index",
        ),
        (
            "HbA1c %, plausible values only (primary)",
            median_iqr(base["baseline_hba1c"], min_cell, 2),
            "Last value in 365 days before index",
        ),
        (
            "HbA1c %, all values (sensitivity)",
            median_iqr(base["baseline_hba1c_all_values"], min_cell, 2),
            "Last value in 365 days before index",
        ),
        (
            "Follow-up, years",
            median_iqr(pd.to_numeric(base["follow_up_days"]) / 365.25, min_cell),
            "Index to end of observation or death",
        ),
    ]
    return pd.DataFrame(rows, columns=["Characteristic", "Value", "Section"])


def metformin_summary(base: pd.DataFrame, eras: pd.DataFrame, min_cell: int) -> pd.DataFrame:
    n = len(base)
    if n == 0:
        return pd.DataFrame([("Persons", "0")], columns=["Measure", "Value"])
    eras = eras.merge(base[["person_id", "index_date", "exit_date"]], on="person_id")
    post = eras[
        (eras["era_start_date"] >= eras["index_date"])
        & (eras["era_start_date"] <= eras["exit_date"])
    ].copy()
    first = post.sort_values("era_start_date").groupby("person_id").head(1).copy()
    first["days_to_start"] = (
        pd.to_datetime(first["era_start_date"]) - pd.to_datetime(first["index_date"])
    ).dt.days
    first["era_days"] = (
        pd.to_datetime(first["era_end_date"]) - pd.to_datetime(first["era_start_date"])
    ).dt.days + 1
    within_year = int((first["days_to_start"] <= 365).sum())
    rows = [
        ("Cohort persons", str(n)),
        (
            "Metformin in the 365 days before index",
            n_pct(int(base["rx_metformin"].sum()), n, min_cell),
        ),
        (
            "Started a metformin era on or after index (during follow-up)",
            n_pct(len(first), n, min_cell),
        ),
        ("... of whom within 365 days of index", n_pct(within_year, n, min_cell)),
        (
            "Days from index to first metformin era, median [IQR]",
            median_iqr(first["days_to_start"], min_cell, 0),
        ),
        (
            "Length of first metformin era in days, median [IQR]",
            median_iqr(first["era_days"], min_cell, 0),
        ),
        (
            "Metformin eras per treated person, median [IQR]",
            median_iqr(post.groupby("person_id").size(), min_cell, 0),
        ),
    ]
    return pd.DataFrame(rows, columns=["Measure", "Value"])


def hba1c_windows(values: pd.DataFrame, plausible_only: bool, min_cell: int) -> pd.DataFrame:
    """Per window: persons contributing, values, median [IQR] of per-person mean HbA1c."""
    # astype(bool): on an empty frame the column is object dtype, and df[series] would then
    # be read as a list of column labels instead of a boolean mask
    v = values[values["plausible"].astype(bool)] if plausible_only else values
    rows = []
    for label, grp in v.dropna(subset=["window_label"]).groupby("window_label", sort=True):
        per_person = grp.groupby("person_id")["hba1c_pct"].mean()
        name = label.split(" ", 1)[1]
        if label.startswith("6"):
            name += " (beyond the 5-year horizon; not interpreted)"
        rows.append(
            (
                name,
                count(per_person.size, min_cell),
                str(len(grp)),
                median_iqr(per_person, min_cell, 2),
            )
        )
    return pd.DataFrame(
        rows,
        columns=["Window from index", "Persons", "Values", "Per-person mean HbA1c %, median [IQR]"],
    )


# ---- figure -------------------------------------------------------------------------------


HORIZON_YEARS = 5  # chosen after inspecting follow-up (up to ~48 y for a few people); see report


def plot_hba1c(values: pd.DataFrame, path: Path, min_cell: int) -> None:
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    v = values.assign(
        years=pd.to_numeric(values["days_from_index"]) / 365.25,
        hba1c=pd.to_numeric(values["hba1c_pct"]),
    )
    beyond = int((v["years"] > HORIZON_YEARS).sum())
    v = v[v["years"] <= HORIZON_YEARS]

    for i, (_, grp) in enumerate(v.sort_values("years").groupby("person_id")):
        ax.plot(
            grp["years"],
            grp["hba1c"],
            color=BASELINE,
            linewidth=1,
            zorder=1,
            label="Individual patients (all values)" if i == 0 else None,
        )

    excluded = v[~v["plausible"]]
    if len(excluded):
        ax.scatter(
            excluded["years"],
            excluded["hba1c"],
            s=36,
            facecolors="none",
            edgecolors=SERIES_2,
            linewidths=1.5,
            marker="o",
            zorder=3,
            label=f"Excluded from primary analysis: below 3% ({len(excluded)} values shown)",
        )

    primary = v[v["plausible"]].dropna(subset=["window_label"])
    pts = []
    for _, grp in primary.groupby("window_label", sort=True):
        per_person = grp.groupby("person_id")["hba1c"].mean()
        if per_person.size >= max(min_cell, 1):
            pts.append((grp["years"].median(), per_person.median()))
    if pts:
        xs, ys = zip(*pts, strict=True)
        ax.plot(
            xs,
            ys,
            color=SERIES_1,
            linewidth=2,
            marker="o",
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            zorder=4,
            label="Median of per-patient window means (primary analysis)",
        )

    ax.set_xlim(-1.1, HORIZON_YEARS + 0.1)
    for y, text, style in (
        (6.5, "6.5%: diagnostic threshold", "--"),
        (3.0, "3%: plausibility floor", ":"),
    ):
        ax.axhline(y, color=MUTED, linewidth=1, linestyle=style, zorder=2)
        ax.text(-1.05, y + 0.05, text, color=INK_2, fontsize=8, va="bottom", ha="left")

    ax.axvline(0, color=BASELINE, linewidth=1, zorder=0)
    ax.set_xlabel(
        f"Years from index date (first type 2 diabetes record); {beyond} values beyond "
        f"{HORIZON_YEARS} years not shown",
        color=INK_2,
        fontsize=9,
    )
    ax.set_ylabel("HbA1c (%)", color=INK_2, fontsize=9)
    ax.set_title(
        "HbA1c around type 2 diabetes diagnosis - SYNTHETIC data, no clinical meaning",
        color=INK,
        fontsize=11,
        loc="left",
    )
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_ylim(2.3, 8.6)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


# ---- report -------------------------------------------------------------------------------


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if len(df) else "_(empty)_"


def run(conn: psycopg.Connection, out_dir: Path, min_cell: int, fingerprint: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    attrition = fetch(
        conn, "select step, criterion, persons from results.t2dm_attrition order by step"
    )
    base = fetch(conn, "select * from results.t2dm_baseline order by person_id")
    eras = fetch(conn, "select * from results.t2dm_metformin_eras order by person_id, era_number")
    values = fetch(conn, "select * from results.t2dm_hba1c order by person_id, measurement_date")
    source = fetch(conn, "select vocabulary_version from cdm.cdm_source")
    # Evidence for the "no diabetes signal" statement: HbA1c in everyone, by T2DM status.
    signal = fetch(
        conn,
        """
        select case when t.person_id is null then 'No type 2 diabetes record'
                    else 'Type 2 diabetes record (any time)' end as group_,
               count(distinct m.person_id) as persons, count(*) as hba1c_values,
               round(percentile_disc(0.5) within group (order by m.value_as_number)::numeric, 2)
                   as median_pct,
               round(100.0 * avg((m.value_as_number >= 6.5)::int), 1) as pct_values_ge_6_5
        from cdm.measurement m
        join results.concept_set_members cs
          on cs.concept_id = m.measurement_concept_id and cs.concept_set = 'hba1c'
        left join (select distinct co.person_id from cdm.condition_occurrence co
                   join results.concept_set_members s
                     on s.concept_id = co.condition_concept_id and s.concept_set = 't2dm') t
               on t.person_id = m.person_id
        group by 1 order by 1""",
    )

    attrition["persons"] = attrition["persons"].map(lambda k: count(int(k), min_cell))
    t1 = table1(base, min_cell)
    met = metformin_summary(base, eras, min_cell)
    primary = hba1c_windows(values, plausible_only=True, min_cell=min_cell)
    sensitivity = hba1c_windows(values, plausible_only=False, min_cell=min_cell)
    if len(values):
        plot_hba1c(values, out_dir / "hba1c_trajectories.png", min_cell)

    n_excluded = int((~values["plausible"]).sum()) if len(values) else 0
    hb = values.assign(hba1c=pd.to_numeric(values["hba1c_pct"])) if len(values) else values

    def window_median(prefix: str) -> str:
        if not len(hb):
            return "n/a"
        w = hb[hb["plausible"] & hb["window_label"].fillna("").str.startswith(prefix)]
        per_person = w.groupby("person_id")["hba1c"].mean()
        return f"{per_person.median():.2f}%" if per_person.size >= max(min_cell, 1) else "n/a"

    late_below_floor = (
        int((~hb["plausible"] & (hb["window_label"] == "6 >5 years")).sum()) if len(hb) else 0
    )
    late_total = int((hb["window_label"] == "6 >5 years").sum()) if len(hb) else 0
    no_t2dm = signal[signal["group_"].str.startswith("No")]
    no_t2dm_median = f"{no_t2dm['median_pct'].iloc[0]}%" if len(no_t2dm) else "n/a"
    vocab = source["vocabulary_version"].iloc[0] if len(source) else "unknown"
    sections = [
        "# Incident type 2 diabetes: metformin exposure and HbA1c over time",
        "> **Synthetic data (Synthea). This analysis demonstrates OMOP CDM methodology; "
        "it supports no clinical conclusion.** Synthea's HbA1c follows simulator rules, not "
        "physiology (see *What this does and does not show*).",
        f"Vocabulary: `{vocab}` - config fingerprint `{fingerprint}` - small-cell suppression: "
        f"counts below {min_cell} shown as `<{min_cell}`. Cohort definition: ADR-0010.",
        "## Cohort attrition",
        md(attrition),
        "## Baseline characteristics (Table 1)",
        md(t1),
        "## Metformin exposure",
        "Exposures are joined into eras with the OHDSI DRUG_ERA rule (gaps of 30 days or less "
        "merge). Each prescription counts as a 30-day exposure (THEMIS convention, ADR-0007), "
        "so era lengths inherit that assumption.",
        md(met),
        "## HbA1c over time",
        "Per window, each person's values are averaged, then the median [IQR] across persons "
        f"is reported. The primary analysis excludes {n_excluded} values below the 3% "
        "plausibility floor (Phase 2 data-quality rule); the sensitivity analysis keeps them.\n\n"
        f"**Analysis horizon: {HORIZON_YEARS} years after index. This was decided after looking "
        "at the data, not pre-specified.** A few people have follow-up of several decades with "
        "sparse values, and an open-ended last window made the plotted median imply a "
        "trend across 35 years. The >5-year row is still reported, but not interpreted.",
        "### Primary (plausible values)",
        md(primary),
        "### Sensitivity (all values)",
        md(sensitivity),
        "![HbA1c trajectories](hba1c_trajectories.png)" if len(values) else "",
        "## What this does and does not show",
        "HbA1c across the whole synthetic population, by type 2 diabetes status:",
        md(signal),
        "What is plausible: around diagnosis, this cohort's HbA1c is in the diabetic range "
        f"(baseline median of per-person means {window_median('1')}, 1-2 years "
        f"{window_median('4')}), so Synthea does model HbA1c rising to a diagnosis.\n\n"
        "What is not: over long follow-up, values drift down well below the diabetic range "
        f"(beyond 5 years after index: {window_median('6')}, with {late_below_floor} of "
        f"{late_total} values under the 3% plausibility floor; this is a data-quality "
        "observation, outside the analysis horizon); people with no diabetes record "
        f"have a median of {no_t2dm_median}, below the usual adult range; and within a person "
        "values move in smooth monotone steps. The trajectory is produced by Synthea's "
        "disease-module rules, not by physiology or by any drug. **So no statement about "
        "glycaemic control or metformin effect can be made from these numbers**, and a "
        "before/after comparison around metformin would only recover the simulator's rules.\n\n"
        "What the analysis does show is the method: concept sets with descendants, an "
        "incident cohort with an observed look-back, attrition, time-anchored covariates, "
        "drug eras, measurement windows relative to index, a pre-specified plausibility rule "
        "with a sensitivity analysis, and small-cell suppression.",
        "## Limitations",
        "- n is small (see attrition); estimates are descriptive only, with no inference.\n"
        "- The observed look-back (one visit in the prior year) cannot guarantee incidence: "
        "earlier diagnoses outside the exported history window would be missed (ADR-0005).\n"
        "- The single observation period per person counts gaps in care as observed time "
        "(ADR-0008).\n"
        "- Drug era lengths depend on the 30-day prescription assumption (ADR-0007).\n"
        "- Only primary small-cell suppression is applied. A suppressed cell can sometimes be "
        "recovered from its complement (e.g. a race category where the other categories are "
        "shown). Releasing real data would need complementary suppression too; it is not "
        "implemented here because the data are synthetic.",
    ]
    (out_dir / "report.md").write_text("\n\n".join(s for s in sections if s) + "\n")
    attrition.to_csv(out_dir / "attrition.csv", index=False)
    t1.to_csv(out_dir / "table1.csv", index=False)
    met.to_csv(out_dir / "metformin.csv", index=False)
    primary.to_csv(out_dir / "hba1c_windows_primary.csv", index=False)
    sensitivity.to_csv(out_dir / "hba1c_windows_sensitivity.csv", index=False)
    return {
        "cohort_persons": len(base),
        "hba1c_values": len(values),
        "hba1c_excluded_implausible": n_excluded,
        "output_dir": str(out_dir),
    }
