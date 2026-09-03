/**
 * What a settled build actually says — the terminal report, on a page.
 *
 * The blueprint string is the smallest interesting thing here. `flab2bp`'s CLI
 * prints all of the rest to stderr for a reason: whether the recipe selection
 * was pinned or re-derived, whether the belt ceiling was read from the URL or
 * assumed from a fully-researched save, and which strategy/candidate pairs
 * produced no layout at all are the parts you need before trusting the result.
 * Every one of them reads as silence if the UI does not say it.
 */
import type {
  Attempt,
  AttemptDetail,
  AttemptFailure,
  BuildResult,
  ProjectionFailure,
  Refusal,
} from '../api/build';
export function ProjectionFailures({ failures }: { failures: ProjectionFailure[] }) {
  if (failures.length === 0) return null;
  return (
    <ul className="projection-failures">
      {failures.map((failure) => (
        <li
          key={`${failure.band}/${failure.check}/${failure.buildings.join(',')}/${failure.detail}`}
        >
          band {failure.band} — {failure.check} — buildings {failure.buildings.join(', ')} —{' '}
          {failure.detail}
        </li>
      ))}
    </ul>
  );
}

function AttemptFailures({ attempts }: { attempts: AttemptFailure[] }) {
  if (attempts.length === 0) return null;
  return (
    <ul className="reasons">
      {attempts.map((attempt) => (
        <li key={`${attempt.candidate}/${attempt.strategy ?? 'direct'}`}>
          {attempt.strategy ? `${attempt.strategy} / ` : ''}
          {attempt.candidate}: {attempt.reason}
          <ProjectionFailures failures={attempt.projection_failures} />
        </li>
      ))}
    </ul>
  );
}

/** One refused strategy/candidate pair per line, as a result rather than an error. */
export function RefusalReport({ refusal }: { refusal: Refusal }) {
  return (
    <section className="build-report refused" data-testid="refusal">
      <h2>No layout for this spec</h2>
      <p>{refusal.message}</p>
      <AttemptFailures attempts={refusal.attempts} />
      <p className="note">
        A refusal is a result, not a crash: each line above is one strategy trying one candidate and
        saying why it gave up. Raising the budget or the candidate count sometimes helps; a spec
        that never lays out is more likely a defect in the layout model than a hard instance.
      </p>
    </section>
  );
}

export function BuildReportPanel({
  result,
  elapsedS,
  selectedAttempt,
  onSelectAttempt,
}: {
  result: BuildResult;
  /** Optional server wall clock for the whole build. */
  elapsedS?: number;
  selectedAttempt: Attempt | null;
  onSelectAttempt(attempt: Attempt): void;
}) {
  // The panel describes the SELECTED candidate, and falls back to the winner
  // only when nothing is selectable — an invalid build withholds every string,
  // and its report is still the thing to show. Build-global facts (flow
  // provenance, belt rules, refusals) stay on `result` regardless.
  const shown: AttemptDetail = selectedAttempt?.detail ?? {
    machines: result.machines,
    buildings: result.buildings,
    primary_band: result.primary_band,
    certified_bands: result.certified_bands,
    title: result.title,
    outputs: result.outputs,
    external_inputs: result.external_inputs,
    input_markers: result.input_markers,
    unmarked_inputs: result.unmarked_inputs,
    belt_tiers: result.belt_tiers,
    report: result.report,
  };
  const strategy = selectedAttempt?.strategy ?? result.strategy;
  const candidate = selectedAttempt?.candidate ?? result.candidate;
  const area = selectedAttempt?.area ?? result.area;
  const viewingLoser = selectedAttempt !== null && !selectedAttempt.chosen;
  const inputs = Object.keys(shown.external_inputs);
  const belt = result.belt_rules;

  return (
    <section className="build-report" data-testid="build-report">
      {/* The blueprint's own name, which is what the game will show. It names
          the PRODUCT and the rate — `space-warper 10/min (max prolif)` — so it
          is the heading; which strategy and candidate produced it is how, not
          what, and sits under it. */}
      <h2 data-testid="report-title">{shown.title}</h2>
      <dl>
        <dt>{viewingLoser ? 'Showing' : 'Won with'}</dt>
        <dd>
          {strategy} / {candidate}
        </dd>
        <dt>Machines</dt>
        <dd>{shown.machines}</dd>
        <dt>Area</dt>
        <dd>{area} tiles</dd>
        <dt>primary_band</dt>
        <dd>{shown.primary_band}</dd>
        <dt>certified_bands</dt>
        <dd>{shown.certified_bands.join(', ')}</dd>
        <dt>Buildings</dt>
        <dd>{shown.buildings}</dd>
        <dt>Makes</dt>
        <dd>
          {Object.entries(shown.outputs)
            .map(([item, rate]) => `${item} ${round(rate.per_minute)}/min`)
            .join(', ') || 'nothing declared'}
        </dd>
        <dt>Belt in</dt>
        <dd>
          {inputs.length > 0 ? inputs.join(', ') : 'nothing'}
          {inputs.length > 0 && ` (${shown.input_markers} marked with icons)`}
        </dd>
        <dt>Belts</dt>
        <dd>
          {shown.belt_tiers.floor}
          {shown.belt_tiers.ceiling !== shown.belt_tiers.floor
            ? `, ${shown.belt_tiers.runs_upgraded} run(s) raised to ${
                shown.belt_tiers.upgrade_tiers.join(', ') || 'nothing'
              } (ceiling ${shown.belt_tiers.ceiling})`
            : ' (the URL unlocks nothing faster)'}
        </dd>
        {elapsedS !== undefined && (
          <>
            <dt>Solved in</dt>
            <dd>{elapsedS.toFixed(1)}s on the server</dd>
          </>
        )}
      </dl>

      {shown.unmarked_inputs.length > 0 && (
        // Say it here rather than let someone find it while staring at an
        // unlabelled belt in game.
        <p className="warn">
          No icon placed for {shown.unmarked_inputs.join(', ')} — those input belts are unlabelled.
        </p>
      )}

      {/* "No differences" and "nothing was checked" read identically in silence,
          and only one of them is reassuring. */}
      {result.flow_pinned ? (
        result.flow_findings.length > 0 ? (
          <>
            <p>{result.flow_findings.length} difference(s) from the pinned flow:</p>
            <ul className="reasons">
              {result.flow_findings.map((finding) => (
                <li key={finding}>{finding}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="note">Recipe selection pinned to the supplied flow, no differences.</p>
        )
      ) : (
        <p className="note">
          Recipe selection <strong>derived, not pinned</strong> — FactorioLab's own choice of which
          recipe makes what was re-solved here rather than read from a flow export. Select automatic
          flow fetch above to run FactorioLab's solve in a server-side browser, or paste or upload a
          flow export to pin it (the CLI's <code>--fetch-flow</code> or <code>--flow</code>).
        </p>
      )}

      {belt &&
        (belt.from_url ? (
          <p className="note">
            Belt ceiling {belt.max_z} (lab level {belt.lab_level}), vertical belt construction{' '}
            {belt.vertical_construction ? 'yes' : 'no'} — read from the URL's researched
            technologies.
          </p>
        ) : (
          <p className="warn">
            This URL carried no technology set, so a{' '}
            <strong>fully-researched save is assumed</strong>: belt ceiling {belt.max_z} (lab level{' '}
            {belt.lab_level}), vertical belt construction{' '}
            {belt.vertical_construction ? 'yes' : 'no'}. If your save is not fully researched, the
            belts here may climb higher than it allows.
          </p>
        ))}

      {result.refused.length > 0 && (
        <>
          {/* Invisible in `attempts`, and silence would read as "that pair simply
              was not the best" — a much more reassuring claim than the truth. */}
          <p>{result.refused.length} strategy/candidate pair(s) produced no layout:</p>
          <AttemptFailures attempts={result.refused} />
        </>
      )}

      {shown.report.skipped.length > 0 && (
        <p className="note">
          {shown.report.skipped.length} check(s) could not run: {shown.report.skipped.join(', ')}
        </p>
      )}

      {/* A warning is a check that RAN and found something the player has to
          act on -- a belt run past its ceiling, an input arriving on two
          separate lanes. The build is valid and the string is emitted, so
          nothing else on this page would ever mention them. */}
      {shown.report.warnings.length > 0 && (
        <div className="warn" data-testid="validation-warnings">
          <p>
            <strong>{shown.report.warnings.length} warning(s).</strong> The blueprint is valid and
            will run; these are things to look at before you paste it.
          </p>
          <ul className="reasons">
            {shown.report.warnings.map((finding) => (
              <li key={`${finding.check}:${finding.message}`}>
                {finding.check}: {finding.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {shown.report.errors.length > 0 && (
        <div className="error" data-testid="validation-errors">
          <p>
            <strong>{shown.report.errors.length} validation error(s).</strong> This blueprint would
            paste cleanly and then not run, which is worse than not having one — so the string is
            withheld unless you ask for it.
          </p>
          <ul className="reasons">
            {shown.report.errors.map((finding) => (
              <li key={`${finding.check}:${finding.message}`}>
                {finding.check}: {finding.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.attempts.length > 1 && (
        <table className="attempts" aria-label="Candidate blueprints">
          <thead>
            <tr>
              <th>candidate</th>
              <th>strategy</th>
              <th>area</th>
              <th>errors</th>
              <th>blueprint</th>
            </tr>
          </thead>
          <tbody>
            {result.attempts.map((attempt) => {
              const selectable = attempt.blueprint !== null;
              const selected = attempt === selectedAttempt;
              const select = () => {
                if (selectable) onSelectAttempt(attempt);
              };
              return (
                <tr
                  key={`${attempt.candidate}/${attempt.strategy}`}
                  className={
                    selectable ? (selected ? 'selectable selected' : 'selectable') : undefined
                  }
                  aria-selected={selected}
                  aria-disabled={selectable ? undefined : true}
                  tabIndex={selectable ? 0 : undefined}
                  onClick={select}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    select();
                  }}
                >
                  <td>{attempt.candidate}</td>
                  <td>{attempt.strategy}</td>
                  <td>{attempt.area}</td>
                  <td>{attempt.errors}</td>
                  <td>{selectable ? (selected ? 'selected' : 'view') : 'unavailable'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, '');
}
