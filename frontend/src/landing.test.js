import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('landing page provides dashboard entry, research references and honest simulation context',async()=>{
  const server=await createServer({server:{middlewareMode:true},appType:'custom'});
  try{
    const {default:LandingPage}=await server.ssrLoadModule('/src/LandingPage.jsx');
    const html=renderToStaticMarkup(React.createElement(LandingPage));
    assert.match(html,/Health monitoring/);
    assert.match(html,/for astronauts/);
    assert.match(html,/Simulated mission data/);
    assert.equal((html.match(/href="\/dashboard"/g)||[]).length,3);
    for(const url of ['https://www.nasa.gov/hrp/','https://www.nasa.gov/hrp/hazards/','https://humanresearchroadmap.nasa.gov/evidence/'])assert.ok(html.includes(`href="${url}"`));
    assert.match(html,/Not affiliated with or endorsed by NASA/);
    assert.match(html,/aria-label="Explore human systems"/);
    assert.equal((html.match(/aria-pressed="true"/g)||[]).length,1);
    assert.match(html,/href="#approach"/);
    assert.match(html,/id="research"/);
    const {default:Dashboard}=await server.ssrLoadModule('/src/Dashboard.jsx');
    const dashboard=renderToStaticMarkup(React.createElement(Dashboard));
    assert.match(dashboard,/Crew overview/);
    assert.match(dashboard,/Connecting to your mission/);
    assert.match(dashboard,/href="\/" aria-label="BioOrbit home"/);
  }finally{await server.close()}
});
