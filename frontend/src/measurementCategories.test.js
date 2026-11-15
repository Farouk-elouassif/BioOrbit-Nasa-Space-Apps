import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import catalogue from './measurementCatalogue.json' with {type:'json'};
import {CATEGORIES,categoryReadings,readableValue} from './measurementCategories.js';

const reading=value=>({value,measured_at:'2026-11-15T12:00:00Z',freshness:'current'});
const member={id:'AST_001',name:'Crew 01',habitat_id:'HAB_1',zone_id:'CABIN_MAIN',shift:'Resting',alerts:[],measurements:{heart_rate:reading(68),mood:reading(8),sleep_duration:reading(0),jugular_flow:reading('normal'),urine_sg_ph:reading({specific_gravity:1.015,ph:6.5})}};
const habitat={habitat_id:'HAB_1',zone_id:'CABIN_MAIN',name:'Main habitat',measurements:{co2_partial_pressure:reading(2.1),is_solar_storm:reading(false)},alerts:[]};

test('every catalogue measurement belongs to exactly one requested category',()=>{
  assert.equal(catalogue.length,88);
  assert.equal(new Set(catalogue.map(row=>row.metric)).size,88);
  assert.ok(catalogue.every(row=>CATEGORIES.some(category=>category.id===row.category)));
  for(const [category,metric] of [['body','heart_rate'],['mind','mood'],['sleep','sleep_duration'],['habitat','co2_partial_pressure']]){
    assert.ok(categoryReadings(category,member,habitat).some(entry=>entry.metric===metric&&entry.reading));
  }
});
test('habitat values never come from another astronaut habitat',()=>{
  assert.ok(categoryReadings('habitat',member,{...habitat,habitat_id:'HAB_OTHER'}).every(entry=>!entry.reading));
  assert.ok(categoryReadings('habitat',member,null).every(entry=>!entry.reading));
  assert.equal(readableValue(false),'No');assert.equal(readableValue(0),'0.00');
  assert.equal(readableValue('normal'),'Normal');assert.equal(readableValue(null),'Awaiting reading');
});
test('all measurement cards remain visible without category tabs',async()=>{
  const server=await createServer({server:{middlewareMode:true},appType:'custom'});
  try{
    const {default:CrewSnapshot}=await server.ssrLoadModule('/src/CrewSnapshot.jsx');
    const render=(extra={})=>renderToStaticMarkup(React.createElement(CrewSnapshot,{member,habitat,...extra}));
    const html=render();
    assert.doesNotMatch(html,/role="tab"|role="tablist"|role="tabpanel"|measurement-categories/);
    assert.equal((html.match(/<article /g)||[]).length,88);
    for(const category of CATEGORIES)assert.match(html,new RegExp(`${category.label} measurements`));
    for(const value of ['68.00','8.00','0.00','2.10','6.50'])assert.ok(html.includes(value));
    assert.match(html,/Specific gravity/);assert.match(html,/Normal/);assert.match(html,/>No</);
    assert.match(html,/Shared habitat: Main habitat/);assert.doesNotMatch(html,/\[object Object\]/);
    const missing=render({habitat:{...habitat,habitat_id:'WRONG'}});
    assert.match(missing,/No habitat readings received yet/);assert.doesNotMatch(missing,/2\.10/);
    const empty=render({member:{...member,measurements:{}}});
    assert.match(empty,/Awaiting reading/);assert.match(empty,/No body readings received yet/);
  }finally{await server.close();}
});
