import { useState } from 'react';
import type { Summary } from '../api';

// Four steps: Ask -> AI identifies -> People validate -> Value quantified,
// with the platform piece behind each step. Steps light up as the demo reaches them.
export type Step = 0 | 1 | 2 | 3;

interface Props {
  summary: Summary | null;
  lastQuestion: string | null;
  reached: number; // highest step reached so far (-1 = none)
}

const fmt = (v: number) =>
  v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}K` : `$${Math.round(v)}`;

export default function DecisionStrip({ summary, lastQuestion, reached }: Props) {
  const [showEq, setShowEq] = useState(false);
  const s = summary;
  const steps = [
    {
      title: 'Ask',
      value: lastQuestion ? `“${lastQuestion.length > 46 ? lastQuestion.slice(0, 44) + '…' : lastQuestion}”` : 'A business question, in plain language',
      by: 'Genie',
    },
    {
      title: 'AI identifies',
      value: s ? `${s.identified_groups.toLocaleString()} opportunities · ${fmt(s.identified_savings)}/yr` : '…',
      by: s ? `Vector Search · ${Math.round(s.parts / 1000)}K parts compared` : 'Vector Search',
    },
    {
      title: 'People validate',
      value: s ? (s.validated_groups ? `${s.validated_groups} approved by ${s.reviewers} reviewer${s.reviewers === 1 ? '' : 's'}` : 'Experts approve or dismiss each one') : '…',
      by: 'Databricks Apps · Lakebase',
    },
    {
      title: 'Value quantified',
      value: s ? `${fmt(s.validated_savings)}/yr validated of ${fmt(s.identified_savings)} identified` : '…',
      by: 'AI/BI dashboard',
      link: s?.links?.dashboard,
    },
  ];

  return (
    <div className="dstrip">
      {steps.map((st, i) => (
        <div key={st.title} className={`dstep ${i <= reached ? 'on' : ''}`}>
          <div className="dstep-n">{i + 1}</div>
          <div className="dstep-body">
            <div className="dstep-t">
              {st.title}
              {i === 3 && (
                <button className="dstep-eq" onClick={() => setShowEq((v) => !v)} title="How the value is calculated">ⓘ</button>
              )}
            </div>
            <div className="dstep-v">{st.value}</div>
            <div className="dstep-by">
              {st.link ? <a href={st.link} target="_blank" rel="noreferrer">{st.by} ↗</a> : st.by}
            </div>
          </div>
          {i < steps.length - 1 && <div className="dstep-arrow">→</div>}
        </div>
      ))}
      <div className="dstrip-gov">
        {s?.links?.catalog ? (
          <a href={s.links.catalog} target="_blank" rel="noreferrer">Governed by Unity Catalog ↗</a>
        ) : (
          <span>Governed by Unity Catalog</span>
        )}
        <span className="dstrip-ill">Illustrative · synthetic data</span>
      </div>
      {showEq && (
        <div className="dstrip-pop" onClick={() => setShowEq(false)}>
          <div className="eq">Annual savings = Σ<sub>groups</sub> Σ<sub>parts</sub> (part's best price − group's best price) × annual volume</div>
          <div className="muted">Buy every part in a group at the best price already paid for that same part. Prices and volumes are synthetic and illustrative.</div>
        </div>
      )}
    </div>
  );
}
