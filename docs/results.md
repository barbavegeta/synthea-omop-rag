# Test-set results

Synthetic data (Synthea): these numbers describe this pipeline on synthetic, templated notes, not clinical performance. 95% CIs are patient-clustered bootstraps (ADR-0015).

## Retrieval (all configurations; no LLM involved)
| corpus   | mode           |   questions |   recall@1 |   recall@3 |   recall@5 |   recall@10 |   MRR |
|:---------|:---------------|------------:|-----------:|-----------:|-----------:|------------:|------:|
| clean    | bm25           |        1016 |      0.69  |      0.796 |      0.845 |       0.903 | 0.76  |
| clean    | dense          |        1016 |      0.564 |      0.666 |      0.719 |       0.781 | 0.638 |
| clean    | hybrid         |        1016 |      0.645 |      0.746 |      0.775 |       0.846 | 0.712 |
| clean    | hybrid_recency |        1016 |      0.8   |      0.875 |      0.894 |       0.902 | 0.843 |
| messy    | bm25           |        1016 |      0.586 |      0.757 |      0.831 |       0.898 | 0.692 |
| messy    | dense          |        1016 |      0.53  |      0.645 |      0.71  |       0.793 | 0.615 |
| messy    | hybrid         |        1016 |      0.576 |      0.729 |      0.806 |       0.898 | 0.678 |
| messy    | hybrid_recency |        1016 |      0.781 |      0.889 |      0.913 |       0.932 | 0.84  |

| corpus   | mode           | recall@5 [95% CI]    |
|:---------|:---------------|:---------------------|
| clean    | bm25           | 0.845 [0.824, 0.865] |
| clean    | dense          | 0.719 [0.694, 0.743] |
| clean    | hybrid         | 0.775 [0.752, 0.796] |
| clean    | hybrid_recency | 0.894 [0.875, 0.912] |
| messy    | bm25           | 0.831 [0.807, 0.853] |
| messy    | dense          | 0.710 [0.683, 0.736] |
| messy    | hybrid         | 0.806 [0.782, 0.829] |
| messy    | hybrid_recency | 0.913 [0.895, 0.931] |

## Answer accuracy
| run_name                  |    n |   patients | correct              |
|:--------------------------|-----:|-----------:|:---------------------|
| test-clean-bm25           | 1200 |        150 | 0.908 [0.892, 0.923] |
| test-clean-dense          | 1200 |        150 | 0.827 [0.806, 0.846] |
| test-clean-hybrid         | 1200 |        150 | 0.867 [0.849, 0.884] |
| test-clean-hybrid_recency | 1200 |        150 | 0.925 [0.912, 0.938] |
| test-messy-hybrid_recency | 1200 |        150 | 0.942 [0.927, 0.955] |

### By template
| run_name                  | template                 |   n |   patients | correct              |
|:--------------------------|:-------------------------|----:|-----------:|:---------------------|
| test-clean-bm25           | condition_current        |  85 |         85 | 0.988 [0.965, 1.000] |
| test-clean-bm25           | condition_historical     |  95 |         95 | 0.663 [0.558, 0.758] |
| test-clean-bm25           | current_medications      | 150 |        150 | 0.980 [0.953, 1.000] |
| test-clean-bm25           | dx_date                  | 150 |        150 | 0.947 [0.907, 0.980] |
| test-clean-bm25           | family_history           |  96 |         96 | 1.000 [1.000, 1.000] |
| test-clean-bm25           | family_trap              |  79 |         79 | 0.886 [0.810, 0.949] |
| test-clean-bm25           | lab_not_documented       | 125 |        125 | 1.000 [1.000, 1.000] |
| test-clean-bm25           | latest_lab               | 150 |        150 | 0.633 [0.553, 0.707] |
| test-clean-bm25           | negation_trap            | 150 |        150 | 0.987 [0.967, 1.000] |
| test-clean-bm25           | stop_reason              |  61 |         61 | 1.000 [1.000, 1.000] |
| test-clean-bm25           | stop_reason_undocumented |  59 |         59 | 1.000 [1.000, 1.000] |
| test-clean-dense          | condition_current        |  85 |         85 | 0.953 [0.906, 0.988] |
| test-clean-dense          | condition_historical     |  95 |         95 | 0.537 [0.432, 0.632] |
| test-clean-dense          | current_medications      | 150 |        150 | 0.847 [0.787, 0.900] |
| test-clean-dense          | dx_date                  | 150 |        150 | 0.880 [0.827, 0.927] |
| test-clean-dense          | family_history           |  96 |         96 | 1.000 [1.000, 1.000] |
| test-clean-dense          | family_trap              |  79 |         79 | 0.924 [0.861, 0.975] |
| test-clean-dense          | lab_not_documented       | 125 |        125 | 1.000 [1.000, 1.000] |
| test-clean-dense          | latest_lab               | 150 |        150 | 0.300 [0.227, 0.373] |
| test-clean-dense          | negation_trap            | 150 |        150 | 0.953 [0.920, 0.987] |
| test-clean-dense          | stop_reason              |  61 |         61 | 0.984 [0.951, 1.000] |
| test-clean-dense          | stop_reason_undocumented |  59 |         59 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | condition_current        |  85 |         85 | 0.976 [0.941, 1.000] |
| test-clean-hybrid         | condition_historical     |  95 |         95 | 0.558 [0.453, 0.653] |
| test-clean-hybrid         | current_medications      | 150 |        150 | 0.927 [0.887, 0.967] |
| test-clean-hybrid         | dx_date                  | 150 |        150 | 0.927 [0.880, 0.967] |
| test-clean-hybrid         | family_history           |  96 |         96 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | family_trap              |  79 |         79 | 0.949 [0.899, 0.987] |
| test-clean-hybrid         | lab_not_documented       | 125 |        125 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | latest_lab               | 150 |        150 | 0.420 [0.340, 0.507] |
| test-clean-hybrid         | negation_trap            | 150 |        150 | 0.980 [0.953, 1.000] |
| test-clean-hybrid         | stop_reason              |  61 |         61 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | stop_reason_undocumented |  59 |         59 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | condition_current        |  85 |         85 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | condition_historical     |  95 |         95 | 0.905 [0.842, 0.958] |
| test-clean-hybrid_recency | current_medications      | 150 |        150 | 0.973 [0.947, 0.993] |
| test-clean-hybrid_recency | dx_date                  | 150 |        150 | 0.927 [0.880, 0.967] |
| test-clean-hybrid_recency | family_history           |  96 |         96 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | family_trap              |  79 |         79 | 0.949 [0.899, 0.987] |
| test-clean-hybrid_recency | lab_not_documented       | 125 |        125 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | latest_lab               | 150 |        150 | 0.607 [0.527, 0.680] |
| test-clean-hybrid_recency | negation_trap            | 150 |        150 | 0.980 [0.953, 1.000] |
| test-clean-hybrid_recency | stop_reason              |  61 |         61 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | stop_reason_undocumented |  59 |         59 | 1.000 [1.000, 1.000] |
| test-messy-hybrid_recency | condition_current        |  85 |         85 | 0.988 [0.965, 1.000] |
| test-messy-hybrid_recency | condition_historical     |  95 |         95 | 0.905 [0.842, 0.958] |
| test-messy-hybrid_recency | current_medications      | 150 |        150 | 0.993 [0.980, 1.000] |
| test-messy-hybrid_recency | dx_date                  | 150 |        150 | 0.940 [0.900, 0.973] |
| test-messy-hybrid_recency | family_history           |  96 |         96 | 1.000 [1.000, 1.000] |
| test-messy-hybrid_recency | family_trap              |  79 |         79 | 0.962 [0.911, 1.000] |
| test-messy-hybrid_recency | lab_not_documented       | 125 |        125 | 1.000 [1.000, 1.000] |
| test-messy-hybrid_recency | latest_lab               | 150 |        150 | 0.780 [0.713, 0.840] |
| test-messy-hybrid_recency | negation_trap            | 150 |        150 | 0.987 [0.967, 1.000] |
| test-messy-hybrid_recency | stop_reason              |  61 |         61 | 0.803 [0.689, 0.902] |
| test-messy-hybrid_recency | stop_reason_undocumented |  59 |         59 | 1.000 [1.000, 1.000] |

### By phenomenon
| run_name                  | phenomenon     |   n |   patients | correct              |
|:--------------------------|:---------------|----:|-----------:|:---------------------|
| test-clean-bm25           | abstention     | 184 |        138 | 1.000 [1.000, 1.000] |
| test-clean-bm25           | family_history |  79 |         79 | 0.886 [0.810, 0.949] |
| test-clean-bm25           | lookup         | 450 |        150 | 0.853 [0.820, 0.882] |
| test-clean-bm25           | negation       | 150 |        150 | 0.987 [0.967, 1.000] |
| test-clean-bm25           | note_only      | 157 |        122 | 1.000 [1.000, 1.000] |
| test-clean-bm25           | temporality    | 180 |        136 | 0.817 [0.764, 0.870] |
| test-clean-dense          | abstention     | 184 |        138 | 1.000 [1.000, 1.000] |
| test-clean-dense          | family_history |  79 |         79 | 0.924 [0.861, 0.975] |
| test-clean-dense          | lookup         | 450 |        150 | 0.676 [0.633, 0.716] |
| test-clean-dense          | negation       | 150 |        150 | 0.953 [0.920, 0.987] |
| test-clean-dense          | note_only      | 157 |        122 | 0.994 [0.980, 1.000] |
| test-clean-dense          | temporality    | 180 |        136 | 0.733 [0.676, 0.793] |
| test-clean-hybrid         | abstention     | 184 |        138 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | family_history |  79 |         79 | 0.949 [0.899, 0.987] |
| test-clean-hybrid         | lookup         | 450 |        150 | 0.758 [0.722, 0.793] |
| test-clean-hybrid         | negation       | 150 |        150 | 0.980 [0.953, 1.000] |
| test-clean-hybrid         | note_only      | 157 |        122 | 1.000 [1.000, 1.000] |
| test-clean-hybrid         | temporality    | 180 |        136 | 0.756 [0.698, 0.815] |
| test-clean-hybrid_recency | abstention     | 184 |        138 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | family_history |  79 |         79 | 0.949 [0.899, 0.987] |
| test-clean-hybrid_recency | lookup         | 450 |        150 | 0.836 [0.804, 0.867] |
| test-clean-hybrid_recency | negation       | 150 |        150 | 0.980 [0.953, 1.000] |
| test-clean-hybrid_recency | note_only      | 157 |        122 | 1.000 [1.000, 1.000] |
| test-clean-hybrid_recency | temporality    | 180 |        136 | 0.950 [0.917, 0.978] |
| test-messy-hybrid_recency | abstention     | 184 |        138 | 1.000 [1.000, 1.000] |
| test-messy-hybrid_recency | family_history |  79 |         79 | 0.962 [0.911, 1.000] |
| test-messy-hybrid_recency | lookup         | 450 |        150 | 0.904 [0.876, 0.931] |
| test-messy-hybrid_recency | negation       | 150 |        150 | 0.987 [0.967, 1.000] |
| test-messy-hybrid_recency | note_only      | 157 |        122 | 0.924 [0.882, 0.962] |
| test-messy-hybrid_recency | temporality    | 180 |        136 | 0.944 [0.911, 0.977] |

## Grounding of claims
| run_name                  |   n |   patients | grounded             |
|:--------------------------|----:|-----------:|:---------------------|
| test-clean-bm25           | 758 |        150 | 0.905 [0.884, 0.925] |
| test-clean-dense          | 672 |        150 | 0.885 [0.864, 0.906] |
| test-clean-hybrid         | 718 |        150 | 0.893 [0.871, 0.913] |
| test-clean-hybrid_recency | 724 |        150 | 0.909 [0.889, 0.928] |
| test-messy-hybrid_recency | 733 |        150 | 0.917 [0.896, 0.935] |

## Abstention
| run_name                  |   should_abstain |   abstained |   precision |   recall |   over_abstentions |   answered_unanswerable |
|:--------------------------|-----------------:|------------:|------------:|---------:|-------------------:|------------------------:|
| test-clean-bm25           |              184 |         206 |       0.893 |        1 |                 22 |                       0 |
| test-clean-dense          |              184 |         266 |       0.692 |        1 |                 82 |                       0 |
| test-clean-hybrid         |              184 |         225 |       0.818 |        1 |                 41 |                       0 |
| test-clean-hybrid_recency |              184 |         236 |       0.78  |        1 |                 52 |                       0 |
| test-messy-hybrid_recency |              184 |         222 |       0.829 |        1 |                 38 |                       0 |

## Plain SQL baseline (structured templates)
Same definitions as the gold, so this is the ceiling by construction; note-only templates (family history, stop reasons) are not answerable from the CDM. Disagreements with gold: `eval/results/test/sql_vs_gold_disagreements.csv`.
| template             |   n |   patients | correct              |
|:---------------------|----:|-----------:|:---------------------|
| condition_current    |  85 |         85 | 1.000 [1.000, 1.000] |
| condition_historical |  95 |         95 | 1.000 [1.000, 1.000] |
| current_medications  | 150 |        150 | 1.000 [1.000, 1.000] |
| dx_date              | 150 |        150 | 1.000 [1.000, 1.000] |
| family_trap          |  79 |         79 | 0.987 [0.962, 1.000] |
| lab_not_documented   | 125 |        125 | 1.000 [1.000, 1.000] |
| latest_lab           | 150 |        150 | 1.000 [1.000, 1.000] |
| negation_trap        | 150 |        150 | 1.000 [1.000, 1.000] |

## Grounding check vs independent labels (sample of 50 claims)
_(not labelled yet)_
