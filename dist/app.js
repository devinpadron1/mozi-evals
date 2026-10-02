import {readJson} from './data.mjs';

const byId = id => document.getElementById(id);
const human = value => String(value ?? '').replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
const make = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
};
let manifest;
let spec;
let baselineSpec;
let report = null;
let progress = null;
let baselineReport = null;
let baselineProgress = null;
let localRunner = false;
let keyConfigured = false;
let workerCount = 32;
let active = false;
let errorMessage = '';
let pollingTimer = null;
const expandedBreakdowns = new Set();

function iconFor(label) {
  const icon = make('span', 'constraint-icon ' + label);
  icon.setAttribute('aria-hidden', 'true');
  return icon;
}
function thumbnailLink(item) {
  const anchor = make('a', 'case-thumbnail');
  anchor.href = item.source.url;
  anchor.target = '_blank';
  anchor.rel = 'noopener noreferrer';
  anchor.setAttribute('aria-label', 'Watch ' + item.name);
  anchor.title = 'Watch ' + item.name;
  const image = document.createElement('img');
  image.src = item.source.thumbnail_url;
  image.alt = '';
  image.loading = 'lazy';
  image.decoding = 'async';
  anchor.append(image);
  return anchor;
}
function renderRules() {
  byId('question').textContent = spec.question.instructions;
  const definitions = byId('criteria');
  definitions.replaceChildren();
  for (const label of manifest.prompts.taxonomy) {
    const term = make('dt', 'criteria-term');
    term.append(iconFor(label), make('span', '', human(label)));
    definitions.append(term, make('dd', '', spec.question.criteria[label]));
  }
}
function currentResults() {
  if (active || progress?.status === 'failed') return progress?.results || [];
  return report?.results || progress?.results || [];
}
function currentBaselineResults() {
  if (baselineProgress?.status === 'running' || baselineProgress?.status === 'failed') return baselineProgress.results || [];
  return baselineReport?.results || baselineProgress?.results || [];
}
function currentPairedResultCount() {
  const jevIds = new Set(currentResults().map(result => result.case_id));
  return currentBaselineResults().filter(result => jevIds.has(result.case_id)).length;
}
function renderCases() {
  const body = byId('experiment-cases');
  for (const details of body.querySelectorAll('.score-breakdown[open]')) {
    expandedBreakdowns.add(details.dataset.caseId);
  }
  body.replaceChildren();
  const results = new Map(currentResults().map(result => [result.case_id, result]));
  const baselines = new Map(currentBaselineResults().map(result => [result.case_id, result]));
  let displayIndex = 0;
  for (const item of manifest.cases) {
    const baseline = baselines.get(item.id);
    const result = results.get(item.id);
    if (!baseline && !result) continue;
    displayIndex += 1;
    const row = make('tr');
    const video = make('td', 'video-cell');
    const videoContent = make('div', 'video-content');
    videoContent.append(thumbnailLink(item));
    const description = make('div', 'video-description');
    const title = make('a', '', `${displayIndex} · ${item.name}`);
    title.href = item.source.url;
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    description.append(title);
    videoContent.append(description);
    video.append(videoContent);
    const baselineCell = make('td', 'classification-cell');
    if (baseline) {
      const value = make('div', 'constraint-result ' + baseline.choice);
      value.title = baseline.basis || '';
      value.append(make('strong', '', human(baseline.choice)), iconFor(baseline.choice));
      baselineCell.append(value);
    } else baselineCell.append(make('span', 'queued', baselineProgress?.status === 'running' ? 'Waiting' : '—'));
    const classification = make('td', 'classification-cell');
    if (baseline && result) {
      const outcome = baseline.choice === result.choice ? 'comparison-match' : 'comparison-mismatch';
      baselineCell.classList.add(outcome);
      classification.classList.add(outcome);
    }
    if (result) {
      const label = result.choice;
      const value = make('div', 'constraint-result ' + label);
      value.append(make('strong', '', human(label)), iconFor(label));
      const details = make('details', 'score-breakdown');
      details.dataset.caseId = item.id;
      details.open = expandedBreakdowns.has(item.id);
      const summary = make('summary');
      summary.setAttribute('aria-label', `View Jev breakdown for ${item.name}`);
      summary.append(value);
      details.append(summary);
      details.addEventListener('toggle', () => {
        if (details.open) expandedBreakdowns.add(item.id);
        else expandedBreakdowns.delete(item.id);
      });
      const breakdown = make('div', 'breakdown-panel');
      const confidence = make('p', 'breakdown-confidence');
      confidence.append(make('span', '', 'Confidence'), make('strong', '', `${Math.round(Number(result.confidence || 0) * 100)}%`));
      breakdown.append(confidence);
      for (const option of manifest.prompts.taxonomy) {
        const score = Number(result.probabilities?.[option] || 0);
        const line = make('div', 'breakdown-score' + (option === label ? ' selected' : ''));
        const name = make('span', 'breakdown-label', human(option));
        const track = make('span', 'breakdown-track');
        track.setAttribute('aria-hidden', 'true');
        const fill = make('span', 'breakdown-fill');
        fill.style.width = `${Math.max(0, Math.min(100, score * 100))}%`;
        track.append(fill);
        const percent = make('span', 'breakdown-percent', `${Math.round(score * 100)}%`);
        line.append(name, track, percent);
        breakdown.append(line);
      }
      details.append(breakdown);
      classification.append(details);
    } else classification.append(make('span', 'queued', active ? 'Waiting' : '—'));
    row.append(video, baselineCell, classification);
    body.append(row);
  }
  byId('results-summary').textContent = `${currentPairedResultCount()} / ${baselines.size}`;
}
function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}` : `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}
function elapsedSeconds() {
  if (!progress) return report?.total_elapsed_seconds || 0;
  if (active && progress.started_at) return Math.max(Number(progress.elapsed_seconds) || 0, Date.now() / 1000 - progress.started_at);
  return progress.elapsed_seconds || report?.total_elapsed_seconds || 0;
}
function renderProgress() {
  const total = currentBaselineResults().length;
  const complete = currentPairedResultCount();
  const fraction = total ? complete / total : 0;
  const cost = Number(active || progress?.status === 'failed' ? progress?.total_cost_usd : report?.total_cost_usd ?? progress?.total_cost_usd ?? 0);
  byId('progress-fill').style.width = `${(fraction * 100).toFixed(1)}%`;
  byId('progress-track').setAttribute('aria-valuemax', String(total));
  byId('progress-track').setAttribute('aria-valuenow', String(complete));
  byId('progress-count').textContent = `${complete} / ${total} complete`;
  byId('elapsed-time').textContent = formatDuration(elapsedSeconds());
  byId('api-cost').textContent = '$' + (Number.isFinite(cost) ? cost.toFixed(4) : '0.0000');
  const jevByCase = new Map(currentResults().map(result => [result.case_id, result]));
  const paired = currentBaselineResults().filter(result => jevByCase.has(result.case_id));
  const matches = paired.filter(result => jevByCase.get(result.case_id).choice === result.choice).length;
  byId('baseline-match').textContent = paired.length ? `${Math.round(matches / paired.length * 100)}%` : '—';
  byId('baseline-match-detail').textContent = paired.length ? `${matches} / ${paired.length} cases match` : 'Awaiting paired classifications';
  byId('runtime-status').textContent = active
    ? ''
    : errorMessage || '';
}
function render() {
  if (!manifest || !spec) return;
  renderRules();
  renderCases();
  renderProgress();
  const button = byId('run-jev');
  byId('clear-run').closest('.run-actions').hidden = !localRunner;
  button.disabled = active || !keyConfigured;
  button.classList.toggle('is-running', active);
  byId('run-jev').querySelector('.run-button-label').textContent = active ? 'Classifying…' : 'Run Jev';
  const hasRun = Boolean(report || (progress && progress.status !== 'running' && progress.status !== 'idle'));
  byId('clear-run').disabled = active || !hasRun;
  byId('page-status').textContent = errorMessage || (!localRunner
      ? 'Start the local Python server to run classification.'
    : !keyConfigured
      ? 'Set OPENROUTER_API_KEY in the local environment or .env, then restart the server.'
      : '');
  byId('page-status').hidden = !byId('page-status').textContent;
  byId('run-meta').textContent = report ? `Last run · ${new Date(report.created_at).toLocaleString()}` : '';
}
async function loadReport() {
  const response = await fetch('jev_report.json?v=' + Date.now());
  const value = await readJson(response, {optional: true, label: 'Saved Jev report'});
  if (value === null) { report = null; return; }
  const ids = manifest.cases.map(item => item.id);
  const labels = manifest.prompts.taxonomy;
  if (value.dataset_version !== manifest.dataset_version || value.spec_version !== spec.version ||
      value.model !== spec.model || !Array.isArray(value.results) || value.results.length !== ids.length ||
      new Set(value.results.map(result => result.case_id)).size !== ids.length ||
      value.results.some(result => !ids.includes(result.case_id) || !labels.includes(result.choice)))
    throw new Error(`Saved Jev report does not match these ${ids.length.toLocaleString()} cases. Run Jev again.`);
  report = value;
}
async function loadBaselineReport() {
  const response = await fetch('baseline_report.json?v=' + Date.now());
  const value = await readJson(response, {optional: true, label: 'Saved baseline report'});
  if (value === null) { baselineReport = null; return; }
  const ids = manifest.cases.map(item => item.id);
  const labels = manifest.prompts.taxonomy;
  if (value.dataset_version !== manifest.dataset_version || value.spec_version !== baselineSpec.version ||
      value.model !== baselineSpec.model || !Array.isArray(value.results) ||
      new Set(value.results.map(result => result.case_id)).size !== value.results.length ||
      value.results.some(result => !ids.includes(result.case_id) || !labels.includes(result.choice)))
    throw new Error('Saved baseline report does not match this dataset and taxonomy.');
  baselineReport = value;
}
async function refreshBaselineStatus() {
  const response = await fetch('/api/baseline/status');
  if (!response.ok) return;
  const job = await readJson(response, {label: 'Baseline status'});
  if (job.progress) baselineProgress = job.progress;
  if (job.status === 'completed' || baselineProgress?.status === 'completed') await loadBaselineReport();
}
async function refreshStatus() {
  const response = await fetch('/api/jev/status');
  if (!response.ok) throw new Error('Lost connection to the local runner.');
  const job = await readJson(response, {label: 'Jev status'});
  if (job.progress) progress = job.progress;
  active = job.status === 'running' || progress?.status === 'running';
  if (job.status === 'failed' || progress?.status === 'failed') {
    active = false;
    errorMessage = job.error || `${progress?.failed || 1} transcript(s) failed. Completed classifications are shown below.`;
  } else if (job.status === 'completed' || progress?.status === 'completed') {
    await loadReport();
    active = false;
    errorMessage = '';
  }
  render();
  return active;
}
function startPolling() {
  if (pollingTimer) clearTimeout(pollingTimer);
  const poll = async () => {
    if (active) {
      try { await refreshStatus(); }
      catch (error) { errorMessage = error.message; render(); }
    } else renderProgress();
    try { await refreshBaselineStatus(); } catch (error) { console.warn(error); }
    renderCases();
    renderProgress();
    pollingTimer = setTimeout(poll, active ? 250 : 1000);
  };
  pollingTimer = setTimeout(poll, active ? 250 : 1000);
}
async function runJev() {
  if (active || !keyConfigured) return;
  errorMessage = '';
  report = null;
  progress = {status: 'running', started_at: Date.now() / 1000, elapsed_seconds: 0, total: manifest.cases.length,
    finished: 0, completed: 0, failed: 0, workers: workerCount, total_cost_usd: 0, results: []};
  active = true;
  render();
  startPolling();
  try {
    const response = await fetch('/api/jev/evaluate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (!response.ok) throw new Error((await readJson(response, {label: 'Jev runner'})).error || 'Could not start Jev.');
  } catch (error) {
    active = false;
    errorMessage = error.message;
    render();
  }
}
byId('run-jev').onclick = runJev;
byId('clear-run').onclick = async () => {
  if (active) return;
  errorMessage = '';
  try {
    const response = await fetch('/api/jev/clear', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (!response.ok) throw new Error((await readJson(response, {label: 'Clear run'})).error || 'Could not clear the run.');
    report = null;
    progress = null;
    errorMessage = '';
    render();
  } catch (error) {
    errorMessage = error.message;
    render();
  }
};

try {
  const manifestResponse = await fetch('manifest.json?v=' + Date.now());
  manifest = await readJson(manifestResponse, {label: 'Case data'});
  const specResponse = await fetch('jev_spec.json?v=' + Date.now());
  spec = await readJson(specResponse, {label: 'Jev specification'});
  const baselineSpecResponse = await fetch('baseline_spec.json?v=' + Date.now());
  baselineSpec = await readJson(baselineSpecResponse, {label: 'Baseline specification'});
  try { await loadReport(); } catch (error) { errorMessage = error.message; }
  try { await loadBaselineReport(); } catch (error) { errorMessage = error.message; }
  if (['localhost', '127.0.0.1'].includes(location.hostname)) {
    try {
      const response = await fetch('/api/health');
      if (response.ok) {
        const health = await readJson(response, {label: 'Local runner'});
        localRunner = health.runner === true;
        keyConfigured = health.jev_configured === true;
        workerCount = Number(health.jev_workers) || 32;
      }
      const statusResponse = await fetch('/api/jev/status');
      if (statusResponse.ok) {
        const job = await readJson(statusResponse, {label: 'Jev status'});
        if (job.progress) progress = job.progress;
        active = job.status === 'running' || progress?.status === 'running';
        if (active) startPolling();
      }
      await refreshBaselineStatus();
    } catch {}
  }
  render();
  startPolling();
} catch (error) {
  byId('page-status').textContent = error.message;
  byId('runtime-status').textContent = error.message;
}
