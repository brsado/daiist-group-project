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
   less than `REVIEW_BELOW_P` (TODO part C: final value), or if Gemini failed. In the example B
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

Numbers on the draft cases (36); TODO part A: rerun with the final cases.

| Component | Metric | Result | Test data |
|---|---|---|---|
| A · router (Gemini, prompt v2) | Category accuracy / macro-F1 | 97% / 0.97 | 36 cases |
| A · router | Category accuracy on normal + hard | 100% | 23 cases |
| A · router | Action accuracy (guiar / transferir / persona / fuera de ámbito) | 78% | 36 cases |
| B · auditor (complement naive Bayes, chosen) | Accuracy / macro-F1 | 75% / 0.73 | 142 held-out phrases |
| B · auditor, alternatives | Logistic regression; calibrated linear SVM | 72% / 0.71; 75% / 0.73 | same 142 phrases |
| B · auditor | Category accuracy on the cases | 83% | 36 cases |

The router made no category error on the normal and hard draft cases, so the auditor had no
router error to catch: every call it sent to review there was a false alarm (5 of 23 at the
current threshold). TODO part A: harder cases.

### End to end

> TODO (part A + B): how `eval/cases.csv` was written (counts by kind, two examples), results
> against the baseline, the judge's rubric (`JUDGE_PROMPT` in `evaluate.py`) and the agreement
> with our own labels.

### Cost and latency

Per call, on the 36 cases: about 2,640 tokens and €0.00028 for the router (2–4 Gemini requests,
because of the tool rounds), median 3.6 s and 90th percentile 17 s (slow when Gemini is busy and we
retry). The auditor costs nothing and takes milliseconds. Prices in `router.PRICE_EUR_PER_M` are an
assumption to check against https://ai.google.dev/gemini-api/docs/pricing. TODO part C: cost per
month at the chosen volume.

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
calls, or more than `THUMBS_DOWN_ALERT` of rated calls are 👎 (TODO part C: final thresholds and
why).

## Failures

> TODO (part D): failed cases grouped by cause (router, auditor, or the hand-off), with counts,
> and what we would fix first.

Known so far, from the demo: the auditor gives false alarms on colloquial and Canarian Spanish
it has not seen; it is lost in other languages (which is why that is the drift we watch); and
the department for street furniture was wrong until we added "Limpieza y Residuos".

## Decision

> TODO (part C): the review rule and how many calls a day it would send to a person; go / no-go
> / go with conditions, the conditions and the evidence.

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
