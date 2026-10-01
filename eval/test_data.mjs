import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readJson} from '../dist/data.mjs';

const html='<!doctype html><html><body>Homepage fallback</body></html>';
const optional={optional:true,label:'Saved evaluation report'};

test('missing report served as a successful HTML homepage is an empty state',async()=>{
  assert.equal(await readJson(new Response(html,{headers:{'Content-Type':'text/html'}}),optional),null);
  assert.equal(await readJson(new Response(html),optional),null);
});
test('404 and 204 reports are absent',async()=>{
  assert.equal(await readJson(new Response(html,{status:404}),optional),null);
  assert.equal(await readJson(new Response(null,{status:204}),optional),null);
});
test('a real saved report is parsed',async()=>{
  const report={run_id:'test-only',results:[]};
  assert.deepEqual(await readJson(new Response(JSON.stringify(report),{headers:{'Content-Type':'application/json'}}),optional),report);
});
test('corrupt JSON and server failures are not treated as missing results',async()=>{
  await assert.rejects(readJson(new Response('{broken'),optional),/invalid JSON/);
  await assert.rejects(readJson(new Response(html,{status:500}),optional),/HTTP 500/);
});
test('required manifest served as HTML reports a readable error',async()=>{
  await assert.rejects(readJson(new Response(html),{label:'Evaluation manifest'}),/returned a webpage instead of JSON/);
});
