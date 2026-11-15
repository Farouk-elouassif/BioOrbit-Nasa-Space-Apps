import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {telemetryStatus,scopedCrew,splitHistory,guidanceSteps,sleepDayLabel} from './viewData.js';

const at='2026-11-15T10:00:00Z';
test('telemetry inactivity uses receipt wall time, independent of simulated time',()=>{
  assert.equal(telemetryStatus(at,Date.parse(at)+30000).state,'recent');
  assert.equal(telemetryStatus(at,Date.parse(at)+31000).state,'inactive');
  assert.equal(telemetryStatus(null).state,'unknown');
  assert.equal(telemetryStatus('invalid').state,'unknown');
  assert.match(telemetryStatus('2027-01-01',Date.parse(at)).label,/0s/);
});
test('habitat roster excludes other habitats and zones',()=>{
  const crew=[{id:'a',habitat_id:'h1',zone_id:'z1'},{id:'b',habitat_id:'h1',zone_id:'z2'},{id:'c',habitat_id:'h2',zone_id:'z1'}];
  assert.deepEqual(scopedCrew(crew,'h1','z1').map(p=>p.id),['a']);
  assert.equal(scopedCrew(crew,'h1').length,2);
  assert.deepEqual(scopedCrew(crew,null),[]);
});
test('history segments preserve zero and break across missing hours, days, and invalid observations',()=>{
  const point=(bucket,value)=>({bucket,value});
  const hours=[point(at,0),point('2026-11-15T11:00:00Z',2),point('2026-11-15T13:00:00Z',3)];
  assert.deepEqual(splitHistory(hours,'24h').map(s=>s.length),[2,1]);
  assert.deepEqual(splitHistory([hours[0],point('2026-11-15T11:00:00Z',null),hours[2]],'24h').map(s=>s.length),[1,1]);
  const days=[point(at,1),point('2026-11-16T10:00:00Z',2),point('2026-11-18T10:00:00Z',3)];
  assert.deepEqual(splitHistory(days,'7d').map(s=>s.length),[2,1]);
  assert.deepEqual(splitHistory(days,'30d').map(s=>s.length),[2,1]);
});
test('sleep dates use UTC mission days rather than hourly labels or local timezone',()=>{
  assert.equal(sleepDayLabel('2026-11-14T00:00:00Z','2026-11-14T18:00:00Z'),'Day 1 · Nov 14, 2026');
  assert.equal(sleepDayLabel('2026-11-15T00:00:00Z','2026-11-14T18:00:00Z'),'Day 2 · Nov 15, 2026');
  assert.equal(sleepDayLabel('2026-11-15T00:00:00Z',null),'Nov 15, 2026');
});
test('guidance preserves workbook steps without JSON formatting',()=>{
  assert.deepEqual(guidanceSteps(['1) Confirm reading. 2) Review activity.','Follow checklist.']),['Confirm reading.','Review activity.','Follow checklist.']);
});
test('rendered decisions and charts expose evidence, dual blood pressure, references and separate gap segments',async()=>{
  const server=await createServer({server:{middlewareMode:true},appType:'custom'});
  try{
    const {default:AlertDetail}=await server.ssrLoadModule('/src/AlertDetail.jsx');
    const {HistoryChart}=await server.ssrLoadModule('/src/charts.jsx');
    const alert={id:1,tier:'caution',title:'Blood pressure',rule_code:'bp_systolic',message:'Recorded rule explanation',evidence:{value:85,components:{score:3}},rule_reference:{condition:'Recorded workbook condition',unit:'mmHg'},actions:['1) Confirm reading. 2) Review context.'],last_observation_at:at,recheck_due_at:at,provenance:{source:'Workbook'}};
    const html=renderToStaticMarkup(React.createElement(AlertDetail,{alert}));
    assert.match(html,/Recorded workbook condition/);
    assert.match(html,/<li>Confirm reading\.<\/li>/);
    assert.match(html,/Observed \(mission time\)/);
    assert.match(html,/<details class="raw-evidence">/);
    assert.match(html,/Recheck deadline/);
    const data={window:'24h',unit:'mmHg',aggregation:'mean',anchor_time:'2026-11-15T13:00:00Z',points:[{bucket:at,value:110,count:1},{bucket:'2026-11-15T13:00:00Z',value:115,count:1}]};
    const chart=renderToStaticMarkup(React.createElement(HistoryChart,{series:{data},secondary:{data:{...data,points:[{bucket:at,value:70,count:1}]}},baseline:{min:105,max:120},secondaryBaseline:{min:65,max:80}}));
    assert.match(chart,/Systolic/);assert.match(chart,/Diastolic/);
    assert.match(chart,/Preflight reference: 105\.00–120\.00 mmHg/);
    assert.match(chart,/Preflight reference: 65\.00–80\.00 mmHg/);
    assert.match(chart,/Systolic: 110\.00 mmHg/);
    assert.equal((chart.match(/<polyline /g)||[]).length,3);
    const cabin=renderToStaticMarkup(React.createElement(HistoryChart,{domain:'cabin',series:{data:{...data,metric:'co2_partial_pressure',unit:'mmHg'}}}));
    assert.match(cabin,/Recorded habitat values/);
    assert.match(cabin,/Co2 Partial Pressure: 110\.00 mmHg/);
    assert.equal((cabin.match(/<polyline /g)||[]).length,2);
    assert.doesNotMatch(cabin,/preflight|personal reference/i);
    const {default:HabitatMetric}=await server.ssrLoadModule('/src/HabitatMetric.jsx');
    const card=renderToStaticMarkup(React.createElement(HabitatMetric,{entry:{metric:'co2_partial_pressure',label:'CO₂',name:'Carbon dioxide',unit:'mmHg',value:2.5,measured_at:at},habitat:{runId:'run',habitat_id:'hab',zone_id:'LAB'}}));
    assert.match(card,/Carbon dioxide/);
    assert.match(card,/24 hours/);assert.match(card,/7 days/);assert.match(card,/30 days/);
    assert.match(card,/Loading recorded history/);
    assert.match(card,/lucide-cloud/);
    const temperature=renderToStaticMarkup(React.createElement(HabitatMetric,{entry:{metric:'cabin_temperature',label:'TEMP',name:'Cabin temperature',unit:'°C',value:31,alert:{id:2,tier:'caution',message:'Recorded temperature alert'}},habitat:{runId:'run',habitat_id:'hab',zone_id:'LAB'},onAlert:()=>{}}));
    assert.match(temperature,/lucide-thermometer/);
    assert.match(temperature,/has-cabin-alert tier-caution/);
    assert.match(temperature,/cabin-alert-badge">Caution/);
    assert.match(temperature,/Recorded temperature alert/);
    assert.match(temperature,/View alert details/);
    assert.doesNotMatch(card,/has-cabin-alert|cabin-alert-badge/);

    const sleep=renderToStaticMarkup(React.createElement(HistoryChart,{metric:'sleep_duration',missionStartedAt:'2026-11-14T00:00:00Z',series:{data:{metric:'sleep_duration',window:'7d',unit:'hours',aggregation:'mean',anchor_time:'2026-11-16T12:00:00Z',points:[{bucket:'2026-11-14T00:00:00Z',value:7,count:1},{bucket:'2026-11-16T00:00:00Z',value:8,count:1}]}}}));
    assert.match(sleep,/Day 1/);assert.match(sleep,/Day 2/);assert.match(sleep,/Day 3/);
    assert.match(sleep,/Nov 14/);assert.match(sleep,/Mission day/);
    assert.match(sleep,/mean per day/);
    assert.equal((sleep.match(/<polyline /g)||[]).length,2);
    const {SeriesPanel}=await server.ssrLoadModule('/src/charts.jsx');
    const sleepPanel=renderToStaticMarkup(React.createElement(SeriesPanel,{metric:'sleep_duration',defaultWindow:'24h',member:{id:'crew',runId:'run'}}));
    assert.doesNotMatch(sleepPanel,/24 hours/);
    assert.match(sleepPanel,/aria-pressed="true"[^>]*>7 days/);
    const {default:BodyModel}=await server.ssrLoadModule('/src/BodyModel.jsx');
    const body=renderToStaticMarkup(React.createElement(BodyModel,{member:{id:'AST_001',name:'Crew',alerts:[],measurements:{heart_rate:{value:65}},hr:65},viewState:{current:null},region:1}));
    assert.match(body,/Heart &amp; circulation/);
    assert.doesNotMatch(body,/aria-label="Eyes"|aria-label="Skin"|Brain &amp; mind/);
    assert.doesNotMatch(body,/No measurement available/);
    assert.match(body,/Crew measurements/);
    assert.equal((body.match(/role="tab"/g)||[]).length,0);
    assert.match(body,/Awaiting reading/);
    const partial=renderToStaticMarkup(React.createElement(HistoryChart,{series:{data},secondary:{data:{...data,points:[]}}}));
    assert.match(partial,/No recorded measurements for this component/);
  }finally{await server.close()}
});
