import {readJson} from './data.mjs';
const escape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const human=x=>String(x??'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
const list=items=>`<ul>${(items||[]).map(x=>`<li>${escape(x)}</li>`).join('')}</ul>`;
const link=(url,text)=>`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(text)}</a>`;
const thumbnail=c=>`<img src="${escape(c.source.thumbnail_url)}" alt="${escape(c.source.title)}" loading="lazy" decoding="async">`;
const table=document.querySelector('#evals'),status=document.querySelector('#status'),runButton=document.querySelector('#run');
let manifest,report=null,localRunner=false,busy=false;
const tabs=[...document.querySelectorAll('[role=tab]')];
function selectTab(id,focus=false){
  const selected=tabs.find(t=>t.id===id)||tabs[0];
  for(const tab of tabs){const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;document.getElementById(tab.getAttribute('aria-controls')).hidden=!active;}
  if(focus)selected.focus();
}
for(const tab of tabs){
  tab.onclick=()=>{selectTab(tab.id);history.replaceState(null,'',tab.id==='tab-evaluations'?'#evaluations':'#manifest');};
  tab.onkeydown=e=>{const index=tabs.indexOf(tab);const next={ArrowRight:(index+1)%tabs.length,ArrowLeft:(index+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[e.key];if(next!==undefined){e.preventDefault();tabs[next].click();tabs[next].focus();}};
}
addEventListener('hashchange',()=>selectTab(location.hash==='#evaluations'?'tab-evaluations':'tab-manifest'));
selectTab(location.hash==='#evaluations'?'tab-evaluations':'tab-manifest');
function intake(c){return Object.entries(c.inputs).map(([key,value])=>`<div class="field"><strong>${escape(human(key))}</strong>${Array.isArray(value)?list(value):escape(typeof value==='number'?value.toLocaleString('en-US'):value)}</div>`).join('');}
function reference(c){return `<span class="label">${escape(human(c.reference.constraint))}</span><p>${escape(c.reference.diagnosis)}</p><div class="field"><strong>Next action</strong>${escape(c.reference.action)}</div><details><summary>Alternatives & caveat</summary><div class="field"><strong>Acceptable alternatives</strong>${list(c.reference.acceptable_alternatives)}</div><p class="note">${escape(c.reference.caution)}</p></details>`;}
function renderManifest(){
  document.querySelector('#case-count').textContent=manifest.cases.length;
  document.querySelector('#eval-count').textContent=manifest.cases.length*2;
  document.querySelector('#dataset-meta').textContent=`${manifest.cases.length} cases · Baseline vs. grounded`;
  document.querySelector('#manifest-status').textContent=manifest.reference_status;
  document.querySelector('#criteria').innerHTML=manifest.judgement.criteria.map(c=>`<div class="criterion"><h3>${escape(human(c.id))}<span>${c.method==='llm_judge'?'Model judge':'Exact match'}</span></h3><p>${escape(c.criteria)}</p>${c.anchors?`<div class="anchors">${Object.entries(c.anchors).sort((a,b)=>Number(a[0])-Number(b[0])).map(([score,description])=>`${escape(score)}: ${escape(description)}`).join(' · ')}</div>`:''}</div>`).join('');
  document.querySelector('#cases').innerHTML=manifest.cases.map((c,i)=>`<article class="case" id="case-${escape(c.id)}"><div class="case-media">${link(c.source.url,'').replace('></a>',`>${thumbnail(c)}</a>`)}<div class="video-title">${link(c.source.url,c.source.title)}</div><small>MoreMozi · Source consultation</small></div><div class="case-content"><div class="case-number">CASE ${String(i+1).padStart(2,'0')}</div><h2>${escape(c.name)}</h2><p class="metrics">${escape(c.sector)} · Revenue <b>${escape(c.revenue)}</b> · Goal <b>${escape(c.goal)}</b></p><div class="case-columns"><div><h3>Business input</h3><p>${escape(c.inputs.business)}</p><details><summary>All intake facts & unknowns</summary>${intake(c)}</details></div><div><h3>Consultation reference</h3>${reference(c)}</div></div><details class="source-details"><summary>Source & timestamps</summary><p>Owner input: ${escape(c.source.input_window)}<br>Reference advice: ${escape(c.source.reference_window)}</p><p>${escape(c.source.transcript_source)}</p>${link(c.source.url+'&t='+c.source.reference_seconds+'s','Watch reference segment')}${link(c.source.transcript_url,'Read transcript')}</details></div></article>`).join('');
  document.querySelector('#method').innerHTML=`<p>${escape(manifest.dataset_version)} · ${escape(manifest.prompts.version)}</p><dl><dt>Model</dt><dd>${escape(manifest.model.name)} · Temperature ${escape(manifest.model.temperature)} · ${escape(manifest.model.samples_per_case)} sample per case and prompt</dd><dt>Judge</dt><dd>${escape(manifest.judgement.model)} · Temperature ${escape(manifest.judgement.temperature)}</dd></dl><details><summary>Prompt comparison</summary><dl><dt>Baseline</dt><dd>${escape(manifest.prompts.baseline)}</dd><dt>Grounded</dt><dd>${escape(manifest.prompts.grounded)}</dd></dl></details><details><summary>Framework context supplied to the grounded prompt</summary>${manifest.prompts.framework.map(s=>`<div class="field"><strong>${escape(s.title)}</strong><p>${escape(s.text)}</p>${link(s.url,s.locator)}</div>`).join('')}</details><details><summary>Judge instructions</summary><p>${escape(manifest.judgement.system_prompt)}</p></details>${list(manifest.limitations)}`;
}
function score(r,key){const m=r?.scores?.[key];return m?`${Number(m.score).toFixed(2)}<details><summary>Judgment</summary><div class="reason">${escape(m.reason)}</div></details>`:'<span class="pending">—</span>';}
function output(brief){return `<strong>${escape(human(brief.constraint))}</strong><details class="output"><summary>Full output</summary><p>${escape(brief.diagnosis)}</p><strong>Evidence</strong>${list(brief.evidence)}<strong>Next action</strong><p>${escape(brief.next_action)}</p><strong>Follow-up question</strong><p>${escape(brief.follow_up_question)}</p><strong>Missing information</strong>${list(brief.missing_information)}<strong>Sources</strong><p>${escape(brief.source_ids.join(', ')||'None cited')}</p></details>`;}
function render(){
  table.innerHTML=manifest.cases.flatMap(c=>['baseline','grounded'].map(variant=>{const r=report?.results.find(x=>x.case_id===c.id&&x.variant===variant);return `<tr><td><div class="eval-case">${link(c.source.url,'').replace('></a>',`>${thumbnail(c)}</a>`)}<div><strong>${escape(c.name)}</strong><small>${escape(c.id)}</small><details><summary>Input & source</summary>${intake(c)}${link(c.source.url,'Source video')}</details></div></div></td><td>${human(variant)}</td><td>${escape(human(c.reference.constraint))}<details><summary>Reference</summary>${reference(c)}</details></td><td>${r?output(r.brief):'<span class="pending">Not run</span>'}</td>${['diagnosis_agreement','grounded_advice','missing_information','label_match'].map(k=>`<td>${score(r,k)}</td>`).join('')}<td>${r?Number(r.latency_seconds).toFixed(2)+'s':'<span class="pending">—</span>'}</td></tr>`;})).join('');
  status.textContent=busy?'Running evaluations…':report?`Run ${report.run_id} · ${report.model} · Scores 0–1`:`${manifest.cases.length * 2} evaluations · No completed model run — OpenAI account has no credits remaining.`;
  runButton.disabled=busy;runButton.textContent=busy?'Running…':'Run evals';
}
async function loadReport(){
  const response=await fetch('report.json?v='+Date.now());
  const value=await readJson(response,{optional:true,label:'Saved evaluation report'});
  if(value===null)return;
  const pairs=manifest.cases.flatMap(c=>['baseline','grounded'].map(v=>c.id+':'+v));
  if(value.dataset_version!==manifest.dataset_version||value.prompt_version!==manifest.prompts.version||!Array.isArray(value.results)||value.results.length!==pairs.length||new Set(value.results.map(r=>r.case_id+':'+r.variant)).size!==pairs.length||value.results.some(r=>!pairs.includes(r.case_id+':'+r.variant)))throw new Error('Saved report does not match this manifest. Run evaluations again.');
  report=value;
}
async function run(){if(busy)return;busy=true;render();try{const response=await fetch('/api/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok)throw new Error((await readJson(response,{label:'Evaluation runner'})).error||'Could not start evaluation');while(true){await new Promise(resolve=>setTimeout(resolve,1800));const response=await fetch('/api/status');if(!response.ok)throw new Error('Lost connection to local runner');const job=await readJson(response,{label:'Evaluation status'});if(job.status==='failed')throw new Error(job.error);if(job.status==='completed')break;}await loadReport();if(!report)throw new Error('The evaluation finished without a saved report.');busy=false;render();}catch(e){busy=false;render();status.textContent=e.message;}}
try{
  const response=await fetch('manifest.json');manifest=await readJson(response,{label:'Evaluation manifest'});renderManifest();
  let reportError;try{await loadReport();}catch(e){reportError=e.message;}
  if(['localhost','127.0.0.1'].includes(location.hostname)){try{const response=await fetch('/api/health');if(response.ok)localRunner=(await readJson(response,{label:'Local runner'})).runner===true;}catch{}}
  runButton.hidden=!localRunner;runButton.onclick=run;render();if(reportError)status.textContent=reportError;
}catch(e){document.querySelector('#manifest-status').textContent=e.message;status.textContent=e.message;}
