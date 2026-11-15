# Expanded workbook simulation

The supplied `Data.xlsx` Parameters sheet contains **83 indicators**, not 81. All are represented. Existing internal radiation/preflight fields remain, giving **88 wire metric codes**: the original 26 plus 62 additions. The 26-to-83 difference is not 57 because some original codes are internal extras or alternate representations.

Existing measurements retain their context-aware model. The 62 additions are independent random fixtures generated at initialization and every **one simulated hour**. They use plausible demonstration ranges taken from the supplied workbook where available and explicit team-selected ranges otherwise. They are not physiological models or medically validated reference intervals. No new activity, environmental, symptom or temporal coupling is imposed.

Categorical findings are strings; yes/no findings are booleans; compound examinations are JSON objects. No real photos, prescriptions, or medication doses are generated. Skin entries explicitly state that no real photograph exists.

`context.synthetic_random=true` identifies the independent fixtures. They are stored in PostgreSQL and exposed in the dashboard measurement dictionaries. They are excluded from clinical alert input frames, so random consciousness/NEWS2 fixtures do not override the established context-aware facts or calculated NEWS2. Numeric added measurements support the existing trends API; categorical/structured values are available as latest readings and original journal payloads, not numeric charts.

`SIM_ERROR_LEVEL` continues to inject abnormal readings into the original context-aware measurements; these new independent fixtures are not part of that selection.

Old SQLite checkpoints resume without reset: the first subsequent advance adds the new fixture stream, then continues hourly. Existing journal payloads and event identities are not rewritten. New fixtures use a separate deterministic generator and do not perturb the physiological dynamics RNG.

Apply Django migration `0007_typed_workbook_measurements` before delivering the expanded stream. It adds nullable JSON columns, widens catalogue units and extends the value-type constraints; existing numeric/boolean readings remain intact. Backend and simulator definitions are packaged independently and checked for exact agreement. `simulator/schemas/workbook-coverage.json` records all 83 source IDs and their canonical measurement codes, with a SHA-256 of the supplied workbook.

| Indicator | Type | Unit | Synthetic range or representation |
|---|---|---|---|
| `consciousness` | categorical | Alert / new confusion / voice / pain / unresponsive | alert, new_confusion, voice, pain, unresponsive |
| `news2` | numeric | score 0–20 | [0, 6] integer |
| `hrv` | numeric | ms (RMSSD) | [25, 90] |
| `ecg_flag` | categorical | device flag | none, sinus_rhythm, irregular_rhythm |
| `etco2` | numeric | mmHg | [35, 45] |
| `spco` | numeric | % | [0.1, 2] |
| `spmet` | numeric | % | [0.1, 1.5] |
| `perfusion_index` | numeric | % | [0.5, 8] |
| `sphb` | numeric | g/dL | [12, 17] |
| `hemoglobin` | numeric | g/dL | [12, 17] |
| `hematocrit` | numeric | % | [36, 52] |
| `platelets` | numeric | ×10⁹/L | [150, 400] integer |
| `wbc` | numeric | ×10⁹/L | [4, 10] |
| `serum_calcium` | numeric | mmol/L | [2, 2.6] |
| `vitamin_d` | numeric | ng/mL | [25, 70] |
| `ferritin` | numeric | ng/mL | [25, 200] |
| `creatinine` | numeric | mg/dL | [0.8, 1.3] |
| `sodium` | numeric | mmol/L | [135, 145] |
| `potassium` | numeric | mmol/L | [3.5, 5] |
| `cortisol_dhea` | numeric | ratio | [0.8, 1.8] |
| `herpes_dna` | boolean | detected / not | true / false; 5% positive findings |
| `urine_sg_ph` | structured | SG; pH | specific_gravity, ph |
| `urinary_calcium` | numeric | mg/24 h | [100, 300] |
| `ntx` | numeric | vs baseline | [0.8, 1.6] |
| `urine_volume` | numeric | L/day | [2, 3.5] |
| `urine_colour` | categorical | pale / yellow / dark | pale, yellow, dark |
| `flank_pain` | boolean | yes / no | true / false; 5% positive findings |
| `urinary_retention` | boolean | yes / no | true / false; 5% positive findings |
| `bone_density` | numeric | % of pre-mission | [94, 100] |
| `resistance_ex` | numeric | sessions | [0, 6] integer |
| `exercise_min` | numeric | min/week | [450, 650] integer |
| `fitness` | numeric | % of pre-mission; mL/min/kg | [80, 105] |
| `strength` | numeric | % of baseline | [80, 105] |
| `energy_intake` | numeric | kcal/day | [2200, 3000] |
| `vision_change` | boolean | yes / no | true / false; 5% positive findings |
| `oct_rnfl` | numeric | µm change | [0, 20] |
| `amsler_acuity` | structured | lines / distortion | acuity_lines, distortion |
| `jugular_flow` | categorical | normal / stagnant / reversed / clot | normal, stagnant, reversed, clot |
| `orthostatic` | structured | symptoms; BP/HR | symptoms, systolic_mmhg, diastolic_mmhg, heart_rate_bpm |
| `motion_sickness` | numeric | grade 0–3 | [0, 3] integer |
| `balance` | numeric | check-in score | [0, 3] integer |
| `hearing` | numeric | dB HL | [0, 25] integer |
| `headache` | numeric | severity 0–3 | [0, 3] integer |
| `infection_signs` | structured | checklist | rash, cold_sores, fever |
| `skin` | structured | photo + note | condition, note, photo_available |
| `pain_injury` | structured | 0–10, location on body | severity, location |
| `medication_log` | structured | log | taken, item, stock_remaining |
| `circadian` | numeric | sleep midpoint | [2, 5] |
| `workload` | structured | Bedford 1–10; Borg 0–10 | bedford, borg_cr10 |
| `reaction_ms` | numeric | ms | [220, 400] |
| `cognition` | numeric | score vs baseline | [85, 110] |
| `team_cohesion` | numeric | survey score | [6, 10] integer |
| `eva_hr` | numeric | % of age-predicted max | [50, 85] |
| `eva_core_temp` | numeric | °C | [36.8, 38] |
| `suit_status` | structured | per suit system | pressure_kpa, o2_partial_pressure_mmhg, co2_partial_pressure_mmhg, metabolic_rate_watts |
| `dcs` | structured | symptom check | joint_pain, tingling, weakness |
| `dust_symptoms` | boolean | yes / no | true / false; 5% positive findings |
| `solar_storm` | structured | S-level; projected mSv | noaa_s_level, projected_event_dose_msv |
| `rad_bfo` | numeric | mGy-Eq | [0, 80] |
| `ars_symptoms` | structured | symptoms | nausea, vomiting, loss_of_appetite |
| `combustion` | structured | ppm | co_ppm, hcn_ppm, hcl_ppm, hf_ppm |
| `water_supply` | numeric | L/person/day | [2.5, 4] |
