/**
 * Paste a FactorioLab URL, get a blueprint, see it rendered.
 *
 * The whole panel is shaped by one fact: a build takes seconds to minutes, and
 * the wall clock is a multiple of the per-layout budget because `best` lays out
 * every candidate with both strategies. So nothing here waits on a request —
 * the job is submitted, and then polled, and the panel says where it is the
 * whole time rather than showing a spinner and hoping.
 */
import { useEffect, useId, useRef, useState } from 'react';
import {
  type BuildOptions,
  BuildRequestError,
  DEFAULT_OPTIONS,
  type Job,
  runBuild,
} from '../api/build';
import { useBlueprint } from '../state/BlueprintProvider';
import { BuildReportPanel, RefusalReport } from './BuildReport';

export function BuildPanel() {
  const { load } = useBlueprint();
  const [options, setOptions] = useState<BuildOptions>(DEFAULT_OPTIONS);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const urlId = useId();
  const nameId = useId();
  const strategyId = useId();
  const candidatesId = useId();
  const budgetId = useId();

  // A build outlives the panel if the page changes under it; aborting on
  // unmount stops the poll loop rather than leaving it talking to nobody.
  useEffect(() => () => abort.current?.abort(), []);

  const set = <K extends keyof BuildOptions>(key: K, value: BuildOptions[K]) =>
    setOptions((previous) => ({ ...previous, [key]: value }));

  const start = async (overrides: Partial<BuildOptions> = {}) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setRequestError(null);
    setCopied(false);
    setCopyError(null);
    setJob(null);
    try {
      const settled = await runBuild({ ...options, ...overrides }, setJob, controller.signal);
      // Render it the moment it exists. The point of having the viewer in the
      // same page is not having to copy the string somewhere to look at it.
      if (settled.result?.blueprint) load(settled.result.blueprint);
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

  const blueprint = job?.result?.blueprint ?? null;

  /**
   * The clipboard is a permission, not a guarantee: an insecure origin, a
   * denied prompt or a headless browser all leave `navigator.clipboard`
   * unusable. A button that silently did nothing there would be the worst
   * possible answer, so a failure says so and the string stays selectable.
   */
  const copy = () => {
    if (!blueprint) return;
    const written = navigator.clipboard?.writeText(blueprint);
    if (!written) {
      setCopyError(
        'This browser would not give the page the clipboard. Select the string instead.',
      );
      return;
    }
    void written.then(
      () => {
        setCopied(true);
        setCopyError(null);
      },
      (cause: unknown) => {
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
        <button type="button" onClick={() => void start()} disabled={!options.url.trim() || busy}>
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
          onChange={(e) => set('strategy', e.target.value as BuildOptions['strategy'])}
        >
          <option value="best">best (both, smallest valid wins)</option>
          <option value="spine">spine</option>
          <option value="freeform">freeform</option>
        </select>

        <label htmlFor={candidatesId}>Candidates</label>
        <input
          id={candidatesId}
          type="number"
          min={1}
          max={8}
          value={options.candidates}
          onChange={(e) => set('candidates', Number(e.target.value))}
        />

        <label htmlFor={budgetId}>Budget (s/layout)</label>
        <input
          id={budgetId}
          type="number"
          min={0.5}
          step={0.5}
          value={options.budget_s}
          onChange={(e) => set('budget_s', Number(e.target.value))}
        />

        <label className="checkbox">
          <input
            type="checkbox"
            checked={options.power}
            onChange={(e) => set('power', e.target.checked)}
          />
          Tesla Towers (off is the CLI's --no-power)
        </label>

        <label htmlFor={nameId}>Name</label>
        <input
          id={nameId}
          value={options.name}
          placeholder="(defaults to what it makes)"
          onChange={(e) => set('name', e.target.value)}
        />
      </div>

      <p className="note">
        Budget is per layout, and <code>best</code> lays out every candidate with both strategies —
        so {options.candidates} × {options.strategy === 'best' ? 2 : 1} × {options.budget_s}s is up
        to {options.candidates * (options.strategy === 'best' ? 2 : 1) * options.budget_s}s of
        solving, plus rates, validation and encoding on top.
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
                {job.result.title}
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
          <BuildReportPanel result={job.result} elapsedS={job.elapsed_s} />
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
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
