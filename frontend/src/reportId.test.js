import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createReportId} from './reportId.js';

const uuidV4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
test('uses native UUID generation when available',()=>{
  const id='32dcd8a5-9b73-4b7b-afc1-499c5d217111';
  assert.equal(createReportId({randomUUID(){return id}}),id);
});
test('HTTP-compatible fallback generates distinct valid UUIDs without randomUUID',()=>{
  const provider={getRandomValues(bytes){return webcrypto.getRandomValues(bytes)}};
  const ids=Array.from({length:1000},()=>createReportId(provider));
  assert.ok(ids.every(id=>uuidV4.test(id)));
  assert.equal(new Set(ids).size,ids.length);
});
test('fallback sets version and variant bits and preserves zero padding',()=>{
  assert.equal(createReportId({getRandomValues(bytes){return bytes.fill(0)}}),'00000000-0000-4000-8000-000000000000');
  assert.equal(createReportId({getRandomValues(bytes){return bytes.fill(255)}}),'ffffffff-ffff-4fff-bfff-ffffffffffff');
});
test('missing Web Crypto produces a clear recoverable error',()=>{
  assert.throws(()=>createReportId({}),/Your entries have been kept/);
});
