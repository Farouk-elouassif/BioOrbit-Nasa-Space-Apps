import catalogue from './measurementCatalogue.json' with {type:'json'};
import {highestAlert} from './data.js';

export const CATEGORIES=[
  {id:'body',label:'Body',description:'Vitals, blood tests, physical systems and exposure.'},
  {id:'mind',label:'Mind',description:'Mood, stress, cognition and mental workload.'},
  {id:'sleep',label:'Sleep',description:'Sleep duration and circadian timing.'},
  {id:'habitat',label:'Habitat',description:'Shared air, environment and supplies.'},
];
export const hasValue=reading=>reading?.value!==null&&reading?.value!==undefined;
export function categoryReadings(category,member,habitat){
  // A habitat selected elsewhere must never be presented as this crew's cabin.
  const matches=Boolean(habitat&&member?.habitat_id&&habitat.habitat_id===member.habitat_id);
  return catalogue.filter(meta=>meta.category===category).map(meta=>{
    const source=meta.domain==='cabin'?(matches?habitat?.measurements:null):member?.measurements;
    let reading=source?.[meta.metric];
    let baselineOnly=false;
    if(!reading&&meta.group==='Preflight reference'&&member?.baselines?.[meta.metric]){
      reading={value:member.baselines[meta.metric].mean,unit:meta.unit};baselineOnly=true;
    }
    const alerts=meta.domain==='cabin'?(matches?habitat?.alerts:[]):member?.alerts;
    return {...meta,reading,baselineOnly,alert:highestAlert((alerts||[]).filter(a=>a.metric_id===meta.metric))};
  });
}
export function readableLabel(value){
  const labels={ph:'pH',co_ppm:'CO (ppm)',hcn_ppm:'HCN (ppm)',hcl_ppm:'HCl (ppm)',hf_ppm:'HF (ppm)',
    pressure_kpa:'Pressure (kPa)',o2_partial_pressure_mmhg:'Oxygen (mmHg)',co2_partial_pressure_mmhg:'CO₂ (mmHg)',
    heart_rate_bpm:'Heart rate (bpm)',metabolic_rate_watts:'Metabolic rate (W)',noaa_s_level:'NOAA S-level',
    projected_event_dose_msv:'Projected dose (mSv)',photo_available:'Photograph available'};
  return labels[value]||String(value).replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase());
}
export function readableValue(value){
  if(value===null||value===undefined)return 'Awaiting reading';
  if(typeof value==='boolean')return value?'Yes':'No';
  if(typeof value==='number')return Number.isFinite(value)?value.toFixed(2):'Unavailable';
  if(typeof value==='string')return readableLabel(value);
  return null;
}
