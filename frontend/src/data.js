export const KEY_METRICS = {
  hr: 'heart_rate', bp: 'systolic_blood_pressure', glucose: 'blood_glucose', temp: 'body_temperature',
  sleep: 'sleep_duration', mood: 'mood', rr: 'respiratory_rate', spo2: 'spo2', stress: 'stress_level',
  fluid: 'fluid_intake', dose: 'mission_cumulative_radiation_dose', radiation: 'personal_radiation_dose_rate',
};
export const FIELD_META = {
  hr: ['Heart rate','bpm',0], bp: ['Blood pressure','mmHg',0], glucose:['Blood glucose','mg/dL',1],
  temp:['Temperature','°C',2],sleep:['Sleep','hours',1],mood:['Mood','/10',1],rr:['Breathing rate','breaths/min',1],
  spo2:['Oxygen saturation','%',1],stress:['Stress','/10',1],fluid:['Fluid intake','L',2],
  dose:['Mission dose','mSv',3],radiation:['Personal radiation','mSv/day',3],
};
export const CABIN_META = [
  {metric:'co2_partial_pressure',name:'Carbon dioxide',label:'CO₂',unit:'mmHg'},
  {metric:'o2_partial_pressure',name:'Oxygen partial pressure',label:'O₂',unit:'mmHg'},
  {metric:'total_cabin_pressure',name:'Cabin pressure',label:'PRESSURE',unit:'kPa'},
  {metric:'cabin_temperature',name:'Cabin temperature',label:'TEMP',unit:'°C'},
  {metric:'relative_humidity',name:'Relative humidity',label:'HUMIDITY',unit:'%'},
  {metric:'noise_level',name:'Noise',label:'NOISE',unit:'dBA'},
  {metric:'dust_concentration',name:'Dust',label:'DUST',unit:'mg/m³'},
  {metric:'radiation_level',name:'Cabin radiation',label:'RADIATION',unit:'mSv/day'},
];
export function formatValue(value,digits=1) {
  if (typeof value==='boolean') return value?'Yes':'No';
  return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits).replace(/\.0+$/,''):'—';
}
export function timeLabel(value) {
  if(!value)return 'No observation';
  const date=new Date(value);
  return Number.isNaN(date.getTime())?'Timestamp unavailable':date.toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC';
}
export function baselineText(member,key) {
  const one=member.baselines?.[KEY_METRICS[key]];
  if(!one)return 'No preflight baseline available';
  const digits=FIELD_META[key]?.[2]??1;
  if(key==='bp'){
    const diastolic=member.baselines?.diastolic_blood_pressure;
    return `Preflight ${formatValue(one.mean,0)} / ${diastolic?formatValue(diastolic.mean,0):'—'} mmHg · mean`;
  }
  return `Preflight ${formatValue(one.min,digits)}–${formatValue(one.max,digits)} ${FIELD_META[key]?.[1]||''}`;
}
export function adaptCrew(person,run) {
  const readings=person.measurements||{};
  const values=Object.fromEntries(Object.entries(KEY_METRICS).map(([key,metric])=>[key,readings[metric]?.value??null]));
  const systolic=readings.systolic_blood_pressure?.value,diastolic=readings.diastolic_blood_pressure?.value;
  values.bp=systolic!=null||diastolic!=null?`${formatValue(systolic,0)}/${formatValue(diastolic,0)}`:null;
  const colors=['#eaa586','#a4c6aa','#b9b0d7','#8db5ce'];
  const number=(person.id.match(/\d+$/)||[])[0];
  const overdue=Object.values(readings).filter(r=>r.freshness==='overdue').length;
  return {...person,...values,runId:run.id,observedAt:run.observation_time,
    initials:number?number.slice(-2).padStart(2,'0'):person.name.split(' ').map(p=>p[0]).join('').slice(0,2),
    color:colors[[...person.id].reduce((sum,c)=>sum+c.charCodeAt(0),0)%colors.length],
    role:'CREW MEMBER',location:[person.habitat_id,person.zone_id].filter(Boolean).join(' / ')||'Location unavailable',
    shift:person.activity?person.activity.replaceAll('_',' '):'No activity recorded',
    status:!Object.keys(readings).length?'Awaiting telemetry':overdue?`${overdue} overdue`:'Data current',
    overdue,wave:(person.heart_rate_history||[]).map(p=>p.value).filter(v=>typeof v==='number'&&Number.isFinite(v)),
  };
}
export function cabinReadings(cabin) {
  return CABIN_META.map(meta=>({...meta,...(cabin?.measurements?.[meta.metric]||{}),
    value:cabin?.measurements?.[meta.metric]?.value??null}));
}
export function lastObservation(member,key) {return member?.measurements?.[KEY_METRICS[key]];}
