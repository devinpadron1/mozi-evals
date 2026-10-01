import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
await build({entryPoints:[new URL('./vendor/src/responses.ts',import.meta.url).pathname],outfile:new URL('./build/transport.mjs',import.meta.url).pathname,bundle:true,platform:'node',format:'esm',packages:'external'});
const {streamResponse}=await import('./build/transport.mjs');
const completed={type:'response.completed',response:{status:'completed',model:'test-model',id:'test-id',usage:{output_tokens:1}}};
function stream(events){return new Response(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join(''),{headers:{'content-type':'text/event-stream'}});}
test('streams structured requests with mandatory controls and preserves terminal metadata',async()=>{
  let body;
  const original=globalThis.fetch;
  globalThis.fetch=async(url,options)=>{assert.equal(url,'https://api.openai.com/v1/responses');body=JSON.parse(options.body);return stream([{type:'response.output_text.delta',delta:'{}'},completed]);};
  try {
    const result=await streamResponse('synthetic-test-token',{model:'test-model',input:'test-only',parameters:{temperature:0,reasoning:{effort:'none'},max_output_tokens:50},text:{format:{type:'json_schema',name:'Test',schema:{type:'object'}}}},new AbortController().signal);
    assert.equal(body.store,false);assert.equal(body.stream,true);assert.equal(body.temperature,0);
    assert.equal(body.text.format.type,'json_schema');assert.equal(result.text,'{}');
    assert.deepEqual(result.response,completed.response);
  }finally{globalThis.fetch=original;}
});
for(const [name,event,code] of [
  ['incomplete',{type:'response.incomplete'},'response_incomplete'],
  ['usage limit',{type:'response.failed',response:{error:{code:'subscription_sharing_usage_limit_exceeded',message:'Test-only'}}},'subscription_sharing_usage_limit_exceeded'],
  ['missing terminal metadata',{type:'response.completed',response:{status:'completed'}},'invalid_stream'],
  ['interrupted',{type:'response.output_text.delta',delta:'partial'},'stream_interrupted'],
])test('rejects '+name,async()=>{
  const original=globalThis.fetch;globalThis.fetch=async()=>stream([event]);
  try{await assert.rejects(streamResponse('synthetic-test-token',{model:'test-model',input:'test-only'},new AbortController().signal),error=>error.code===code);}
  finally{globalThis.fetch=original;}
});
