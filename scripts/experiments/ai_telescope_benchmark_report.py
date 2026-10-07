"""Verify and publish a local summary/figure of the frozen physical benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.experiments.ai_telescope_blind_scan import _checked_complete
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256


def report_metadata(spec, summary, operating):
    """Validate cohort/operating-point agreement before publishing a comparison."""
    ids = {role: [str(row["target_id"]) for row in spec["targets"][role]]
           for role in ("calibration", "evaluation")}
    if any(not members or len(members) != len(set(members)) for members in ids.values()):
        raise ValueError("Report requires nonempty, unique cohort memberships")
    if set(ids["calibration"]) & set(ids["evaluation"]):
        raise ValueError("Calibration and evaluation cohorts overlap")
    hosts = len(ids["evaluation"])
    if summary["registered_hosts"] != hosts or operating["calibration_hosts"] != len(ids["calibration"]):
        raise ValueError("Reported cohort sizes differ from the frozen membership")
    thresholds = {**spec["neural_thresholds"], **{
        m: operating["classical"][m]["selected_threshold"] for m in ("bls", "tls")}}
    if summary["thresholds"] != thresholds or operating["neural"] != spec["neural_thresholds"]:
        raise ValueError("Reported thresholds differ from the frozen operating points")
    budget = spec["config"]["target_control_events_per_27_days"]
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("Invalid report control budget")
    observed_counts = set()
    for method in ("v2", "v3", "bls", "tls"):
        row = summary["methods"][method]
        observed = row["hosts_with_observable_injection"]
        if (row["registered_hosts"] != hosts or type(observed) is not int
                or not 0 <= row["incremental_hosts"] <= observed <= hosts):
            raise ValueError("Method recovery counts differ from the frozen cohort")
        observed_counts.add(observed)
    if len(observed_counts) != 1:
        raise ValueError("Methods have different observable-host denominators")
    observable = observed_counts.pop()
    return {"registered_hosts": hosts, "calibration_hosts": len(ids["calibration"]),
            "observable_hosts": observable, "unobservable_hosts": hosts-observable,
            "control_budget": budget, "thresholds": thresholds}


def verify_spec_binding(spec, summary, operating, receipt):
    checksum = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    if any(item.get("spec_sha256") != checksum for item in (summary, operating, receipt)):
        raise ValueError("Report artifacts reference different frozen specifications")


def report_paths(run_value, output_value):
    paths = []
    for value in (run_value, output_value):
        part = Path(value)
        if part.is_absolute() or ".." in part.parts or not part.parts:
            raise ValueError("Paths must stay inside the project")
        path = (ROOT/part).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("Report paths resolve outside the project")
        paths.append(path)
    run, output = paths
    if run == output or run in output.parents or output in run.parents:
        raise ValueError("Export directory must be separate from the frozen run")
    return run, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="outputs/research/ai_telescope/physical-benchmark-v1")
    parser.add_argument("--output", default="results/ai_telescope_physical_benchmark_v1")
    args = parser.parse_args(argv)
    run, output = report_paths(args.run, args.output)
    receipt = _checked_complete(run)
    summary = json.loads((run/"summary.json").read_text())
    spec = json.loads((run/"spec.json").read_text())
    operating = json.loads((run/"operating_point.json").read_text())
    verify_spec_binding(spec, summary, operating, receipt)
    metadata = report_metadata(spec, summary, operating)
    hosts, calibration_hosts = metadata["registered_hosts"], metadata["calibration_hosts"]
    budget = metadata["control_budget"]
    run_link = Path(os.path.relpath(run, output)).as_posix()
    methods_link = Path(os.path.relpath(ROOT/"docs/ai_telescope_research.md", output)).as_posix()
    output.mkdir(parents=True, exist_ok=True)
    methods = ["v2", "v3", "bls", "tls"]
    colors = ["#8395a7", "#2471a3", "#ca6f1e", "#148f77"]
    labels = ["v2", "v3", "BLS", "TLS"]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    totals = [summary["methods"][m] for m in methods]
    recovery = np.array([r["incremental_host_recovery"] for r in totals])*100
    bounds = np.array([r["host_wilson_95"] for r in totals])*100
    axes[0, 0].bar(labels, recovery, color=colors,
                   yerr=np.array([recovery-bounds[:, 0], bounds[:, 1]-recovery]), capsize=4)
    axes[0, 0].set(ylabel="Incremental host recovery (%)", ylim=(0, 100), title=f"All {hosts} registered hosts · Wilson 95% intervals")
    for i, row in enumerate(totals):
        axes[0, 0].text(i, bounds[i, 1]+2, f"{row['incremental_hosts']}/{hosts}", ha="center", fontsize=9)
    rates = [r["inverted_alerts_per_27_days"] for r in totals]
    axes[0, 1].bar(labels, rates, color=colors)
    axes[0, 1].axhline(budget, color="#333333", linestyle="--", label="Calibration budget")
    axes[0, 1].set(ylabel="Inverted-control events / 27 exposure-days", title="Realized evaluation alert rates")
    axes[0, 1].legend(frameon=False)
    for i, rate in enumerate(rates):
        axes[0, 1].text(i, rate+.02, f"{rate:.2f}", ha="center", fontsize=9)
    for axis, source, ticks, title in (
            (axes[1, 0], summary["by_mode"], spec["config"]["modes"], "Recovery by signal mode"),
            (axes[1, 1], summary["by_depth"], [str(d) for d in spec["config"]["depths"]], "Recovery by injected central depth")):
        x = np.arange(len(ticks)); width = .18
        for i, method in enumerate(methods):
            values = [100*source[t][method]["incremental_host_recovery"] for t in ticks]
            axis.bar(x+(i-1.5)*width, values, width, label=labels[i], color=colors[i])
        names = ticks if source is summary["by_mode"] else [f"{float(t)*1e6:g} ppm" for t in ticks]
        axis.set(xticks=x, xticklabels=names, ylabel="Incremental host recovery (%)", ylim=(0, 100), title=title)
    axes[1, 0].legend(frameon=False, ncol=4)
    for axis in axes.flat:
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True); axis.grid(axis="y", alpha=.2)
    fig.suptitle("Frozen TESS physical-injection benchmark\nEvent localization; matches already present on original data excluded", fontsize=13)
    fig.savefig(output/"comparison.png", dpi=180)
    fig.savefig(output/"comparison.pdf")
    plt.close(fig)
    v2, v3 = summary["methods"]["v2"], summary["methods"]["v3"]
    tls = summary["methods"]["tls"]
    interpretation = (
        f"v3 recovered {v3['incremental_hosts']}/{hosts} hosts versus v2's {v2['incremental_hosts']}/{hosts} "
        f"(paired exact p={summary['paired_incremental_recovery']['v3_vs_v2']['mcnemar_exact_two_sided_p']:.3f}). "
        f"Its control-alert rate was {v3['inverted_alerts_per_27_days']:.3f} per 27 days "
        f"against the frozen calibration budget of {budget:g}. "
        f"TLS recovered {tls['incremental_hosts']}/{hosts} hosts and {tls['incremental_events']} individual events "
        f"versus v3's {v3['incremental_events']}, at {tls['inverted_alerts_per_27_days']:.3f} control alerts per 27 days."
    )
    lines = [f"# Frozen physical-injection benchmark on {hosts} hosts", "",
             f"All {calibration_hosts} calibration hosts and all {hosts} development-disjoint evaluation hosts completed. "
             "Weights, injection schedule, and search settings were frozen before inference; BLS/TLS operating thresholds were frozen before evaluation.", "",
             interpretation, "",
             "| Method | Incremental host recovery | Incremental event recovery | Inverted alerts / 27 days |",
             "| --- | ---: | ---: | ---: |"]
    for method, label in zip(methods, labels):
        row = summary["methods"][method]
        lines.append(f"| {label} | {row['incremental_hosts']}/{hosts} ({row['incremental_host_recovery']:.1%}) | "
                     f"{row['incremental_events']}/{row['injected_events']} ({row['incremental_event_recovery']:.1%}) | {row['inverted_alerts_per_27_days']:.3f} |")
    lines += ["", "![Recovery and control comparison](comparison.png)", "",
              f"v3 recovered {v3['incremental_hosts']} hosts versus v2's {v2['incremental_hosts']} under the same new protocol. "
              f"The shared calibration budget is at most {budget:g} control events per 27 exposure-days; actual evaluation alert rates differ. "
              "The table must be read jointly across sensitivity and alert volume.", "",
              f"{metadata['observable_hosts']}/{hosts} hosts had sufficiently observed injections; "
              f"{metadata['unobservable_hosts']} lacked adequate transit coverage. "
              f"The registered primary denominator remains {hosts}. The recovery counts should not be interpreted "
              "as sensitivity conditional on having observed a transit.", "", "## By signal mode", "",
              "| Mode | Hosts | v2 recovered | v3 recovered | BLS recovered | TLS recovered |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for mode, data in summary["by_mode"].items():
        lines.append(f"| {mode} | {data['v3']['registered_hosts']} | " + " | ".join(str(data[m]["incremental_hosts"]) for m in methods) + " |")
    lines += ["", "## Interpretation", "",
              "Recovery requires a one-to-one event match within half the true transit duration. "
              "The primary metric removes matches already found in the original, uninjected observation. "
              f"All {hosts} hosts remain in the denominator; raw matches and observable-event counts are retained in the machine-readable summary. "
              "This stricter matching differs from the previous trapezoidal audit, so its percentages are not directly comparable.", ""]
    for comparison, paired in summary["paired_incremental_recovery"].items():
        lines.append(f"- {comparison}: {paired['v3_only']} v3-only recoveries, {paired['other_only']} other-only; "
                     f"two-sided exact McNemar p={paired['mcnemar_exact_two_sided_p']:.4g}, without multiplicity correction.")
    long_events = []
    for target in spec["targets"]["evaluation"]:
        row = json.loads((run/"evaluation"/("TIC"+target["target_id"]+".json")).read_text())
        if row["truth"]["duration_hours"] > spec["duration_bounds_hours"][1]:
            long_events.append(target["target_id"])
    lines += ["", "BLS/TLS search one strongest periodic hypothesis from the exact injected aperture sums, "
              "using the same trial-period grid and blind detrending. v2/v3 scan pixels and light curves for local events. "
              "Single transits and TTVs probe different algorithmic capabilities; detection of an event does not establish a planet or recover its orbit. "
              f"{len(long_events)} injected durations exceed the neural models' frozen upper segment-duration prior; those hosts remain included.", "",
              "Physical transit shapes use assumed stellar density and limb darkening, with an empirical static pixel template. "
              "The hosts are an archival sample previously scanned by v2, excluded from development, with one sector each. "
              "Inverted controls do not represent every astrophysical false positive. "
              "No watcher or website scoring was changed.", "",
              "The coarse predeclared threshold grids achieved different calibration alert rates. "
              f"BLS selected a depth-S/N threshold of {metadata['thresholds']['bls']:g}; its recovery here "
              "does not establish an intrinsic limitation of BLS. A claim about the algorithms in general "
              "requires independently tuned baselines and a fresh evaluation cohort.", "",
              "Background-source and eclipsing-binary injections, human/catalog review, repeated seeds, "
              "independently retrained ablations, and multi-sector tests remain necessary before broader claims or deployment.", "",
              f"- [Detailed protocol and report]({run_link}/report.md)",
              f"- [Per-host results]({run_link}/host_recovery.csv)",
              f"- [Calibration operating points]({run_link}/operating_point.json)",
              f"- [Full summary]({run_link}/summary.json)",
              "- [Exportable figure](comparison.pdf)",
              f"- [Methods]({methods_link})"]
    (output/"README.md").write_text("\n".join(lines)+"\n")
    evidence = {"status": "complete", "created_at": utc_now(), "benchmark_spec_sha256": receipt["spec_sha256"],
                "report_metadata": metadata,
                "verified_benchmark_artifacts": len(receipt["files"]),
                "durations_exceeding_neural_upper_prior": long_events,
                "files": {str((run/name).relative_to(ROOT)): file_sha256(run/name) for name in
                          ("complete.json", "spec.json", "operating_point.json", "summary.json", "host_recovery.csv", "report.md")}}
    evidence["files"].update({str(p.relative_to(ROOT)): file_sha256(p) for p in
                              (output/"README.md", output/"comparison.png", output/"comparison.pdf", Path(__file__))})
    atomic_json(output/"evidence.json", evidence)
    print(json.dumps({"status": "complete", "verified_benchmark_artifacts": len(receipt["files"]), "output": args.output}))


if __name__ == "__main__":
    main()
