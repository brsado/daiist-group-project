"""
Evaluation. `uv run python main.py evaluate`

1. Component A (router agent): category accuracy / macro-F1 and action accuracy on eval/cases.csv.
2. Component B (ML auditor): held-out accuracy / macro-F1 (from auditor.py, eval/component_b_metrics.json),
   its category accuracy on the cases, and how well its review flag catches A's mistakes.
3. End to end, against two baselines: today's switchboard (everything to 301) and a supervisor
   who audits a random 10% of calls.
4. LLM judge on A's free-text reply, and its agreement with eval/human_labels.csv.
5. Cost and latency per request.

Writes eval/results.csv, eval/summary.json and eval/to_label.csv (the replies for the team to grade).
Gemini answers (router and judge) are cached in cache/, so a rerun costs nothing.
"""

import csv
import hashlib
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

import env
import pipeline
import router

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "eval" / "cases.csv"
RESULTS = ROOT / "eval" / "results.csv"
SUMMARY = ROOT / "eval" / "summary.json"
TO_LABEL = ROOT / "eval" / "to_label.csv"
HUMAN_LABELS = ROOT / "eval" / "human_labels.csv"
B_METRICS = ROOT / "eval" / "component_b_metrics.json"
JUDGE_CACHE = ROOT / "cache" / "judge.jsonl"
RANDOM_AUDIT_SHARE = 0.10
JUDGE_VERSION = "judge-rubric-v1"

JUDGE_PROMPT = """Eres un evaluador estricto de una operadora telefónica automática de un ayuntamiento.
Te doy lo que dijo el vecino, lo que se esperaba (categoría | acción) y la respuesta de la operadora.

Rúbrica. La respuesta APRUEBA (pass) solo si cumple las cuatro:
1. Es coherente con lo que pidió el vecino (no responde a otra cosa).
2. Deriva bien: guía, transfiere, pasa a una persona o dice que no es del ayuntamiento, según lo esperado.
3. No inventa datos concretos (plazos, precios, documentos, teléfonos) que no estén justificados.
4. Es breve, educada y comprensible por teléfono.
Si hay peligro para personas, debe mencionar el 112.

Devuelve SOLO JSON: {"label": "pass" o "fail", "reason": "una frase"}"""


def expected_parts(case: dict) -> tuple[str, str]:
    category, _, action = case["expected"].partition("|")
    return category.strip(), action.strip()


def outcome_correct(case: dict, a: dict, review: bool) -> bool:
    """Is the end result right for the town hall? See REPORT.md, Evaluation."""
    category, action = expected_parts(case)
    kind = case["kind"].strip().lower()
    if kind == "out_of_scope":
        return a["action"] == "fuera_de_ambito" or (a["category"] == "Otro" and review)
    if kind == "review":
        return review or a["action"] == "persona"
    a_right = a["category"] == category
    return a_right != review  # right and not flagged, or wrong and caught


def baseline_switchboard_correct(case: dict) -> bool:
    """Today: every call goes to Atención al Ciudadano (301); right only if that is where it belongs."""
    return "(correcto)" in case["baseline"]


# --- LLM judge ------------------------------------------------------------------

def _judge_cache() -> dict:
    if not JUDGE_CACHE.is_file():
        return {}
    return {r["key"]: r["verdict"] for r in map(json.loads, JUDGE_CACHE.read_text(encoding="utf-8").splitlines())}


def judge(case: dict, reply: str) -> dict:
    key = hashlib.sha256(f"{JUDGE_VERSION}|{case['input']}|{case['expected']}|{reply}".encode()).hexdigest()[:24]
    if hit := _judge_cache().get(key):
        return hit
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"Vecino: «{case['input']}»\nEsperado: {case['expected']}\nRespuesta de la operadora: «{reply}»"
    try:
        response = router._generate(  # same retries on 503/429 as the router
            client, prompt,
            types.GenerateContentConfig(system_instruction=JUDGE_PROMPT, temperature=0, response_mime_type="application/json"),
        )
        data = json.loads(re.search(r"\{.*\}", response.text, re.S).group(0))
        verdict = {"label": "pass" if data.get("label") == "pass" else "fail", "reason": data.get("reason", "")}
    except Exception as error:  # noqa: BLE001
        return {"label": None, "reason": f"judge error: {type(error).__name__}"}
    JUDGE_CACHE.parent.mkdir(exist_ok=True)
    with JUDGE_CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "verdict": verdict}, ensure_ascii=False) + "\n")
    return verdict


# --- Main -----------------------------------------------------------------------

def main() -> None:
    env.load_env()
    with CASES.open(newline="", encoding="utf-8") as f:
        cases = [r for r in csv.DictReader(f) if (r.get("input") or "").strip()]
    rows = []
    for i, case in enumerate(cases, 1):
        print(f"  {i}/{len(cases)}", end="\r", flush=True)
        started = time.perf_counter()
        result = pipeline.run(case["input"])
        a, b = result["outputs"]["component_a"], result["outputs"]["component_b"]
        exp_cat, exp_action = expected_parts(case)
        verdict = judge(case, a["reply"])
        rows.append({
            "id": case["id"], "kind": case["kind"].strip().lower(), "input": case["input"],
            "expected_category": exp_cat, "expected_action": exp_action,
            "a_category": a["category"], "a_action": a["action"], "a_reply": a["reply"], "a_error": a.get("error", ""),
            "b_category": b["category"], "p_a_category": b["p_a_category"], "agrees": b["agrees"],
            "review": result["review"],
            "a_correct": a["category"] == exp_cat,
            "a_action_correct": a["action"] == exp_action,
            "correct": outcome_correct(case, a, result["review"]),
            "baseline_correct": baseline_switchboard_correct(case),
            "judge": verdict["label"], "judge_reason": verdict["reason"],
            # Latency of a real (uncached) model call, from the cache when the answer was cached.
            "latency_s": a.get("model_latency_s", round(time.perf_counter() - started, 3)),
            "tokens": result["tokens"], "cost_eur": result["cost_eur"],
        })
    results = pd.DataFrame(rows)
    results.to_csv(RESULTS, index=False)
    print(f"Wrote {RESULTS.relative_to(ROOT)} ({len(results)} cases).\n")
    if results["a_error"].astype(bool).any():
        print(f"WARNING: {results['a_error'].astype(bool).sum()} cases had a Gemini error; their numbers are not meaningful.\n")

    summary = {}

    # 1. Component A
    in_scope = results[results["kind"].isin(["normal", "hard"])]
    summary["component_a"] = {
        "category_accuracy_all": round(accuracy_score(results["expected_category"], results["a_category"]), 3),
        "category_macro_f1_all": round(f1_score(results["expected_category"], results["a_category"], average="macro", zero_division=0), 3),
        "category_accuracy_normal_hard": round(in_scope["a_correct"].mean(), 3),
        "action_accuracy_all": round(results["a_action_correct"].mean(), 3),
    }

    # 2. Component B
    a_wrong = results[~results["a_correct"] & results["kind"].isin(["normal", "hard"])]
    flagged = results[results["review"] & results["kind"].isin(["normal", "hard"])]
    summary["component_b"] = {
        "held_out": json.loads(B_METRICS.read_text()) if B_METRICS.is_file() else None,
        "category_accuracy_on_cases": round(accuracy_score(results["expected_category"], results["b_category"]), 3),
        "router_errors_normal_hard": int(len(a_wrong)),
        "router_errors_caught (recall)": round(a_wrong["review"].mean(), 3) if len(a_wrong) else None,
        "flagged_that_were_errors (precision)": round((~flagged["a_correct"]).mean(), 3) if len(flagged) else None,
    }

    # 3. End to end vs baselines
    n_errors = int((~results["a_correct"] & results["kind"].isin(["normal", "hard"])).sum())
    summary["end_to_end"] = {
        "by_kind": results.groupby("kind").agg(cases=("id", "count"), correct=("correct", "mean"),
                                                sent_to_review=("review", "mean"),
                                                baseline_switchboard=("baseline_correct", "mean")).round(3).to_dict("index"),
        "product_correct": round(results["correct"].mean(), 3),
        "baseline_switchboard_correct": round(results["baseline_correct"].mean(), 3),
        "share_sent_to_review": round(results["review"].mean(), 3),
        "router_errors_caught_by_product": int(a_wrong["review"].sum()) if len(a_wrong) else 0,
        "router_errors_caught_by_random_10pct_audit (expected)": round(n_errors * RANDOM_AUDIT_SHARE, 2),
    }

    # 4. LLM judge and agreement with the team's labels
    judged = results.dropna(subset=["judge"])
    summary["judge"] = {"version": JUDGE_VERSION, "pass_rate": round((judged["judge"] == "pass").mean(), 3) if len(judged) else None}
    results[["id", "input", "expected_category", "expected_action", "a_reply"]].assign(label="", comment="").to_csv(TO_LABEL, index=False)
    if HUMAN_LABELS.is_file():
        human = pd.read_csv(HUMAN_LABELS).dropna(subset=["label"])
        merged = human.merge(results[["id", "judge"]], on="id")
        if len(merged):
            summary["judge"]["human_labels"] = len(merged)
            summary["judge"]["agreement_with_humans"] = round((merged["label"].str.strip() == merged["judge"]).mean(), 3)

    # 5. Cost and latency
    live = results[results["tokens"] > 0]
    summary["cost"] = {
        "mean_tokens": round(live["tokens"].mean(), 1) if len(live) else 0,
        "mean_cost_eur": round(live["cost_eur"].mean(), 6) if len(live) else 0,
        "median_latency_s": round(results["latency_s"].median(), 2),
        "p90_latency_s": round(results["latency_s"].quantile(0.9), 2),
        "price_assumption_eur_per_m_tokens": router.PRICE_EUR_PER_M,
    }

    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nWrote {SUMMARY.relative_to(ROOT)} and {TO_LABEL.relative_to(ROOT)} (grade 20+ replies there and copy them to human_labels.csv).")


if __name__ == "__main__":
    main()
