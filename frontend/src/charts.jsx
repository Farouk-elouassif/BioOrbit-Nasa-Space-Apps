import React,{useState} from 'react';
import {useSeries} from './api.js';
import {timeLabel,formatValue} from './data.js';
import {humanLabel,splitHistory,sleepDayLabel} from './viewData.js';

export function Spark({data=[],times=[],color='#8ba4c6',large=false}){
  const values=data.filter(v=>typeof v==='number'&&Number.isFinite(v));
  if(!values.length)return <span className="spark-empty">No history yet</span>;
  const low=Math.min(...values),high=Math.max(...values),spread=high-low||1;
  const timing=times.map(t=>Date.parse(t));
  const spaced=timing.length===values.length&&timing.every(Number.isFinite)&&timing.at(-1)>timing[0];
  const points=values.map((v,i)=>`${values.length===1?50:spaced?(timing[i]-timing[0])/(timing.at(-1)-timing[0])*100:i*100/(values.length-1)},${high===low?32:55-(v-low)/spread*44}`).join(' ');
  return <svg className={large?'spark large':'spark'} viewBox="0 0 100 65" preserveAspectRatio="none" role="img" aria-label="Recorded measurement trend">
    {values.length===1?<circle cx="50" cy="32" r="2" fill={color}/>:<><polygon points={`0,65 ${points} 100,65`} fill={color} opacity=".08"/><polyline points={points} fill="none" stroke={color} strokeWidth="1.2" vectorEffect="non-scaling-stroke"/></>}
  </svg>;
}
const colors=['var(--chart-primary, #397ac6)','var(--chart-secondary, #a95b26)'];
export function HistoryChart({series,secondary,baseline,secondaryBaseline,compact=false,domain='astronaut',missionStartedAt,metric}){
  const [inspected,setInspected]=useState(null);
  const daily=metric==='sleep_duration'||series.data?.metric==='sleep_duration';
  const pointLabel=bucket=>daily?sleepDayLabel(bucket,missionStartedAt):timeLabel(bucket);
  const datasets=[{remote:series,label:secondary?'Systolic':humanLabel(series.data?.metric||'measurement'),baseline},...(secondary?[{remote:secondary,label:'Diastolic',baseline:secondaryBaseline}]:[])];
  const prepared=datasets.map((set,i)=>({...set,color:colors[i],segments:splitHistory(set.remote.data?.points||[],set.remote.data?.window)}));
  const points=prepared.flatMap(set=>set.segments.flat());
  if(!points.length)return <p role="status" className="data-message">{series.loading||secondary?.loading?'Loading recorded history…':series.error||secondary?.error||'No recorded measurements in this time window.'}</p>;
  const unit=series.data?.unit||secondary?.data?.unit||'';
  const bounds=prepared.map(set=>{
    const b=set.baseline;
    return b&&Number.isFinite(b.min)&&Number.isFinite(b.max)?[b.min,b.max]:b&&Number.isFinite(b.mean)?[b.mean,b.mean]:null;
  });
  const values=[...points.map(p=>p.value),...bounds.filter(Boolean).flat()];
  const min=Math.min(...values),max=Math.max(...values),pad=(max-min)*.12||1;
  const low=min-pad,high=max+pad;
  const anchor=Date.parse(series.data?.anchor_time||secondary?.data?.anchor_time);
  let end=Math.max(Number.isFinite(anchor)?anchor:0,...points.map(p=>Date.parse(p.bucket)));
  const duration=(series.data?.window||secondary?.data?.window)==='24h'?86400000:(series.data?.window||secondary?.data?.window)==='7d'?7*86400000:30*86400000;
  let start=Math.min(end-duration,...points.map(p=>Date.parse(p.bucket)));
  const dayMs=86400000;
  let dayTicks=[];
  if(daily){
    end=Math.floor(end/dayMs)*dayMs;
    start=Math.min(end-duration+dayMs,...points.map(p=>Date.parse(p.bucket)));
    const missionStart=Date.parse(missionStartedAt);
    if(Number.isFinite(missionStart))start=Math.max(start,Math.floor(missionStart/dayMs)*dayMs);
    start=Math.floor(start/dayMs)*dayMs;
    for(let tick=start;tick<=end;tick+=dayMs)dayTicks.push(tick);
  }
  const plotWidth=daily?Math.max(600,dayTicks.length*85):600;
  const plotRight=plotWidth-20,plotSpan=plotRight-62;
  const x=time=>end===start?(62+plotRight)/2:62+(Date.parse(time)-start)/(end-start)*plotSpan;
  const y=value=>20+(high-value)/(high-low)*180;
  const active=inspected&&prepared.some(set=>set.label===inspected.label&&set.segments.flat().some(p=>p.bucket===inspected.point.bucket&&p.value===inspected.point.value))?inspected:null;
  return <>
    {prepared.filter(set=>set.remote.error).map(set=><p role="status" className="data-message" key={set.label}>{set.label}: {set.remote.error}{set.remote.data?' Showing last recorded history.':''}</p>)}
    <div className="history-legend">{prepared.map((set,i)=><span key={set.label} style={{'--series-color':set.color}}><i/>{set.label}{domain==='astronaut'?(bounds[i]?' · shaded personal preflight reference':' · no preflight reference'):''}</span>)}</div>
    <div className="history-plot"><svg viewBox={`0 0 ${plotWidth} ${daily?265:245}`} style={daily?{minWidth:plotWidth}:undefined} aria-label={`Recorded ${secondary?'systolic and diastolic blood pressure':'measurement'} history in ${unit}`}>
      <text x="62" y="12" className="axis-label">{unit}</text>
      {[0,1,2,3,4].map(i=>{const value=low+(high-low)*i/4;return <g key={i}><line x1="62" x2={plotRight} y1={y(value)} y2={y(value)} className="history-grid"/><text x="54" y={y(value)+4} textAnchor="end" className="axis-label">{formatValue(value)}</text></g>})}
      {prepared.map((set,i)=><g key={set.label}>
        {bounds[i]&&<g><rect x="62" width={plotSpan} y={y(bounds[i][1])} height={Math.max(1,y(bounds[i][0])-y(bounds[i][1]))} fill={set.color} opacity=".1"/><line x1="62" x2={plotRight} y1={y(bounds[i][0])} y2={y(bounds[i][0])} stroke={set.color} strokeDasharray="5 4"/><line x1="62" x2={plotRight} y1={y(bounds[i][1])} y2={y(bounds[i][1])} stroke={set.color} strokeDasharray="5 4"/></g>}
        {set.segments.map((segment,j)=><polyline key={j} points={segment.map(p=>`${x(p.bucket)},${y(p.value)}`).join(' ')} fill="none" stroke={set.color} strokeWidth="2"/>)}
        {set.segments.flat().map(point=><g key={point.bucket}><circle cx={x(point.bucket)} cy={y(point.value)} r="3" fill={set.color}/><circle className="history-point" cx={x(point.bucket)} cy={y(point.value)} r="8" fill="transparent" tabIndex="0" role="button" aria-label={`${set.label}: ${formatValue(point.value)} ${unit}, ${pointLabel(point.bucket)}, ${point.count} observations`} onMouseEnter={()=>setInspected({label:set.label,point})} onFocus={()=>setInspected({label:set.label,point})} onClick={()=>setInspected({label:set.label,point})} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();setInspected({label:set.label,point})}}}><title>{set.label}: {formatValue(point.value)} {unit} · {pointLabel(point.bucket)}</title></circle></g>)}
      </g>)}
      {daily?dayTicks.map(tick=>{const bucket=new Date(tick).toISOString();const label=sleepDayLabel(bucket,missionStartedAt);const [day,date]=label.includes(' · ')?label.split(' · '):['',label];return <g key={tick}><line x1={x(bucket)} x2={x(bucket)} y1="200" y2="205" className="history-grid"/><text x={x(bucket)} y="222" textAnchor={tick===start?'start':tick===end?'end':'middle'} className="axis-label"><tspan x={x(bucket)}>{day}</tspan><tspan x={x(bucket)} dy="18">{date.replace(/, \d{4}$/,'')}</tspan></text></g>}):[0,.5,1].map(ratio=><g key={ratio}><line x1={62+ratio*plotSpan} x2={62+ratio*plotSpan} y1="200" y2="205" className="history-grid"/><text x={62+ratio*plotSpan} y="222" textAnchor={ratio===0?'start':ratio===1?'end':'middle'} className="axis-label">{new Date(start+(end-start)*ratio).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',timeZone:'UTC'})}</text></g>)}<text x={plotRight} y={daily?260:240} textAnchor="end" className="axis-label">{daily?"Mission day · Date (UTC)":"Mission time · UTC"}</text>
    </svg></div>
    <div className="chart-inspection" role="status">{active?<><strong>{active.label}: {formatValue(active.point.value)} {unit}</strong><span>{pointLabel(active.point.bucket)} · {active.point.count} observations in bucket</span></>:<span>Hover, tap, or focus a point to inspect its recorded aggregate.</span>}</div>
    <p className={compact?'outlook-disclaimer':'data-message'}>{points.reduce((sum,p)=>sum+p.count,0).toLocaleString()} stored observations · {series.data?.aggregation||secondary?.data?.aggregation} per {daily?'day':(series.data?.window||secondary?.data?.window)==='24h'?'hour':'day'}. Gaps indicate missing time buckets; lines do not bridge them.</p>
    <details className="history-values"><summary>{domain==='cabin'?'Recorded habitat values':'Recorded values and personal references'}</summary>{prepared.map((set,i)=><div key={set.label}><h4>{set.label}</h4>{domain==='astronaut'&&<p>{bounds[i]?`Preflight reference: ${formatValue(bounds[i][0])}–${formatValue(bounds[i][1])} ${unit}`:'No preflight reference available.'}</p>}{set.segments.length?<table><thead><tr><th>{daily?'Mission day / Date (UTC)':'Bucket (UTC)'}</th><th>Value ({unit})</th><th>Count</th></tr></thead><tbody>{set.segments.flat().map(p=><tr key={p.bucket}><td>{pointLabel(p.bucket)}</td><td>{formatValue(p.value)}</td><td>{p.count}</td></tr>)}</tbody></table>:<p>No recorded measurements for this component.</p>}</div>)}</details>
  </>;
}
export function SeriesPanel({member,metric,habitat,domain='astronaut',defaultWindow='7d',compact=false}){
  const daily=metric==='sleep_duration';
  const [window,setWindow]=useState(daily&&defaultWindow==='24h'?'7d':defaultWindow);
  const params={runId:member?.runId||habitat?.runId,astronautId:domain==='astronaut'?member?.id:null,
    habitatId:domain==='cabin'?habitat?.habitat_id:null,zoneId:domain==='cabin'?habitat?.zone_id:null,domain,window};
  const series=useSeries({...params,metric});
  const bp=metric==='systolic_blood_pressure'&&domain==='astronaut';
  const diastolic=useSeries({...params,metric:bp?'diastolic_blood_pressure':null});
  return <div className="series-panel"><div className="segmented chart-switch">{(daily?[['7d','7 days'],['30d','30 days']]:[['24h','24 hours'],['7d','7 days'],['30d','30 days']]).map(([key,label])=><button key={key} aria-pressed={window===key} className={window===key?'chosen':''} onClick={()=>setWindow(key)}>{label}</button>)}</div><HistoryChart key={`${params.runId}:${params.astronautId}:${params.habitatId}:${params.zoneId}:${metric}:${window}`} series={series} domain={domain} missionStartedAt={member?.missionStartedAt} metric={metric} secondary={bp?diastolic:null} baseline={member?.baselines?.[metric]} secondaryBaseline={member?.baselines?.diastolic_blood_pressure} compact={compact}/></div>;
}
