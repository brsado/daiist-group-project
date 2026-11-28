# Contributions

*Fill this in as you go, not on the last day. It is checked against the commits and against the peer assessment. A first name and a GitHub username are enough: this repo is public.*

## Members

| First name | GitHub username | Main areas |
|---|---|---|
| Bruno | brsado | Idea and context (Moysi Voice AI), architecture, technical base: router agent, ML auditor, app, monitoring, evaluation pipeline, deploy |
| Manuela |mcarreiraieu2022| Part A · evaluation cases (see TAREAS.md) |
| Brissa | brissajames | Part B · human labels (24 router replies graded pass/fail with reasons) and check of the LLM judge against them; judge analysis in REPORT.md |
| Maria | mfernandezg | Part C · thresholds and go / no-go decision |
| | | Part D · business case and failure analysis |
| | | Part E · online operation and presentation |

## Log

*One line per piece of work: the date, who did it (more than one name is fine), and what. Code done in pair programming counts for both, even if only one of you committed it.*

| Date | Who | What |
|---|---|---|
| 2026-11-25 | Bruno | Chose the use case (post-call audit of an AI call router, from Moysi Voice AI) and the two components; fictional municipality and anonymised data |
| 2026-11-25 | Bruno | Component A: Gemini router agent with tools (`router.py`), based on his assignment 3 agent |
| 2026-11-25 | Bruno | Component B: ML auditor (`auditor.py`), training phrases (`data/`), model comparison |
| 2026-11-25 | Bruno | Pipeline and review rule, Spanish app, Monitoring tab, drift alert, evaluation script (`evaluate.py`), threshold sweep |
| 2026-11-25 | Bruno | First draft of eval files, Render config, team task kit (`TAREAS.md`) |
| 2026-11-25 | Manuela | Part A: reviewed the 36 draft cases and wrote 15 new hard cases (51 in total: 16 normal, 22 hard, 7 review, 6 out_of_scope); ran the evaluation and check.py |
| 2026-11-28 | Brissa | Part B: graded 24 router replies by hand (8 normal, 8 hard, 4 review, 4 out_of_scope; 17 pass, 7 fail) with a short reason each, in `eval/human_labels.csv` |
| 2026-11-28 | Brissa | Ran the evaluation: judge agreement with our labels 70.8%, but it caught only 1 of our 7 fails |
| 2026-11-28 | Brissa | Analysed the judge's disagreements (person vs department, unnamed or wrong department, inconsistency); decided to keep rubric v2 and not use its pass rate as evidence of quality |
| 2026-11-28 | Brissa | Wrote the LLM judge paragraph in REPORT.md (Evaluation > End to end); ran check.py (all checks passed) |
| 2026-11-28 | Maria | Part C: chose the review rule and threshold (kept `disagree_or_p<t`, `REVIEW_BELOW_P` from 0.35 to 0.10) from the threshold sweep, and re-ran the evaluation |
| 2026-11-28 | Maria | Part C: set the alert thresholds (agreement 0.6, thumbs-down 0.3, PSI 0.25) and removed the placeholder comments in `monitor.py` and `pipeline.py` |
| 2026-11-28 | Maria | Part C: estimated the daily call volume from city 010 data, the share sent to review and the monthly cost; wrote "Other alerts", the cost and the "Decision" (go with conditions) in REPORT.md; ran drift-demo and check.py |
