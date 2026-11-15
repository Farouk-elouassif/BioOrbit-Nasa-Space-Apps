import React from 'react';
import {Wind} from 'lucide-react';
import {SeriesPanel} from './charts.jsx';
import {formatValue,timeLabel} from './data.js';

export default function HabitatMetric({entry,habitat}) {
  return <article className="environment-reading">
    <Wind size={23}/>
    <span className="tiny-index">{entry.label}</span>
    <h3>{entry.name}</h3>
    <strong>{formatValue(entry.value,entry.metric==='dust_concentration'?3:2)}<small>{entry.unit}</small></strong>
    <p>{entry.value===null?'No measurement available':`${entry.freshness==='overdue'?'Overdue · ':''}${timeLabel(entry.measured_at)}`}</p>
    <SeriesPanel domain="cabin" habitat={habitat} metric={entry.metric} defaultWindow="24h" compact/>
  </article>;
}
