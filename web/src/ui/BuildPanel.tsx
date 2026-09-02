/**
 * Paste a FactorioLab URL, get a blueprint, see it rendered.
 *
 * The whole panel is shaped by one fact: a build takes seconds to minutes, and
 * the wall clock is a multiple of the per-layout budget. So nothing here waits
 * on a request — the job is submitted, and then polled, and the panel says
 * where it is the whole time rather than showing a spinner and hoping.
 */
import { useEffect, useId, useRef, useState } from 'react';
import {
  BAND_OPTIONS,
  BandSelection,
  type Attempt,
  type BuildOptions,
  BuildRequestError,
  DEFAULT_OPTIONS,
  type Job,
  ProliferatorTier,
  RequestStrategy,
  runBuild,
} from '../api/build';
import { useBlueprint } from '../state/BlueprintProvider';
import { BuildReportPanel, ProjectionFailures, RefusalReport } from './BuildReport';

export function BuildPanel() {
  const { load, markStale } = useBlueprint();
  const [options, setOptions] = useState<BuildOptions>(DEFAULT_OPTIONS);
  const [job, setJob] = useState<Job | null>(null);
  const [selectedAttemptKey, setSelectedAttemptKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const copyGeneration = useRef(0);
  const urlId = useId();
  const nameId = useId();
  const strategyId = useId();
  const bandId = useId();
  const budgetId = useId();
  const proliferatorTierId = useId();
  const flowId = useId();

  // A build outlives the panel if the page changes under it; aborting on
  // unmount stops the poll loop rather than leaving it talking to nobody.
  useEffect(() => () => abort.current?.abort(), []);

  const set = <K extends keyof BuildOptions>(key: K, value: BuildOptions[K]) =>
    setOptions((previous) => ({ ...previous, [key]: value }));

  const setFlow = (flow: string) =>
    setOptions((previous) => ({
      ...previous,
      flow,
      // A local file read may finish after automatic fetch was selected.
      // The supplied flow wins without discarding what the user uploaded.
      fetch_flow: flow.trim() ? false : previous.fetch_flow,
    }));

  const start = async (overrides: Partial<BuildOptions> = {}) => {
    copyGeneration.current += 1;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setRequestError(null);
    setCopied(false);
    setCopyError(null);
    setJob(null);
    setSelectedAttemptKey(null);
    try {
      const settled = await runBuild({ ...options, ...overrides }, setJob, controller.signal);
      // Render the chosen attempt the moment it exists. The point of having the
      // viewer in the same page is not having to copy the string somewhere to
      // look at it.
      const chosen = settled.result?.attempts.find(
        (attempt) => attempt.chosen && attempt.blueprint,
      );
      if (chosen?.blueprint) load(chosen.blueprint);
      // A refusal, an error, or a build whose string was withheld leaves the
      // canvas showing the build before it. Keeping it is the right call --
      // clearing would throw away what you were looking at -- but the toolbar
      // then names a result that has been superseded, so it is told.
      else markStale();
    } catch (cause) {
      if (controller.signal.aborted) return;
      setRequestError(
        cause instanceof BuildRequestError || cause instanceof Error
          ? cause.message
          : String(cause),
      );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  const cancel = () => {
    // Only the polling stops. The solve itself keeps its worker until it
    // finishes — there is no way to interrupt CP-SAT from here, and pretending
    // otherwise would be worse than saying so.
    abort.current?.abort();
    setBusy(false);
    setJob(null);
  };

  const selectedAttempt =
    job?.result?.attempts.find(
      (attempt) =>
        attempt.blueprint !== null &&
        `${attempt.candidate}/${attempt.strategy}` === selectedAttemptKey,
    ) ??
    job?.result?.attempts.find((attempt) => attempt.chosen && attempt.blueprint !== null) ??
    null;
  const blueprint = selectedAttempt?.blueprint ?? null;
  const selectAttempt = (attempt: Attempt) => {
    if (!attempt.blueprint) return;
    copyGeneration.current += 1;
    setSelectedAttemptKey(`${attempt.candidate}/${attempt.strategy}`);
    setCopied(false);
    setCopyError(null);
    load(attempt.blueprint);
  };
  const effectiveCandidateCount =
    options.flow.trim() || options.fetch_flow ? 1 : options.candidate_policies.length;
  const strategyCount = options.strategy === 'best' ? 2 : 1;

  /**
   * The clipboard is a permission, not a guarantee: an insecure origin, a
   * denied prompt or a headless browser all leave `navigator.clipboard`
   * unusable. A button that silently did nothing there would be the worst
   * possible answer, so a failure says so and the string stays selectable.
   */
  const copy = () => {
    if (!blueprint) return;
    const generation = ++copyGeneration.current;
    setCopied(false);
    setCopyError(null);
    const written = navigator.clipboard?.writeText(blueprint);
    if (!written) {
      setCopyError(
        'This browser would not give the page the clipboard. Select the string instead.',
      );
      return;
    }
    void written.then(
      () => {
        if (copyGeneration.current !== generation) return;
        setCopied(true);
        setCopyError(null);
      },
      (cause: unknown) => {
        if (copyGeneration.current !== generation) return;
        setCopied(false);
        setCopyError(cause instanceof Error ? cause.message : String(cause));
      },
    );
  };

  return (
    <section className="build-panel">
      <div className="row">
        <label htmlFor={urlId}>FactorioLab URL</label>
        <input
          id={urlId}
          value={options.url}
          spellCheck={false}
          placeholder="https://factoriolab.github.io/dsp/flow?o=…"
          onChange={(e) => set('url', e.target.value)}
        />
        <button
          type="button"
          onClick={() => void start()}
          disabled={!options.url.trim() || options.candidate_policies.length === 0 || busy}
        >
          {busy ? 'Building…' : 'Build'}
        </button>
        {busy && (
          <button type="button" onClick={cancel}>
            Stop watching
          </button>
        )}
      </div>

      <div className="row options">
        <label htmlFor={strategyId}>Strategy</label>
        <select
          id={strategyId}
          value={options.strategy}
          onChange={(event) => {
            const strategy = RequestStrategy.safeParse(event.target.value);
            if (strategy.success) set('strategy', strategy.data);
          }}
        >
          <option value="best">best (freeform + sequence-pair, smallest valid wins)</option>
          <option value="freeform">freeform</option>
          <option value="sequence-pair">sequence-pair</option>
        </select>

        <label htmlFor={bandId}>Latitude band</label>
        <select
          id={bandId}
          value={options.band}
          onChange={(event) => {
            const band = BandSelection.safeParse(event.target.value);
            if (band.success) set('band', band.data);
          }}
        >
          <option value="portable">Portable (smallest + up to two wider)</option>
          {BAND_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>

        <label htmlFor={proliferatorTierId}>Proliferator tier</label>
        <select
          id={proliferatorTierId}
          value={options.proliferator_tier}
          onChange={(event) => {
            const tier = ProliferatorTier.safeParse(event.target.value);
            if (tier.success) set('proliferator_tier', tier.data);
          }}
        >
          <option value="auto">URL selection (Mk.III if unspecified)</option>
          <option value="none">None</option>
          <option value="1">Mk.I</option>
          <option value="2">Mk.II</option>
          <option value="3">Mk.III</option>
        </select>

        <fieldset className="candidate-policies checkbox">
          <legend>Candidate policies</legend>
          {DEFAULT_OPTIONS.candidate_policies.map((policy) => (
            <label className="checkbox" key={policy}>
              <input
                type="checkbox"
                checked={options.candidate_policies.includes(policy)}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setOptions((previous) => ({
                    ...previous,
                    candidate_policies: checked
                      ? DEFAULT_OPTIONS.candidate_policies.filter(
                          (candidate) =>
                            candidate === policy || previous.candidate_policies.includes(candidate),
                        )
                      : previous.candidate_policies.filter((candidate) => candidate !== policy),
                  }));
                }}
              />
              {policy}
            </label>
          ))}
          {options.candidate_policies.length === 0 && (
            <span className="error" aria-live="polite">
              Select at least one candidate policy.
            </span>
          )}
        </fieldset>

        <label htmlFor={budgetId}>Budget (s/layout)</label>
        <input
          id={budgetId}
          type="number"
          min={0.5}
          step={0.5}
          value={options.budget_s}
          onChange={(e) => set('budget_s', Number(e.target.value))}
        />

        <label htmlFor={nameId}>Name</label>
        <input
          id={nameId}
          value={options.name}
          maxLength={60}
          placeholder="(defaults to what it makes)"
          onChange={(e) => set('name', e.target.value)}
        />
      </div>

      {/* `--flow`, as a paste or an upload. This is the stronger of the two
          guarantees the report can make: with a flow pinned, WHICH recipe makes
          what is FactorioLab's own decision rather than one re-derived here.
          The export has to have come from this URL — `flow_from_text` checks
          that and refuses otherwise, so a stale paste is an error and never a
          quiet mis-pin. */}
      <div className="row flow">
        <label htmlFor={flowId}>Flow export (optional)</label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={options.fetch_flow}
            disabled={Boolean(options.flow.trim()) || busy}
            onChange={(event) => set('fetch_flow', event.target.checked)}
          />
          Fetch FactorioLab flow automatically
        </label>
        <span className="note">
          Runs FactorioLab in a server-side browser and pins its solved recipe selection.
        </span>
        <textarea
          id={flowId}
          value={options.flow}
          spellCheck={false}
          rows={3}
          disabled={options.fetch_flow || busy}
          placeholder="Paste FactorioLab's CSV export, or choose the file — pins WHICH recipe makes what"
          onChange={(e) => setFlow(e.target.value)}
          data-testid="flow-text"
        />
        <input
          type="file"
          accept=".csv,.tsv,.txt,text/csv,text/plain"
          aria-label="flow export file"
          data-testid="flow-file"
          disabled={options.fetch_flow || busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            // Read here rather than uploading the File: the API takes the CSV
            // text, and a browser that cannot read a local file it was handed
            // should say so rather than submit an empty pin.
            file
              .text()
              .then(setFlow, (cause: unknown) =>
                setRequestError(
                  `Could not read ${file.name}: ${cause instanceof Error ? cause.message : String(cause)}`,
                ),
              );
          }}
        />
        {options.flow.trim() && (
          <button type="button" onClick={() => setFlow('')}>
            Clear flow
          </button>
        )}
      </div>

      <p className="note">
        Budget is per layout. <code>{options.strategy}</code> runs {strategyCount}{' '}
        {strategyCount === 1 ? 'layout' : 'layouts'} per candidate, so {effectiveCandidateCount}{' '}
        candidate{effectiveCandidateCount === 1 ? '' : 's'} × {strategyCount} strategies ×{' '}
        {options.budget_s}s is up to {effectiveCandidateCount * strategyCount * options.budget_s}s
        of solving, plus rates, validation and encoding on top.
      </p>

      {busy && job && <Progress job={job} />}

      {requestError && (
        <p role="alert" className="error">
          {requestError}
        </p>
      )}

      {job?.state === 'error' && job.error && (
        <p role="alert" className="error">
          {job.error}
        </p>
      )}

      {job?.refusal && <RefusalReport refusal={job.refusal} />}

      {job?.result && (
        <>
          {blueprint ? (
            <div className="row result-head">
              {/* The title is what the game will show on the blueprint, and it
                  names the PRODUCT — `space-warper 10/min (max prolif)` — not
                  the candidate that happened to win. */}
              <strong className="bp-title" data-testid="blueprint-title">
                {selectedAttempt?.detail.title ?? job.result.title}
              </strong>
              {/* The string itself is 10kB of base64 and there is nothing to
                  read in it. It stays in the DOM for tests and for anyone who
                  wants to select it by hand, and the button is the way out. */}
              <input
                className="blueprint-out"
                readOnly
                value={blueprint}
                spellCheck={false}
                aria-label="blueprint string"
                data-testid="blueprint-string"
              />
              <button type="button" onClick={copy} data-testid="copy-blueprint">
                {copied ? 'Copied' : 'Copy blueprint string'}
              </button>
            </div>
          ) : (
            <div className="row">
              <button type="button" onClick={() => void start({ allow_invalid: true })}>
                Build it anyway and show me the string
              </button>
              <span className="note">It will paste, and it will not run correctly.</span>
            </div>
          )}
          {copyError && (
            <p role="alert" className="error">
              {copyError}
            </p>
          )}
          <BuildReportPanel
            result={job.result}
            elapsedS={job.elapsed_s}
            selectedAttempt={selectedAttempt}
            onSelectAttempt={selectAttempt}
          />
        </>
      )}
    </section>
  );
}

/**
 * Where the job is.
 *
 * Two different things get shown here, and the difference is the point.
 *
 * Once `pipeline.build` reaches its layout loop it reports each (candidate,
 * strategy) pair as it starts and as it ends, so the bar is a real count of
 * work finished — 2 of 6 means two pairs are done, not that two sixths of the
 * clock has passed.
 *
 * Before that it has nothing to report: parsing the URL and solving the rates
 * happen first, take an unknown time, and are not divided into pairs. So the
 * fallback is elapsed against `solver_ceiling_s`, which bounds the CP-SAT
 * budgets ONLY — validation and encoding are on top, and a strategy that
 * refuses spends its retry budget as well. It gives the wait a scale; it is not
 * a promise of a finish time, and it never claims to be finished.
 */
function Progress({ job }: { job: Job }) {
  if (job.state === 'queued') {
    return (
      <div className="progress" data-testid="progress">
        <p>
          {job.queue_position && job.queue_position > 0
            ? `Queued — ${job.queue_position} build(s) ahead. One build runs at a time; a CP-SAT solve already uses every core.`
            : 'Queued — starting next.'}
        </p>
        <div className="bar" />
      </div>
    );
  }

  const step = job.progress;
  // Pairs FINISHED, not pairs reached: a pair that has started is work in
  // flight, and counting it as done is how a bar gets to 100% and stays there.
  const fraction = step
    ? job.settled.length / step.total
    : Math.min(job.elapsed_s / Math.max(job.solver_ceiling_s, 0.001), 1);

  return (
    <div className="progress" data-testid="progress">
      <p>
        {step
          ? `Laying out ${step.index} of ${step.total}: ${step.candidate} / ${step.strategy} — ${job.elapsed_s.toFixed(1)}s elapsed.`
          : `Reading the URL and solving the rates… ${job.elapsed_s.toFixed(1)}s elapsed, then up to ${job.solver_ceiling_s}s of layout solving.`}
      </p>
      <div className="bar">
        <div className="fill" style={{ width: `${(fraction * 100).toFixed(1)}%` }} />
      </div>
      {job.settled.length > 0 && (
        <ul className="reasons" data-testid="settled">
          {job.settled.map((done) => (
            <li key={`${done.candidate}/${done.strategy}`}>
              {done.candidate} / {done.strategy}:{' '}
              {done.phase === 'refused'
                ? `no layout — ${done.reason ?? 'no reason given'}`
                : `${done.area} tiles, ${done.ok ? 'valid' : 'INVALID'}`}
              <ProjectionFailures failures={done.projection_failures} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
