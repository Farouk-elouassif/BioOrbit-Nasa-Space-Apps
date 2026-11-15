import test from 'node:test';
import assert from 'node:assert/strict';
import {adaptCrew,baselineText,cabinReadings,formatValue,hasMeasurement} from './data.js';
import {apiUrl,readJSON,postJSON} from './api.js';

test('missing values stay missing, zero and boolean false are preserved',()=>{
 assert.equal(formatValue(null),'—');assert.equal(formatValue(undefined),'—');
 assert.equal(formatValue(0),'0.00');assert.equal(formatValue(false),'No');
 const readings=cabinReadings({measurements:{co2_partial_pressure:{value:0,unit:'mmHg'}}});
 assert.equal(readings[0].value,0);assert.equal(readings[1].value,null);
});
test('crew adapter uses actual identifiers and values without fake roster entries',()=>{
 const member=adaptCrew({id:'AST_017',name:'AST_017',activity:'sleeping',measurements:{heart_rate:{value:62,freshness:'current'},
   systolic_blood_pressure:{value:110},diastolic_blood_pressure:{value:72}},heart_rate_history:[{value:61},{value:62}]},{id:'run',observation_time:'2026-11-14T00:00:00Z'});
 assert.equal(member.id,'AST_017');assert.equal(member.hr,62);assert.equal(member.bp,'110.00/72.00');
 assert.equal(member.sleep,null);assert.deepEqual(member.wave,[61,62]);assert.equal(member.runId,'run');
 assert.equal(baselineText(member,'hr'),'No preflight baseline available');
});
test('blood pressure does not fabricate a missing half',()=>{
 const member=adaptCrew({id:'AST_001',name:'Crew',measurements:{systolic_blood_pressure:{value:110}}},{id:'run'});
 assert.equal(member.bp,'110.00/—');
});
test('query parameters are encoded and omitted when empty',()=>{
 assert.equal(apiUrl('dashboard',{run_id:'run / 1',habitat_id:''}),'/api/v1/dashboard?run_id=run+%2F+1');
});
test('HTTP failures propagate instead of falling back to demonstration data',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async()=>({ok:false,status:503,json:async()=>({message:'Storage unavailable'})});
  await assert.rejects(readJSON('/api/v1/dashboard'),/Storage unavailable/);
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({crew:[]})});
  assert.deepEqual(await readJSON('/api/v1/dashboard'),{crew:[]});
 } finally {globalThis.fetch=original;}
});

test('write failures preserve HTTP status instead of hiding a missing backend endpoint',async()=>{
 const originalFetch=globalThis.fetch;
 const originalDocument=Object.getOwnPropertyDescriptor(globalThis,'document');
 try{
  Object.defineProperty(globalThis,'document',{configurable:true,value:{cookie:'csrftoken=test-token'}});
  for(const status of [404,403,500]){
   globalThis.fetch=async()=>({ok:false,status,json:async()=>{throw new SyntaxError('HTML error page')}});
   await assert.rejects(postJSON('check-ins',{id:'report'}),error=>error.status===status&&error.message.includes(String(status)));
  }
 }finally{
  globalThis.fetch=originalFetch;
  if(originalDocument)Object.defineProperty(globalThis,'document',originalDocument);
  else delete globalThis.document;
 }
});

test('measurement visibility keeps zero, overdue and partial blood pressure while hiding missing values',()=>{
 const member={measurements:{mood:{value:0},heart_rate:{value:65,freshness:'overdue'},diastolic_blood_pressure:{value:70},body_temperature:{value:null},sleep_duration:{value:NaN}}};
 assert.equal(hasMeasurement(member,'mood'),true);
 assert.equal(hasMeasurement(member,'hr'),true);
 assert.equal(hasMeasurement(member,'bp'),true);
 assert.equal(hasMeasurement(member,'temp'),false);
 assert.equal(hasMeasurement(member,'sleep'),false);
 assert.equal(hasMeasurement(member,'stress'),false);
});
