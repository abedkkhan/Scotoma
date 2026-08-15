const state={index:null,trace:null,coverage:null,adjudication:null,flip:null,evaluation:null,audited:false,selectedRepoFiles:[],repoName:'Flask'};
const $=(q,r=document)=>r.querySelector(q);const $$=(q,r=document)=>[...r.querySelectorAll(q)];
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const pct=n=>`${Number(n).toFixed(2)}%`;

async function loadDemo(){
  const names=['index','trace','coverage','adjudication','flip','evaluation'];
  try{const values=await Promise.all(names.map(n=>fetch(`data/${n}.json`).then(r=>{if(!r.ok)throw Error(n);return r.json()})));names.forEach((n,i)=>state[n]=values[i]);renderBase();}
  catch(e){toast(`Could not load demo data: ${e.message}`);}
}

function renderBase(){
  $('#questionText').textContent=state.trace.question;$('#questionInput').value=state.trace.question;$('#agentModel').textContent=state.trace.model.toUpperCase();
  $('#originalAnswer').innerHTML=highlightBefore(state.trace.answer);$('#correctedAnswer').innerHTML=highlightAfter(state.flip.new_answer);
  $('#changeSummary').textContent=state.flip.comparison.summary;
  $('#rwcMetric').textContent=pct(state.coverage.rwc_percent);$('#naiveMetric').textContent=pct(state.coverage.naive_file_coverage_percent);
  const full=Object.values(state.trace.examined).filter(v=>v===1).length;$('#fullReadMetric').textContent=String(full);
  renderMap();renderClaims();renderEvidence();renderEvaluation();
}

function highlightBefore(text){let s=escapeHtml(text);['confidentiality and integrity','can be decrypted'].forEach(p=>{s=s.replaceAll(p,`<mark>${p}</mark>`)});return s;}
function highlightAfter(text){let s=escapeHtml(text);['not encrypted','readable by clients','integrity and authenticity','not confidentiality'].forEach(p=>{s=s.replaceAll(p,`<mark>${p}</mark>`)});return s;}

function renderMap(){
  const root=$('#coverageMap');root.innerHTML='';const verdicts=new Map(state.adjudication.ranked_candidates.map(x=>[x.path,x.verdict]));
  const units=[...state.coverage.units].sort((a,b)=>b.relevance-a.relevance);
  units.forEach(u=>{const el=document.createElement('div');const size=u.relevance>.68?3:u.relevance>.47?2:1;const depth=u.depth>=1?100:u.depth>=.6?60:u.depth>=.25?25:0;const verdict=verdicts.get(u.path)||'unreviewed';el.className=`tile size-${size} depth-${depth} ${verdict==='contradicts'?'contradicts':''}`;el.dataset.tip=`${u.path}\nrelevance ${u.relevance.toFixed(3)} · depth ${u.depth.toFixed(2)}\n${verdict}`;el.setAttribute('aria-label',el.dataset.tip);root.appendChild(el)});
  $('#mapFiles').textContent=`${state.coverage.unit_count} files`;$('#mapTouched').textContent=`${state.coverage.examined_unit_count} examined`;$('#mapContradictions').textContent=`${state.adjudication.ranked_candidates.filter(x=>x.verdict==='contradicts').length} contradictions`;
}

function renderClaims(){
  const contradicted=new Set(state.adjudication.ranked_candidates.filter(x=>x.verdict==='contradicts').map(x=>x.target_claim_id));
  $('#claimsList').innerHTML=state.adjudication.claims.map(c=>`<article class="claim-card"><span class="claim-id">${escapeHtml(c.id)}</span><p>${escapeHtml(c.text)}</p><span class="tag ${contradicted.has(c.id)?'contradicted':''}">${contradicted.has(c.id)?'CONTRADICTED':'UNTESTED'}</span></article>`).join('');
}

function renderEvidence(){
  $('#evidenceList').innerHTML=state.adjudication.ranked_candidates.map((x,i)=>`<article class="evidence-row ${x.verdict}"><div><b>${String(i+1).padStart(2,'0')} · ${escapeHtml(x.path)}</b><small>${escapeHtml(x.reason)}</small><span class="tag ${x.verdict==='contradicts'?'contradicted':''}">${escapeHtml(x.verdict.toUpperCase())}</span></div><span class="evidence-score">${x.adjudicated_risk.toFixed(3)}</span><div class="evidence-bar"><i style="width:${Math.max(1,x.adjudicated_risk/0.54*100)}%"></i></div></article>`).join('');
}

function renderEvaluation(){
  if(!state.evaluation)return;const labels={random:'Random baseline',semantic_only:'Semantic only',three_signal_composite:'Three-signal composite',claim_adjudicated:'Claim adjudicated'};
  $('#evaluationList').innerHTML=Object.entries(state.evaluation.rankers).map(([name,m])=>`<article class="eval-row ${name==='claim_adjudicated'?'winner':''}"><div><header><b>${labels[name]||name}</b><small>MRR ${m.mrr.toFixed(3)} · NDCG@5 ${m.ndcg_at_5.toFixed(3)}</small></header><div class="eval-track"><i style="width:${m.recall_at_2*100}%"></i></div></div><span class="eval-score">${Math.round(m.recall_at_2*100)}%</span></article>`).join('');
}

function runAudit(){
  if(!state.coverage)return;const entered=$('#questionInput').value.trim();if(entered&&entered!==state.trace.question){$('#uploadQuestion').value=entered;$('#uploadStatus').innerHTML='<b>New question detected.</b> Choose its repository folder, then configure the hosted API or load completed Scotoma artifacts.';dialog.showModal();return}state.audited=true;const btn=$('#runAudit');btn.disabled=true;btn.innerHTML='Tracing agent <span>···</span>';
  setTimeout(()=>{btn.innerHTML='Measuring coverage <span>···</span>'},650);
  setTimeout(()=>{btn.innerHTML='Adjudicating claims <span>···</span>'},1300);
  setTimeout(()=>{$('#auditMessage').classList.remove('hidden');btn.innerHTML='Audit complete <span>✓</span>';activateTab('coverage');$('#auditMessage').scrollIntoView({behavior:'smooth',block:'center'});toast('Blind spot detected · 5.51% coverage')},2100);
}

function injectEvidence(){
  if(!state.audited){runAudit();setTimeout(injectEvidence,2300);return}
  const btn=$('#injectEvidence');btn.disabled=true;btn.textContent='Injecting json/tag.py + sessions.py…';
  setTimeout(()=>{$('#correctedMessage').classList.remove('hidden');btn.innerHTML='Conclusion changed <span>✓</span>';$('#correctedMessage').scrollIntoView({behavior:'smooth',block:'center'});toast('The agent corrected its security claim')},1200);
}

function activateTab(name){$$('.inspector-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));$$('.tab-panel').forEach(p=>p.classList.remove('active'));$(`#${name}Panel`).classList.add('active')}
function toast(msg){const el=$('#toast');el.textContent=msg;el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),2800)}

$$('.inspector-tabs button').forEach(b=>b.addEventListener('click',()=>activateTab(b.dataset.tab)));
$$('.expand-answer').forEach(b=>b.addEventListener('click',()=>{const a=b.previousElementSibling;a.classList.toggle('clamp');b.textContent=a.classList.contains('clamp')?'Show full answer ↓':'Collapse answer ↑'}));
$('#runAudit').addEventListener('click',runAudit);$('#injectEvidence').addEventListener('click',injectEvidence);
$('#presentBtn').addEventListener('click',()=>{document.body.classList.toggle('present');$('#presentBtn').textContent=document.body.classList.contains('present')?'Exit present mode':'Present mode'});

const dialog=$('#uploadDialog');$('#uploadBtn').addEventListener('click',()=>dialog.showModal());$('#newAudit').addEventListener('click',beginNewAudit);$('.dialog-close').addEventListener('click',()=>dialog.close());
const obsoleteApi='https://scotoma-api.onrender.com';if(localStorage.getItem('scotomaApiUrl')===obsoleteApi)localStorage.removeItem('scotomaApiUrl');
$('#apiUrl').value=localStorage.getItem('scotomaApiUrl')||window.SCOTOMA_CONFIG?.apiUrl||'';$('#accessToken').value=localStorage.getItem('scotomaAccessToken')||'';
$('#uploadQuestion').value=$('#questionInput').value;$('#uploadQuestion').addEventListener('input',e=>$('#questionInput').value=e.target.value);
function beginNewAudit(){$('#questionInput').value='';$('#uploadQuestion').value='';state.selectedRepoFiles=[];$('#repoFolder').value='';$('#startLiveAudit').disabled=true;$('#uploadStatus').innerHTML='<b>New audit.</b> Choose a repository folder and ask a question. Flask remains available as the bundled fallback demo.';dialog.showModal()}
$('#repoFolder').addEventListener('change',e=>{
  const files=[...e.target.files];const skip=/(^|\/)(\.git|node_modules|\.venv|dist|build)(\/|$)/;const source=/\.(py|js|jsx|ts|tsx|go|rs|java|rb|php|c|cpp|h|css|html|sql|sh|swift|kt|kts|vue|svelte)$/i;const units=files.filter(f=>source.test(f.name)&&!skip.test(f.webkitRelativePath)&&f.size<=400*1024);state.selectedRepoFiles=units;state.repoName=files[0]?.webkitRelativePath.split('/')[0]||'Repository';const locPromise=Promise.all(units.slice(0,250).map(f=>f.text().then(t=>t.split(/\r?\n/).filter(Boolean).length).catch(()=>0)));
  locPromise.then(lines=>{$('#uploadStatus').innerHTML=`<b>${escapeHtml(state.repoName)}</b> ready: ${units.length} source files · ${lines.reduce((a,b)=>a+b,0).toLocaleString()} sampled LOC. Ask your question below, then run the complete hosted audit.`;$('#workspaceLabel').textContent=`NEW AUDIT / ${state.repoName.toUpperCase()}`;$('#startLiveAudit').disabled=!units.length;toast('Repository ready for live audit')});
});
$('#artifactFiles').addEventListener('change',async e=>{
  const loaded={};for(const f of e.target.files){try{const data=JSON.parse(await f.text());if(data.units&&'rwc' in data)loaded.coverage=data;else if(data.units)loaded.index=data;else if(data.ranked_candidates)loaded.adjudication=data;else if(data.new_answer)loaded.flip=data;else if(data.examined)loaded.trace=data;else if(data.rankers)loaded.evaluation=data}catch{toast(`Invalid JSON: ${f.name}`)}}
  Object.assign(state,loaded);if(state.index&&state.trace&&state.coverage&&state.adjudication&&state.flip){renderBase();dialog.close();toast('Investigation artifacts loaded')}else{$('#uploadStatus').textContent=`Loaded ${Object.keys(loaded).join(', ')||'no recognized'} artifacts. Select all five JSON outputs for a complete investigation.`}
});

$('#startLiveAudit').addEventListener('click',startLiveAudit);
async function startLiveAudit(){
  const api=$('#apiUrl').value.trim().replace(/\/$/,'');const token=$('#accessToken').value.trim();const question=$('#uploadQuestion').value.trim();const button=$('#startLiveAudit');
  if(!api)return setUploadError('Backend not configured. Deploy render.yaml, then paste its service URL here.');if(question.length<5)return setUploadError('Enter a specific repository question in the chat box first.');if(!state.selectedRepoFiles.length)return setUploadError('Choose a repository folder first.');
  localStorage.setItem('scotomaApiUrl',api);if(token)localStorage.setItem('scotomaAccessToken',token);button.disabled=true;button.textContent='Uploading repository…';
  const form=new FormData();form.append('question',question);state.selectedRepoFiles.forEach(file=>{form.append('files',file,file.name);form.append('paths',file.webkitRelativePath||file.name)});
  const headers={};if(token)headers['X-Scotoma-Token']=token;
  try{const response=await fetch(`${api}/api/audits`,{method:'POST',headers,body:form});const body=await response.json().catch(()=>({}));if(!response.ok)throw Error(body.detail||`API returned ${response.status}`);dialog.close();showLiveProgress(body);await pollAudit(api,body.id,headers)}catch(error){const message=error instanceof TypeError?'Could not reach that API URL. Confirm the service is deployed and CORS allows this Pages origin.':error.message;setUploadError(message);dialog.showModal();button.disabled=false;button.innerHTML='Run live repository audit <span>→</span>'}
}
function setUploadError(message){$('#uploadStatus').innerHTML=`<b style="color:var(--red)">Live audit unavailable:</b> ${escapeHtml(message)}`;toast(message)}
function showLiveProgress(job){
  state.audited=false;$('#modeKicker').textContent='LIVE REPOSITORY · AGENT COVERAGE ANALYSIS';$('#workspaceLabel').textContent=`LIVE / ${state.repoName.toUpperCase()}`;$('#questionText').textContent=$('#questionInput').value.trim();$('#originalAnswer').textContent='Scotoma is mapping the repository and launching a bounded analysis agent…';$('#auditMessage').classList.add('hidden');$('#correctedMessage').classList.add('hidden');
  $('.history-item b').textContent=`${state.repoName} · live audit`;$('.history-item small').textContent=`${job.file_count} files · queued`;$('#runAudit').disabled=true;$('#runAudit').textContent='Audit running…';toast('Live audit queued')
}
async function pollAudit(api,id,headers){
  const stageLabels={queued:'Queued',indexing:'Mapping territory',agent:'Agent investigating',coverage:'Measuring coverage',adjudication:'Adjudicating claims',flip:'Running flip test'};
  while(true){await new Promise(r=>setTimeout(r,2200));const response=await fetch(`${api}/api/audits/${id}`,{headers});const job=await response.json().catch(()=>({}));if(!response.ok)throw Error(job.detail||`Polling failed (${response.status})`);$('.history-item small').textContent=`${job.unit_count||job.file_count} files · ${stageLabels[job.stage]||job.stage} ${job.progress}%`;$('#originalAnswer').innerHTML=`<span style="color:var(--acid)">${escapeHtml(stageLabels[job.stage]||job.stage)}</span>\n\nScotoma is running the real agent pipeline. This can take a few minutes on a new repository.\n\n${'▓'.repeat(Math.round(job.progress/5))}${'░'.repeat(20-Math.round(job.progress/5))} ${job.progress}%`;if(job.status==='failed')throw Error(job.error||'Audit failed');if(job.status==='complete'){Object.assign(state,job.result,{audited:true});renderBase();$('#auditMessage').classList.remove('hidden');$('#correctedMessage').classList.remove('hidden');$('#runAudit').disabled=false;$('#runAudit').innerHTML='Audit complete <span>✓</span>';$('.history-item small').textContent=`${state.coverage.unit_count} files · completed`;activateTab('evidence');toast('Live Scotoma audit complete');break}}
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'&&dialog.open)dialog.close();if(e.key.toLowerCase()==='p'&&!['INPUT','TEXTAREA'].includes(e.target.tagName))$('#presentBtn').click()});
loadDemo();
