import React,{useState} from 'react';
import {useSeries} from './api.js';
import {timeLabel,formatValue} from './data.js';

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
export function HistoryChart({series,compact=false}){
  if(series.loading&&!series.data)return <p className="data-message">Loading recorded history…</p>;
  if(series.error)return <p role="status" className="data-message">{series.error}</p>;
  const points=series.data?.points||[];
  if(!points.length)return <p className="data-message">No recorded measurements in this time window.</p>;
  const low=Math.min(...points.map(p=>p.value)),high=Math.max(...points.map(p=>p.value));
  return <><div className="recorded-chart"><div className="chart-range"><span>{formatValue(high,2)}</span><span>{formatValue(low,2)}</span></div><Spark data={points.map(p=>p.value)} times={points.map(p=>p.bucket)} color="#85a3c8" large/></div>
    <div className="chart-endpoints"><span>{timeLabel(points[0].bucket)}</span><span>{timeLabel(points.at(-1).bucket)}</span></div>
    <p className={compact?'outlook-disclaimer':'data-message'}>{points.reduce((sum,p)=>sum+p.count,0).toLocaleString()} stored observations · {series.data.aggregation} per {series.data.window==='24h'?'hour':'day'} · {series.data.unit}. Recorded mission history.</p></>;
}
export function SeriesPanel({member,metric,habitat,domain='astronaut',defaultWindow='7d',compact=false}){
  const [window,setWindow]=useState(defaultWindow);
  const series=useSeries({runId:member?.runId||habitat?.runId,metric,astronautId:domain==='astronaut'?member?.id:null,
    habitatId:domain==='cabin'?habitat?.habitat_id:null,zoneId:domain==='cabin'?habitat?.zone_id:null,domain,window});
  return <div className="series-panel"><div className="segmented chart-switch">{[['24h','24 hours'],['7d','7 days'],['30d','30 days']].map(([key,label])=><button key={key} className={window===key?'chosen':''} onClick={()=>setWindow(key)}>{label}</button>)}</div><HistoryChart series={series} compact={compact}/></div>;
}
