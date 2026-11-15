// Pure presentation helpers shared with the UI tests.
export function telemetryStatus(receivedAt,now=Date.now()) {
  const received=Date.parse(receivedAt);
  if(!Number.isFinite(received))return {state:'unknown',label:'No telemetry receipt recorded'};
  const seconds=Math.max(0,Math.floor((now-received)/1000));
  return seconds>30
    ?{state:'inactive',label:`No recent telemetry · ${seconds}s since receipt`}
    :{state:'recent',label:`Telemetry received ${seconds}s ago`};
}
export function scopedCrew(crew,habitatId,zoneId) {
  return habitatId?crew.filter(person=>person.habitat_id===habitatId&&(!zoneId||person.zone_id===zoneId)):[];
}
export function splitHistory(points,window) {
  const interval=window==='24h'?3600000:86400000;
  const segments=[];
  let segment=[];
  for(const point of points){
    if(typeof point.value!=='number'||!Number.isFinite(point.value)||!Number.isFinite(Date.parse(point.bucket))){
      if(segment.length)segments.push(segment);
      segment=[];continue;
    }
    if(segment.length&&Date.parse(point.bucket)-Date.parse(segment.at(-1).bucket)>interval*1.5){
      segments.push(segment);segment=[];
    }
    segment.push(point);
  }
  if(segment.length)segments.push(segment);
  return segments;
}
export function guidanceSteps(value) {
  if(Array.isArray(value))return value.flatMap(guidanceSteps);
  if(typeof value==='string')return value.split(/(?:^|\s+)\d+\)\s*/).map(s=>s.trim()).filter(Boolean);
  return [];
}
export function humanLabel(value){return value.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
