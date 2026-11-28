"""
Monitoring: quality signals over time, drift against the reference set, alerts.

The thresholds below were chosen by the team; see REPORT.md (Decision) for the reasons.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
REFERENCE_FILE = ROOT / "monitoring" / "reference_features.csv"

PSI_BINS = 5           # quantile bins of the reference; few, because samples are small
PSI_ALERT = 0.25       # alert when a feature's PSI exceeds this...
NOISE_MULTIPLE = 2     # ...and this many times the PSI expected by chance (psi_noise)
WINDOW = 100           # the drift check looks at the last WINDOW requests...
MIN_WINDOW = 20        # ...and stays silent with fewer than this
THUMBS_DOWN_ALERT = 0.3  # alert when this share of rated requests is 👎
AGREEMENT_ALERT = 0.6    # alert when the auditor agrees with the router on fewer than this share of calls

# Which features can fire the drift alert, and in which direction ("both", or "down": only when the
# live mean is below the reference mean). The others are still logged and shown with their PSI.
#   share_spanish_words - callers in another language: the auditor was trained on Spanish only.
#   auditor_confidence  - inputs unlike the training data; only a DROP matters (more confidence is fine).
# Not watched: n_words (normal phrasing varies a lot), router_self_confidence (Gemini says 0.95-1.0
# almost always, so its PSI swings on tiny changes), p_router_category / agreement (quality signals, not drift).
DRIFT_FEATURES = {"share_spanish_words": "both", "auditor_confidence": "down"}


def _bin(values: np.ndarray, reference: np.ndarray, bins: int) -> np.ndarray:
    """Bin index of each value, with bins defined by the reference.

    A feature with few distinct values in the reference (counts, labels coded as
    numbers) gets one bin per value plus one for anything else; a continuous one
    gets quantile bins, so each holds about the same share of the reference.
    """
    distinct = np.unique(reference)
    if len(distinct) <= bins:
        index = np.searchsorted(distinct, values)
        found = (index < len(distinct)) & (distinct[np.minimum(index, len(distinct) - 1)] == values)
        return np.where(found, index, len(distinct))
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)[1:-1]))
    return np.searchsorted(edges, values, side="right")


def psi(reference, current, bins: int = PSI_BINS) -> float:
    """Population stability index of `current` against `reference`.

    0 means the same distribution; the usual rule of thumb is < 0.1 stable,
    0.1-0.25 moderate, > 0.25 a large shift. With small samples, though, PSI is
    large by chance alone: see `psi_noise`.
    """
    reference, current = np.asarray(reference, float), np.asarray(current, float)
    reference, current = reference[~np.isnan(reference)], current[~np.isnan(current)]
    if len(reference) == 0 or len(current) == 0:
        return float("nan")
    ref_bins, cur_bins = _bin(reference, reference, bins), _bin(current, reference, bins)
    n_bins = max(ref_bins.max(), cur_bins.max()) + 1
    expected = np.bincount(ref_bins, minlength=n_bins) / len(reference)
    actual = np.bincount(cur_bins, minlength=n_bins) / len(current)
    expected, actual = np.clip(expected, 1e-4, None), np.clip(actual, 1e-4, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def psi_noise(n_reference: int, n_current: int, bins: int = PSI_BINS) -> float:
    """PSI you would expect by chance, with no drift at all, for these sample sizes.

    About (bins - 1) * (1/n_reference + 1/n_current): with 40 reference inputs and
    20 live ones that is already 0.3. An alert below this is a coin toss.
    """
    return (bins - 1) * (1 / n_reference + 1 / n_current)


def load_reference() -> pd.DataFrame | None:
    """Features of the reference inputs (`main.py reference` writes them)."""
    return pd.read_csv(REFERENCE_FILE) if REFERENCE_FILE.is_file() else None


def drift(reference: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """PSI per feature, and whether it alerts. Both frames have one column per feature (no `f_` prefix).

    The rule: alert when PSI exceeds PSI_ALERT *and* NOISE_MULTIPLE times what
    chance alone would give with these sample sizes.
    """
    rows = []
    for feature in reference.columns:
        if feature in current.columns:
            value = psi(reference[feature], current[feature])
            noise = psi_noise(reference[feature].notna().sum(), max(current[feature].notna().sum(), 1))
            threshold = max(PSI_ALERT, NOISE_MULTIPLE * noise)
            direction = DRIFT_FEATURES.get(feature)
            fires = direction is not None and value > threshold
            if direction == "down":
                fires = fires and current[feature].mean() < reference[feature].mean()
            rows.append({"feature": feature, "watched": direction or "no", "psi": round(value, 3),
                         "threshold": round(threshold, 3), "alert": bool(fires)})
    return pd.DataFrame(rows, columns=["feature", "watched", "psi", "threshold", "alert"])


def live_features(logs: pd.DataFrame) -> pd.DataFrame:
    """The features of the last WINDOW logged requests, without the `f_` prefix."""
    columns = [c for c in logs.columns if c.startswith("f_")]
    return logs[columns].tail(WINDOW).rename(columns=lambda c: c[2:])


QUALITY_ROLLING = 10  # each point of the quality chart = the mean over the last 10 requests


def quality(logs: pd.DataFrame) -> pd.DataFrame:
    """Quality signals as a rolling mean over the last QUALITY_ROLLING requests, one point per request.

    Long format (time, signal, value) for a line plot. Rolling over requests (not hours) so the
    chart has a line even with little traffic, as on the free plan.
    """
    if logs.empty:
        return pd.DataFrame(columns=["time", "signal", "value"])
    df = logs.sort_values("timestamp").set_index("timestamp")
    roll = lambda series: series.astype(float).rolling(QUALITY_ROLLING, min_periods=1).mean()
    signals = pd.DataFrame({"share sent to review": roll(df["review"])})
    if "f_agreement" in df:
        signals["share router-auditor agreement"] = roll(df["f_agreement"])
    if "f_p_router_category" in df:
        signals["mean P(router category)"] = roll(df["f_p_router_category"])
    long = signals.reset_index(names="time").melt("time", var_name="signal", value_name="value")
    rated = df["feedback"].dropna()
    if len(rated):
        thumbs = roll(rated.astype(float) < 0).rename("value").reset_index(names="time")
        long = pd.concat([long, thumbs.assign(signal="share 👎 (of rated)")], ignore_index=True)
    return long.dropna()


def summary(logs: pd.DataFrame) -> pd.DataFrame:
    if logs.empty:
        return pd.DataFrame({"metric": ["requests"], "value": [0]})
    rated = logs["feedback"].dropna().astype(float)
    rows = {
        "requests": len(logs),
        "sent to review": f"{logs['review'].mean():.0%}",
        "rated 👍/👎": len(rated),
        "share 👎 (of rated)": f"{(rated < 0).mean():.0%}" if len(rated) else "-",
        "router-auditor agreement": f"{logs['f_agreement'].mean():.0%}" if "f_agreement" in logs else "-",
        "median latency (s)": round(float(logs["latency_s"].median()), 2),
        "mean cost per request (€)": round(float(logs["cost_eur"].mean()), 5),
        "total cost (€)": round(float(logs["cost_eur"].sum()), 4),
    }
    return pd.DataFrame({"metric": list(rows), "value": [str(v) for v in rows.values()]})


def alerts(logs: pd.DataFrame, reference: pd.DataFrame | None) -> list[str]:
    """The alert rules. Each fired alert is one message."""
    fired = []
    window = logs.tail(WINDOW)
    if reference is not None and len(window) >= MIN_WINDOW:
        report = drift(reference, live_features(window))
        for row in report[report["alert"]].itertuples():
            fired.append(f"Drift in `{row.feature}`: PSI {row.psi} > {row.threshold} over the last {len(window)} requests.")
    if "f_agreement" in window and len(window) >= MIN_WINDOW and window["f_agreement"].mean() < AGREEMENT_ALERT:
        fired.append(f"The auditor agrees with the router on only {window['f_agreement'].mean():.0%} of the last {len(window)} calls (< {AGREEMENT_ALERT:.0%}).")
    rated = window["feedback"].dropna().astype(float) if not window.empty else pd.Series(dtype=float)
    if len(rated) >= MIN_WINDOW and (rated < 0).mean() > THUMBS_DOWN_ALERT:
        fired.append(f"{(rated < 0).mean():.0%} of the last {len(rated)} rated requests are 👎 (> {THUMBS_DOWN_ALERT:.0%}).")
    return fired


def by_category(logs: pd.DataFrame) -> pd.DataFrame:
    """Calls per router category, split by whether they went to review."""
    if logs.empty:
        return pd.DataFrame(columns=["category", "result", "calls"])
    cats = logs["outputs"].map(lambda o: (o or {}).get("component_a", {}).get("category", "?"))
    table = pd.DataFrame({"category": cats, "result": logs["review"].map({True: "a revisión", False: "validada"})})
    return table.value_counts().rename("calls").reset_index()
