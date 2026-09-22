"""Validation-only calibration and explicitly descriptive candidate metrics."""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit
from sklearn.metrics import average_precision_score, roc_auc_score


def checked(y, logits):
    y, logits = np.asarray(y, dtype=float), np.asarray(logits, dtype=float)
    if (y.ndim != 1 or not len(y) or logits.shape != y.shape
            or not np.isin(y, [0, 1]).all() or not np.isfinite(logits).all()):
        raise ValueError("Metrics require equally sized finite logits and binary labels")
    return y, logits


def fit_temperature(y, logits):
    y, logits = checked(y, logits)
    if len(np.unique(y)) != 2:
        raise ValueError("Calibration requires both classes")
    def objective(log_t):
        z = logits / np.exp(log_t)
        return float(np.mean(np.logaddexp(0, z) - y * z))
    result = minimize_scalar(objective, bounds=(np.log(.05), np.log(20.)), method="bounded",
                             options={"maxiter": 100, "xatol": 1e-8})
    # Include identity explicitly: a numerical optimizer may not worsen its fit.
    log_t = float(result.x) if result.success and result.fun < objective(0.) else 0.
    return {"temperature": float(np.exp(log_t)), "n_fit": len(y),
            "nll_before": objective(0.), "nll_after": objective(log_t),
            "bounds": [.05, 20.], "fit_scope": "calibration_validation_groups_only",
            "optimizer_success": bool(result.success),
            "at_bound": bool(np.exp(log_t) < .051 or np.exp(log_t) > 19.99)}


def rates(y, scores, threshold):
    y = np.asarray(y, dtype=int)
    chosen = np.zeros(len(y), dtype=bool) if threshold is None else scores >= threshold
    tp, fp = int(np.sum(chosen & (y == 1))), int(np.sum(chosen & (y == 0)))
    pos, neg = int(np.sum(y == 1)), int(np.sum(y == 0))
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": pos - tp, "tn": neg - fp,
            "recall": tp / pos if pos else None, "fpr": fp / neg if neg else None,
            "precision": tp / (tp + fp) if tp + fp else None, "selected": tp + fp}


def choose_thresholds(y, logits, precision_target=.9, fpr_target=.05):
    """Use only the checkpoint-selection subset; empirical, not rate guarantees."""
    y, logits = checked(y, logits)
    p = expit(logits)
    candidates = [rates(y, p, float(t)) for t in np.unique(p)]
    output = {}
    for name, acceptable in (
        ("precision", [r for r in candidates if r["precision"] is not None and r["precision"] >= precision_target]),
        ("fpr", [r for r in candidates if r["fpr"] is not None and r["fpr"] <= fpr_target])):
        best = max(acceptable, key=lambda r: (r["recall"], r["threshold"])) if acceptable else rates(y, p, None)
        output[name] = {**best, "attainable": bool(acceptable),
                        "target": precision_target if name == "precision" else fpr_target,
                        "scope": "selection_validation_empirical_not_survey_guarantee"}
    return output


def metrics(y, logits, temperature=1., thresholds=None):
    y, logits = checked(y, logits)
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Temperature must be positive and finite")
    z = logits / temperature
    p = expit(z)
    bins = []
    assignment = np.minimum((p * 10).astype(int), 9)
    ece = 0.
    for i in range(10):
        use = assignment == i
        n = int(use.sum())
        score = float(p[use].mean()) if n else None
        observed = float(y[use].mean()) if n else None
        if n:
            ece += n / len(y) * abs(score - observed)
        bins.append({"lower": i / 10, "upper": (i + 1) / 10, "n": n,
                     "mean_score": score, "positive_fraction": observed})
    both = len(np.unique(y)) == 2
    result = {"n": len(y), "positive": int(y.sum()),
              "average_precision": float(average_precision_score(y, logits)) if both else None,
              "roc_auc": float(roc_auc_score(y, logits)) if both else None,
              "ranking_basis": "logits_avoids_sigmoid_saturation_ties",
              "brier": float(np.mean((p - y) ** 2)),
              "nll": float(np.mean(np.logaddexp(0, z) - y * z)),
              "ece_10_equal_width": float(ece), "reliability": bins,
              "at_0_5": rates(y, p, .5)}
    if thresholds:
        # Use unscaled logits for the original decision set. Temperature scaling
        # preserves this set when the threshold is transformed consistently.
        result["selection_thresholds"] = {name: rates(y, expit(logits), spec["threshold"])
                                           for name, spec in thresholds.items()}
    return result


def paired_group_bootstrap(y, groups, baseline, treatment, seed=2718, repeats=200):
    """Descriptive paired AP difference interval on one audit, not a p-value."""
    y, baseline = checked(y, baseline)
    _, treatment = checked(y, treatment)
    groups = np.asarray(groups)
    if groups.shape != y.shape or not 20 <= repeats <= 2000:
        raise ValueError("Invalid grouped bootstrap inputs")
    unique = np.unique(groups)
    blocks = [np.flatnonzero(groups == g) for g in unique]
    rng = np.random.default_rng(seed)
    delta = []
    for _ in range(repeats):
        idx = np.concatenate([blocks[i] for i in rng.integers(len(blocks), size=len(blocks))])
        if len(np.unique(y[idx])) == 2:
            delta.append(average_precision_score(y[idx], treatment[idx]) -
                         average_precision_score(y[idx], baseline[idx]))
    return {"metric": "DANN_minus_pooled_average_precision", "repeats": repeats,
            "valid_repeats": len(delta), "seed": seed,
            "percentile_95": np.quantile(delta, [.025, .975]).tolist() if delta else None,
            "scope": "paired_validation_audit_groups_descriptive_not_independent_confirmation"}
