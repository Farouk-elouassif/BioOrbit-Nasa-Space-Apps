import React from 'react';
import {ArrowUpRight,Cloud,CloudFog,Droplets,Gauge,Radiation,Thermometer,Volume2,Wind} from 'lucide-react';
import {SeriesPanel} from './charts.jsx';
import {formatNumericText,formatValue,tierLabel,timeLabel} from './data.js';

const metricIcons={
  co2_partial_pressure:Cloud,
  o2_partial_pressure:Wind,
  total_cabin_pressure:Gauge,
  cabin_temperature:Thermometer,
  relative_humidity:Droplets,
  noise_level:Volume2,
  dust_concentration:CloudFog,
  radiation_level:Radiation,
};

export default function HabitatMetric({entry,habitat,onAlert}) {
  const Icon=metricIcons[entry.metric]||Gauge;
  const alert=entry.alert;
  return <article className={`environment-reading${alert?` has-cabin-alert tier-${alert.tier}`:''}`}>
    <div className="cabin-metric-heading"><Icon size={25} aria-hidden="true"/>{alert&&<span className="cabin-alert-badge">{tierLabel(alert.tier)}</span>}</div>
    <span className="tiny-index">{entry.label}</span>
    <h3>{entry.name}</h3>
    <strong className="habitat-value">{formatValue(entry.value)}<small>{entry.unit}</small></strong>
    <p>{entry.value===null?'No measurement available':`${entry.freshness==='overdue'?'Overdue · ':''}${timeLabel(entry.measured_at)}`}</p>
    {alert&&<div className="cabin-alert-explanation"><p>{formatNumericText(alert.message)}</p>{onAlert&&<button className="cabin-alert-details" onClick={()=>onAlert(alert)} aria-label={`View ${entry.name} alert details`}>View alert details<ArrowUpRight size={15}/></button>}</div>}
    <SeriesPanel domain="cabin" habitat={habitat} metric={entry.metric} defaultWindow="24h" compact/>
  </article>;
}
