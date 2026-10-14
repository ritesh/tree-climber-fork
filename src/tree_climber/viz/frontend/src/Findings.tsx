import { useGraph } from './GraphContext';
import type { PathStep } from './GraphContext';
import './Findings.css';

function stepLabel(step: PathStep, index: number): string {
  const arrow = index === 0 ? '' : `--${[step.edge ?? 'flow', step.variable].filter(Boolean).join(' ')}--> `;
  const text = step.node_type === 'ENTRY' || step.node_type === 'EXIT' ? `${step.node_type} ${step.text}` : step.text;
  return `${arrow}[${step.node}] ${text}`;
}

const Findings = () => {
  const { findings, highlightedPath, setHighlightedPath } = useGraph();

  return (
    <div className="findings">
      <h3>
        Taint findings <span className="findings-note">(built-in example rules)</span>
      </h3>
      {findings.length === 0 ? (
        <div className="findings-empty">No findings</div>
      ) : (
        <ol className="findings-list">
          {findings.map((finding, index) => {
            const selected = finding.path.steps === highlightedPath;
            return (
              <li key={`${finding.rule}-${finding.source}-${finding.sink}-${finding.argument}-${index}`}>
                <button
                  className={selected ? 'finding finding-selected' : 'finding'}
                  aria-pressed={selected}
                  onClick={() => setHighlightedPath(selected ? null : finding.path.steps)}
                >
                  <strong>{finding.rule}</strong>: argument {finding.argument} of <code>{finding.sink_call}</code>
                </button>
                {selected && (
                  <ol className="finding-path">
                    {finding.path.steps.map((step, stepIndex) => (
                      <li key={stepIndex}>
                        <code>{stepLabel(step, stepIndex)}</code>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
};

export default Findings;
