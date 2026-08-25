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
import type { BuildResult, Refusal } from '../api/build';

/** One refused strategy/candidate pair per line, as a result rather than an error. */
export function RefusalReport({ refusal }: { refusal: Refusal }) {
  return (
    <section className="build-report refused" data-testid="refusal">
      <h2>No layout for this spec</h2>
      <p>{refusal.message}</p>
      {refusal.reasons.length > 0 && (
        <ul className="reasons">
          {refusal.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <p className="note">
        A refusal is a result, not a crash: each line above is one strategy trying one candidate and
        saying why it gave up. Raising the budget or the candidate count sometimes helps; a spec
        that never lays out is more likely a defect in the layout model than a hard instance.
      </p>
    </section>
  );
}

export function BuildReportPanel({ result }: { result: BuildResult }) {
  const inputs = Object.keys(result.external_inputs);
  const belt = result.belt_rules;

  return (
    <section className="build-report" data-testid="build-report">
      {/* The blueprint's own name, which is what the game will show. It names
          the PRODUCT and the rate — `space-warper 10/min (max prolif)` — so it
          is the heading; which strategy and candidate produced it is how, not
          what, and sits under it. */}
      <h2 data-testid="report-title">{result.title}</h2>
      <dl>
        <dt>Won with</dt>
        <dd>
          {result.strategy} / {result.candidate}
        </dd>
        <dt>Machines</dt>
        <dd>{result.machines}</dd>
        <dt>Area</dt>
        <dd>{result.area} tiles</dd>
        <dt>Buildings</dt>
        <dd>{result.buildings}</dd>
        <dt>Makes</dt>
        <dd>
          {Object.entries(result.outputs)
            .map(([item, rate]) => `${item} ${round(rate.per_minute)}/min`)
            .join(', ') || 'nothing declared'}
        </dd>
        <dt>Belt in</dt>
        <dd>
          {inputs.length > 0 ? inputs.join(', ') : 'nothing'}
          {inputs.length > 0 && ` (${result.input_markers} marked with icons)`}
        </dd>
      </dl>

      {result.unmarked_inputs.length > 0 && (
        // Say it here rather than let someone find it while staring at an
        // unlabelled belt in game.
        <p className="warn">
          No icon placed for {result.unmarked_inputs.join(', ')} — those input belts are unlabelled.
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
          recipe makes what was re-solved here rather than read from a flow export. The CLI's{' '}
          <code>--flow</code> / <code>--fetch-flow</code> pin it; this page does not offer them yet.
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
          <ul className="reasons">
            {result.refused.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}

      {result.report.skipped.length > 0 && (
        <p className="note">
          {result.report.skipped.length} check(s) could not run: {result.report.skipped.join(', ')}
        </p>
      )}

      {/* A warning is a check that RAN and found something the player has to
          act on -- a belt run past its ceiling, an input arriving on two
          separate lanes. The build is valid and the string is emitted, so
          nothing else on this page would ever mention them. */}
      {result.report.warnings.length > 0 && (
        <div className="warn" data-testid="validation-warnings">
          <p>
            <strong>{result.report.warnings.length} warning(s).</strong> The blueprint is valid and
            will run; these are things to look at before you paste it.
          </p>
          <ul className="reasons">
            {result.report.warnings.map((finding) => (
              <li key={`${finding.check}:${finding.message}`}>
                {finding.check}: {finding.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.report.errors.length > 0 && (
        <div className="error" data-testid="validation-errors">
          <p>
            <strong>{result.report.errors.length} validation error(s).</strong> This blueprint would
            paste cleanly and then not run, which is worse than not having one — so the string is
            withheld unless you ask for it.
          </p>
          <ul className="reasons">
            {result.report.errors.map((finding) => (
              <li key={`${finding.check}:${finding.message}`}>
                {finding.check}: {finding.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.attempts.length > 1 && (
        <table className="attempts">
          <thead>
            <tr>
              <th>candidate</th>
              <th>strategy</th>
              <th>area</th>
              <th>errors</th>
            </tr>
          </thead>
          <tbody>
            {result.attempts.map((attempt) => (
              <tr
                key={`${attempt.candidate}/${attempt.strategy}`}
                className={attempt.chosen ? 'chosen' : undefined}
              >
                <td>{attempt.candidate}</td>
                <td>{attempt.strategy}</td>
                <td>{attempt.area}</td>
                <td>{attempt.errors}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, '');
}
