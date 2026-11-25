"""
Component B: the post-call ML auditor (scikit-learn).

It reads the caller's words and predicts one of the 16 Moysi call categories with a
probability. In the pipeline it receives component A's decision and answers: how likely is
it that A's category is right (P(A's category)), and which category would it pick itself.

    uv run python auditor.py          # compare models on data/phrases.csv, save the best

The trained model is committed as models/auditor.joblib (a few hundred KB), so the app
never trains anything at start-up.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parent
PHRASES = ROOT / "data" / "phrases.csv"
REFERENCE = ROOT / "eval" / "reference.csv"
MODEL_FILE = ROOT / "models" / "auditor.joblib"
METRICS_FILE = ROOT / "eval" / "component_b_metrics.json"


def _features() -> FeatureUnion:
    return FeatureUnion([
        ("words", TfidfVectorizer(strip_accents="unicode", lowercase=True, ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("chars", TfidfVectorizer(strip_accents="unicode", lowercase=True, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
    ])


CANDIDATES = {
    "tfidf_logreg": lambda: Pipeline([("tfidf", _features()), ("clf", LogisticRegression(C=10, max_iter=2000, class_weight="balanced"))]),
    "tfidf_complement_nb": lambda: Pipeline([("tfidf", _features()), ("clf", ComplementNB(alpha=0.3))]),
    "tfidf_linear_svm_calibrated": lambda: Pipeline([("tfidf", _features()), ("clf", CalibratedClassifierCV(LinearSVC(C=1, class_weight="balanced"), cv=3))]),
}


def train() -> None:
    data = pd.read_csv(PHRASES)
    train_df, test_df = data[data["split"] == "train"], data[data["split"] == "test"]
    results = {}
    for name, make in CANDIDATES.items():
        model = make().fit(train_df["text"], train_df["categoria"])
        pred = model.predict(test_df["text"])
        results[name] = {
            "accuracy": round(accuracy_score(test_df["categoria"], pred), 3),
            "macro_f1": round(f1_score(test_df["categoria"], pred, average="macro"), 3),
        }
        print(f"{name:<30} accuracy {results[name]['accuracy']:.3f}  macro-F1 {results[name]['macro_f1']:.3f}")
    # The review rule thresholds a probability, so we prefer logistic regression (better calibrated
    # probabilities than naive Bayes) unless another model beats it by more than 2 points of macro-F1.
    best = max(results, key=lambda n: results[n]["macro_f1"])
    if results[best]["macro_f1"] - results["tfidf_logreg"]["macro_f1"] <= 0.02:
        best = "tfidf_logreg"
    print(f"\nChosen: {best}. Per-class report on the held-out split:\n")
    model = CANDIDATES[best]().fit(train_df["text"], train_df["categoria"])
    print(classification_report(test_df["categoria"], model.predict(test_df["text"]), zero_division=0))

    # The saved model is trained on all phrases except the drift reference set (eval/reference.csv):
    # the auditor would be over-confident on phrases it was trained on, and the drift check compares
    # live confidence with the reference. The numbers above come from the held-out split.
    reference = set(pd.read_csv(REFERENCE)["input"].str.strip()) if REFERENCE.is_file() else set()
    final_data = data[~data["text"].str.strip().isin(reference)]
    final = CANDIDATES[best]().fit(final_data["text"], final_data["categoria"])
    print(f"Final model trained on {len(final_data)} phrases ({len(data) - len(final_data)} kept out as the drift reference).")
    MODEL_FILE.parent.mkdir(exist_ok=True)
    joblib.dump({"model": final, "version": f"auditor-{best}-v1", "n_train": len(final_data)}, MODEL_FILE)
    METRICS_FILE.write_text(json.dumps({"n_train": len(train_df), "n_test": len(test_df), "candidates": results, "chosen": best}, indent=2))
    print(f"Saved {MODEL_FILE.relative_to(ROOT)} and {METRICS_FILE.relative_to(ROOT)}.")


_loaded: dict | None = None


def load() -> dict:
    global _loaded
    if _loaded is None:
        _loaded = joblib.load(MODEL_FILE)
    return _loaded


def audit(text: str, a_category: str) -> dict:
    """Component B's verdict on component A's category for this call."""
    bundle = load()
    model = bundle["model"]
    proba = model.predict_proba([text])[0]
    classes = list(model.classes_)
    order = np.argsort(proba)[::-1]
    b_category, b_top = classes[order[0]], float(proba[order[0]])
    p_a = float(proba[classes.index(a_category)]) if a_category in classes else 0.0
    return {
        "category": b_category,
        "confidence": round(b_top, 3),
        "p_a_category": round(p_a, 3),
        "margin": round(b_top - float(proba[order[1]]), 3),
        "agrees": b_category == a_category,
        "top3": {classes[i]: round(float(proba[i]), 3) for i in order[:3]},
        "version": bundle["version"],
    }


if __name__ == "__main__":
    train()
