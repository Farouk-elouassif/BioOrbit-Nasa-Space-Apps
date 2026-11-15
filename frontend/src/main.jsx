import React,{lazy,Suspense,useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity,ArrowUpRight,Bell,Check,ChevronLeft,ChevronRight,CircleHelp,ClipboardList,House,LayoutDashboard,Moon,Orbit,Plus,Radio,RefreshCw,ShieldCheck,Thermometer,Wind,X} from 'lucide-react';
import AlertDetail from './AlertDetail.jsx';
import {telemetryStatus,scopedCrew} from './viewData.js';
import CheckInForm from './CheckInForm.jsx';
import HabitatMetric from './HabitatMetric.jsx';
import {acknowledgeAlert,apiUrl,useRemote,useSeries} from './api.js';
import {ALERT_COLORS,highestAlert,tierLabel,adaptCrew,baselineText,cabinReadings,FIELD_META,formatValue,KEY_METRICS,lastObservation,timeLabel} from './data.js';
import {HistoryChart,SeriesPanel,Spark} from './charts.jsx';
import './styles.css';
import './readability.css';

const BodyModel=lazy(()=>import('./BodyModel.jsx'));

function TelemetryStatus({run}){
 const [now,setNow]=useState(Date.now);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[]);
 const telemetry=telemetryStatus(run.telemetry_received_at,now);
 return <div className={`telemetry-status telemetry-${telemetry.state}`}><strong>{telemetry.label}</strong><span>Last telemetry received: {timeLabel(run.telemetry_received_at)}</span><span>Simulated observation time: {timeLabel(run.observation_time)}</span><small>Receipt age uses onboard wall time; measurement freshness uses mission time. Feed inactivity threshold: 30 seconds.</small></div>;
}

const coreKeys=['hr','bp','glucose','temp','sleep','mood'];
function DisplayValue({member,field}){return <>{field==='bp'?(member.bp||'—'):formatValue(member[field],FIELD_META[field]?.[2]??1)}</>}
function CrewCard({member,selected,onSelect}){
 return <button className={`crew-tile ${selected?'current':''}`} onClick={onSelect} style={{'--crew-color':member.color}}>
  <div className="crew-tile-top"><span className="crew-number">CREW / {member.id}</span><span className={`crew-condition ${member.topAlert?`tier-${member.topAlert.tier}`:member.overdue?'data-overdue':''}`}><i/>{member.status}</span></div>
  <div className="crew-identity"><div className="crew-monogram">{member.initials}</div><div><h3>{member.name}</h3><p>{member.role}</p></div></div>
  <div className="waveform"><Spark data={member.wave} color={member.color}/><span>{formatValue(member.hr,0)}<small>BPM</small></span></div>
  <div className="crew-bottom"><span>{member.activity==='sleeping'?<Moon size={12}/>:<Activity size={12}/>} {member.shift}</span><span>{formatValue(member.sleep,1)}h sleep <ChevronRight size={13}/></span></div>
 </button>;
}
function App(){
 const [theme,setTheme]=useState(()=>{try{return localStorage.getItem('bioorbit-theme')==='dark'?'dark':'light'}catch{return 'light'}});
 useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('bioorbit-theme',theme)}catch{}},[theme]);
 const [runId,setRunId]=useState(''),[habitatId,setHabitatId]=useState(''),[zoneId,setZoneId]=useState(''),[active,setActive]=useState('crew');
 const remote=useRemote(apiUrl('dashboard',{run_id:runId,habitat_id:habitatId,zone_id:zoneId}),5000);
 const snapshot=remote.data,run=snapshot?.run;
 const crew=useMemo(()=>run?(snapshot.crew||[]).map(p=>adaptCrew(p,run)):[],[snapshot]);
 const [person,setPerson]=useState(null),[region,setRegion]=useState(0),[filter,setFilter]=useState('all');
 const member=crew.find(p=>p.id===person)||crew[0];
 const habitat=snapshot?.cabin?{...snapshot.cabin,runId:run?.id}:null;
 const cabin=useMemo(()=>cabinReadings(habitat),[snapshot]);
 const bodyView=useRef(null);
 const [detail,setDetail]=useState(null),[entry,setEntry]=useState(false),[entryCrew,setEntryCrew]=useState('');
 const reports=useRemote(active==='log'&&run?apiUrl('check-ins',{run_id:run.id}):null,5000);
 const logs=reports.data?.checkins||[];
 const shown=filter==='overdue'?crew.filter(p=>p.overdue):crew;
 const overdue=crew.filter(p=>p.overdue).length;
 function selectPerson(p){setPerson(p.id);setDetail(null);if(p.habitat_id){setHabitatId(p.habitat_id);setZoneId(habitat?.habitat_id===p.habitat_id&&habitat.zones?.includes(p.zone_id)?p.zone_id:'')}}
 function nextPerson(delta){if(crew.length)selectPerson(crew[(crew.findIndex(p=>p.id===member?.id)+delta+crew.length)%crew.length])}
 function checkin(p=member){if(!p)return;setEntryCrew(p.id);setEntry(true)}
 const sourceTime=run?.observation_time;
 const habitatCrew=scopedCrew(crew,habitat?.habitat_id,habitat?.zone_id);
 const alerts=snapshot?.alerts||[],priority=highestAlert(alerts);
 const [ackBusy,setAckBusy]=useState(false),[ackError,setAckError]=useState('');
 async function acknowledge(a){setAckBusy(true);setAckError('');try{await acknowledgeAlert(a);remote.refresh()}catch(e){setAckError(e.message)}finally{setAckBusy(false)}}
 return <div className="console">
  <aside className="rail"><button className="rail-brand" aria-label="Crew overview" onClick={()=>setActive('crew')}><Orbit size={27}/></button><span className="rail-rule"/>
   {[[LayoutDashboard,'crew','Crew overview'],[House,'habitat','Habitat'],[Bell,'alerts','Alerts'],[ClipboardList,'log','Crew check-ins']].map(([Icon,key,label])=><button key={key} aria-label={label} title={label} className={`rail-item ${active===key?'selected':''}`} onClick={()=>setActive(key)}><Icon size={20}/></button>)}
   <div className="rail-bottom"><span className="signal-dot"/><span className="vertical-type">ONBOARD CONSOLE</span><button className="rail-item" aria-label="About this console" onClick={()=>setDetail({type:'about'})}><CircleHelp size={19}/></button></div>
  </aside>
  <div className="console-main">
   <header className="command-header"><a className="wordmark" href="#" onClick={e=>{e.preventDefault();setActive('crew')}}>Bio<span>Orbit</span><sup> / 01</sup></a>
    <div className="mission-name">{run?.mission_name||'MISSION CONSOLE'}<span>{run?.environment.replaceAll('_',' ').toUpperCase()||'AWAITING MISSION DATA'}</span></div>
    <div className="mission-time"><span className="signal-dot"/>{remote.error?'CONNECTION INTERRUPTED':remote.loading?'CONNECTING':'API CONNECTED'}<b>{run?.mission_day?`DAY ${run.mission_day}`:'PREFLIGHT'}</b></div>
    <button className="theme-toggle" aria-label={theme==='dark'?'Switch to light mode':'Switch to navy dark mode'} aria-pressed={theme==='dark'} onClick={()=>setTheme(theme==='dark'?'light':'dark')}><Moon size={14}/><span>{theme==='dark'?'Light mode':'Dark mode'}</span></button><span className="simulation">SYNTHETIC TELEMETRY</span>
   </header>
   <main className="workspace">
    <div className="title-row"><div><div className="kicker">HUMAN SYSTEMS / {active==='crew'?'CREW TELEMETRY':active==='habitat'?'ENVIRONMENTAL CONTROL':'SESSION OBSERVATIONS'}</div><h1>{active==='crew'?'People first. Mission always.':active==='habitat'?'The space between us.':'Every observation matters.'}</h1></div><button className="entry-button" disabled={!member} onClick={()=>checkin()}><Plus size={16}/>Record check-in</button></div>
    <div className="data-controls"><label>Mission run<select aria-label="Mission run" value={runId} onChange={e=>{setRunId(e.target.value);setHabitatId('');setZoneId('');setPerson(null);setDetail(null)}}><option value="">Latest available run</option>{snapshot?.runs?.map(r=><option key={r.id} value={r.id}>{r.mission_code} / {r.id}</option>)}</select></label>
     {!!snapshot?.habitats?.length&&<label>Habitat<select aria-label="Habitat" value={habitatId||habitat?.habitat_id||''} onChange={e=>{setHabitatId(e.target.value);setZoneId('')}}>{snapshot.habitats.map(h=><option key={h.id} value={h.id}>{h.name}</option>)}</select></label>}
     {!!habitat?.zones?.length&&<label>Cabin zone<select aria-label="Cabin zone" value={zoneId||habitat.zone_id} onChange={e=>setZoneId(e.target.value)}>{habitat.zones.map(zone=><option key={zone} value={zone}>{zone.replaceAll('_',' ')}</option>)}</select></label>}
     <button className="refresh-button" onClick={remote.refresh}><RefreshCw size={13}/>Refresh</button><span className="data-contact">Last contact {remote.receivedAt?timeLabel(remote.receivedAt):'—'}</span>
    </div>
    {run&&<TelemetryStatus run={run}/>}
    {remote.error&&<div className="connection-message" role="status"><Radio size={17}/><div><strong>Mission data connection interrupted</strong><p>{remote.error}{snapshot?' Showing the last received snapshot.':''}</p></div><button onClick={remote.refresh}>Retry</button></div>}
    <div className="status-bar"><span><i/>{String(crew.length).padStart(2,'0')} CREW IN THIS RUN</span><span>{overdue} WITH OVERDUE DATA</span><span>{alerts.length} ACTIVE ALERTS</span><span className="status-end"><Radio size={13}/>OBSERVED <b>{sourceTime?timeLabel(sourceTime):'—'}</b></span></div>
    {priority&&active!=='alerts'&&<button className={`alert-banner tier-${priority.tier}`} onClick={()=>setActive('alerts')}><Bell size={19}/><span><strong>{tierLabel(priority.tier)} · {priority.title}</strong><small>{priority.message}</small></span><b>{alerts.length} active →</b></button>}
    {!snapshot&&remote.loading&&<div className="empty-log" role="status"><Orbit size={30}/><h2>Connecting to your mission.</h2><p>Loading crew and habitat observations.</p></div>}
    {snapshot&&!run&&<div className="empty-log"><Radio size={32}/><h2>Waiting for mission telemetry.</h2><p>No simulation run has been ingested yet. This console refreshes automatically as data arrives.</p></div>}
    {run&&active==='crew'&&<>
     <div className="crew-command-layout">
      {member?<Suspense fallback={<div className="empty-log" role="status">Loading interactive body view…</div>}><BodyModel member={member} cabin={cabin} habitat={habitat} viewState={bodyView} region={region} onRegionChange={setRegion} onEnvironment={()=>setActive('habitat')} onHabitat={()=>setDetail({type:'cabin'})} onCheckin={()=>checkin()} onAlert={a=>setDetail({type:'alert',id:a.id})}/></Suspense>:<div className="empty-log"><h2>Waiting for crew observations.</h2><p>There are no astronaut records in this run yet.</p></div>}
      <section className="roster"><div className="section-cap"><h2>Crew at a glance</h2><div className="segmented"><button className={filter==='all'?'chosen':''} onClick={()=>setFilter('all')}>All crew</button><button className={filter==='overdue'?'chosen':''} onClick={()=>setFilter('overdue')}>Overdue <b>{overdue}</b></button></div></div><div className="crew-grid">{shown.map(p=><CrewCard key={p.id} member={p} selected={member?.id===p.id} onSelect={()=>selectPerson(p)}/>)}</div>{!shown.length&&<p className="data-message">No crew members match this filter.</p>}</section>
     </div>
     {member&&<section className="crew-workspace"><div className="person-sheet"><div className="person-heading"><div><div className="kicker">SELECTED CREW / {member.id}</div><h2>{member.name}</h2><p>{member.shift}<span>·</span>{member.location}</p></div><div className="person-switch"><button aria-label="Previous astronaut" onClick={()=>nextPerson(-1)}><ChevronLeft size={17}/></button><button aria-label="Next astronaut" onClick={()=>nextPerson(1)}><ChevronRight size={17}/></button></div></div>
      <div className="measurements"><div className="measurement-head"><span>INDICATOR</span><span>LATEST</span><span>PERSONAL REFERENCE</span><span/></div>{coreKeys.map((key,i)=><button className="measurement-row" key={key} onClick={()=>setDetail({type:'metric',memberId:member.id,field:key})}><span><span className="measure-dot" style={{background:['#7e9dff','#ad9bfb','#e6b27c','#ef929b','#b19bec','#7cc7af'][i]}}/>{FIELD_META[key][0]}</span><span className="measurement-value"><DisplayValue member={member} field={key}/><small>{FIELD_META[key][1]}</small></span><span>{baselineText(member,key)}<small className="reading-time">{timeLabel(lastObservation(member,key)?.measured_at)}{lastObservation(member,key)?.context?.meal_context?' · '+lastObservation(member,key).context.meal_context.replaceAll('_',' '):''}{lastObservation(member,key)?.freshness==='overdue'?' · overdue':''}</small></span><ArrowUpRight size={14}/></button>)}</div><div className="sheet-foot"><ShieldCheck size={14}/>Stored personal reference data<span>{timeLabel(member.latest_at)}</span></div></div>
      <div className="trend-sheet"><div className="section-cap"><h2>Rest & recovery</h2><Moon size={17}/></div><div className="trend-summary"><strong>{formatValue(member.sleep,1)}<small>h</small></strong><div>LATEST SLEEP SUMMARY<span>{timeLabel(lastObservation(member,'sleep')?.measured_at)}</span></div></div><SeriesPanel member={member} metric="sleep_duration" defaultWindow="7d" compact/><div className="recovery-note"><span className="tiny-index">RECORDED OBSERVATIONS</span><p>Charts reflect recorded measurements. Missing history stays empty; Workbook rules evaluate available observations; missing inputs remain unevaluated.</p><button onClick={()=>checkin()}>Add a session observation<ArrowUpRight size={14}/></button></div></div>
     </section>}
     <section className="crew-comparison"><div className="section-cap"><h2><span>03</span>The whole crew, one picture</h2><span className="mono-muted">LATEST STORED VALUES</span></div><div className="comparison-scroll"><table><thead><tr><th>CREW MEMBER</th>{coreKeys.map(key=><th key={key}>{FIELD_META[key][0]}<small>{FIELD_META[key][1]}</small></th>)}</tr></thead><tbody>{crew.map(p=><tr key={p.id} className={p.id===member?.id?'selected-row':''} onClick={()=>selectPerson(p)}><th><button onClick={()=>selectPerson(p)}><span style={{color:p.color}}>{p.id}</span>{p.name}</button></th>{coreKeys.map(key=><td key={key}><DisplayValue member={p} field={key}/></td>)}</tr>)}</tbody></table></div></section>
    </>}
    {run&&active==='habitat'&&<section className="environment"><div className="section-cap"><h2><span>01</span>Shared cabin environment</h2><span className="mono-muted">{habitat?.name||'NO HABITAT'} / {habitat?.zone_id||'—'}</span></div>{habitat?<><div className="environment-grid">{cabin.map(point=><HabitatMetric key={`${habitat.runId}:${habitat.habitat_id}:${habitat.zone_id}:${point.metric}`} entry={point} habitat={habitat}/>)}</div><div className="environment-story"><div><span className="kicker">ENVIRONMENTAL CONTEXT</span><h2>{habitat.name}. {habitatCrew.length} crew in this zone.</h2><p>These are the stored environmental observations for {habitat.name}. They provide context alongside crew readings; they do not establish a symptom’s cause.</p><p>Solar storm present: <strong>{formatValue(habitat.measurements.is_solar_storm?.value)}</strong></p></div><div className="deck-plan"><div className="deck-label">{habitat.name} / CREW LOCATIONS</div><div className="module-grid">{habitatCrew.map(p=><span key={p.id}>{p.zone_id||'LOCATION UNAVAILABLE'}<br/><b>{p.name}</b></span>)}{!habitatCrew.length&&<p>No crew locations recorded in this zone.</p>}</div><span className="tiny-index">LOCATIONS FROM INGESTED OBSERVATIONS</span></div></div></>:<p className="data-message">No habitat observations have been received yet.</p>}</section>}
    {run&&active==='alerts'&&<section className="alerts-panel"><div className="section-cap"><h2>Mission alerts</h2><span className="mono-muted">WORKBOOK RULES · PROTOTYPE</span></div><p>Evidence uses mission observation time. Acknowledgment records review; it does not resolve an alert. Missing inputs remain unevaluated.</p>{alerts.length?alerts.map(a=><button key={a.id} className={`alert-card tier-${a.tier}`} onClick={()=>{setAckError('');setDetail({type:'alert',id:a.id})}}><span className="alert-tier">{tierLabel(a.tier)}</span><div><h3>{a.title}</h3><p>{a.astronaut_id||a.habitat_id} · {a.message}</p><small>Observed {timeLabel(a.last_observation_at)} · {a.recheck_interval_seconds===0?'Continuous recheck':`Recheck ${timeLabel(a.recheck_due_at)}`}{a.recheck_overdue?' · Recheck due':''}{a.acknowledged_at?' · Acknowledged':''}</small></div><ArrowUpRight size={17}/></button>):<div className="empty-log"><Bell size={28}/><h2>No active alerts.</h2><p>This does not establish that all measurements or rule inputs are available.</p></div>}<h2 className="collection-heading">Rule coverage</h2>{crew.map(p=><details className="collection-task" key={p.id}><summary>{p.name} · {p.assessment?.evaluated_rules||0} rules evaluated</summary><p>NEWS2: {p.assessment?.news2?.state||'Not evaluated'}</p><p>Missing NEWS2 inputs: {(p.assessment?.news2?.missing||[]).join(', ')||'None reported'}</p><p>Rules awaiting data: {(p.assessment?.insufficient_data||[]).join(', ')||'None reported'}</p></details>)}<h2 className="collection-heading">Collection tasks</h2><p>Missing or overdue data are collection tasks, separate from medical alerts.</p>{(snapshot.collection_tasks||[]).map((task,i)=><div className="collection-task" key={i}><strong>{task.astronaut_id||task.habitat_id} · {task.metric.replaceAll("_"," ")}</strong><p>{task.kind==='measurement_missing'?'Missing measurement':'Overdue measurement'} · Due {timeLabel(task.due_at)}</p></div>)}</section>}
    {active==='log'&&<section className="log-page"><div className="section-cap"><h2>Stored crew check-ins</h2><span className="mono-muted">MISSION OBSERVATIONS</span></div>{reports.error&&<p role="alert">{reports.error}</p>}{logs.map(log=><article key={log.id} className="log-entry"><div><span className="tiny-index">{timeLabel(log.observed_at)} / {log.run_id}</span><h3>{log.name}</h3>{Object.entries(log.measurements.values||{}).map(([code,value])=><p key={code}>{code.replaceAll('_',' ')}: {value}</p>)}{Object.entries(log.rule_inputs).map(([code,finding])=><p key={code}>{code.replaceAll('_',' ')}: {String(finding.value)}</p>)}{log.notes&&<p className="log-notes">{log.notes}</p>}</div></article>)}{!logs.length&&<p>No stored reports loaded. Sign in when recording a check-in.</p>}<button className="entry-button" disabled={!member} onClick={()=>checkin()}>Record check-in</button></section>}
    {run&&habitat&&<button className="habitat-banner resolved live-habitat-banner" onClick={()=>setDetail({type:'cabin'})}><span className="banner-code">SHARED / ENV</span><Wind size={20}/><div><strong>{habitat.name} · {habitat.zone_id}</strong><span>CO₂ {formatValue(cabin[0].value,2)} mmHg · {timeLabel(cabin[0].measured_at)}</span></div><span className="banner-action">Review observations<ArrowUpRight size={16}/></span></button>}
    <footer className="console-footer"><span>BioOrbit<b>HUMAN SYSTEMS CONSOLE</b></span><span>BACKEND TELEMETRY<i/>Synthetic observations · Not for clinical use</span></footer>
   </main>
  </div>
  {detail&&<div className="dialog-backdrop" onClick={()=>setDetail(null)}><section className="console-dialog" role="dialog" aria-modal="true" aria-label="Observation details" onClick={e=>e.stopPropagation()}><button className="dialog-close" autoFocus aria-label="Close details" onClick={()=>setDetail(null)}><X size={21}/></button>
   {detail.type==='alert'?<AlertDetail alert={alerts.find(a=>a.id===detail.id)} busy={ackBusy} error={ackError} onAcknowledge={acknowledge}/>:detail.type==='about'?<><div className="kicker">BioOrbit / CONNECTED CONSOLE</div><h2>A shared view of crew health.</h2><p>The roster, readings, preflight references, habitat measurements, and recorded charts come from the backend. Telemetry is currently generated by the mission simulator. Workbook alert rules are connected. They are a prototype, not a validated clinical system. Forecasts are not connected. Authenticated check-ins are stored and evaluated by the backend.</p></>:detail.type==='cabin'?<><div className="kicker">SHARED HABITAT / STORED OBSERVATIONS</div><h2>{habitat?.name||'Cabin observations'}</h2><p>{habitat?.zone_id||'No zone available'} · {timeLabel(sourceTime)}</p>{cabin.slice(0,4).map(point=><div className="hover-reading" key={point.metric}><span>{point.name}</span><strong>{formatValue(point.value,2)}<small>{point.unit}</small></strong></div>)}<SeriesPanel domain="cabin" habitat={habitat} metric="co2_partial_pressure" defaultWindow="24h"/><div className="dialog-note">Workbook alerts appear in the Alerts panel, with evidence and source references. Missing observations do not count as normal.</div></>:<MetricDetail member={crew.find(p=>p.id===detail.memberId)} field={detail.field}/>}
  </section></div>}
  {entry&&<div className="dialog-backdrop" onClick={()=>setEntry(false)}><section className="console-dialog" role="dialog" aria-modal="true" aria-label="Crew check-in" onClick={e=>e.stopPropagation()}><button className="dialog-close" aria-label="Close check-in" onClick={()=>setEntry(false)}><X size={21}/></button><CheckInForm run={run} crew={crew} initialCrew={entryCrew} onSaved={()=>{setEntry(false);setActive('log');remote.refresh();reports.refresh()}}/></section></div>}
 </div>;
}
function MetricDetail({member,field}){
 if(!member)return <p className="data-message">This crew member is no longer available in the selected run.</p>;
 const reading=lastObservation(member,field);
 return <><div className="kicker">{member.name} / RECORDED TELEMETRY</div><h2>{FIELD_META[field][0]}</h2><div className="dialog-reading"><DisplayValue member={member} field={field}/><small>{FIELD_META[field][1]}</small></div><p>{baselineText(member,field)}</p><p>{timeLabel(reading?.measured_at)}{reading?.context?.meal_context?' · '+reading.context.meal_context.replaceAll('_',' '):''}{reading?.freshness==='overdue'?' · overdue observation':''}</p><SeriesPanel key={`${member.runId}:${member.id}:${field}`} member={member} metric={KEY_METRICS[field]} defaultWindow="24h"/><div className="dialog-note">{field==='bp'?'Systolic and diastolic observations are shown separately. ':''}Recorded history is grouped by observation time. It is not a forecast or a clinical assessment.</div></>;
}
createRoot(document.getElementById('root')).render(<App/>);
