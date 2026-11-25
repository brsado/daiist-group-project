"""
The product: an AI call router (component A, Gemini agent) audited after the call by an
ML classifier (component B, scikit-learn). A's output is B's input: B scores A's category.

    run(raw_input) -> {input_summary, features, outputs, versions, review, tokens, cost_eur}

`raw_input` is the caller's words as transcribed (text). No names, phone or ID numbers.
"""

import re

import auditor
import router

# Review rule: a call goes to the supervisor when the auditor disagrees with the router, or
# when the auditor gives the router's category a probability below this threshold.
# PLACEHOLDER until the team sets it from eval/results.csv (see REPORT.md, Decision).
REVIEW_BELOW_P = 0.35

_SPANISH = {"de", "la", "que", "el", "en", "y", "a", "los", "se", "del", "las", "un", "por", "con", "no",
            "una", "su", "para", "es", "al", "lo", "me", "mi", "quiero", "hola", "necesito", "quería", "tengo", "le"}


def input_features(text: str) -> dict[str, float]:
    """What the drift check watches about the input itself."""
    words = re.findall(r"\w+", text.lower())
    return {
        "n_words": float(len(words)),
        "share_spanish_words": sum(w in _SPANISH for w in words) / len(words) if words else 0.0,
    }


def run(raw_input: str) -> dict:
    text = str(raw_input).strip()
    a = router.route(text)                       # component A: the router agent
    b = auditor.audit(text, a["category"])       # component B: audits A's category
    review = bool(a.get("error")) or (not b["agrees"]) or b["p_a_category"] < REVIEW_BELOW_P
    features = input_features(text) | {
        "auditor_confidence": b["confidence"],
        "p_router_category": b["p_a_category"],
        "agreement": float(b["agrees"]),
        "router_self_confidence": float(a.get("self_confidence", 0.0)),
    }
    return {
        "input_summary": text[:120],
        "features": features,
        "outputs": {"component_a": a, "component_b": b},
        "versions": {"component_a": f"{router.MODEL}/{router.PROMPT_VERSION}", "component_b": b["version"],
                     "review_rule": f"disagree_or_p<{REVIEW_BELOW_P}"},
        "review": review,
        "tokens": int(a.get("tokens", 0)),
        "cost_eur": float(a.get("cost_eur", 0.0)),
    }
