import React from 'react';
import {tierLabel,timeLabel} from './data.js';
import {guidanceSteps,humanLabel} from './viewData.js';

function Evidence({value}) {
  if(value===null||value===undefined)return <span>Unavailable</span>;
  if(Array.isArray(value))return value.length?<ul>{value.map((item,i)=><li key={i}><Evidence value={item}/></li>)}</ul>:<span>None recorded</span>;
  if(typeof value==='object')return <dl className="decision-facts">{Object.entries(value).map(([key,item])=><div key={key}><dt>{humanLabel(key)}</dt><dd><Evidence value={item}/></dd></div>)}</dl>;
  return <span>{typeof value==='boolean'?(value?'Yes':'No'):String(value)}</span>;
}
export default function AlertDetail({alert:a,busy,error,onAcknowledge}) {
  if(!a)return <><h2>Alert no longer active.</h2><p>Refresh the alert list for its current state.</p></>;
  const steps=guidanceSteps(a.actions);
  const evidence=a.evidence||{};
  const facts=Object.fromEntries(Object.entries(evidence).filter(([key])=>!['event_id','event_ids','candidate_tier','held_until_three_normal_readings'].includes(key)));
  const reference=a.rule_reference||{};
  return <>
    <div className={`alert-tier tier-${a.tier}`}>{tierLabel(a.tier)} / {a.astronaut_id||a.habitat_id}{a.zone_id?` / ${a.zone_id}`:''}</div>
    <h2>{a.title}</h2>
    <section className="decision-section"><h3>Why this needs review</h3><p>{a.message}</p>
      {reference.condition&&<><h4>Workbook condition for {tierLabel(a.tier).toLowerCase()}</h4><p>{reference.condition}</p><small>Reference text; the recorded evaluation and evidence determine this alert.</small></>}
      <p className="tiny-index">Rule: {humanLabel(a.rule_code||'unknown')}</p>
      {evidence.held_until_three_normal_readings&&<p>The alert remains at this tier pending three distinct normal observations. The latest candidate tier is {tierLabel(evidence.candidate_tier)}.</p>}
    </section>
    <section className="decision-section"><h3>Recorded measurements & findings</h3>
      {Object.keys(facts).length?<><Evidence value={facts}/>{Object.hasOwn(facts,'value')&&reference.unit&&<p>Measurement unit: {reference.unit}</p>}</>:<p>No numerical evidence was attached. Review the recorded rule explanation above.</p>}
      <dl className="decision-facts"><div><dt>Observed (mission time)</dt><dd>{timeLabel(a.last_observation_at)}</dd></div><div><dt>Recheck deadline (mission time)</dt><dd>{a.recheck_interval_seconds===0?'Continuous monitoring':timeLabel(a.recheck_due_at)}{a.recheck_overdue?' · Due':''}</dd></div><div><dt>Review status</dt><dd>{a.acknowledged_at?`Acknowledged ${timeLabel(a.acknowledged_at)}`:'Awaiting acknowledgment'}</dd></div></dl>
    </section>
    <section className="decision-section"><h3>Workbook guidance</h3>{steps.length?<ol className="guidance-steps">{steps.map((step,i)=><li key={i}>{step}</li>)}</ol>:<p>No guidance recorded.</p>}<p>Reference recipients: {a.recipients||'Not specified'}</p><p className="dialog-note">Prototype reference guidance. This console does not send notifications or deliver treatment.</p></section>
    <details className="raw-evidence"><summary>Raw evidence and source details</summary><pre className="alert-evidence">{JSON.stringify({evidence:a.evidence,rule_reference:a.rule_reference,provenance:a.provenance},null,2)}</pre></details>
    {error&&<p role="alert">{error}</p>}
    <button className="entry-button" disabled={busy||!!a.acknowledged_at} onClick={()=>onAcknowledge(a)}>{a.acknowledged_at?'Acknowledged':busy?'Saving…':'Acknowledge review'}</button><p>Acknowledgment records review. Three distinct normal observations lower the alert by one tier.</p>
  </>;
}
