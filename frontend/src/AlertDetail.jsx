import React from 'react';
import {formatNumericText,formatValue,tierLabel,timeLabel} from './data.js';
import {guidanceSteps,humanLabel} from './viewData.js';

function Evidence({value}) {
  if(value===null||value===undefined)return <span>Unavailable</span>;
  if(Array.isArray(value))return value.length?<ul>{value.map((item,i)=><li key={i}><Evidence value={item}/></li>)}</ul>:<span>None recorded</span>;
  if(typeof value==='object')return <dl className="decision-facts">{Object.entries(value).map(([key,item])=><div key={key}><dt>{humanLabel(key)}</dt><dd><Evidence value={item}/></dd></div>)}</dl>;
  return <span>{typeof value==='number'||typeof value==='boolean'?formatValue(value):String(value)}</span>;
}
export default function AlertDetail({alert:a,busy,error,onAcknowledge}) {
  if(!a)return <><h2>Alert no longer active.</h2><p>Refresh the alert list for its current state.</p></>;
  const steps=guidanceSteps(a.actions);
  const evidence=a.evidence||{};
  const isNews2=a.rule_code==='news2';
  const retainedTier=Boolean(evidence.held_until_three_normal_readings);
  const facts=Object.fromEntries(Object.entries(evidence).filter(([key])=>!['event_id','event_ids','candidate_tier','held_until_three_normal_readings'].includes(key)));
  const reference=a.rule_reference||{};
  return <>
    <div className={`alert-tier tier-${a.tier}`}>{tierLabel(a.tier)} / {a.astronaut_id||a.habitat_id}{a.zone_id?` / ${a.zone_id}`:''}</div>
    <h2>{a.title}</h2>
    <section className="decision-section"><h3>Why this needs review</h3><p>{formatNumericText(a.message)}</p>
      {reference.condition&&<><h4>{retainedTier?'Workbook condition for retained alert tier':'Workbook condition for'} {tierLabel(a.tier).toLowerCase()}</h4><p>{formatNumericText(reference.condition)}</p><small>Reference text; the recorded evaluation and evidence determine this alert.</small></>}
      <p className="tiny-index">Rule: {humanLabel(a.rule_code||'unknown')}</p>
      {retainedTier&&<div className="dialog-note">
        <p><strong>Retained alert tier: {tierLabel(a.tier)}.</strong> The latest calculated tier is {tierLabel(evidence.candidate_tier)}. The alert keeps its earlier, higher severity until the recovery requirements are met.</p>
        <p>Three distinct later qualifying normal observations lower the alert by one tier. A lower score that still triggers an alert does not count as normal and resets that counter. Acknowledgment does not lower severity.</p>
      </div>}
    </section>
    <section className="decision-section"><h3>{isNews2?'NEWS2 scores & findings':'Recorded measurements & findings'}</h3>
      {isNews2&&<div className="dialog-note">
        <p><strong>These are component scores, not measured vital signs.</strong> A score of 0.00 means the available reading contributes no points to this calculation. It does not mean a heart rate of 0 bpm or an oxygen saturation of 0%.</p>
        <p>The numerical component scores are added together, with any consciousness and supplemental-oxygen contributions, to produce the total. For example, a temperature component of 2.00 contributes two points; it is not a temperature of 2°C. Actual readings are shown in the crew measurements.</p>
        <p>Missing or invalid inputs are not scored as zero.{evidence.partial?' This is a partial score: unavailable components remain unknown.':''}</p>
      </div>}
      {Object.keys(facts).length?<><Evidence value={facts}/>{Object.hasOwn(facts,'value')&&reference.unit&&<p>Measurement unit: {reference.unit}</p>}</>:<p>No numerical evidence was attached. Review the recorded rule explanation above.</p>}
      <dl className="decision-facts"><div><dt>Observed (mission time)</dt><dd>{timeLabel(a.last_observation_at)}</dd></div><div><dt>Recheck deadline (mission time)</dt><dd>{a.recheck_interval_seconds===0?'Continuous monitoring':timeLabel(a.recheck_due_at)}{a.recheck_overdue?' · Due':''}</dd></div><div><dt>Review status</dt><dd>{a.acknowledged_at?`Acknowledged ${timeLabel(a.acknowledged_at)}`:'Awaiting acknowledgment'}</dd></div></dl>
    </section>
    <section className="decision-section"><h3>Workbook guidance</h3>{steps.length?<ol className="guidance-steps">{steps.map((step,i)=><li key={i}>{formatNumericText(step)}</li>)}</ol>:<p>No guidance recorded.</p>}<p>Reference recipients: {a.recipients||'Not specified'}</p><p className="dialog-note">Prototype reference guidance. This console does not send notifications or deliver treatment.</p></section>
    <details className="raw-evidence"><summary>Raw evidence and source details</summary><pre className="alert-evidence">{JSON.stringify({evidence:a.evidence,rule_reference:a.rule_reference,provenance:a.provenance},null,2)}</pre></details>
    {error&&<p role="alert">{error}</p>}
    <button className="entry-button" disabled={busy||!!a.acknowledged_at} onClick={()=>onAcknowledge(a)}>{a.acknowledged_at?'Acknowledged':busy?'Saving…':'Acknowledge review'}</button><p>Acknowledgment records review. Three distinct normal observations lower the alert by one tier.</p>
  </>;
}
