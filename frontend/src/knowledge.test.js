import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {searchReferences} from './referenceSearch.js';
import {chapters} from './biologyContent.js';

const bibliography=JSON.parse(readFileSync(new URL('./references.json',import.meta.url),'utf8'));
const atlas=JSON.parse(readFileSync(new URL('./measurementAtlas.json',import.meta.url),'utf8'));

test('supplied bibliography preserves retained entries, category and explicitly missing URL',()=>{
  assert.equal(bibliography.references.length,139);
  assert.equal(bibliography.groups.length,7);
  assert.equal(new Set(bibliography.references.map(ref=>ref.id)).size,139);
  const groups=new Set(bibliography.groups.map(g=>g.id));
  for(const ref of bibliography.references){
    assert.ok(groups.has(ref.groupId));assert.ok(ref.title.length>4);assert.ok(ref.citation.length>10);
    if(ref.url)assert.ok(['https:','http:'].includes(new URL(ref.url).protocol));
  }
  assert.deepEqual(bibliography.references.filter(ref=>!ref.url).map(ref=>ref.id),['ref-059']);
  assert.ok(existsSync(new URL('../public/downloads/References.docx',import.meta.url)));
});
test('reference search combines author, study ID and category filters without mutating the library',()=>{
  assert.equal(searchReferences(bibliography.references,'Trudel').length,1);
  assert.equal(searchReferences(bibliography.references,'OSD-51','group-3').length,1);
  assert.equal(searchReferences(bibliography.references,'OSD-51','group-1').length,0);
  assert.ok(searchReferences(bibliography.references,'clement','group-2').length>0);
  assert.equal(searchReferences(bibliography.references,'unlikely-reference-query').length,0);
  assert.equal(searchReferences(bibliography.references,'','all').length,139);
});
test('every biology citation and atlas topic resolves, and all configured measurements have explanations',()=>{
  const refs=new Set(bibliography.references.map(ref=>ref.id)),sections=new Set(chapters.map(c=>c.id));
  for(const chapter of chapters)for(const id of chapter.refs)assert.ok(refs.has(id),id);
  assert.equal(atlas.length,87);
  assert.equal(new Set(atlas.map(record=>record.code)).size,87);
  for(const record of atlas){assert.ok(sections.has(record.chapter),record.code);assert.ok(record.biology.length>35,record.code)}
  const extra=JSON.parse(readFileSync(new URL('../../backend/bitorbit/core/ingestion/additional_metrics.json',import.meta.url),'utf8'));
  for(const code of Object.keys(extra).filter(code=>code!=='ferritin'))assert.ok(atlas.some(record=>record.code===code),code);
});
test('documentation and resources render with working navigation, source anchors and source download',async()=>{
  const server=await createServer({server:{middlewareMode:true},appType:'custom'});
  try{
    const {default:Documentation}=await server.ssrLoadModule('/src/DocumentationPage.jsx');
    const html=renderToStaticMarkup(React.createElement(Documentation));
    assert.match(html,/The biology behind/);assert.match(html,/87 measurement types/);
    assert.match(html,/href="\/resources#ref-007"/);
    assert.match(html,/id="measurement-atlas"/);assert.match(html,/id="glossary"/);
    assert.match(html,/href="\/documentation" aria-current="page"/);
    const {default:Resources}=await server.ssrLoadModule('/src/ResourcesPage.jsx');
    const resources=renderToStaticMarkup(React.createElement(Resources));
    assert.match(resources,/139 of 139 references/);
    assert.match(resources,/No URL was supplied for this entry/);
    assert.match(resources,/href="\/downloads\/References.docx" download/);
    assert.equal((resources.match(/class="reference-entry"/g)||[]).length,139);
    assert.match(resources,/id="ref-139"/);
    assert.match(resources,/href="\/resources" aria-current="page"/);
  }finally{await server.close()}
});
