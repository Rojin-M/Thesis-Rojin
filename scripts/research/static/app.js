"use strict";
// Every data-bearing string is escaped. Only fixed local routes become links.
const app = document.getElementById("app");
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pretty = value => esc(JSON.stringify(value, null, 2));
const words = value => String(value ?? "").replaceAll("_", " ");
const badge = value => `<span class="badge ${/^[a-z_]+$/.test(value) ? value : ""}">${esc(words(value))}</span>`;
const date = value => value ? esc(new Date(value).toLocaleString()) : "—";
const short = value => esc(String(value).slice(0, 12));
const number = (value, digits=4) => value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "Unavailable";
const cohorts = ["synthetic_fixture", "known_object_control", "archival_pilot", "prospective_search"];
const statuses = ["unreviewed", "in_review", "on_hold", "follow_up", "rejected"];
let csrf = null;
let navigation = 0;
let activeRenders = 0;
let checkInFlight = false;
const autoRefreshRoutes = new Set(["overview", "jobs", "candidates", "watcher"]);

function currentRoute() {
  return (location.hash.slice(1) || "overview").split(/[/?]/, 1)[0];
}

function safeToRefreshAutomatically() {
  return autoRefreshRoutes.has(currentRoute()) && !document.hidden && !checkInFlight &&
    !document.activeElement?.closest("form") && !app.querySelector('form[data-dirty="true"]');
}

function refreshControls(watcher) {
  const automation = watcher?.automation;
  const request = automation?.check_request;
  const pending = request && ["queued", "running"].includes(request.status);
  const available = automation?.enabled && automation.service_state === "running" && automation.phase !== "paused";
  const reason = !automation?.enabled ? "Start the automatic watcher to check for new data." :
    automation.service_state !== "running" ? "The automatic watcher is stopped or its heartbeat is stale." :
    automation.phase === "paused" ? "The automatic watcher is paused; inspect its status below." :
    pending ? "A check is already queued or running." : "Checks the watched targets and processes newly available products within the saved limits.";
  return '<button id="refresh" class="secondary" title="Reload saved results without starting a search">Refresh results</button>' +
    (watcher ? `<button id="check-new-data" ${!available || pending ? "disabled" : ""} aria-describedby="check-help" title="${esc(reason)}">Check for new data</button><span id="check-help" class="small muted action-help">${esc(reason)}</span><span id="check-message" class="small action-help" role="status"></span>` : "");
}

function automationPanel(watcher) {
  const automation = watcher.automation;
  if (!automation?.enabled) return '<section class="card"><h2>Automatic processing</h2><p>Automatic processing is not running. Saved candidates remain available below.</p><p class="tagline">Refresh results reloads the saved records. Metadata-only polling observes availability without creating candidates.</p></section>';
  const phases = {waiting:"Waiting for the next scheduled check", polling:"Checking public data availability", processing:"Detecting signals and assembling review evidence", paused:"Processing paused", error:"The latest cycle reported an error"};
  const phaseLabel = automation.service_state === 'stopped' ? 'Automatic worker is stopped' :
    automation.service_state === 'stale' ? 'Worker heartbeat is stale; processing state is unverified' :
    phases[automation.phase] || words(automation.phase);
  const request = automation.check_request;
  const requestText = {queued:"Check queued. The worker will pick it up shortly.", running:"Requested check is running.", succeeded:"Requested check finished. The saved results are shown below.", failed:"Requested check failed. Inspect the recorded error."};
  return `<section class="card"><h2>Automatic processing ${badge(automation.service_state)}</h2><p><strong>${esc(phaseLabel)}</strong><br><span class="small muted">Recorded phase: ${esc(words(automation.phase))}</span></p><dl class="facts"><div><dt>Watched TICs</dt><dd>${esc((automation.targets || []).join(', ') || 'None')}</dd></div><div><dt>Candidate cohort</dt><dd>${badge(automation.cohort || 'archival_pilot')}</dd></div><div><dt>Worker heartbeat</dt><dd>${date(automation.heartbeat_at)}</dd></div><div><dt>Check request</dt><dd>${request ? badge(request.status) : 'None pending'}</dd></div></dl><p class="tagline">New public light curves for these targets are checked for transit signals, scored by the retained CNN, checked against available catalog evidence, and saved for review within the configured limits. Known controls and archival proposals retain their cohort labels; an unmatched signal does not establish a discovery.</p>${request ? `<p class="notice ${request.status === 'failed' ? 'error' : ''}" role="status">${esc(requestText[request.status] || words(request.status))}<br><span class="small">Request ${short(request.id)} · ${date(request.created_at)}</span></p>${request.error ? details('Check error', request.error) : ''}` : ''}${automation.last_error ? `<p class="notice error">${esc(automation.last_error.message || JSON.stringify(automation.last_error))}</p>` : ''}${automation.last_cycle ? `<p class="small">Latest cycle: ${badge(automation.last_cycle.status)} · ${Number(automation.last_cycle.new_candidates || 0)} new proposals saved · ${(automation.last_cycle.selected_product_ids || []).length} products selected for processing.</p>${details('Latest automatic cycle and processing result', automation.last_cycle)}` : ''}<p class="tagline">This view refreshes every 30 seconds while visible and idle. Editing a form pauses updates.</p></section>`;
}

async function api(path, data) {
  const options = {headers: {"Accept": "application/json"}, cache: "no-store"};
  if (data !== undefined) {
    if (!csrf) csrf = (await api("/api/session")).csrf_token;
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrf;
    options.body = JSON.stringify(data);
  }
  const controller = new AbortController();
  options.signal = controller.signal;
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, options);
    if (!response.headers.get("Content-Type")?.includes("application/json")) {
      throw new Error(`The website returned an unexpected response (HTTP ${response.status}). Reconnect port 8766 in VS Code's Ports panel, then retry loading.`);
    }
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("The website did not respond within 15 seconds. Reconnect port 8766 in VS Code's Ports panel, then retry loading." +
        (data !== undefined ? " Check the saved status before submitting this action again." : ""));
    }
    if (error instanceof TypeError) throw new Error("Connection to the website was interrupted. Reconnect port 8766 in VS Code's Ports panel, then retry loading.");
    if (error instanceof SyntaxError) throw new Error("The website response was incomplete. Retry loading; if it persists, reconnect port 8766 in VS Code's Ports panel.");
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function details(title, value) { return `<details><summary>${esc(title)}</summary><pre>${pretty(value)}</pre></details>`; }
function empty(title, message) { return `<div class="empty"><strong>${esc(title)}</strong>${esc(message)}</div>`; }
function heading(eyebrow, title, lead, actions="") {
  return `<div class="page-head"><div><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p class="lead">${esc(lead)}</p></div><div class="actions">${actions}</div></div>`;
}
function options(values, current, all) {
  return (all ? `<option value="">${esc(all)}</option>` : "") + values.map(value => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(words(value))}</option>`).join("");
}
function stageStrip(stages) {
  return `<div class="stage-list">${stages.map(s => `<div class="stage ${esc(s.status)}"><strong>${esc(words(s.name))}</strong>${badge(s.status)}<small>attempt ${s.attempts}/${s.max_attempts}</small></div>`).join("")}</div>`;
}
function candidateRows(items) {
  return `<div class="table-wrap"><table><thead><tr><th>Signal / target</th><th>Cohort</th><th>Period / epoch</th><th>CNN ranking / registry snapshot</th><th>Execution</th><th>Review</th></tr></thead><tbody>${items.map(c => `<tr><td><a href="#candidate/${c.id}">${esc(c.target_id)}</a><br><span class="small muted">${esc(c.signal_key)}</span></td><td>${badge(c.cohort)}</td><td>${c.ephemeris.period_days.toFixed(6)} d<br><span class="small muted">${c.ephemeris.epoch_bjd_tdb} BJD TDB</span></td><td>${number(c.assessment?.score, 5)}<br><span class="small muted">${esc(words(c.assessment?.registry_status || "not_run"))}</span></td><td>${badge(c.job_status)}</td><td>${badge(c.review_status)}</td></tr>`).join("")}</tbody></table></div>`;
}

function modelComparisonCard(evidence) {
  const comparison = evidence.get("model_comparison");
  if (comparison?.state !== "complete") return "";
  const p = comparison.payload;
  return `<section class="card"><h2>Experimental model comparison</h2><p>These models scored the same saved signal. The reference CNN score above remains separate.</p><div class="table-wrap"><table><thead><tr><th>Training approach</th><th>Mean ranking score</th><th>Range across seeds</th></tr></thead><tbody>${Object.entries(p.by_arm).map(([arm, r]) => `<tr><td>${esc(words(arm))}</td><td>${number(r.mean_score, 5)}</td><td>${number(r.min_score, 5)}–${number(r.max_score, 5)} (${r.seeds.length} seeds)</td></tr>`).join("")}</tbody></table></div><p class="tagline">Scores are uncalibrated for blind detections. Seed ranges are not probability confidence intervals. A higher score does not establish a planet.</p><p><a href="#experiments">View the completed training comparison</a> · ${esc(p.run_id)}</p>${details("Model and input receipts", p)}</section>`;
}

function diagnosticCards(c, evidence) {
  const d = evidence.get("transit_diagnostics")?.payload || {};
  const coverage = d.event_coverage || d;
  const odd = d.odd_even_by_covered_event;
  const secondary = d.secondary_scan;
  const registry = evidence.get("registry")?.payload;
  const model = evidence.get("model_score");
  const native = evidence.get("centroid")?.payload.products || [];
  const crowd = evidence.get("contamination")?.payload.products || [];
  return `<div class="columns"><section class="card"><h2>Transit evidence at a glance</h2><dl class="facts"><div><dt>Covered / expected events</dt><dd>${coverage.n_covered_events ?? "—"} / ${coverage.n_expected_events ?? "—"}</dd></div><div><dt>Odd/even event difference · white errors</dt><dd>${number(coverage.odd_even_difference_sigma, 2)} σ</dd></div><div><dt>Odd/even · event scatter floor</dt><dd>${number(odd?.difference_sigma_with_event_scatter_floor, 2)} σ</dd></div><div><dt>Dominant event · fraction of S/N²</dt><dd>${number(coverage.single_event_snr2_fraction, 3)}</dd></div><div><dt>Scanned secondary phase</dt><dd>${number(secondary?.best?.phase, 3)}</dd></div><div><dt>Scanned secondary · white S/N</dt><dd>${number(secondary?.best?.snr, 2)}</dd></div></dl><p class="tagline">Secondary scan: ${secondary?.trials ?? "—"} trials. These errors and S/N values are descriptive; correlated noise and the trials effect are not calibrated.</p>${d.aliases ? `<h3>Fixed-epoch alias checks</h3><div class="table-wrap"><table><thead><tr><th>Period</th><th>Depth (ppm)</th><th>White S/N</th></tr></thead><tbody>${d.aliases.fixed_epoch_comparisons.map(a => `<tr><td>${number(a.period_days, 5)} d (${a.period_multiplier}×)</td><td>${number(a.depth === null ? null : a.depth * 1e6, 1)}</td><td>${number(a.snr, 2)}</td></tr>`).join("")}</tbody></table></div><p class="tagline">Same duration and epoch; these are diagnostic comparisons, not independent detections.</p>` : ""}</section>` +
    `<section class="card"><h2>Catalog evidence</h2>${registry ? `<p>${badge(evidence.get("registry").state)} <strong>${esc(words(registry.status))}</strong></p><p>${esc(registry.summary)}</p><p class="small muted">Snapshot assessment ${date(registry.generated_at_utc)}. Required-source coverage: ${esc(registry.coverage)}.</p><p class="small">${esc(registry.interpretation || "UNMATCHED is not proof of novelty.")}</p>${registry.matches?.length ? `<div class="table-wrap"><table><thead><tr><th>Record</th><th>Relationship</th><th>Disposition</th></tr></thead><tbody>${registry.matches.map(m => `<tr><td>${esc(m.record_id)}<br><small>${esc(m.source_id)}</small></td><td>${esc(words(m.ephemeris_match))}${m.source_current ? "" : " · stale"}</td><td>${esc(m.disposition)}</td></tr>`).join("")}</tbody></table></div>` : ""}<p class="tagline">Coordinate, TCE, eclipsing-binary and literature searches remain outside this checker’s coverage.</p>` : "<p>No registry assessment recorded.</p>"}</section></div>` +
    `<div class="columns"><section class="card"><h2>Trained model and input provenance</h2>${model?.state === "complete" ? `<p><strong>${esc(model.payload.model_name)}</strong><br>Kepler training normalization · ${esc(model.payload.device)} inference</p><p>Score ${number(model.payload.score, 6)} · logit ${number(model.payload.logit, 4)}<br>Calibration: ${esc(words(model.payload.calibration))}<br>Uncertainty: ${esc(words(model.payload.uncertainty))}</p><p class="small muted">Source validation threshold ${number(model.payload.validation_threshold, 3)} is retained for context. It does not remove proposals from this queue.</p><p class="small">${esc(model.payload.domain_warning)}</p>${details("Checkpoint, normalization and input receipts", model.payload)}` : "<p>No usable model score. The proposal remains reviewable.</p>"}</section>` +
    `<section class="card"><h2>Centroid and contamination evidence</h2>${native.flatMap(p => Object.entries(p.axes || {}).map(([axis, v]) => `<p class="small">${esc(axis)}: event shift ${number(v.shift_pixel, 5)} px; white error ${number(v.white_error_pixel, 5)} px.</p>`)).join("") || "<p>No native photometric centroid measurement available.</p>"}${crowd.map(p => `<p class="small">Pipeline aperture estimates: CROWDSAP ${number(p.header_fractions?.CROWDSAP, 4)} · FLFRCSAP ${number(p.header_fractions?.FLFRCSAP, 4)}</p>`).join("")}<p class="tagline">Photometric centroids and pipeline crowding estimates are partial evidence. Difference images, nearby-source checks and aperture comparisons are still incomplete. No additional crowding correction is applied to PDCSAP flux.</p></section></div>` +
    `<section class="card"><h2>Review attention</h2><p>Every proposal stays in the review queue, including low scores and unusual signals. ${evidence.get("model_comparison")?.state === "complete" ? "Experimental model scores are shown below for comparison; differences need human investigation." : "Only the reference model has been applied; experimental comparison is not yet available."}</p><ul>${(c.review_triage?.flags || []).map(f => `<li>${esc(words(f))}</li>`).join("")}</ul><a href="#candidate/${c.id}" id="jump-review">Go to human review form ↓</a></section>`;
}
function jobRows(items) {
  return `<div class="table-wrap"><table><thead><tr><th>Job</th><th>Cohort</th><th>State</th><th>Updated</th></tr></thead><tbody>${items.map(j => `<tr><td><a href="#job/${j.id}">${esc(j.job_key)}</a><br><span class="mono small muted">${short(j.id)}</span></td><td>${badge(j.cohort)}</td><td>${badge(j.status)}</td><td class="small">${date(j.updated_at)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function overview() {
  const [o, jobs, candidates, watcher] = await Promise.all([api("/api/overview"), api("/api/jobs?limit=5"), api("/api/candidates?limit=5"), api("/api/watcher")]);
  const count = cohort => o.candidates_by_cohort[cohort] || 0;
  return heading("Kepler → TESS", "Research workspace", "Blind transit proposals, trained CNN ranking, recorded catalog checks, and human evidence review. Follow the watcher below for automatic processing and saved results.", refreshControls(watcher)) +
    `<div class="notice"><strong>Local detection pilot · provisional research protocol.</strong> Synthetic experiments, known-object controls, archival work, and prospective search have separate cohort labels. Search readiness has not been established. A BLS proposal may be noise.</div>` +
    `<div class="grid">${cohorts.map(c => `<div class="card metric"><span>${esc(words(c))}</span><strong>${count(c)}</strong><small>${c === "synthetic_fixture" ? "Synthetic tests / transformed controls" : c === "prospective_search" ? "Blocked by the current protocol" : "Persisted proposals"}</small></div>`).join("")}</div>` +
    automationPanel(watcher) +
    `<div class="columns"><section class="card"><h2>Recent processing jobs</h2>${jobs.items.length ? jobRows(jobs.items) : empty("No jobs recorded", "The next pipeline stage will create audited jobs from a bounded selection manifest.")}<p class="tagline"><a href="#jobs">Inspect all jobs and failures →</a></p></section>` +
    `<section class="card"><h2>Public availability & resource bounds</h2><dl class="facts"><div><dt>Observed releases</dt><dd>${o.release_count}</dd></div><div><dt>Recorded products</dt><dd>${o.product_count}</dd></div><div><dt>Download budget</dt><dd>2 GiB cumulative</dd></div><div><dt>Initial selection cap</dt><dd>20 targets / products</dd></div></dl><p class="tagline">Watcher: ${watcher.configs.length ? watcher.configs.map(c => esc(words(c.health))).join(", ") : "not configured"}. Last successful poll: ${date(watcher.configs[0]?.last_success_at)}.<br><a href="#watcher">Poll health, failures, acquisition budget and progress →</a></p>${o.expired_running_stages ? `<p class="notice">${o.expired_running_stages} expired worker leases await recovery.</p>` : ""}</section></div>` +
    `<section class="card"><h2>Recent candidate dossiers</h2>${candidates.items.length ? candidateRows(candidates.items) : empty("No signals to review", "No fabricated candidate feed is shown. Real results will appear here when pipeline workers persist their evidence.")}</section>`;
}

async function listPage(kind, params) {
  const query = new URLSearchParams(params);
  query.set("limit", "50");
  const result = await api(`/api/${kind}?${query}`);
  const offset = Number(query.get("offset") || 0);
  const isCandidates = kind === "candidates";
  const title = isCandidates ? "Candidate review queue" : "Processing jobs";
  const lead = isCandidates ? "Cohort and review state are independent of model score. Open a dossier to see missing evidence and provenance." : "Stages retain attempts, source identities, errors, and worker leases. Retrying never rewrites a completed stage.";
  return heading("Persisted records", title, lead, refreshControls()) +
    `<form id="filters" class="filters"><label>Cohort<select name="cohort">${options(cohorts, query.get("cohort"), "All cohorts")}</select></label>${isCandidates ? `<label>Review status<select name="review_status">${options(statuses, query.get("review_status"), "All review states")}</select></label>` : ""}<label><button type="submit">Apply filters</button></label></form>` +
    `<section class="card">${result.items.length ? (isCandidates ? candidateRows(result.items) : jobRows(result.items)) : empty("No matching records", "This view reads the actual database. No example records are inserted automatically.")}</section>` +
    `<div class="pagination">${offset > 0 ? '<button id="previous" class="secondary">← Previous</button>' : ""}<span>Showing ${offset + (result.items.length ? 1 : 0)}–${offset + result.items.length}</span>${result.items.length === 50 ? '<button id="next" class="secondary">Next →</button>' : ""}</div>`;
}

async function jobPage(id) {
  const job = await api(`/api/jobs/${id}`);
  const retryable = job.stages.filter(s => s.status === "failed" && s.attempts < s.max_attempts && s.error?.retryable);
  return heading("Pipeline execution", job.job_key, "Execution completion does not imply a valid astrophysical signal.", '<a class="button secondary" href="#jobs">All jobs</a>') +
    `${badge(job.cohort)}${badge(job.status)}${stageStrip(job.stages)}` +
    `<div class="columns"><section class="card"><h2>Stage results & failures</h2>${job.stages.map(s => `<div class="evidence-row"><h3>${esc(words(s.name))} ${badge(s.status)}</h3><p>${s.error ? esc(s.error.message) : s.status === "queued" ? "Awaiting a worker and completed prerequisites." : s.status === "running" ? `Worker ${esc(s.worker)}; lease expires ${date(s.lease_until)}.` : s.status === "skipped" ? esc(s.result.reason) : "Recorded stage result available."}</p>${s.result ? details("Result", s.result) : ""}${s.error ? details("Failure record", s.error) : ""}</div>`).join("")}</section>` +
    `<section class="card"><h2>Job identity</h2><p>Created ${date(job.created_at)}<br>Updated ${date(job.updated_at)}</p>${details("Immutable inputs", job.inputs)}${details("Protocol and code provenance", {protocol_id: job.protocol_id, code_provenance_id: job.code_provenance_id, release_id: job.release_id, product_id: job.product_id})}` +
    (retryable.length ? `<h2>Request bounded retry</h2><p class="small muted">Queues one failed stage. A pipeline worker must be running to execute it.</p><form id="retry-form" data-job="${job.id}"><label>Stage<select name="stage">${options(retryable.map(s => s.name), "")}</select></label><label>Reviewer / operator<input name="actor" required maxlength="200"></label><label>Reason<textarea name="reason" required maxlength="2000"></textarea></label><button type="submit">Queue retry</button><p id="form-message" role="status"></p></form>` : '<p class="small muted">No retryable failed stages within the attempt budget.</p>') + `</section></div><section class="card"><h2>Audit history</h2>${details("All stage attempts (including abandoned workers)", job.attempt_history)}${details("Ordered job events", job.events)}</section>`;
}

async function candidatePage(id) {
  const c = await api(`/api/candidates/${id}`);
  const eph = c.ephemeris;
  const evidence = new Map(c.evidence.map(e => [e.kind, e]));
  const required = c.protocol.document.required_evidence;
  const kinds = [...new Set([...required, ...evidence.keys()])];
  const score = evidence.get("model_score");
  const plots = c.artifacts.filter(a => a.kind === "plot");
  return heading("Human review dossier", `${c.mission} · ${c.target_id}`, `Signal ${c.signal_key} · ${c.id}`, `<a class="button secondary" href="/api/candidates/${id}/report.json">Export JSON</a><a class="button secondary" href="/api/candidates/${id}/report.md">Export report</a>`) +
    `<p>${badge(c.cohort)}${badge(c.review_status)}${badge(c.evidence_state)}</p>` +
    (c.cohort === "synthetic_fixture" ? `<div class="notice"><strong>SYNTHETIC EXPERIMENT.</strong> ${c.detection.ephemeris_origin === "blind_search" ? "Blind search on artificial or transformed control photometry. Inspect the experiment label and recovery evaluation; this is not a sky discovery." : "Generated demonstration data with assigned ephemerides; no blind detection was run."}</div>` : "") +
    `<div class="notice"><strong>${c.incomplete_evidence.length ? `${c.incomplete_evidence.length} required evidence categories are incomplete.` : "Required evidence is recorded; interpretation still requires review."}</strong><br>${esc(c.incomplete_evidence.map(words).join(", "))}</div>` +
    `<div class="columns"><section class="card"><h2>Transit proposal</h2><dl class="facts"><div><dt>Period</dt><dd>${eph.period_days} days</dd></div><div><dt>Duration</dt><dd>${eph.duration_hours} hours</dd></div><div><dt>Epoch · canonical</dt><dd>${eph.epoch_bjd_tdb} BJD TDB</dd></div><div><dt>Epoch · original</dt><dd>${eph.epoch_original} ${esc(eph.epoch_system)}</dd></div><div><dt>Proposal method</dt><dd>${esc(c.detection.method)}</dd></div><div><dt>Model ranking score</dt><dd>${score?.state === "complete" ? Number(score.payload.score).toFixed(5) : "Not available"}</dd></div></dl><p class="tagline">Scores are evidence priorities, never planet-confirmation probabilities. Missing scores do not reject a signal.</p>${details("Detection record", c.detection)}</section>` +
    `<section class="card"><h2>Pipeline state</h2><p>${badge(c.job.status)}<a href="#job/${c.job.id}">Inspect job & failures →</a></p>${stageStrip(c.job.stages)}<p class="small muted">Protocol <code>${short(c.protocol.id)}</code> · ${esc(c.protocol.document.scientific_status)}</p></section></div>` +
    diagnosticCards(c, evidence) + modelComparisonCard(evidence) +
    `<section class="card"><h2>Light curves & diagnostic plots</h2>${plots.length ? plots.map(a => `<figure><img class="plot" src="/api/artifacts/${a.id}/plot.svg" alt="${esc(a.filename)}: recorded ${esc(a.metadata.preview_points ?? "")} point preview" loading="lazy"><figcaption>${esc(a.filename)} · <a href="/api/artifacts/${a.id}">Download plotted values</a> · SHA-256 <code>${short(a.sha256)}</code></figcaption></figure>`).join("") : empty("No plots recorded", "A missing plot is an evidence gap. Pipeline stages can attach unfolded, phase-folded, periodogram and diagnostic previews.")}</section>` +
    `<section class="card"><h2>Data & experiment reports</h2>${c.artifacts.filter(a => a.kind !== "plot").map(a => `<p><a href="/api/artifacts/${a.id}">${esc(a.filename)}</a> · ${a.size_bytes} bytes · SHA-256 <code>${short(a.sha256)}</code></p>`).join("") || '<p>No data or report artifacts recorded.</p>'}</section>` +
    `<div class="columns"><section class="card"><h2>Evidence checklist</h2>${kinds.map(kind => { const e = evidence.get(kind); return `<div class="evidence-row"><h3>${esc(words(kind))} ${badge(e?.state || "not_run")}</h3><p>${esc(e?.summary || "No evidence has been recorded.")}</p>${kind === "registry" ? '<p>UNMATCHED means no compatible record in required snapshots; it does not prove novelty.</p>' : ""}${e ? details("Recorded values & provenance", e) : ""}</div>`; }).join("")}</section>` +
    `<section class="card"><h2>Human review</h2><p class="small muted">Review labels organize investigation. Follow-up may be requested despite incomplete evidence; the gaps remain visible. This app has no planet-confirmation action.</p><form id="review-form" data-candidate="${id}" data-revision="${c.revision}"><label>Review status<select name="status">${options(statuses, c.review_status)}</select></label><label>Your name / reviewer ID<input name="reviewer" required maxlength="200" autocomplete="name"></label><label>Evidence and reasoning<textarea name="note" required maxlength="4000"></textarea></label><button type="submit">Save review</button><p id="form-message" role="status"></p></form><h3>Review history</h3>${c.reviews.length ? c.reviews.map(r => `<div class="review-item">${badge(r.status)}<span class="small">${esc(r.reviewer)} · ${date(r.created_at)}</span><p class="small">${esc(r.note)}</p></div>`).join("") : '<p class="small muted">No reviews recorded.</p>'}</section></div>` +
    `<section class="card"><h2>Reproducibility & source receipts</h2><p class="small muted">Protocol snapshots, retrieval timestamps, hashes, model identities and review history travel with the exported dossier.</p>${details("Release and product identity", {release:c.release, product:c.product})}${details("Provenance records", c.provenance)}${details("Immutable artifact receipts", c.artifacts)}${details("Evidence revision history", c.evidence_history)}${details("Protocol snapshot for this candidate", c.protocol)}</section>`;
}

async function protocolPage() {
  const p = await api("/api/protocol"), c = p.document;
  return heading("Research governance", "Bounded pilot protocol", "This version is provisional. Engineering safeguards do not establish scientific readiness or human approval.") +
    `<div class="notice"><strong>Prospective search is disabled.</strong> ${esc(c.review.reason)}</div><section class="card"><h2>Provisional hypothesis</h2><p>${esc(c.hypothesis)}</p><p class="small muted">Immutable protocol SHA-256: <code>${p.id}</code><br>Registered ${date(p.created_at)}</p></section>` +
    `<div class="protocol-grid"><section class="card"><h2>Bounded resources</h2><p>${c.limits.initial_targets} targets · ${c.limits.initial_products} products<br>2 GiB total download allowance<br>${c.limits.cpu_workers} CPU workers · ${c.limits.gpu_devices} idle GPU<br>${c.limits.download_workers} simultaneous downloads</p></section><section class="card"><h2>Scientific separation</h2><p>Blind proposals estimate their own ephemerides. Known ephemerides evaluate controls. Benchmark test rows never select models or thresholds.</p></section><section class="card"><h2>Evidence obligations</h2><p>Injection/recovery and negative controls precede search-readiness claims. Missing catalogs and diagnostics remain incomplete.</p></section></div>${details("Full machine-readable protocol", c)}`;
}

function bindPage(route, params) {
  document.getElementById("jump-review")?.addEventListener("click", event => { event.preventDefault(); document.getElementById("review-form")?.scrollIntoView({behavior:"smooth"}); });
  document.getElementById("refresh")?.addEventListener("click", render);
  document.querySelectorAll("#app form").forEach(form => {
    const initial = JSON.stringify([...new FormData(form)]);
    const trackChanges = () => { form.dataset.dirty = String(JSON.stringify([...new FormData(form)]) !== initial); };
    form.addEventListener("input", trackChanges);
    form.addEventListener("change", trackChanges);
  });
  document.getElementById("check-new-data")?.addEventListener("click", async event => {
    const button = event.currentTarget;
    const message = document.getElementById("check-message");
    const originalHash = location.hash;
    button.disabled = true;
    checkInFlight = true;
    message.textContent = "Queuing a data check…";
    try {
      const request = await api("/api/watcher/check", {});
      message.textContent = `Check ${words(request.status)}. The worker will update the saved results.`;
      if (location.hash === originalHash) await render();
    } catch (error) {
      message.textContent = error.message;
      message.className = "small action-help error";
      button.disabled = false;
    } finally {
      checkInFlight = false;
    }
  });
  document.getElementById("filters")?.addEventListener("submit", event => {
    event.preventDefault();
    const values = new URLSearchParams(new FormData(event.target));
    [...values.keys()].forEach(k => { if (!values.get(k)) values.delete(k); });
    location.hash = route + (values.size ? "?" + values : "");
  });
  for (const [id, delta] of [["previous", -50], ["next", 50]]) document.getElementById(id)?.addEventListener("click", () => {
    params.set("offset", String(Math.max(0, Number(params.get("offset") || 0) + delta)));
    location.hash = route + "?" + params;
  });
  for (const formId of ["review-form", "retry-form"]) document.getElementById(formId)?.addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.target, button = form.querySelector("button"), message = document.getElementById("form-message");
    button.disabled = true;
    message.textContent = "Saving…";
    try {
      const data = Object.fromEntries(new FormData(form));
      const isReview = formId === "review-form";
      if (isReview) data.expected_revision = Number(form.dataset.revision);
      await api(isReview ? `/api/candidates/${form.dataset.candidate}/review` : `/api/jobs/${form.dataset.job}/retry`, data);
      await render();
      const feedback = document.getElementById("form-message");
      if (feedback) { feedback.textContent = isReview ? "Review saved to the audit history." : "Retry queued. A worker is required to execute it."; feedback.className = "notice success"; }
    } catch (error) {
      message.textContent = error.message;
      message.className = "notice error";
      button.disabled = false;
    }
  });
  document.querySelectorAll(".plot").forEach(img => img.addEventListener("error", () => {
    const failure = document.createElement("p");
    failure.className = "notice error";
    failure.textContent = "Plot could not be loaded. The service may be busy, or the recorded bytes may be unavailable. Reload this page; if it persists, inspect the download link and server log.";
    img.replaceWith(failure);
  }));
}

async function render(settings = {}) {
  const background = settings.background === true;
  if (background && (activeRenders || !safeToRefreshAutomatically())) return;
  activeRenders += 1;
  const version = ++navigation;
  const [path, query = ""] = (location.hash.slice(1) || "overview").split("?", 2);
  const [route, id] = path.split("/");
  const params = new URLSearchParams(query);
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.hash === "#" + (route === "candidate" ? "candidates" : route === "job" ? "jobs" : route)));
  if (!background) app.classList.add("busy");
  try {
    let html;
    if (route === "watcher") html = await watcherPage();
    else if (route === "experiments") html = await experimentsPage();
    else if (route === "overview") html = await overview();
    else if (route === "jobs" || route === "candidates") html = await listPage(route, params);
    else if ((route === "candidate" || route === "job") && /^[a-f0-9]{32}$/.test(id || "")) html = await (route === "candidate" ? candidatePage(id) : jobPage(id));
    else if (route === "protocol") html = await protocolPage();
    else throw new Error("Unknown page. Use the navigation links to return to the workspace.");
    if (version !== navigation || (background && !safeToRefreshAutomatically())) return;
    const scrollPosition = window.scrollY;
    app.innerHTML = html;
    bindPage(route, params);
    if (background) window.scrollTo(0, scrollPosition);
    document.getElementById("updated").textContent = "View fetched " + new Date().toLocaleString() + (autoRefreshRoutes.has(route) ? " · Updates every 30 seconds while visible and idle" : " · Automatic refresh paused on this page");
  } catch (error) {
    if (background) {
      if (version === navigation) document.getElementById("updated").textContent = "Automatic refresh failed: " + error.message + ". Saved view retained; retrying in 30 seconds.";
      return;
    }
    if (version === navigation) app.innerHTML = `<div class="notice error"><strong>Could not load persisted records.</strong><p>${esc(error.message)}</p><button id="refresh">Retry loading</button></div>`;
    document.getElementById("refresh")?.addEventListener("click", render);
  } finally {
    activeRenders -= 1;
    if (version === navigation) app.classList.remove("busy");
  }
}

async function experimentsPage() {
  const value = await api('/api/experiments');
  const service = value.comparison_service;
  return heading('Recorded research experiments', 'Mission adaptation models', 'Completed training comparisons. Candidate dossiers show experimental scores alongside the frozen reference CNN when available.', '<button id="refresh">Refresh</button>') +
    (service ? `<section class="card"><h2>Automatic candidate comparisons · ${badge(service.state)}</h2><p>Experiment ${esc(service.run_id || "unavailable")} · last heartbeat ${date(service.heartbeat_at)}. Completed watcher jobs receive comparison scores while this service is running.</p>${service.error ? `<p class="notice error">${esc(service.error.message)}</p>` : ""}<p class="small muted">The reference scorer remains active. Experimental model scores do not change catalog matches or human review labels.</p></section>` : "") +
    `<div class="notice"><strong>Development evidence on known-ephemeris inputs.</strong> Validation-derived audits do not establish blind recovery, survey false-alarm rates, planet probabilities, or prospective readiness.</div>` +
    (value.items.length ? value.items.map(run => `<section class="card"><h2>${esc(run.id)} · ${badge(run.status)}</h2>${run.error ? `<p class="notice error">${esc(run.error.type)}: ${esc(run.error.message)}</p>` : ''}${run.verified ?
      `<p>${esc(words(run.cohort))} · completed ${date(run.completed_at)}</p><p>${run.config.steps} updates × ${run.config.batch_size} examples per arm; seeds ${esc(run.config.seeds.join(', '))}. Fine-tuning includes ${run.config.pretrain_steps} pretraining updates in that total.</p><div class="table-wrap"><table><thead><tr><th>Arm</th><th>TESS audit AP · mean ± seed SD</th><th>Raw Brier</th><th>Calibrated Brier</th></tr></thead><tbody>${Object.entries(run.results).map(([arm, r]) => `<tr><td>${esc(words(arm))}</td><td>${number(r.raw_average_precision.mean)} ± ${number(r.raw_average_precision.sd)}</td><td>${number(r.raw_brier.mean)}</td><td>${number(r.calibrated_brier.mean)}</td></tr>`).join('')}</tbody></table></div><p class="tagline">Brier is lower-is-better. Calibration can worsen the audit even when its fit improves. Seed SD is not a population confidence interval.</p><img class="plot" src="${esc(run.links['comparison.png'])}" alt="Recorded per-seed average precision and mean Brier scores"><div class="actions"><a href="${esc(run.links['report.json'])}">Full JSON results</a><a href="${esc(run.links['report.md'])}">Research report</a><a href="${esc(run.links['comparison.png'])}">Download figure</a></div><ul>${run.limitations.map(x => `<li>${esc(x)}</li>`).join('')}</ul>${details('Actual selected steps, calibration and mission-head diagnostics', run.runs)}${details('Configuration and verification', {config: run.config, spec_sha256: run.spec_sha256, verification: run.verification, claims: run.claims})}` :
      `<p>No verified completed metrics available.</p><p>Attempt ${run.attempts ?? '—'} · ${esc(words(run.arm || 'awaiting training'))} · seed ${run.seed ?? '—'} · step ${run.step ?? '—'} · heartbeat ${date(run.heartbeat_at)}</p>`}</section>`).join('') : empty('No experiments recorded', 'Training is an explicit local command; opening this page starts no compute.')) +
    (value.truncated ? '<p class="notice">The bounded experiment listing is truncated.</p>' : '');
}
window.addEventListener("hashchange", render);
window.setInterval(() => render({background:true}), 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) render({background:true}); });
render();

async function watcherPage() {
  const w = await api('/api/watcher');
  const bytes = n => `${number(n / 1048576, 2)} MiB`;
  return heading('Public archive stream', 'Release watcher', 'Check watched targets, follow automatic processing, and review saved signal evidence.', refreshControls(w)) +
    `<div class="notice"><strong>Explicit watched targets.</strong> ${esc(w.scope)}. New available products can enter bounded automatic processing for the configured targets. Existing pilot selections stay fixed.</div>` +
    automationPanel(w) +
    `<div class="grid"><div class="card metric"><span>Cumulative network charge</span><strong>${bytes(w.budget.charged_bytes)}</strong><small>Includes metadata, imported prior usage, retries and conservative crash reservations</small></div><div class="card metric"><span>Remaining global budget</span><strong>${bytes(w.budget.remaining_bytes)}</strong><small>${w.budget.unsettled_reservations} unsettled reservations remain fully charged</small></div></div>` +
    `<section class="card"><h2>Service health and poll schedule</h2>${w.configs.length ? w.configs.map(c => `<div class="evidence-row"><h3>${badge(c.health)} · TIC ${esc(c.config.targets.join(', '))}</h3><p>${c.scheduler?.kind === 'automatic' ? 'Automatic worker' : 'Original metadata-only scheduler'}</p><p>Last poll: ${date(c.last_poll_at)}<br>Last success: ${date(c.last_success_at)}<br>Next due: ${date(c.next_poll_at)}<br>Worker heartbeat: ${date(c.scheduler?.heartbeat_at || c.heartbeat_at)} · ${c.failures}/3 consecutive failures</p>${c.last_error ? `<p class="notice error">${esc(c.last_error.message)}</p>` : ''}${details('Frozen metadata configuration', c.config)}</div>`).join('') : empty('No watcher configured', 'No live or fixture data is inserted automatically.')}</section>` +
    `<section class="card"><h2>Finite acquisition and processing queue</h2>${w.queue.length ? `<div class="table-wrap"><table><thead><tr><th>Target / sector</th><th>State</th><th>Attempts</th><th>Receipt / failure</th><th>Processing</th></tr></thead><tbody>${w.queue.map(q => `<tr><td>${esc(q.target_id)} / ${esc(q.metadata.sector)}</td><td>${badge(q.state)}</td><td>${q.attempts}/3</td><td>${q.receipt ? `${esc(words(q.receipt.mode))}<br>${bytes(q.receipt.bytes)} verified · ${bytes(q.receipt.new_download_bytes || 0)} newly downloaded<br>SHA256 ${short(q.receipt.sha256)}` : 'No verified acquisition'}${q.error ? `<p class="notice error">${esc(q.error.message)}</p>` : ''}${q.next_attempt_at && q.state === 'failed' ? `<br>Retry after ${date(q.next_attempt_at)}` : ''}</td><td>${q.job_id ? `<a href="#job/${q.job_id}">Job and stage evidence →</a>` : 'Awaiting verified source'}</td></tr>`).join('')}</tbody></table></div>` : empty('No science products selected', 'Metadata-only polling never queues an entire sector.')}${w.pilots.map(p => details(`Pilot ${p.id} · ${p.status} · ${number(p.runtime_charged, 1)} / ${p.spec.max_seconds} seconds charged`, p)).join('')}</section>` +
    `<section class="card"><h2>Recent polls and observed changes</h2>${w.polls.map(p => `<div class="evidence-row"><h3>${badge(p.status)} · ${date(p.started_at)}</h3><p>${p.result?.product_ids?.length ?? 0} selected products observed; ${p.result?.new_product_ids?.length ?? 0} new immutable identities. ${p.result?.metadata_pages_complete === false ? 'Metadata truncated: scope is incomplete.' : ''}</p>${p.error ? `<p class="notice error">${esc(p.error.message)}</p>` : ''}${details('Poll receipt and provenance links', p)}</div>`).join('') || '<p>No polls recorded.</p>'}${details('Network accounting by operation', w.budget)}</section>`;
}
