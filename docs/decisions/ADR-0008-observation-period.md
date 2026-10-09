# ADR-0008: Observation period derived from visits only

**Status:** accepted (Phase 2)

## Context
OBSERVATION_PERIOD says when a person's data is expected to be captured. It is the denominator for incidence and the window for washout or lookback (e.g. "≥365 days of prior observation"). Claims data derive it from insurance enrolment. EHR data have no enrolment, so it must be inferred.

## Decision
One period per person, from the first visit start to the last visit end, using **visits only**.

**Why visits only:** if the period were the span of *all* events, the DQ check "every event lies inside an observation period" would be true by construction and could never fail. Derived from visits, it is a real test of internal consistency. It fails on 23 records (0.002%), each **linked to a visit but timestamped 1–7 days after that visit's recorded end**: some screenings and vaccinations are written after the encounter closes in Synthea. That's a genuine source property, reported at *warn* severity.

## Limitations
- A single period per person ignores gaps in care. Synthea patients can have no visit for years, and those years still count as "observed". This inflates person-time for incidence-style analyses; Phase 3 will say so where relevant.
- `exporter.years_of_history` is not a hard cut-off (ADR-0005), so some periods start decades before most of the data.
- For deceased patients the period ends at the death-certification visit, up to 14 days after death.
