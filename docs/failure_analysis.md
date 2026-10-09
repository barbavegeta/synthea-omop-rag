# Failure analysis (test set)

```
Failure taxonomy, applied to every wrong answer in this order (first match wins):
  answered_unanswerable  gold is "not documented" but the model answered
  retrieval_miss         no gold evidence was among the excerpts shown (split below into
                         abstained = safe failure, answered = unsafe failure)
  over_abstention        the evidence WAS shown but the model said "not documented"
  negation_error         negation trap answered "yes" with the "no evidence of" evidence shown
  family_attribution     family trap answered "yes" (a relative's condition given to the patient)
  temporal_error         current/historical status, latest lab or current meds wrong, evidence shown
  other                  anything else (value, date or format error with evidence shown)
```

## Counts
| run_name                  |   family_attribution |   other |   over_abstention |   retrieval_miss |   temporal_error |
|:--------------------------|---------------------:|--------:|------------------:|-----------------:|-----------------:|
| test-clean-bm25           |                    0 |       1 |                16 |               90 |                3 |
| test-clean-dense          |                    0 |       3 |                19 |              181 |                5 |
| test-clean-hybrid         |                    0 |       3 |                12 |              138 |                7 |
| test-clean-hybrid_recency |                    0 |       3 |                12 |               71 |                4 |
| test-messy-hybrid_recency |                    1 |       4 |                 8 |               56 |                1 |

## What the model did when retrieval missed the evidence
| run_name                  |   abstained (safe) |   answered wrongly (unsafe) |
|:--------------------------|-------------------:|----------------------------:|
| test-clean-bm25           |                  6 |                          84 |
| test-clean-dense          |                 63 |                         118 |
| test-clean-hybrid         |                 29 |                         109 |
| test-clean-hybrid_recency |                 40 |                          31 |
| test-messy-hybrid_recency |                 30 |                          26 |

## Examples
### family_attribution (1)

- **p160-family_trap** (test-messy-hybrid_recency): Does this patient have hyperglycemia?
  - gold: `{"type": "yes_no", "value": false}`
  - model: `{"items": [{"date": "2016-07-07", "value": "Hyperglycemia", "cited_chunks": ["C1", "C2", "C3", "C4"]}], "status": "answered", "yes_no": "yes", "explanation": "Hyperglycemia is listed as an active problem in notes from 2016-01-06 through 2016-07-07, and no excerpt marks it as resolved. The 2020-12-24 note (C5) mentions hyperglycemia only in the father's family history, which does not apply to the patient. That note's problem list excerpt does not include hyperglycemia, but it does not say it resolved either. The patient is currently taking insulin."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Inpatient note, 2016-07-07: - Hyperglycemia Meds: Current: no active prescriptions. Prev on hydrochlorothiazide (last rx 2016-05-26), insulin isophane / insulin, regular, human (last rx 2016-05-26). ROS: pt denies headache, palpitations, leg swelling. Obj: blood glucose 80.52 mg/dL; creatinine 5.95 mg/dL; eGFR 5.1789 mL/min; hemoglobin 16.1 g/dL; potassium 4.28 mmol/L; sodium 143.87 mmol/L; urea n"

### other (14)

- **p289-dx_date** (test-clean-bm25): When was this patient first diagnosed with acute infective cystitis?
  - gold: `{"date": "2022-05-29", "type": "date"}`
  - model: `{"items": [{"date": "2022-05-18", "value": "Acute infective cystitis first diagnosed 2022-05-18", "cited_chunks": ["C2"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The 2022-05-18 note records 'New diagnosis: Acute infective cystitis,' which is the earliest mention. The 2022-05-29 note lists it as diagnosed 2022-05-29, but that is later than the 2022-05-18 new diagnosis, so the earliest date is used. It was resolved 2022-05-30 (C3)."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2022-05-18: OUTPATIENT NOTE Date: 2022-05-18 Patient: female, born 2003 PAST MEDICAL HISTORY - history of Viral sinusitis, resolved 2019-09-02 - history of Limited social contact, resolved 2022-05-18 MEDICATIONS Current: no active prescriptions. REVIEW OF SYSTEMS Denies leg swelling, SOB, fever. OBJECTIVE BMI 20.75 kg/m2; body weight 54.6 kg; DBP 78 mm[Hg]; HR 97 /min; SBP 102 mm["
- **p289-dx_date** (test-clean-dense): When was this patient first diagnosed with acute infective cystitis?
  - gold: `{"date": "2022-05-29", "type": "date"}`
  - model: `{"items": [{"date": "2022-05-18", "value": "Acute infective cystitis first diagnosed", "cited_chunks": ["C2"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The 2022-05-18 note records 'New diagnosis: Acute infective cystitis.' The 2022-05-29 note lists it as diagnosed 2022-05-29, but the earlier note documents the diagnosis first. It was later resolved on 2022-05-30 (C1)."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2022-05-18: OUTPATIENT NOTE Date: 2022-05-18 Patient: female, born 2003 PAST MEDICAL HISTORY - history of Viral sinusitis, resolved 2019-09-02 - history of Limited social contact, resolved 2022-05-18 MEDICATIONS Current: no active prescriptions. REVIEW OF SYSTEMS Denies leg swelling, SOB, fever. OBJECTIVE BMI 20.75 kg/m2; body weight 54.6 kg; DBP 78 mm[Hg]; HR 97 /min; SBP 102 mm["
- **p289-dx_date** (test-clean-hybrid): When was this patient first diagnosed with acute infective cystitis?
  - gold: `{"date": "2022-05-29", "type": "date"}`
  - model: `{"items": [{"date": "2022-05-18", "value": "Acute infective cystitis first diagnosed (new diagnosis documented in assessment and plan)", "cited_chunks": ["C3"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The 2022-05-18 note (C3) lists 'New diagnosis: Acute infective cystitis' in its assessment and plan. The 2022-05-29 note (C1) lists the diagnosis date as 2022-05-29, which conflicts with C3. The earliest documented diagnosis is 2022-05-18, so that is taken as the first diagnosis. The condition was later recorded as resolved on 2022-05-30 (C2)."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2022-05-18: OUTPATIENT NOTE Date: 2022-05-18 Patient: female, born 2003 PAST MEDICAL HISTORY - history of Viral sinusitis, resolved 2019-09-02 - history of Limited social contact, resolved 2022-05-18 MEDICATIONS Current: no active prescriptions. REVIEW OF SYSTEMS Denies leg swelling, SOB, fever. OBJECTIVE BMI 20.75 kg/m2; body weight 54.6 kg; DBP 78 mm[Hg]; HR 97 /min; SBP 102 mm["

### over_abstention (67)

- **p100-dx_date** (test-clean-dense): When was this patient first diagnosed with muscle pain?
  - gold: `{"date": "2021-01-10", "type": "date"}`
  - model: `{"items": [], "status": "not_documented", "yes_no": "not_applicable", "explanation": "The excerpts document muscle pain only as historical, resolved 2021-01-23 (C4, C5). None of the excerpts states the date it was first diagnosed. The 2021-01-10 notes (C2, C3) are cut off at the new diagnosis entries, so the diagnosis date cannot be confirmed."}`
  - gold evidence among excerpts shown: True
- **p1036-family_trap** (test-clean-bm25): Does this patient have neuropathy due to type 2 diabetes mellitus?
  - gold: `{"type": "yes_no", "value": false}`
  - model: `{"items": [], "status": "not_documented", "yes_no": "not_applicable", "explanation": "The only mention of neuropathy due to type 2 diabetes mellitus is in the family history, where it is attributed to the patient's mother. That describes a relative, not the patient. None of the excerpts documents neuropathy in the patient. The problem lists are only partially shown, so whether the patient has this condition is not documented."}`
  - gold evidence among excerpts shown: True
- **p1036-family_trap** (test-clean-hybrid_recency): Does this patient have neuropathy due to type 2 diabetes mellitus?
  - gold: `{"type": "yes_no", "value": false}`
  - model: `{"items": [], "status": "not_documented", "yes_no": "not_applicable", "explanation": "The excerpts mention neuropathy due to type 2 diabetes mellitus only under family history, for the patient's mother (C1\u2013C5). That describes a relative, not the patient. None of the excerpts records this diagnosis for the patient, and the problem lists shown are truncated, so the patient's own status cannot be determined."}`
  - gold evidence among excerpts shown: True

### retrieval_miss (536)

- **p100-latest_lab** (test-clean-bm25): What was this patient's most recent diastolic blood pressure result, and on what date?
  - gold: `{"date": "2025-07-13", "type": "lab", "unit": "mm[Hg]", "value": 73.0}`
  - model: `{"items": [{"date": "2022-08-14", "value": "85.807 mm[Hg]", "cited_chunks": ["C1"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The latest dated diastolic blood pressure is 85.807 mm[Hg], recorded in the Emergency Room note of 2022-08-14. The other readings are older: 80 and 76 mm[Hg] on 2021-01-10, and 73 mm[Hg] on 2018-12-23."}`
  - gold evidence among excerpts shown: False
  - first cited excerpt: "Emergency Room note, 2022-08-14: rystals 25 MG / nitrofurantoin, monohydrate 75 MG Oral Capsule). Previously: norethindrone (last prescribed 2022-03-25). REVIEW OF SYSTEMS Denies shortness of breath, chest pain, blurred vision. OBJECTIVE diastolic blood pressure 85.807 mm[Hg]; heart rate 91.131 /min; systolic blood pressure 136.27 mm[Hg]. ASSESSMENT AND PLAN No evidence of IHD."
- **p100-latest_lab** (test-clean-dense): What was this patient's most recent diastolic blood pressure result, and on what date?
  - gold: `{"date": "2025-07-13", "type": "lab", "unit": "mm[Hg]", "value": 73.0}`
  - model: `{"items": [{"date": "2022-08-14", "value": "85.807 mm[Hg]", "cited_chunks": ["C4"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The latest dated diastolic blood pressure in the excerpts is 85.807 mm[Hg], from the emergency room note of 2022-08-14. The 2023-12-03 excerpt does not include a blood pressure reading."}`
  - gold evidence among excerpts shown: False
  - first cited excerpt: "Emergency Room note, 2022-08-14: rystals 25 MG / nitrofurantoin, monohydrate 75 MG Oral Capsule). Previously: norethindrone (last prescribed 2022-03-25). REVIEW OF SYSTEMS Denies shortness of breath, chest pain, blurred vision. OBJECTIVE diastolic blood pressure 85.807 mm[Hg]; heart rate 91.131 /min; systolic blood pressure 136.27 mm[Hg]. ASSESSMENT AND PLAN No evidence of IHD."
- **p100-latest_lab** (test-clean-hybrid): What was this patient's most recent diastolic blood pressure result, and on what date?
  - gold: `{"date": "2025-07-13", "type": "lab", "unit": "mm[Hg]", "value": 73.0}`
  - model: `{"items": [{"date": "2022-08-14", "value": "85.807 mm[Hg]", "cited_chunks": ["C3"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The latest dated diastolic blood pressure is 85.807 mm[Hg], recorded in the 2022-08-14 emergency room note. Earlier readings were 80 and 76 mm[Hg] on 2021-01-10 and 77 mm[Hg] on 2016-07-03."}`
  - gold evidence among excerpts shown: False
  - first cited excerpt: "Emergency Room note, 2022-08-14: rystals 25 MG / nitrofurantoin, monohydrate 75 MG Oral Capsule). Previously: norethindrone (last prescribed 2022-03-25). REVIEW OF SYSTEMS Denies shortness of breath, chest pain, blurred vision. OBJECTIVE diastolic blood pressure 85.807 mm[Hg]; heart rate 91.131 /min; systolic blood pressure 136.27 mm[Hg]. ASSESSMENT AND PLAN No evidence of IHD."

### temporal_error (20)

- **p144-current_medications** (test-clean-bm25): Which medications is this patient currently taking (as of 2025-05-15)?
  - gold: `{"type": "set", "items": ["amoxicillin / clavulanate", "aspirin", "hydrochlorothiazide", "insulin isophane / insulin, regular, human", "lisinopril", "metoprolol", "pitavastatin", "simvastatin"]}`
  - model: `{"items": [{"date": "2025-05-15", "value": "amoxicillin / clavulanate", "cited_chunks": ["C3", "C4", "C5"]}, {"date": "2025-05-15", "value": "aspirin", "cited_chunks": ["C3", "C4"]}, {"date": "2025-05-15", "value": "hydrochlorothiazide", "cited_chunks": ["C3", "C4"]}, {"date": "2025-05-15", "value": "insulin isophane / insulin regular human", "cited_chunks": ["C3", "C4"]}, {"date": "2025-05-15", "value": "lisinopril", "cited_chunks": ["C3", "C4", "C5"]}, {"date": "2025-05-15", "value": "metoprolol", "cited_chunks": ["C3", "C4", "C5"]}, {"date": "2025-05-15", "value": "pitavastatin", "cited_chunks": ["C3", "C4", "C5"]}, {"date": "2025-05-15", "value": "simvastatin", "cited_chunks": ["C5"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The 2025-05-15 outpatient note lists these eight medications as current. Amoxicillin/clavulanate and simvastatin were started at that visit."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2025-05-15: 5-15 - h/o Imaging finding, resolved 2024-11-23 - h/o Dental caries on smooth surface penetrating into pulp, resolved 2024-12-19 - history of Disorder of teeth AND/OR supporting structures, resolved 2025-05-01 - h/o Dental caries, resolved 2025-05-01 - h/o MI, resolved 2025-05-08 MEDICATIONS Current: amoxicillin / clavulanate (amoxicillin 250 MG / clavulanate 125 MG Or"
- **p144-current_medications** (test-clean-hybrid_recency): Which medications is this patient currently taking (as of 2025-05-15)?
  - gold: `{"type": "set", "items": ["amoxicillin / clavulanate", "aspirin", "hydrochlorothiazide", "insulin isophane / insulin, regular, human", "lisinopril", "metoprolol", "pitavastatin", "simvastatin"]}`
  - model: `{"items": [{"date": "2025-05-15", "value": "amoxicillin / clavulanate", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "aspirin", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "hydrochlorothiazide", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "insulin isophane / insulin, regular, human", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "lisinopril", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "metoprolol", "cited_chunks": ["C1", "C4"]}, {"date": "2025-05-15", "value": "pitavastatin", "cited_chunks": ["C1", "C4"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "The current medication list in the 2025-05-15 outpatient notes contains these seven medications. The list is cut off after pitavastatin, so further medications may not be shown."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2025-05-15: 5-15 - h/o Imaging finding, resolved 2024-11-23 - h/o Dental caries on smooth surface penetrating into pulp, resolved 2024-12-19 - history of Disorder of teeth AND/OR supporting structures, resolved 2025-05-01 - h/o Dental caries, resolved 2025-05-01 - h/o MI, resolved 2025-05-08 MEDICATIONS Current: amoxicillin / clavulanate (amoxicillin 250 MG / clavulanate 125 MG Or"
- **p144-current_medications** (test-clean-hybrid): Which medications is this patient currently taking (as of 2025-05-15)?
  - gold: `{"type": "set", "items": ["amoxicillin / clavulanate", "aspirin", "hydrochlorothiazide", "insulin isophane / insulin, regular, human", "lisinopril", "metoprolol", "pitavastatin", "simvastatin"]}`
  - model: `{"items": [{"date": "2025-05-15", "value": "amoxicillin / clavulanate", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "aspirin", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "hydrochlorothiazide", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "insulin isophane / insulin regular human", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "lisinopril", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "metoprolol", "cited_chunks": ["C1"]}, {"date": "2025-05-15", "value": "pitavastatin", "cited_chunks": ["C1"]}], "status": "answered", "yes_no": "not_applicable", "explanation": "Per the most recent note (2025-05-15), the current medication list includes these agents; the list is truncated in the excerpt, so additional medications may exist."}`
  - gold evidence among excerpts shown: True
  - first cited excerpt: "Outpatient note, 2025-05-15: 5-15 - h/o Imaging finding, resolved 2024-11-23 - h/o Dental caries on smooth surface penetrating into pulp, resolved 2024-12-19 - history of Disorder of teeth AND/OR supporting structures, resolved 2025-05-01 - h/o Dental caries, resolved 2025-05-01 - h/o MI, resolved 2025-05-08 MEDICATIONS Current: amoxicillin / clavulanate (amoxicillin 250 MG / clavulanate 125 MG Or"
