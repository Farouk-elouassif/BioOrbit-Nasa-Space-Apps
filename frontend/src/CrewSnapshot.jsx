import React,{useEffect,useRef} from 'react';
import {Activity,ArrowUpRight,Bell,Plus} from 'lucide-react';
import {KEY_METRICS,highestAlert,tierLabel,timeLabel} from './data.js';
import {CATEGORIES,categoryReadings,hasValue,readableLabel,readableValue} from './measurementCategories.js';
import './measurementCategories.css';

function ReadingValue({value}){
  const text=readableValue(value);
  if(text!==null)return <span>{text}</span>;
  return <dl className="category-result">{Object.entries(value).map(([key,item])=><div key={key}><dt>{readableLabel(key)}</dt><dd><ReadingValue value={item}/></dd></div>)}</dl>;
}
export default function CrewSnapshot({member,habitat,onMetric,onAlert,onCheckin}){
  const panel=useRef(null);
  useEffect(()=>{if(panel.current)panel.current.scrollTop=0;},[member.id,member.runId]);
  const priority=highestAlert((member.alerts||[]).filter(alert=>alert.tier!=='advisory'));
  const habitatMatches=habitat?.habitat_id===member.habitat_id;
  return <section className="crew-snapshot category-snapshot" aria-label={`Current observations for ${member.name}`}>
    <div className="snapshot-heading"><Activity size={19}/><div><h3>Crew measurements</h3><span>{member.name} · {member.shift||'Activity unavailable'}</span></div></div>
    {priority&&<button className={`snapshot-priority tier-${priority.tier}`} onClick={()=>onAlert?.(priority)}><Bell size={17}/><span><strong>{tierLabel(priority.tier)} · {member.name}</strong><span>{priority.title}</span><small>View alert details</small></span><ArrowUpRight size={16}/></button>}
    <div ref={panel} className="category-panel" tabIndex={0} aria-label="All crew and habitat measurements">
    {CATEGORIES.map(selected=>{
      const category=selected.id,entries=categoryReadings(category,member,habitat);
      const groups=[...new Set(entries.map(entry=>entry.group))];
      return <section key={category} aria-label={`${selected.label} measurements`}>
    <div className="category-introduction"><h4>{selected.label} measurements</h4><p>{selected.description}</p>
      {category==='habitat'&&<p className="category-scope">{habitatMatches?`Shared habitat: ${habitat.name||habitat.habitat_id} · ${habitat.zone_id||'zone unavailable'}`:`Awaiting readings for ${member.habitat_id||'this crew member’s habitat'}.`}{habitatMatches&&member.zone_id!==habitat.zone_id?` · Astronaut location: ${member.zone_id||'unknown'}`:''}</p>}
    </div>
    <div>
      {!entries.some(entry=>hasValue(entry.reading))&&<p className="category-empty" role="status">No {selected.label.toLowerCase()} readings received yet. Measurements will appear automatically when available.</p>}
      {groups.map(group=><section className="category-group" key={group} aria-label={group}><h5>{group}</h5><div className="category-reading-grid">{entries.filter(entry=>entry.group===group).map(entry=>{
        const {reading,alert}=entry,available=hasValue(reading),structured=available&&typeof reading.value==='object';
        const key=Object.keys(KEY_METRICS).find(key=>KEY_METRICS[key]===entry.metric);
        return <article key={entry.metric} className={`category-reading${structured?' category-reading-structured':''}${!available?' category-reading-missing':''}${alert?` tier-${alert.tier}`:''}`}>
          <h6>{entry.label}</h6><div className="category-reading-value"><ReadingValue value={reading?.value}/>{available&&!structured&&!['boolean','categorical'].includes(entry.type)&&<small>{reading.unit||entry.unit}</small>}</div>
          <span className="category-reading-time">{entry.baselineOnly?'Preflight reference':timeLabel(reading?.measured_at)}</span>
          {reading?.context?.synthetic_random&&<span className="category-fixture">Random simulation{entry.metric==='news2'?' · not the calculated score':''}</span>}
          {reading?.freshness==='overdue'&&<span className="snapshot-overdue">Overdue observation</span>}
          {alert&&<button className="category-alert-link" onClick={()=>onAlert?.(alert)}>{tierLabel(alert.tier)} · View alert<ArrowUpRight size={13}/></button>}
          {available&&key&&onMetric&&<button className="category-region-link" onClick={()=>onMetric(key)}>Explore body region<ArrowUpRight size={13}/></button>}
        </article>;
      })}</div></section>)}
    </div>
    </section>;
    })}
    </div>
    <button className="snapshot-checkin" onClick={onCheckin}><Plus size={16}/>Record a check-in<ArrowUpRight size={14}/></button>
  </section>;
}
