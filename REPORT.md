# Group Assignment Report

- **Team** (Blackboard group name): TODO
- **Section**: TODO [BBADBA 5A | BBADBA 5B | PPLEDBA 5A]
- **App URL** (on Render): https://auditor-llamadas-valdeolmo.onrender.com
- **Final commit** (tag `final`): TODO

*At most about 3,000 words, tables excluded. Members and who did what go in CONTRIBUTIONS.md.*

## Business case

> TODO (part D, see TAREAS.md): who uses it, which decision it supports, the baseline, the
> success metric, and the value in euros with its assumptions.

Context for whoever writes this section: the product comes from Moysi Voice AI, a project of a
team member that answers the phone calls a town hall receives with AI agents (a router that sends
each call to the right department, and agents that guide citizens through procedures). Nobody
checks today whether the AI routed a call to the wrong place. Our product is that check: an audit
after the call ends, so it adds no delay to a live phone call.

## Architecture

```
caller's words (transcript)
        │
        ▼
┌───────────────────────────────┐      tools over data/municipio.json
│ A · Router agent (Gemini)     │◄──── info_categoria(categoria)
│ router.py                     │◄──── buscar_tramite(consulta)
└───────────────┬───────────────┘
                │ category · department · action · reply
                ▼
┌───────────────────────────────┐
│ B · ML auditor (scikit-learn) │  P(A's category), its own category
│ auditor.py                    │
└───────────────┬───────────────┘
                ▼
     review rule (pipeline.py) ──► ✅ validated  |  ⚠️ to a person
                │
                ▼
     log (logbook.py) ──► Monitoring tab (monitor.py)
```

**One request, end to end.** The supervisor pastes what the caller said, for example "Hay una
farola fundida en mi calle desde hace una semana".

1. **Component A, the router (agentic LLM).** `gemini-3.5-flash-lite` gets a system prompt that
   makes it the town hall's operator. It may call two tools (up to 3 rounds; the last round
   forbids tools so it must answer). Here it searched `buscar_tramite("farola fundida alumbrado
   público")` and read `info_categoria("Vía pública y servicios")`. It answered with JSON:
   category *Vía pública y servicios*, department *Agua y Alumbrado* (ext. 602), action *guiar*,
   procedure *Aviso de incidencia en la vía pública*, and a short reply. Gemini answers are cached
   by model, prompt version and input, so the evaluation and the drift demo do not spend quota twice.
2. **Component B, the auditor (tabular/text ML).** It receives the transcript **and A's category**.
   A TF-IDF representation (word 1–2-grams and character 3–5-grams) feeds a classifier over the 16
   call categories. B returns the probability it gives to A's category and its own top category.
3. **Review rule.** The call goes to a person if B picks another category, or gives A's category
   less than `REVIEW_BELOW_P` 0.10, or if Gemini failed. In the example B
   agreed, so the call was validated automatically; the app shows the reasons when it is not.
4. **Log and monitoring.** Every request is logged (below) and the Monitoring tab reads the logs.

**Why these models.** Gemini Flash-Lite: tool calling, good with colloquial Spanish and other
languages, the largest free daily quota among the allowed services, and about €0.0003 per call.
scikit-learn: runs in milliseconds inside Render's 512 MB, costs nothing, and its probabilities
give a review rule and a drift signal. We compared three classifiers (logistic regression,
complement naive Bayes, calibrated linear SVM) on a held-out split; see Evaluation.

**Why this split of work between the models.** A is the expensive, capable model that makes the
decision; B is a cheap second opinion. In Moysi this would run after the call (shadow mode), so
it adds no latency to a live call.

**Reuse.** The Gemini agent pattern (google-genai, `gemini-3.5-flash-lite`, tool loop) comes from
Bruno's assignment 3 (a RAG agent over the procedures of a town hall). The 16 call categories and
the procedure families come from Bruno's Moysi Voice AI project. Everything else is new.

## Data

| Data | Source | Size | Licence / status |
|---|---|---|---|
| Municipality (departments, extensions, 16 procedures) | Written by the team; fictional town "Valdeolmo"; categories from Moysi | 14 departments, 16 procedures | Own work |
| Training phrases for B (`data/phrases.csv`) | First turn of the synthetic chat tests of Moysi Voice AI (no real callers), plus phrases written for this project (`data/extra_phrases.csv`) | 570 phrases, 16 categories | Own work; synthetic |
| Drift reference (`eval/reference.csv`) | 45 phrases from the set above, kept out of B's final training | 45 | Own work |
| Shifted inputs (`eval/shifted.csv`) | The same kind of requests in English, French, German, Portuguese and Catalan | 12 | Own work |
| Evaluation cases (`eval/cases.csv`) | Written by the team | TODO (part A) | Own work |

**No personal data.** Real municipality names were replaced by fictional ones
(`scripts/build_dataset.py`), phrases with digits that could be phone or ID numbers were dropped,
and no names, phones or ID numbers appear in the cases, the logs or the demo. The logs keep the
first 120 characters of the transcript, which the app asks users not to fill with personal data.
The procedure summaries are illustrative and were not checked against any real town hall.

## Evaluation

### Components

Numbers on the final 51 cases (`eval/summary.json`).

| Component | Metric | Result | Test data |
|---|---|---|---|
| A · router (Gemini, prompt v2) | Category accuracy / macro-F1 | 96% / 0.94 | 51 cases |
| A · router | Category accuracy on normal + hard | 97% (1 error) | 38 cases |
| A · router | Action accuracy (guiar / transferir / persona / fuera de ámbito) | 77% | 51 cases |
| B · auditor (complement naive Bayes, chosen) | Accuracy / macro-F1 | 75% / 0.73 | 142 held-out phrases |
| B · auditor, alternatives | Logistic regression; calibrated linear SVM | 72% / 0.71; 75% / 0.73 | same 142 phrases |
| B · auditor | Category accuracy on the cases | 82% | 51 cases |

On the 38 normal and hard cases the router made one category error (c40), and the auditor sent
it to review. At the current threshold it also sent 17 correct calls to review: 18 flags for 1
real error (precision 0.056). See `eval/threshold_sweep.csv` for other thresholds.

### End to end

> TODO (part A + B): how `eval/cases.csv` was written (counts by kind, two examples), results
> against the baseline, the judge's rubric (`JUDGE_PROMPT` in `evaluate.py`) and the agreement
> with our own labels.

`eval/cases.csv` has 51 cases (part A, Manuela): 16 normal, 22 hard, 7 review and 6 out_of_scope. The 36 drafts were reviewed and kept, and 15 new hard cases were written by hand as realistic, colloquial calls, each built around a trap between two neighbouring categories of `data/municipio.json`; the expected answer follows the category definitions in that file. Two examples: c40 «Necesito que me pasen directamente con el concejal que lleva lo de mi barrio…» (expected Alcaldía y cargos | transferir; the router chose Hablar con una persona concreta and the auditor sent it to review) and c44 «Nada, llamaba para darles las gracias por la estupenda iluminación de mi calle…» (irony; expected Vía pública y servicios | guiar). On the 51 cases the product is right in 66.7% of them, against 11.8% for today's switchboard. The router got the category wrong in only 1 normal or hard case, which the auditor caught, but the auditor also sent many correct hard calls to review (precision 0.056).

**LLM judge (part B).** The router's reply to the caller is free text, so an LLM judge (Gemini, `JUDGE_PROMPT` in `evaluate.py`, version `judge-rubric-v2`) grades it pass/fail. A reply passes only if it meets four criteria: it answers what the caller asked, it routes as expected (guide, transfer, person or out of scope), it invents no concrete data that is not in the procedure facts the router could read, and it is short, polite and clear on the phone; if a person is in danger it must mention 112. To check the judge, we labelled 24 replies ourselves (`eval/human_labels.csv`): 8 normal, 8 hard, 4 review and 4 out_of_scope, with 17 pass and 7 fail. The judge agrees with our labels on 70.8% of them (17/24), but that number is misleading: the judge passes 94.1% of all 51 replies, and a judge that said "pass" to everything would also agree on 70.8%. Of our 7 fails it caught only 1 (c30). It misses three kinds of error: calls that should go to a person but are sent to a department (c24, c26, c28), replies that do not name the department (c05, c44), and a wrong department (c40, a councillor sent to Atención al Ciudadano instead of Alcaldía). It is also inconsistent: it failed c48 for transferring instead of guiding, but passed c07 and c21, which do the same. We kept rubric v2 and do not use the judge's pass rate as evidence that the replies are good; a stricter rubric (a person means a human, not a department; a wrong or unnamed department fails) would have to be checked again against new human labels.

### Cost and latency

Per call, on the 51 cases: about 2,690 tokens and €0.00028 for the router (2–4 Gemini requests,
because of the tool rounds), median 6.4 s and 90th percentile 18 s (slow when Gemini is busy and we
retry). The auditor costs nothing and takes milliseconds. Prices in `router.PRICE_EUR_PER_M` are an
assumption to check against https://ai.google.dev/gemini-api/docs/pricing. 

With one call per resident per year in a town of 5,000 people, that is about 14 calls a day. At an average cost of €0.00028 per call (Gemini only, since the auditor is free), this comes to about €0.12 a month (between €0.03 and €0.15 for 4 to 18 calls a day). The real cost is the time of the person who reviews about 2.7 calls a day.

**Free-tier limit.** One Gemini key allows 500 requests a day (`gemini-3.5-flash-lite`), so about
150 audited calls a day. We hit it while evaluating; the online app uses its own key.

## Operations

**What we log** (`logbook.py`, Postgres on Render): an id, the time, the first 120 characters of
the transcript, both components' outputs (category, department, action, reply, the tools A
called, B's probabilities), the reasons for review, model and prompt versions, latency, tokens,
cost, and the supervisor's 👍/👎.

**Quality signal.** The share of calls where the auditor agrees with the router, as a rolling
mean over the last 10 calls, next to the share sent to review, B's mean probability for A's
category, and the share of 👎. Agreement stands in for "share of calls routed correctly", which
we cannot observe live.

**Drift check.** Six features per call are compared with the 45 reference calls by PSI (5 bins).
Only two can fire the alert (`DRIFT_FEATURES` in `monitor.py`):

- `share_spanish_words`, both directions: the auditor only knows Spanish.
- `auditor_confidence`, only when it falls: inputs unlike the training data.

The others are logged and shown but not watched. Gemini reports a confidence of 0.95–1.0 almost
always, so its PSI swings on tiny changes. The reference phrases are more colloquial than the
normal cases, so the auditor is *more* confident on normal traffic, which is not a problem.
An alert needs PSI > 0.25 **and** more than twice the PSI expected by chance for the sample sizes,
over at least 20 calls.

**Drift demo** (`main.py drift-demo`, prompt v2; TODO part E: rerun after the final cases):

| Inputs | `share_spanish_words` PSI / threshold | `auditor_confidence` PSI / threshold | Alert |
|---|---|---|---|
| 16 normal cases | 0.26 / 0.68 | 0.51 / 0.68 | quiet |
| 12 shifted inputs (other languages) | 7.42 / 0.84 | 3.71 / 0.84, falling | fires |

**Other alerts.** The auditor agrees with the router on fewer than `AGREEMENT_ALERT` of the last
calls, or more than `THUMBS_DOWN_ALERT` of rated calls are 👎. Setting the alerts as follows: agreement at 0.6, thumbs-down at 0.3, and PSI at 0.25. Also, leaving agreement alone because false alerts bother me most: if they fire too often, people stop paying attention, and on normal calls agreement was 100%. We lowered thumbs-down from 0.4 to 0.3 so the alert is actually useful, since the judge rated 94% of answers as good and an extra thumbs-down usually means something. PSI stays at 0.25, the usual value: in drift-demo the panel stayed quiet on the 16 normal calls and fired on the 12 that had been changed. On normal calls we accept almost no false alerts. What would really worry is a change in the kind of calls, with new topics or vocabulary, because we would expect it to push PSI up and agreement down at the same time.

## Failures

> TODO (part D): failed cases grouped by cause (router, auditor, or the hand-off), with counts,
> and what we would fix first.

Known so far, from the demo: the auditor gives false alarms on colloquial and Canarian Spanish
it has not seen; it is lost in other languages (which is why that is the drift we watch); and
the department for street furniture was wrong until we added "Limpieza y Residuos".

## Decision
We keep the `disagree_or_p<t` rule and lower the threshold from 0.35 to 0.10. The `disagree` part catches the only router error in the cases (c40) at every threshold, because the auditor picks a different category. With `p<t` alone, that error is missed at 0.20 or lower and caught only from 0.25. At 0.10, just 4 normal or hard cases are false alarms (11% of the calls the router got right), against 17 (46%) at 0.35. A random 10% audit would catch only 10% of errors on average, and since the audit happens after the call, the error would already have reached the neighbor.

For volume, we assume one call per resident/ year. In a town of 5000 that is about 14 calls a day (between 4 and 18), of which about 2.7 go to review, for about €0.12 a month. The figures come from Pamplona, Las Rozas, Alicante and Zaragoza, with approximate populations: these are cities, not small towns.

Our verdict is go with conditions: revisit the threshold once there is more data, keep watching thumbs-down with the alert at 0.3, and keep a small random review going.

The evidence: at 0.10, across the 51 cases, 19.6% of calls go to review (down from 53%). The product is right 90% of the time (up from 67%), counting false alarms as errors, while the simple switchboard is right 12%; precision rises from 5.6% to 20%. Against this, among the 7 cases that should go to a person, the share sent to review drops from 86% to 57%. Above all, everything rests on a single error, so the evidence is very thin and the threshold may be fitted to that one case.


## Bonus: reinforcement learning

> TODO (part F) or delete this section.

## How to run it

Only `GEMINI_API_KEY` is needed (free key: https://aistudio.google.com/apikey). Follow SETUP.md.
The trained auditor (`models/auditor.joblib`) and the cached Gemini answers for every evaluation,
reference and shifted input (`cache/`) are in the repo, so `main.py evaluate`, `main.py
drift-demo` and `check.py` run in seconds and spend no quota. To retrain the auditor:
`uv run python auditor.py`. Rebuilding `data/phrases.csv` needs the private Moysi test suites
(`scripts/build_dataset.py`); the result is committed.

## AI use

Claude (Claude Code) was used to help write code: the router's tool loop, the auditor's
training script, the app screens, the monitoring changes and the evaluation script, as well as
the first draft of the training phrases in `data/extra_phrases.csv`, which the team reviewed.
Gemini is part of the product (component A and the LLM judge). The problem, the components and
how they connect, the metrics, the thresholds, the review rule, the evaluation cases, our own
labels and the analysis in this report are the team's. TODO: each member adds how they used AI
in their part.

Manuela (part A) used Claude to understand the project and the category definitions, to review the format of her cases, add them to the CSV, and guide the evaluation and git steps. The case phrases, their kinds and their expected answers were written and decided by her.

Brissa (Part B): Claude set up the project, explained the cases, and ran the evaluation. I decided the labels, the criteria behind them, and drafted the report.