'use strict';

const $ = id => document.getElementById(id);
const state = {revision:null, documents:[], selected:new Set(), answer:null, search:null,
  bridge:null, budget:null, busy:false, loading:false, readFailed:false, historyVersion:null};
const make = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const format = value => typeof value === 'number' ? value.toLocaleString('en-US') : '—';
function announce(text, error=false) {
  $('notice').textContent=text; $('notice').hidden=false;
  $('notice').className=error?'error':'';
}
async function api(path, method='GET', body) {
  const options={method};
  if (body!==undefined) {options.headers={'Content-Type':'application/json'}; options.body=JSON.stringify(body);}
  const response=await fetch('/api'+path,options);
  let value;
  try {value=await response.json();} catch {throw Error('The local service returned an unreadable response.');}
  if (!response.ok) throw Error(typeof value.detail==='string'?value.detail:
    typeof value.error==='string'?value.error:'Local request failed ('+response.status+').');
  return value;
}
function action(text, callback, className) {
  const button=make('button',text,className);button.type='button';
  button.addEventListener('click',()=>Promise.resolve(callback(button)).catch(e=>announce(e.message,true)));
  return button;
}
function sourceLink(url,page,label='Original PDF page') {
  if (!/^https:\/\/nvlpubs\.nist\.gov\/nistpubs\/(ai|SpecialPublications)\/[A-Za-z0-9.-]+\.pdf$/.test(url||''))
    return make('span','Local imported text');
  const link=make('a',label+' '+page);link.href=url+'#page='+Number(page);
  link.target='_blank';link.rel='noopener noreferrer';return link;
}
function scope() {return state.selected.size?[...state.selected]:undefined;}
function generationState() {
  const privateScope=state.documents.some(d=>state.selected.has(d.id)&&!d.remote_allowed);
  $('generate').disabled=state.busy || !state.bridge?.online || !$('query').value.trim() || privateScope || state.budget?.attempted>=10;
  $('generation-note').textContent=privateScope?'This selection contains private text. Search stays local; generation is blocked.':
    state.bridge?.online?'Public originals only · workspace requests '+(state.budget?.attempted??0)+'/10 · no automatic retries.':
    'Host bridge is offline. Start it with sh stack.sh bridge; local search remains available.';
}
function renderDocuments() {
  $('documents').replaceChildren();
  for (const doc of state.documents) {
    const article=make('article',undefined,'document'), label=make('label');
    const checkbox=make('input');checkbox.type='checkbox';checkbox.value=doc.id;
    checkbox.checked=state.selected.has(doc.id);
    checkbox.addEventListener('change',()=>{checkbox.checked?state.selected.add(doc.id):state.selected.delete(doc.id);generationState();});
    label.append(checkbox,make('span',doc.title));article.append(label);
    article.append(make('small',format(doc.pages)+' pages · '+format(doc.chunks)+' chunks · v'+doc.version));
    article.append(make('small',doc.remote_allowed?'PUBLIC ORIGINAL · MODEL ELIGIBLE':'PRIVATE · LOCAL SEARCH ONLY','privacy'));
    const controls=make('div',undefined,'doc-actions');
    controls.append(action('Read',()=>readSource(doc.id)),action('Replace text',()=>editDocument(doc)),
      action('Delete',button=>deleteDocument(doc,button),'delete'));
    article.append(controls);$('documents').append(article);
  }
  if (!state.documents.length) $('documents').append(make('p','The index is empty. Import a note or explicitly restore the public originals.','muted'));
  $('revision').textContent='REV '+state.revision;
}
async function refresh() {
  if (state.loading) return;
  state.loading=true;
  try {
    const data=await api('/state');
    if (state.readFailed) {announce('Library reads restored. Current source versions reloaded.');state.readFailed=false;}
    const changed=state.revision!==null&&state.revision!==data.revision;
    state.bridge=data.bridge;state.budget=data.model_budget;
    $('bridge-status').textContent=data.bridge?.online?'● Approved bridge ready · cookllm':'○ Model bridge offline · search locally';
    $('corpus-count').textContent=format(data.counts?.documents)+' DOCUMENTS / '+format(data.counts?.chunks)+' CHUNKS';
    if (data.revision!==state.revision) {
      state.revision=data.revision;state.documents=data.documents||[];
      const existing=new Set(state.documents.map(d=>d.id));
      state.selected=new Set([...state.selected].filter(id=>existing.has(id)));
      renderDocuments();
      if (changed) {
        state.search=null;$('results').replaceChildren(make('p','The library changed. Search again to use the current source versions.','empty'));
        $('search-stats').textContent='Previous results invalidated';
      }
    }
    const historyVersion=JSON.stringify((data.answers||[]).map(a=>[a.id,a.state,a.completed_at,a.reason]));
    if (historyVersion!==state.historyVersion) {
      renderHistory(data.answers||[]);state.historyVersion=historyVersion;
      if (state.answer) await readAnswer(state.answer);
    }
    generationState();
  } finally {state.loading=false;}
}
function renderHistory(answers) {
  $('answer-history').replaceChildren();
  for (const answer of answers) {
    const button=action(answer.question||'Answer invalidated by corpus change',()=>readAnswer(answer.id));
    button.append(make('small',answer.state+' · corpus revision '+answer.revision));
    $('answer-history').append(button);
  }
  if (!answers.length) $('answer-history').append(make('p','No generation requests yet.','muted'));
}
async function mutate(button,path,method,body,message) {
  button.disabled=true;let committed=false;
  try {
    const result=await api(path,method,body);committed=true;
    announce(message);await refresh();return result;
  } catch(error) {announce((committed?'Change saved; library refresh failed: ':'')+error.message,true);}
  finally {button.disabled=false;generationState();}
}
async function search() {
  $('search').disabled=true;$('search-stats').textContent='Searching current source versions…';
  try {
    const result=await api('/search','POST',{query:$('query').value.trim(),mode:$('mode').value,limit:5,document_ids:scope()});
    await refresh();
    if (result.revision!==state.revision) throw Error('The corpus changed during search. Please search again.');
    state.search=result;renderResults(result);
  } catch(error) {announce(error.message,true);$('search-stats').textContent='Search failed; retry when ready.';}
  finally {$('search').disabled=false;}
}
function renderResults(result) {
  $('results').replaceChildren();
  $('search-stats').textContent=result.hits.length+' passages · '+Number(result.took_ms).toFixed(1)+' ms · '+result.mode;
  result.hits.forEach((hit,index)=>{
    const article=make('article',undefined,'passage'),head=make('div',undefined,'passage-head');
    head.append(make('strong',hit.title),make('span',String(index+1).padStart(2,'0'),'rank'));article.append(head);
    article.append(make('small',(hit.remote_allowed?'PDF page ':'Text page ')+hit.page+' · v'+hit.version+' · '+(hit.remote_allowed?'Public original':'Private local text')));
    article.append(make('blockquote',hit.text));
    article.append(sourceLink(hit.source_url,hit.page));
    const read=action('Inspect indexed page',()=>readSource(hit.document_id,hit.page));read.className='inspect-page';article.append(read);
    const details=make('details');details.append(make('summary','Retrieval & identity'));
    details.append(make('p','Score '+Number(hit.score).toFixed(5)+' · lexical rank '+(hit.lexical_rank??'—')+' · latent rank '+(hit.latent_rank??'—')));
    details.append(make('p','Chunk '+hit.chunk_id+' · SHA-256 '+hit.sha256));article.append(details);
    $('results').append(article);
  });
  if (!result.hits.length) {
    const empty=make('div',undefined,'empty');empty.append(make('h3','No useful passage found.'),make('p','Try another term or a broader source selection. The system has not generated an answer.'));$('results').append(empty);
  }
}
async function generate() {
  state.busy=true;generationState();
  try {
    const answer=await api('/answers','POST',{question:$('query').value.trim(),document_ids:scope()});
    state.answer=answer.id;renderAnswer(answer);await refresh();
    announce(answer.state==='queued'?'A bounded public-context request was queued. Watch the evidence ledger.':'The request completed locally without a model call.');
  } catch(error) {announce(error.message,true);}
  finally {state.busy=false;generationState();}
}
async function readAnswer(id) {
  const answer=await api('/answers/'+encodeURIComponent(id));state.answer=id;renderAnswer(answer);
}
function renderAnswer(answer) {
  $('answer').replaceChildren();$('answer').append(make('p',answer.state,'answer-state '+answer.state));
  if (answer.question) $('answer').append(make('p',answer.question,'answer-reason'));
  if (answer.state==='queued') $('answer').append(make('p','Waiting for the host bridge. The request has no automatic retry.','answer-reason'));
  if (answer.reason) $('answer').append(make('p',answer.reason,'answer-reason'));
  const citations=new Map((answer.citations||[]).map(c=>[c.chunk_id||c.id,c]));
  for (const claim of answer.claims||[]) {
    const article=make('article',undefined,'claim');article.append(make('p',claim.text));
    for (const support of claim.supports||[]) {
      const citation=citations.get(support.chunk_id),section=make('div',undefined,'support');
      section.append(make('strong','EXACT QUOTE · SOURCE VALIDATED'),make('blockquote',support.quote));
      if (citation) section.append(make('small',citation.title+' · PDF page '+citation.page+' · v'+citation.version),sourceLink(citation.source_url,citation.page));
      else section.append(make('small','Citation '+support.chunk_id));
      article.append(section);
    }
    $('answer').append(article);
  }
  if (answer.latency_ms!==undefined&&answer.latency_ms!==null) $('answer').append(make('p',
    'Model latency '+(answer.latency_ms/1000).toFixed(1)+' s · '+(answer.model||'cookllm')+' · actual billing unavailable','method'));
}
async function readSource(id,page) {
  $('source-title').textContent='Loading indexed source…';$('source-content').replaceChildren();$('source-dialog').showModal();
  try {
    const result=await api('/documents/'+encodeURIComponent(id)+'/chunks');
    $('source-title').textContent=result.document.title;
    $('source-content').append(make('p',(result.document.remote_allowed?'Original PDF':'Imported text')+' SHA-256: '+result.document.sha256,'method'));
    const pageLabel=result.document.remote_allowed?'Physical PDF page':'Text page';
    const label=make('label',pageLabel),select=make('select');select.setAttribute('aria-label',pageLabel);
    for (const number of [...new Set(result.chunks.map(c=>c.page))].sort((a,b)=>a-b)) {const option=make('option',number);option.value=number;select.append(option);}
    if (page) select.value=page;label.append(select);$('source-content').append(label);
    const container=make('div');$('source-content').append(container);
    const show=()=>{container.replaceChildren();for (const chunk of result.chunks.filter(c=>c.page===Number(select.value))) {
      const segment=make('section',undefined,'source-page');segment.append(make('small','Indexed segment · '+chunk.id),make('pre',chunk.text));container.append(segment);
    }container.append(sourceLink(result.document.source_url,Number(select.value)));};
    select.addEventListener('change',show);show();
  } catch(error) {$('source-content').append(make('p',error.message,'error-text'));}
}
function editDocument(doc) {
  $('document-id').value=doc?.id||'';$('note-title').value=doc?.title||'';$('note-text').value='';$('note-file').value='';
  $('import-title').textContent=doc?'Replace indexed text':'Import a local note';
  $('import-explanation').textContent=doc?'Replace this document with private plain text. Its version changes and prior answers are invalidated. Public model eligibility is removed.':'Plain text or Markdown. Imported text stays private and cannot be sent to the model bridge.';
  $('import-error').hidden=true;$('import-dialog').showModal();
}
async function deleteDocument(doc,button) {
  if (!confirm('Delete “'+doc.title+'” from the index and invalidate dependent answers? Original acquisition files remain in the local cache.')) return;
  await mutate(button,'/documents/'+encodeURIComponent(doc.id),'DELETE',undefined,'Document removed. Search and answer copies were invalidated.');
}
async function saveDocument(event) {
  event.preventDefault();const control=$('import-save');control.disabled=true;let committed=false;
  try {
    const payload={title:$('note-title').value.trim(),text:$('note-text').value};
    if ($('document-id').value) payload.document_id=$('document-id').value;
    await api('/documents','POST',payload);committed=true;$('import-dialog').close();await refresh();announce('Private text saved locally; source versions and dependent answers refreshed.');
  } catch(error) {if (committed) announce('Document saved; library refresh failed: '+error.message,true);else {$('import-error').textContent=error.message;$('import-error').hidden=false;}}
  finally {control.disabled=false;}
}
async function evaluation() {
  try {
    const report=await api('/evaluation');$('evaluation').replaceChildren();
    if (!report.available) {$('evaluation').append(make('p','Evaluation has not been recorded yet. Run the documented local acceptance scripts to create a dated report.','muted'));return;}
    $('evaluation').append(make('p',report.methodology||'Frozen source-page retrieval evaluation.','muted'));
    const cards=make('div',undefined,'eval-metrics');
    for (const row of report.retrieval?.metrics||[]) {const card=make('article');card.append(make('small',row.mode.toUpperCase()),make('strong',(row.hit_at_5*100).toFixed(1)+'%'),make('small','Designated-page Hit@5 · n='+row.n+' · MRR '+row.mrr.toFixed(3)));cards.append(card);}
    $('evaluation').append(cards);
    $('evaluation').append(make('p',report.limitations||'Small corpus and source-page anchors; no general model-quality claim.','method'));
    if (report.live) {$('evaluation').append(make('h3','Live generation checks'),make('p',report.live.summary,'muted'));}
    const scroll=make('div',undefined,'table-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Held-out retrieval results');
    const table=make('table'),caption=make('caption','Held-out queries and designated source-page matches'),head=make('thead'),headRow=make('tr');
    for (const title of ['Question','Mode','First relevant rank','Matched physical pages']) headRow.append(make('th',title));head.append(headRow);table.append(caption,head);
    const body=make('tbody');for (const item of report.retrieval?.results||[]) {const row=make('tr');row.append(make('td',item.query),make('td',item.mode),make('td',item.first_relevant_rank??'Not in top 5'),make('td',(item.matched_pages||[]).join(', ')||'None'));body.append(row);}table.append(body);scroll.append(table);$('evaluation').append(scroll);
  } catch(error) {$('evaluation').replaceChildren(make('p',error.message,'error-text'));}
}
function tab(which) {
  $('work-panel').hidden=which!=='work';$('eval-panel').hidden=which!=='eval';
  $('tab-work').setAttribute('aria-pressed',which==='work');$('tab-eval').setAttribute('aria-pressed',which==='eval');
  if (which==='eval') evaluation();
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();search();});
$('generate').addEventListener('click',generate);$('query').addEventListener('input',generationState);
$('import-open').addEventListener('click',()=>editDocument());$('import-close').addEventListener('click',()=>$('import-dialog').close());
$('source-close').addEventListener('click',()=>$('source-dialog').close());$('import-form').addEventListener('submit',saveDocument);
$('restore').addEventListener('click',()=>mutate($('restore'),'/seed','POST',{},'Original public corpus restored explicitly. Unchanged documents were preserved.'));
$('tab-work').addEventListener('click',()=>tab('work'));$('tab-eval').addEventListener('click',()=>tab('eval'));
document.querySelectorAll('.sample').forEach(button=>button.addEventListener('click',()=>{$('query').value=button.dataset.query;generationState();search();}));
$('note-file').addEventListener('change',async()=>{const file=$('note-file').files[0];if (!file) return;
  if (file.size>200000||!/\.(txt|md)$/i.test(file.name)) {$('import-error').textContent='Choose a .txt or .md file up to 200KB.';$('import-error').hidden=false;return;}
  $('note-text').value=await file.text();if (!$('note-title').value) $('note-title').value=file.name.replace(/\.(txt|md)$/i,'');
});
function readFailure(error) {state.readFailed=true;announce('Library read failed: '+error.message,true);}
refresh().catch(readFailure);
setInterval(()=>{if (document.visibilityState==='visible') refresh().catch(readFailure);},2000);
