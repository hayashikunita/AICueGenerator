const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const out = path.join(root, 'frontend/node_modules/.cache/aicue-ux');
const assets = path.join(root, 'backend/static');
fs.mkdirSync(out, {recursive:true});
const jobs = ['one', 'two'].map((id, i) => ({ id, status: 'COMPLETED', total: 1, completed: 1, failed: 0, track_path: `C:/Music/${i ? 'Second song' : 'First song'}.wav`, created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z' }));
let candidates = ['drop', 'break'].map((id, i) => ({ id, run_id: 'run', type: i ? 'BREAK' : 'DROP', time_ms: i ? 30000 : 60000, confidence: i ? 60 : 90, rank: 1, beat: 32, band: i ? 'review' : 'high', evidence: [], accepted: null, cue_kind: null }));
let purposeMode = false, batchMode = false, batchCandidates = [], batchTracks = [], bulkFailure = false, bulkWrites = 0, previewCalls = 0, decisionWrites = 0, manualAdds = 0;
let diag = 0, created = null, csvAuth = false;
let lastExport = null, lastPlan = null, memoryOverflowFixture = false;
let metadataTrack = null;
let existingConflict=false, existingRace=false, sourceUploads=0, existingExports=0;
let aiAvailable=true;
let aiProgressPercent=34;
function existingReview(data) {
  const tid='purpose-track';
  const chosen=xmlEntries(data).map(item=>({...item,track_id:tid}));
  const duplicate=item=>(item.cue_kind==='MEMORY'&&item.time_ms===0)||(item.cue_kind==='HOT'&&item.time_ms===2000);
  let slot=1;
  const added=chosen.filter(item=>!duplicate(item)).map(item=>({...item,slot:item.cue_kind==='HOT'?String.fromCharCode(65+slot++):null}));
  const keep=[{track_id:tid,cue_kind:'MEMORY',action:'KEEP',time_ms:0,reason:'既存を維持：Existing memory',color:'#112233'},
    {track_id:tid,cue_kind:'HOT',slot:'A',action:'KEEP',time_ms:2000,reason:'既存を維持：Existing hot A',color:'#001122'},
    {track_id:tid,cue_kind:'MEMORY',action:'KEEP',time_ms:4000,end_time_ms:6000,reason:'既存を維持：Keep loop（ループ）',color:'#ff0000'}];
  return {mode:'EXISTING',plan_id:'existing-plan',confirmation_hash:'d'.repeat(64),add:added.length,replace:0,conflict:existingConflict?1:0,preserved:3,duplicates_skipped:chosen.filter(duplicate).length,
    source_name:'original_collection.xml',issues:existingConflict?['元の曲: 既存を含めてMemory Cueの空き枠が不足しています。追加候補を減らしてください。']:[],
    track_updates:[{track_id:tid,title:'Library song',path:'C:/Music/Library.wav',existing_memory:2,existing_hot:1,add_memory:added.filter(i=>i.cue_kind==='MEMORY').length,add_hot:added.filter(i=>i.cue_kind==='HOT').length}],
    items:[...keep,...added,...chosen.filter(duplicate).map(item=>({...item,action:'SKIP',reason:'同じ位置のCueがあるため追加しません（既存の名前・色を維持）'}))]};
}
const memoryScores = [10,95,20,85,70,65,40,90,75,60,55,100,15,80,50];
function xmlEntries(data) {
  return candidates.filter(c=>c.accepted).flatMap(c=>{
    const kinds=[];
    if((c.cue_kind==='MEMORY'||c.cue_kind==='BOTH') && (!data.memory_candidate_ids || data.memory_candidate_ids.includes(c.id))) kinds.push('MEMORY');
    if(c.cue_kind==='HOT'||c.cue_kind==='BOTH') kinds.push('HOT');
    const preset=jobs[0].params?.cue_settings?.[c.type]??jobs[0].params?.cue_default;
    return kinds.map(kind=>({track_id:c.track_id||'track',cue_kind:kind,action:'ADD',time_ms:c.time_ms,reason:'',preset}));
  });
}
let gridRunning = true, gridSaves = 0, gridOffset = 0, gridFail = false, audioReads = 0;
const previewAudio = Buffer.alloc(44 + 8000 * 30 * 2);
previewAudio.write('RIFF',0); previewAudio.writeUInt32LE(previewAudio.length-8,4); previewAudio.write('WAVEfmt ',8);
previewAudio.writeUInt32LE(16,16); previewAudio.writeUInt16LE(1,20); previewAudio.writeUInt16LE(1,22);
previewAudio.writeUInt32LE(8000,24); previewAudio.writeUInt32LE(16000,28); previewAudio.writeUInt16LE(2,32); previewAudio.writeUInt16LE(16,34);
previewAudio.write('data',36); previewAudio.writeUInt32LE(previewAudio.length-44,40);
const gridPreview = firstBeat => ({ content_id:'RB1',title:'Library song',path:'C:/Music/Library.wav',first_beat:firstBeat,beat_count:384,blocked_reason:gridRunning?'保存するには rekordbox を終了してください。':null,beats:Array.from({length:8},(_,i)=>{const before=(i-gridOffset+8)%4+1;return {time_ms:137+i*500,before,after:(before-firstBeat+4)%4+1};}) });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.startsWith('/api/')) {
    const file = path.join(assets, url.pathname === '/' ? 'index.html' : url.pathname);
    if (!fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(fs.readFileSync(file)); return;
  }
  let body = ''; for await (const chunk of req) body += chunk;
  const data = body ? JSON.parse(body) : null;
  if (url.pathname.endsWith('/audio')) {
    if (url.pathname.includes('/rekordbox/')) {
      assert.equal(url.searchParams.get('token'),'ux-test');
      assert.equal(url.searchParams.get('path'),'C:/Music/Library.wav');
      audioReads++;
    }
    const match = /^bytes=(\d+)-(\d*)/.exec(req.headers.range || '');
    const start = match ? Number(match[1]) : 0;
    const end = match && match[2] ? Math.min(Number(match[2]),previewAudio.length-1) : previewAudio.length-1;
    res.setHeader('Content-Type','audio/wav');res.setHeader('Accept-Ranges','bytes');
    if (match) { res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${previewAudio.length}`); }
    res.setHeader('Content-Length',end-start+1);res.end(previewAudio.subarray(start,end+1));return;
  }
  let result;
  if (url.pathname.endsWith('/diagnostics')) result = { process_running: false, db_key_available: true, schema_supported: true, writable: ++diag > 1, state: 'ok' };
  else if (url.pathname.endsWith('/analysis/ai-status')) result={available:aiAvailable,model:'htdemucs',local_only:true,reason:aiAvailable?null:'AI解析環境が未準備です。通常解析を使用できます。'};
  else if(url.pathname==='/api/v1/write/source-xml'&&req.method==='POST') {
    if(data.xml_text.includes('pyrekordbox')) {res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'アプリの出力XMLではなく、rekordboxのコレクションXMLを選んでください。'}));return;}
    sourceUploads++;result={source_id:'b'.repeat(32),filename:data.filename,tracks:1288};
  }
  else if(url.pathname.endsWith('/write/plan')&&data.mode==='EXISTING') {assert.equal(data.source_id,'b'.repeat(32));lastPlan=data;result=existingReview(data);}
  else if(url.pathname.endsWith('/write/export-xml')&&data.mode==='EXISTING') {
    assert.equal(data.source_id,'b'.repeat(32));assert.equal(data.confirmation_hash,'d'.repeat(64));
    if(existingRace) {res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'確認後にライブラリが変わりました。追加内容をもう一度確認してください。'}));return;}
    const plan=existingReview(data);assert.equal(plan.conflict,0);existingExports++;lastExport=data;
    result={mode:'EXISTING',folder:'C:/AppData/exports/existing',xml_path:'C:/AppData/exports/existing/rekordbox.xml',backup_xml_path:'C:/AppData/exports/existing/original_collection.xml',tracks:1,cues:plan.add+plan.preserved,added_cues:plan.add,preserved_cues:3,duplicates_skipped:plan.duplicates_skipped,copied:0,skipped:[],warnings:[],cue_colors:data.cue_colors,cue_settings_used:true};
  }
  else if (url.pathname === '/api/v1/jobs' && req.method === 'POST') {
    created = data; jobs[0].params = data.params;
    batchMode=data.tracks.length>1;
    jobs[0].total=jobs[0].completed=data.tracks.length;
    if (data.tracks.length > 1) {
      batchMode = true;
      jobs[0].total = jobs[0].completed = data.tracks.length;
      batchTracks = data.tracks.map((t,i)=>({...t,id:'batch-'+i,status:'COMPLETED',duration_ms:30000,analysis:{source:'REKORDBOX',available:true,bpm:120+i*10,beat_count:60,downbeat_count:15,phrase_count:6,warnings:[]}}));
      batchCandidates = batchTracks.flatMap((t,index)=>(data.params.intro_outro?.targets??data.params.cue_targets).map((type,i)=>({id:`batch-cue-${index}-${i}`,track_id:t.id,run_id:'batch-run-'+index,type,time_ms:4000+i*(data.params.cue_mode==='INTRO_OUTRO'?1000:6000),original_time_ms:4000+i*(data.params.cue_mode==='INTRO_OUTRO'?1000:6000),confidence:type==='VOCAL_START'?30:85,rank:1,beat:8,band:type==='VOCAL_START'?'reject':'high',evidence:[],accepted:null,cue_kind:null})));
      if(memoryOverflowFixture) batchCandidates = batchTracks.flatMap((t,index)=>memoryScores.map((confidence,i)=>({id:`overflow-${index}-${i}`,track_id:t.id,run_id:'overflow-run-'+index,type:data.params.cue_targets[i%data.params.cue_targets.length],time_ms:i*1000,original_time_ms:i*1000,confidence,rank:i+1,beat:i*2,band:confidence>=66?'high':confidence>=40?'review':'reject',evidence:[],accepted:null,cue_kind:null})));
      candidates = batchCandidates;
    } else if (data.params.cue_mode==='INTRO_OUTRO') {
      purposeMode=true;
      candidates=data.params.intro_outro.targets.flatMap((type,i)=>Array.from({length:type.endsWith('_INTERVAL')?5:1},(_,n)=>({id:`special-${type}-${n}`,track_id:'purpose-track',run_id:'special-run',type,time_ms:1000+i*1000+n*500,original_time_ms:1000+i*1000+n*500,confidence:85,rank:n+1,beat:2+i*2+n,band:'high',evidence:[],accepted:null,cue_kind:null})));
    } else if (data.params.cue_targets) {
      purposeMode = true;
      candidates = data.params.cue_targets.map((type,i)=>({id:'purpose-'+i,run_id:'purpose-run',type,time_ms:({CHORUS_START:4000,CHORUS_END:24000,CHORUS_END_MINUS_8_BARS:8000,VOCAL_START:6000,INTRO_START:0,INTRO_END:2000,OUTRO:27500,OUTRO_END:28000})[type],confidence:type==='VOCAL_START'?30:85,rank:1,beat:8,band:type==='VOCAL_START'?'reject':'high',evidence:[{name:'候補の位置と根拠',weight:100,score:type==='VOCAL_START'?.3:.85,detail:type==='VOCAL_START'?'Verse先頭の仮候補です。歌声は検出していません。':'rekordbox の Chorus フレーズ境界'}],accepted:null,cue_kind:null}));
      candidates.forEach(c=>c.original_time_ms=c.time_ms);
    }
    const jobId = batchMode ? memoryOverflowFixture ? 'batch-overflow' : 'batch' : 'one';
    if(batchMode) jobs.push({...jobs[0],id:jobId});
    result = { job_id: jobId };
  }
  else if (url.pathname === '/api/v1/jobs') result = { jobs };
  else if (url.pathname.endsWith('/candidates')) result = { candidates };
  else if (url.pathname.endsWith('/candidates/accept')) {
    assert.equal(req.headers.authorization,'Bearer ux-test');
    assert(data.candidate_ids.length>0);
    if(bulkFailure) {res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'テスト用: 候補が変更されています。結果を再取得してください。'}));return;}
    bulkWrites++;
    await sleep(250);
    for(const c of candidates) if(data.candidate_ids.includes(c.id))Object.assign(c,{accepted:true,cue_kind:data.cue_kind==='PRESET'?(jobs[0].params?.cue_settings?.[c.type]??jobs[0].params?.cue_default)?.cue_kind??'MEMORY':data.cue_kind});
    result={candidates};
  }
  else if (url.pathname === '/api/v1/rekordbox/playlists') result = { available: true, reason: null, playlists: [
    { id:'folder',name:'Sets',path:'Sets',is_folder:true,is_smart:false,parent_id:null },
    { id:'set',name:'Weekend',path:'Sets / Weekend',is_folder:false,is_smart:false,parent_id:'folder' },
    { id:'empty',name:'Empty',path:'Empty',is_folder:false,is_smart:false,parent_id:null }
  ] };
  else if (url.pathname.startsWith('/api/v1/rekordbox/playlists/')) {
    const id = url.pathname.split('/')[5];
    const query = (url.searchParams.get('query') || '').toLowerCase();
    const offset = Number(url.searchParams.get('offset') || 0);
    let tracks = id === 'empty' ? [] : Array.from({length:51},(_,i)=>({content_id:'playlist-'+i,title:'Playlist song '+(i+1),artist:'Playlist artist',path:i===1?null:'C:/Music/Playlist'+i+'.wav',bpm:126.5,length_sec:180}));
    tracks = tracks.filter(t=>t.title.toLowerCase().includes(query));
    result = {available:true,reason:null,playlist_id:id,playlist_name:id==='empty'?'Empty':'Weekend',total:tracks.length,has_more:offset+50<tracks.length,tracks:tracks.slice(offset,offset+50)};
  }
  else if (url.pathname.endsWith('/grid/plan')) {
    if (gridFail) { res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'解析データが変わりました。変更内容を再確認してください。'}));return; }
    result = {...gridPreview(data.first_beat),plan_id:'a'.repeat(32),expires_in:600};
  }
  else if (url.pathname.endsWith('/grid/apply')) { assert.equal(data.plan_id,'a'.repeat(32)); assert.equal(gridRunning,false); await sleep(250); gridSaves++; gridOffset++; result={ok:true,message:'小節頭を保存しました。rekordbox を起動して曲を読み込み直してください。',backup_dir:'C:/AppData/grid-backups/test'}; }
  else if (url.pathname.endsWith('/grid')) result = gridPreview(1);
  else if (batchMode && url.pathname.endsWith('/write/export-xml')) {lastExport=data;result={folder:'C:/AppData/exports/test-batch',xml_path:'C:/AppData/exports/test-batch/rekordbox.xml',tracks:batchTracks.length,cues:xmlEntries(data).length,copied:batchTracks.length,skipped:[],cue_colors:data.cue_colors,warnings:[]};}
  else if (url.pathname === '/api/v1/jobs/ai-progress/tracks') result = {tracks:[{id:'ai-progress-track',content_id:'AI1',path:'C:/Music/Long song.wav',title:'Long song',format:'WAV',status:jobs.find(j=>j.id==='ai-progress').status==='RUNNING'?'RUNNING':'COMPLETED',duration_ms:440000,
    analysis:{source:'REKORDBOX',available:false,analysis_quality:'AI',ai_started_at:new Date(Date.now()-103000).toISOString(),stage:'AIで音源を分離しています。',
      ai_progress:{phase:'SEPARATING',percent:aiProgressPercent,elapsed_sec:103,remaining_sec:197}}}]};
  else if (url.pathname === '/api/v1/jobs/metadata/tracks') result = {tracks:[metadataTrack]};
  else if (batchMode && url.pathname.endsWith('/tracks') && !url.pathname.includes('rekordbox')) result = {tracks:batchTracks};
  else if (url.pathname.endsWith('/analysis') && url.pathname.includes('/rekordbox/tracks/')) {
    await sleep(100);
    result = url.pathname.includes('/playlist-50/') ? {source:'REKORDBOX',available:false,reason:'BPM / Grid を解析してから再取得してください',warnings:[]} : {source:'REKORDBOX',available:true,bpm:129.25,key:'Am',beat_count:384,downbeat_count:96,phrase_count:12,existing_cues:[{time_ms:10000,kind:0,comment:'Existing'}],warnings:[]};
  }
  else if (url.pathname.endsWith('/tracks') && !url.pathname.includes('rekordbox')) result = { tracks: purposeMode && url.pathname.includes('/one/') ? [{id:'purpose-track',content_id:'RB1',path:'C:/Music/Library.wav',format:'WAV',status:'COMPLETED',duration_ms:30000,analysis:{source:'REKORDBOX',available:true,bpm:120,beat_count:60,downbeat_count:15,phrase_count:6,phrase_used:true,section_labels_used:true,warnings:['歌い始めは Verse 先頭の仮候補です。歌声の自動検出ではありません。']}}] : url.pathname.includes('/two/') ? [{id:'meta',content_id:'meta',path:'C:/Music/Second song.wav',format:'WAV',status:'COMPLETED',duration_ms:180000,analysis:{source:'REKORDBOX',available:true,bpm:129.25,key:'Am',beat_count:384,downbeat_count:96,phrase_count:12,phrase_used:true,existing_cues:[{time_ms:10000,kind:0,comment:'Existing'}],warnings:[]}}] : [] };
  else if (url.pathname.endsWith('/preview-position')) { previewCalls++;const unit=data.snap_to==='BAR'?2000:500;const ms=Math.round(data.time_ms/unit)*unit+data.step*unit;result={time_ms:ms,beat:Math.round(ms/500)}; }
  else if (url.pathname.endsWith('/candidates/manual')) {
    manualAdds++;candidates=candidates.map(c=>({...c,id:c.id+'-fork'}));
    const ms=Math.round(data.time_ms/500)*500;
    const manual={id:'manual-'+manualAdds,run_id:'manual-run',type:data.target,time_ms:ms,original_time_ms:ms,beat:ms/500,confidence:0,rank:2,band:'reject',evidence:[{name:'利用者が指定した位置',weight:100,score:0,detail:'自動検出ではありません。'}],accepted:null,cue_kind:null};candidates.push(manual);result=manual;
  }
  else if (url.pathname.endsWith('/decision')) { decisionWrites++;await sleep(250); const c = candidates.find(c => url.pathname.includes(`/${c.id}/`)); Object.assign(c, data); if(data.edited_time_ms!=null)c.time_ms=data.edited_time_ms;result = { decision_id: 'decision', candidate_id: c.id,time_ms:c.time_ms,beat:c.beat }; }
  else if (url.pathname.endsWith('/export.csv')) { csvAuth = req.headers.authorization === 'Bearer ux-test'; res.end('type,time_ms\nDROP,60000'); return; }
  else if (url.pathname.endsWith('/write/plan')) {lastPlan=data; const items=xmlEntries(data);result = { plan_id: 'plan', confirmation_hash: 'hash', add: items.length, replace: 0, conflict: 0, items };}
  else if (url.pathname.endsWith('/write/export-xml')) { lastExport = data; result = {folder:'C:/AppData/exports/test',xml_path:'C:/AppData/exports/test/rekordbox.xml',tracks:1,cues:xmlEntries(data).length,copied:1,skipped:[],cue_colors:data.cue_colors,cue_settings_used:xmlEntries(data).some(c=>c.preset),warnings:['Memory Cue の色も XML に記録しました。rekordbox での色の反映は未確認のため、取り込み後に確認してください。']}; }
  else if (url.pathname.includes('/rekordbox/tracks')) result = { available: true, tracks: [{ content_id: 'RB1', title: 'Library song', artist: 'Artist', path: 'C:/Music/Library.wav', bpm: 128 }] };
  else result = jobs.find(j => url.pathname.endsWith('/' + j.id)) || {};
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(result));
});
server.on('upgrade', (req, socket) => socket.destroy());
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browserRoot = process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA,'ms-playwright');
  const cachedBrowser = browserRoot && fs.existsSync(browserRoot) ? fs.readdirSync(browserRoot).filter(n=>n.startsWith('chromium_headless_shell-')).sort().reverse().map(n=>path.join(browserRoot,n,'chrome-headless-shell-win64/chrome-headless-shell.exe')).find(p=>fs.existsSync(p)) : null;
  const exe = process.env.CHROMIUM_PATH || cachedBrowser;
  if (!exe || !fs.existsSync(exe)) { server.close();throw new Error('Set CHROMIUM_PATH to a Chromium executable.'); }
  const profile = path.join(out, 'profile');
  try { fs.unlinkSync(path.join(profile, 'DevToolsActivePort')); } catch {}
  const browser = spawn(exe, ['--headless', '--disable-gpu', '--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let ws;
  try {
    let port;
    for (let i=0; i<100; i++) { try { port = fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]; break; } catch {} await sleep(100); }
    assert(port, 'browser startup');
    const pages = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
    ws = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', reject); });
    let seq=0; const pending = new Map(); const errors=[];
    ws.addEventListener('message', ({ data }) => { const msg=JSON.parse(data); if (msg.id) { const p=pending.get(msg.id); pending.delete(msg.id); if (msg.error) p.reject(Error(JSON.stringify(msg.error))); else p.resolve(msg.result); } if (msg.method==='Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.text); });
    const call = (method, params={}) => new Promise((resolve,reject) => { const id=++seq; pending.set(id,{resolve,reject}); ws.send(JSON.stringify({id,method,params})); });
    const evaluate = async expression => { const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true}); if(r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails)); return r.result.value; };
    const until = async expression => { for(let i=0;i<60;i++) { if(await evaluate(`Boolean(${expression})`)) return; await sleep(100); } const state=await evaluate("Array.from(document.querySelectorAll('audio')).map(a=>({src:a.src,time:a.currentTime,paused:a.paused,ready:a.readyState,error:a.error?.message}))");throw Error(`Timed out: ${expression}\nAudio: ${JSON.stringify(state)}\nRuntime: ${JSON.stringify(errors)}`); };
    const click = label => evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`);
    const tap = async selector => {
      const rect=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
      await call('Input.dispatchMouseEvent',{type:'mousePressed',...rect,button:'left',clickCount:1});
      await call('Input.dispatchMouseEvent',{type:'mouseReleased',...rect,button:'left',clickCount:1});
    };
    const input = (id,value) => evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    const setColor = async (label,value) => {
      if(label==='Memory Cue の色') {
        await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').click()");
        await until("document.querySelector('.memory-palette-menu')");
        await evaluate(`document.querySelector('.memory-palette-menu button[data-color="${value}"]').click()`);
      } else await evaluate(`(()=>{const e=document.querySelector('input[aria-label="${label}"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    };
    const openColors = async () => { await evaluate("Array.from(document.querySelectorAll('.panel')).find(p=>p.querySelector('h2')?.textContent.includes('キュー色設定')).querySelector('button').click()");await until("document.querySelector('button[aria-label=\"Memory Cue の色\"]')"); };
    await call('Runtime.enable');
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
    await call('Page.navigate',{url:base+'/?token=ux-test'});
    await until("document.querySelectorAll('.job').length===2");
    await evaluate("localStorage.removeItem('aicue.cuePresets');localStorage.setItem('aicue.exportMode','COPY');localStorage.removeItem('aicue.collectionXml')");
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length===2");
    assert.equal(await evaluate("document.querySelector('.advanced-settings').open"),false);
    await until("document.querySelector('#analysis-quality').value==='AI'");
    await evaluate("(()=>{const s=document.querySelector('#analysis-quality');s.value='STANDARD';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length===2 && document.querySelector('#analysis-quality').value==='STANDARD'");
    await evaluate("(()=>{const s=document.querySelector('#analysis-quality');s.value='AI';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await click('ファイルパスから');
    await input('audio-path','"C:\\Music\\Quoted song.wav"');
    assert.equal(await evaluate("document.querySelector('#phrase-length').value"),'64');
    for (const beats of [8, 16, 4]) {
      await click(`${beats} Beat`);
      await until(`document.querySelector('#phrase-length').value==='${beats}'`);
      assert.equal(await evaluate(`document.querySelector('.beat-presets button[aria-pressed="true"]').textContent`),`${beats} Beat`);
    }
    await evaluate("(()=>{const s=document.querySelector('#phrase-length');s.value='4';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await evaluate("(()=>{const s=document.querySelector('.phrase-unit');s.value='bars';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelector('#phrase-length').value==='1'");
    await evaluate("(()=>{const s=document.querySelector('.phrase-unit');s.value='beats';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelector('#phrase-length').value==='4'");
    await click('解析を開始 →');
    await until("document.querySelector('.result-title')?.textContent==='First song.wav'");
    assert.equal(created.tracks[0].path,'C:\\Music\\Quoted song.wav');
    assert.equal(created.params.bpm,null);
    assert.equal(created.params.analysis_quality,'AI');
    assert.equal(created.params.beats_per_phrase,4);
    assert.equal(created.params.bars_per_phrase,undefined);
    await until("document.querySelector('#analysis-result').textContent.includes('解析単位：4 Beat（1 小節）')");
    await until("document.querySelectorAll('.table-scroll tbody tr').length===2");
    assert.equal(await evaluate("document.querySelectorAll('.cue-dock-row[data-state=candidate]').length"),2,'unadopted cues appear in the dock');
    assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('.cue-dock-row time')).map(e=>e.textContent)"),['00:30:000','01:00:000']);
    const beforeDockFilter = decisionWrites;
    await evaluate("document.querySelector('.cue-dock-filter input').click()");
    await until("document.querySelectorAll('.cue-dock-row').length===0 && document.querySelector('.cue-dock-empty').textContent.includes('未採用の候補も表示')");
    await evaluate("document.querySelector('.cue-dock-filter input').click()");
    await until("document.querySelectorAll('.cue-dock-row').length===2");
    await click('HOT CUE');
    await until("document.querySelector('.cue-dock button[aria-pressed=true]').textContent==='HOT CUE'");
    assert.equal(await evaluate("document.querySelectorAll('.cue-dock-row[data-state=candidate]').length"),2,'candidates can be previewed before choosing a cue kind');
    await click('MEMORY');
    assert.equal(decisionWrites,beforeDockFilter,'dock filtering must never adopt cues');
    await click('Memory Cue');
    await until("document.body.textContent.includes('保存中…')");
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='書き出すキューを確認').disabled"), true);
    await until("document.querySelector('.decision-accepted')?.textContent==='採用 (Memory Cue)'");
    await click('書き出すキューを確認');
    await until("document.querySelector('[aria-label=\"書き込み内容\"]')");
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('rekordbox へ書き込み'))"),false);
    await click('再診断');
    await until("document.body.textContent.includes('ライブラリDBは読み取り専用')");
    await click('Hot Cue');
    await until("document.querySelector('.decision-accepted')?.textContent==='採用 (Hot Cue)'");
    assert.equal(await evaluate("!!document.querySelector('[aria-label=\"書き込み内容\"]')"),false);
    await click('両方');
    await until("document.querySelector('.decision-accepted')?.textContent==='採用 (Memory Cue + Hot Cue)'");
    assert.equal(await evaluate("document.body.textContent.includes('合計 2 キュー')"), true);
    await openColors();
    await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').click()");
    await until("document.querySelectorAll('.memory-palette-menu [role=menuitemradio]').length===9");
    assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('.memory-palette-menu button')).map(b=>b.children[1].textContent)"),['桃','赤','橙','黄','緑','水','青','紫','未設定']);
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Home',code:'Home'});
    await until("document.activeElement.dataset.color==='#ff66ff'");
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown'});
    await until("document.activeElement.dataset.color==='#ff0000'");
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowUp',code:'ArrowUp'});
    await until("document.activeElement.dataset.color==='#ff66ff'");
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'End',code:'End'});
    await until("document.activeElement.dataset.color==='NONE'");
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await until("!document.querySelector('.memory-palette-menu') && document.activeElement.getAttribute('aria-label')==='Memory Cue の色'");
    for(const value of ['#ff66ff','#ff0000','#ff9900','#ffff00','#00ff00','#00ffff','#0000ff','#9900ff']) {
      await setColor('Memory Cue の色',value);
      assert.equal(await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value"),value);
    }
    await setColor('Drop の色','#456789');
    await setColor('Memory Cue の色','#0000ff');
    await setColor('Hot Cue の色','#ffaa00');
    await until("JSON.parse(localStorage.getItem('aicue.cueColors')).MEMORY==='#0000ff'");
    assert.equal(await evaluate("JSON.parse(localStorage.getItem('aicue.cueColors')).HOT"),'#ffaa00');
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Drop の色\"]').value"),'#456789');
    assert.equal(await evaluate("getComputedStyle(Array.from(document.querySelectorAll('.cue-decision-actions button')).find(b=>b.textContent.trim()==='Memory Cue')).backgroundColor"),'rgb(0, 0, 255)');
    assert.equal(await evaluate("getComputedStyle(Array.from(document.querySelectorAll('.cue-decision-actions button')).find(b=>b.textContent.trim()==='Memory Cue')).color"),'rgb(255, 255, 255)');
    assert.equal(await evaluate("getComputedStyle(Array.from(document.querySelectorAll('.cue-decision-actions button')).find(b=>b.textContent.trim()==='Hot Cue')).color"),'rgb(16, 19, 27)');
    assert.equal(await evaluate("document.querySelector('.timeline-marker').style.background.includes('rgb(0, 0, 255)') && document.querySelector('.timeline-marker').style.background.includes('rgb(255, 170, 0)')"),true,'BOTH timeline keeps both configured colors');
    await click('📁 rekordbox XML を書き出し');
    await until("document.body.textContent.includes('書き出した色：Memory Cue #0000ff')");
    await until("document.querySelector('[aria-label=\"rekordboxへの取り込み手順\"]')");
    assert.equal(await evaluate("document.querySelector('#exported-xml-path').value"),'C:/AppData/exports/test/rekordbox.xml');
    assert.equal(await evaluate("document.querySelector('#exported-xml-path').readOnly"),true);
    assert.equal(await evaluate("document.querySelector('.xml-import-guide').textContent.includes('表示 → レイアウト') && document.querySelector('.xml-import-guide').textContent.includes('詳細 → データベース') && document.querySelector('.xml-import-guide').textContent.includes('すべての楽曲')"),true);
    await evaluate("document.querySelector('#exported-xml-path').focus()");
    assert.equal(await evaluate("(()=>{const e=document.querySelector('#exported-xml-path');return e.selectionEnd-e.selectionStart===e.value.length;})()"),true,'full XML path is selectable');
    assert.deepEqual(lastExport.cue_colors,{MEMORY:'#0000ff',HOT:'#ffaa00'});
    await setColor('Memory Cue の色','NONE');
    await until("JSON.parse(localStorage.getItem('aicue.cueColors')).MEMORY==='NONE'");
    await click('📁 rekordbox XML を書き出し');
    await until("document.body.textContent.includes('書き出した色：Memory Cue 未設定')");
    assert.deepEqual(lastExport.cue_colors,{MEMORY:null,HOT:'#ffaa00'});
    assert.equal(await evaluate("document.querySelector('.cue-dock-note').textContent"),'色：未設定');
    assert.equal(await evaluate("document.querySelectorAll('.cue-dock-row[data-state=accepted]').length"),1,'MEMORY dock lists the accepted BOTH cue');
    assert.equal(await evaluate("document.querySelectorAll('.cue-dock-row[data-state=candidate]').length"),1,'unset color does not hide the remaining candidate');
    await evaluate("document.querySelector('.cue-dock-filter input').click()");
    await until("document.querySelectorAll('.cue-dock-row').length===1");
    await click('HOT CUE');
    await until("document.querySelector('.cue-dock button[aria-pressed=true]').textContent==='HOT CUE'");
    assert.equal(await evaluate("document.querySelectorAll('.cue-dock-row').length"),1);
    await click('MEMORY');
    await evaluate("document.querySelector('.cue-dock-filter input').click()");
    await until("document.querySelectorAll('.cue-dock-row').length===2");
    assert.equal(await evaluate("document.body.textContent.includes('rekordbox での色の反映は未確認')"),true);
    await evaluate("document.querySelector('button[aria-label=\"Memory Cue を既定色に戻す\"]').click()");
    await until("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value==='#00ffff'");
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Hot Cue の色\"]').value"),'#ffaa00');
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Drop の色\"]').value"),'#456789');
    await setColor('Memory Cue の色','#0000ff');
    await evaluate("document.querySelectorAll('.job')[1].click()");
    await until("document.querySelector('.result-title')?.textContent==='Second song.wav'");
    await until("document.querySelector('#analysis-result').textContent.includes('rekordbox の解析済みデータを使用')");
    await evaluate("document.querySelectorAll('.job')[0].click()");
    await until("document.querySelector('.result-title')?.textContent==='First song.wav' && document.querySelector('.decision-accepted')?.textContent==='採用 (Memory Cue + Hot Cue)'");
    await evaluate("(()=>{const s=document.querySelector('#cue-filter');s.value='accepted';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===1");
    for (const mode of ['memory', 'hot']) {
      await evaluate(`(()=>{const s=document.querySelector('#cue-filter');s.value='${mode}';s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
      await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===1");
    }
    await evaluate("(()=>{const s=document.querySelector('#cue-filter');s.value='all';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===2");
    await evaluate("Array.from(document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr')[1].querySelectorAll('button')).find(b=>b.textContent.trim()==='Memory Cue').click()");
    await until("document.body.textContent.includes('合計 3 キュー')");
    assert.equal(await evaluate("document.querySelector('.cue-kind-counts').textContent.includes('Memory Cue 2 件') && document.querySelector('.cue-kind-counts').textContent.includes('Hot Cue 1 件')"), true);
    await click('CSV を保存');
    for(let i=0;i<20&&!csvAuth;i++) await sleep(100);
    assert(csvAuth,'CSV must send authentication');
    await click('rekordbox から'); await click('検索');
    await until("document.querySelectorAll('.rb-item').length===1");
    await evaluate("document.querySelector('.rb-item').click()");
    await until("document.querySelector('.selected-track strong')?.textContent==='Library song'");
    await until("document.querySelector('.analysis-source-info').textContent.includes('384 拍')");
    assert.equal(await evaluate("document.querySelector('#analysis-bpm').value"),'129.25');
    assert.equal(await evaluate("document.querySelector('#analysis-bpm').disabled"),true);
    await click('小節頭を調整 ▾');
    await until("document.querySelector('#grid-first-beat')");
    await evaluate("(()=>{const s=document.querySelector('#grid-first-beat');s.value='2';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelector('.grid-beats .downbeat .grid-beat-before').textContent==='元 2'");
    await click('1拍後 →');
    await until("document.querySelector('#grid-first-beat').value==='3'");
    await click('← 1拍前');
    await until("document.querySelector('#grid-first-beat').value==='2'");
    await evaluate("document.querySelectorAll('.grid-beat')[2].click()");
    await until("document.querySelector('#grid-first-beat').value==='3'");
    await click('元に戻す');
    await until("document.querySelector('#grid-first-beat').value==='1'");
    await evaluate("document.querySelectorAll('.grid-beat')[1].click()");
    await until("document.querySelector('#grid-first-beat').value==='2'");
    assert.equal(audioReads,0,'no audio download before asking to play');
    await click('▶ 選んだ小節頭から試聴');
    await until("!document.querySelector('.grid-audition audio').paused && document.querySelector('.grid-audition audio').readyState>=2 && document.querySelector('.grid-audition audio').duration===30 && document.querySelector('.grid-audition audio').currentTime>=0.637");
    assert.equal(await evaluate("document.querySelector('.grid-audition audio').duration"),30);
    assert(audioReads>0,'playback uses authenticated library audio');
    await click('停止');
    await until("document.querySelector('.grid-audition audio').paused");
    await evaluate("(async()=>{const other=document.createElement('audio');other.id='other-preview';other.src=document.querySelector('.grid-audition audio').src;document.body.append(other);await other.play();})()");
    await until("!document.querySelector('#other-preview').paused");
    await click('▶ 選んだ小節頭から試聴');
    await until("!document.querySelector('.grid-audition audio').paused && document.querySelector('#other-preview').paused");
    await click('停止');
    await evaluate("document.querySelector('#other-preview').remove()");
    assert.equal(gridSaves,0,'preview and selection must never save');
    await click('変更内容を確認');
    await until("document.querySelector('.grid-confirm')");
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='rekordbox へ小節頭を保存').disabled"),true,'save blocked while rekordbox runs');
    gridRunning = false;
    await click('調整に戻る');
    await until("!document.querySelector('.grid-confirm')");
    gridFail = true;
    await click('変更内容を確認');
    await until("document.querySelector('.grid-editor [role=alert]')?.textContent==='解析データが変わりました。変更内容を再確認してください。'");
    gridFail = false;
    await click('変更内容を確認');
    await until("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='rekordbox へ小節頭を保存')?.disabled===false");
    assert.equal(gridSaves,0,'confirmation must never save');
    assert.equal(await evaluate("document.querySelector('.grid-confirm strong').textContent"),'Library song');
    await evaluate("window.realNow=Date.now;Date.now=()=>window.realNow()+601000");
    await until("document.querySelector('.grid-confirm').textContent.includes('有効期限が切れました')");
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='rekordbox へ小節頭を保存').disabled"),true);
    await evaluate("Date.now=window.realNow");
    await click('変更内容を確認');
    await until("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='rekordbox へ小節頭を保存')?.disabled===false");
    await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,'grid mobile overflow');
    const gridShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    fs.writeFileSync(path.join(out,'grid-editor.png'),Buffer.from(gridShot.data,'base64'));
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
    await click('rekordbox へ小節頭を保存');
    await until("document.querySelector('.grid-editor').textContent.includes('小節頭を保存しました')");
    await until("!document.querySelector('.start-analysis').disabled");
    assert.equal(gridSaves,1,'only explicit save applies the edit');
    assert.equal(await evaluate("document.querySelector('.grid-editor').textContent.includes('C:/AppData/grid-backups/test')"),true);
    await click('解析を開始 →');
    for (let i=0;i<30 && created.params.analysis_source!=='REKORDBOX';i++) await sleep(50);
    assert.equal(created.params.analysis_source,'REKORDBOX');
    assert.equal(created.params.bpm,129.25);
    await click('プレイリストから');
    await until("document.querySelectorAll('#rekordbox-playlist option').length===4");
    assert.equal(await evaluate("document.querySelector('#rekordbox-playlist option[value=folder]').disabled"), true);
    await evaluate("(()=>{const s=document.querySelector('#rekordbox-playlist');s.value='set';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button').length===50");
    assert.equal(await evaluate("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button')[1].disabled"),true);
    await click('続きを表示');
    await until("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button').length===51");
    await input('playlist-track-search','51');
    await click('絞り込む');
    await until("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button').length===1");
    await evaluate("document.querySelector('[aria-label=\"プレイリストの楽曲\"] button').click()");
    await until("document.querySelector('.selected-track strong')?.textContent==='Playlist song 51'");
    await until("document.querySelector('.analysis-source-info').textContent.includes('BPM / Grid を解析してから再取得してください')");
    assert.equal(await evaluate("document.querySelector('.start-analysis').disabled"),true);
    await evaluate("(()=>{const s=document.querySelector('#rekordbox-playlist');s.value='empty';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelector('.playlist-browser').textContent.includes('このプレイリストに曲はありません。')");
    await evaluate("(()=>{const s=document.querySelector('#rekordbox-playlist');s.value='set';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await until("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button').length===50");
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
    const desktop=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    fs.writeFileSync(path.join(out,'desktop.png'),Buffer.from(desktop.data,'base64'));
    await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    await sleep(200);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,'mobile overflow');
    await evaluate("document.querySelectorAll('.job')[1].click()");
    await until("document.querySelector('.result-title')?.textContent==='Second song.wav' && scrollY>0");
    const mobile=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    fs.writeFileSync(path.join(out,'mobile.png'),Buffer.from(mobile.data,'base64'));
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length===2");
    await openColors();
    assert.equal(await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value"),'#0000ff');
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Hot Cue の色\"]').value"),'#ffaa00');
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Drop の色\"]').value"),'#456789');
    await evaluate("document.querySelector('.color-list').closest('.panel').scrollIntoView({block:'start'})");
    await sleep(300);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,'color settings mobile overflow');
    const colorsShot=await call('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(path.join(out,'cue-colors.png'),Buffer.from(colorsShot.data,'base64'));
    await setColor('Memory Cue の色','NONE');
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length===2");
    await openColors();
    assert.equal(await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value"),'NONE','unset survives reload');
    await evaluate("document.querySelector('.memory-palette').scrollIntoView({block:'center'})");
    await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').click()");
    await until("document.querySelector('.memory-palette-menu')");
    const paletteShot=await call('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(path.join(out,'memory-palette-390.png'),Buffer.from(paletteShot.data,'base64'));
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await click('すべて既定に戻す');
    await until("document.querySelector('input[aria-label=\"Hot Cue の色\"]').value==='#ff5d73'");
    assert.equal(await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value"),'#00ffff');
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"Drop の色\"]').value"),'#ff5d73');
    await evaluate("localStorage.setItem('aicue.cueColors','null')");
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length===2");
    await openColors();
    assert.equal(await evaluate("document.querySelector('button[aria-label=\"Memory Cue の色\"]').value"),'#00ffff');
    await click('検索');
    await until("document.querySelector('.rb-item')");
    await evaluate("document.querySelector('.rb-item').click()");
    await until("!document.querySelector('.start-analysis').disabled");
    await click('目的から選ぶ');
    await until("document.querySelectorAll('.cue-target-options input:checked').length===8");
    await click('選択を解除');
    await until("document.querySelector('.start-analysis').disabled");
    assert.equal(await evaluate("document.querySelector('.analysis-readiness').textContent.includes('1つ以上') && !document.querySelector('.analysis-readiness').classList.contains('ready')"),true);
    for(const type of ['CHORUS_START','CHORUS_END_MINUS_8_BARS','VOCAL_START']) await evaluate(`document.querySelector('.cue-target-options input[value="${type}"]').click()`);
    await click('解析を開始 →');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===3 && document.querySelector('.manual-cue-form')");
    assert.deepEqual(created.params.cue_targets,['CHORUS_START','CHORUS_END_MINUS_8_BARS','VOCAL_START']);
    assert.equal(await evaluate("document.querySelector('#analysis-result').textContent.includes('歌声の自動検出ではありません')"),true);
    const decisionsBefore=decisionWrites;
    await until("document.querySelectorAll('.cue-dock-row[data-state=candidate]').length===3 && document.querySelector('.timeline audio')?.readyState>=1");
    await evaluate("document.querySelector('.cue-dock-row').click()");
    await until("document.querySelector('.timeline audio').currentTime>=4 && !document.querySelector('.timeline audio').paused");
    assert.equal(decisionWrites,decisionsBefore,'auditioning a pending cue never adopts it');
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      await evaluate("document.querySelector('.cue-dock').scrollIntoView({block:'center'})");
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`Cue dock overflow at ${width}`);
      const dockShot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`cue-dock-candidates-${width}.png`),Buffer.from(dockShot.data,'base64'));
    }
    await click('位置を調整');
    await until("document.querySelector('.candidate-position-editor')");
    await click('1拍 →');
    await until("document.querySelector('input[aria-label=\"Cueを置く時刻（秒）\"]').value==='4.500'");
    assert(previewCalls>0);assert.equal(decisionWrites,decisionsBefore,'position preview must never adopt a cue');
    assert.equal(await evaluate("document.querySelector('.manual-cue-add').matches(':disabled')"),true,'manual additions wait for position adjustment');
    await click('調整位置を試聴');
    await until("document.querySelector('.timeline audio').currentTime>=4.5 && !document.querySelector('.timeline audio').paused");
    await click('Memory Cue');
    await until("!document.querySelector('.candidate-position-editor') && document.querySelector('.decision-accepted')");
    assert.equal(candidates[0].time_ms,4500);
    await evaluate("document.querySelector('.cue-dock-row').click()");
    await until("document.querySelector('.timeline audio').currentTime>=4.5 && !document.querySelector('.timeline audio').paused");
    await until("!document.querySelector('.manual-cue-add').matches(':disabled')");
    await evaluate("document.querySelector('.manual-cue-form').open=true");
    await input('manual-cue-seconds','10.123');
    await click('確認用の候補を追加');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===4 && document.querySelector('.manual-cue-form').textContent.includes('確認用の候補を追加しました')");
    assert.equal(manualAdds,1);assert.equal(candidates[0].accepted,true);
    assert.equal(candidates.find(c=>c.id.startsWith('manual-')).accepted,null);
    const purposes=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    fs.writeFileSync(path.join(out,'purpose-cues.png'),Buffer.from(purposes.data,'base64'));
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
    await click('複数曲を一括');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 1 / 200曲') && !document.querySelector('.start-analysis').disabled");
    await click('プレイリストから');
    await until("document.querySelectorAll('#rekordbox-playlist option').length===4");
    const select = (id,value) => evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    await select('rekordbox-playlist','set');
    await until("document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button').length===50");
    await click('プレイリスト全曲を選ぶ');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 51 / 200曲')");
    await until("document.querySelector('.batch-selection').textContent.includes('BPM / Grid を解析してから再取得してください')");
    assert.equal(await evaluate("document.querySelector('.start-analysis').disabled"),true,'any unavailable grid blocks the batch');
    await click('解析できない曲を外す');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 50 / 200曲') && !document.querySelector('.start-analysis').disabled");
    await click('全曲を外す');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 0 / 200曲') && document.querySelector('.start-analysis').disabled");
    for(const index of [0,2]) await evaluate(`document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button')[${index}].click()`);
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 2 / 200曲') && !document.querySelector('.start-analysis').disabled");
    await click('表示中の曲をまとめて選ぶ');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 49 / 200曲')");
    await click('全曲を外す');
    await until("document.querySelector('.batch-selection').textContent.includes('選択中 0 / 200曲')");
    for(const index of [0,2]) await evaluate(`document.querySelectorAll('[aria-label=\"プレイリストの楽曲\"] button')[${index}].click()`);
    await until("!document.querySelector('.start-analysis').disabled");
    await click('2曲を一括解析 →');
    await until("document.querySelector('.result-title')?.textContent==='2曲の一括解析' && document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===6");
    assert.equal(created.tracks.length,2);
    assert.equal(created.params.bpm,null,'batch uses each track grid instead of the first BPM');
    assert.deepEqual(created.params.cue_targets,['CHORUS_START','CHORUS_END_MINUS_8_BARS','VOCAL_START']);
    assert.equal(await evaluate("document.querySelectorAll('.candidate-track-name').length>=6"),true);
    await evaluate("Array.from(document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr')[3].querySelectorAll('button')).find(b=>b.textContent.trim()==='試聴').click()");
    await until("document.querySelector('.timeline audio').src.includes('/tracks/batch-1/audio') && !document.querySelector('.timeline audio').paused && document.querySelector('.timeline audio').currentTime>=4");
    assert.equal(await evaluate("document.querySelector('#result-timeline h2').textContent.includes('Playlist2.wav')"),true,'audition matches the selected candidate track');
    await evaluate("document.querySelectorAll('.result-track')[0].click()");
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===3 && document.querySelector('.timeline audio').src.includes('/tracks/batch-0/audio')");
    await click('位置を調整');
    await until("document.querySelector('.candidate-position-editor')");
    assert.equal(await evaluate("document.querySelectorAll('.result-track')[1].disabled"),true,'changing track waits for edits');
    await click('調整を破棄');
    await until("!document.querySelectorAll('.result-track')[1].disabled");
    await click('全曲の候補を表示');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===6");
    await click('表示中の候補を選ぶ');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] input:checked').length===6");
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='選択した6候補を一括採用').disabled"),true,'requires review before applying');
    await select('bulk-cue-kind','BOTH');
    await evaluate("document.querySelector('.batch-cue-actions .inline-check input').click()");
    bulkFailure=true;
    await click('選択した6候補を一括採用');
    await until("document.body.textContent.includes('テスト用: 候補が変更されています')");
    assert.equal(candidates.filter(c=>c.accepted).length,0,'failed bulk call must not show accepted rows');
    bulkFailure=false;
    await until("!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='選択した6候補を一括採用').disabled");
    await click('選択した6候補を一括採用');
    await until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='一括採用しています…')");
    assert.equal(await evaluate("document.querySelectorAll('.result-track')[0].disabled"),true);
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('rekordbox XML を書き出し')).disabled"),true);
    await until("document.querySelectorAll('.decision-accepted').length===6");
    assert.equal(bulkWrites,1);
    assert.equal(await evaluate("document.querySelector('.cue-kind-counts').textContent.includes('Memory Cue 6 件') && document.querySelector('.cue-kind-counts').textContent.includes('Hot Cue 6 件')"),true);
    await evaluate("document.querySelectorAll('.result-track')[0].click()");
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===3");
    await click('📁 rekordbox XML を書き出し');
    await until("document.querySelector('#analysis-result').textContent.includes('キュー 12')");
    assert.equal(lastExport.job_id,'batch');
    assert.equal(await evaluate("document.querySelector('#analysis-result').textContent.includes('楽曲 2 ・キュー 12')"),true);
    assert.equal(candidates.filter(c=>c.accepted).length,6,'export includes accepted candidates from all tracks despite display filter');
    for(const width of [1440,768,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      await sleep(100);
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`batch layout overflow at ${width}`);
      await evaluate("document.querySelectorAll('.toast-dismiss').forEach(b=>b.click())");
      await evaluate("document.querySelector('.batch-results').scrollIntoView({block:'start'})");
      const shot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`batch-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await tap('.batch-cue-actions .row button');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] input:checked').length===3");
    await tap('.candidate-select');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] input:checked').length===2");
    await tap('.batch-cue-actions .inline-check');
    await until("document.querySelector('.batch-cue-actions .inline-check input').checked");
    assert.equal(await evaluate("document.querySelector('.candidate-select').getBoundingClientRect().height>=40"),true,'mobile checkbox hit target');
    await evaluate("document.querySelector('.batch-cue-actions').scrollIntoView({block:'start'})");
    const reviewShot=await call('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(path.join(out,'batch-review-390.png'),Buffer.from(reviewShot.data,'base64'));
    memoryOverflowFixture=true;
    await select('candidate-count','5');
    await click('2曲を一括解析 →');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===30");
    assert.equal(created.params.top_k,5);
    await click('表示中の候補を選ぶ');
    await select('bulk-cue-kind','MEMORY');
    await evaluate("document.querySelector('.batch-cue-actions .inline-check input').click()");
    await click('選択した30候補を一括採用');
    await until("document.querySelectorAll('.decision-accepted').length===30 && document.querySelectorAll('.memory-export-row input:checked').length===20");
    assert.equal(await evaluate("document.querySelectorAll('.memory-export-row').length"),30,'all 30 accepted memory cues remain available');
    const topTen=[1,3,4,5,7,8,9,10,11,13];
    assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('.memory-export-track')[0].querySelectorAll('input')).map((e,i)=>e.checked?i:-1).filter(i=>i>=0)"),topTen);
    assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('rekordbox XML を書き出し')).disabled"),true,'auto-limited export requires confirmation');
    const decisionCountBeforeExportChoice=decisionWrites;
    await evaluate("document.querySelectorAll('.memory-export-track')[0].querySelectorAll('input')[1].click()");
    await evaluate("document.querySelectorAll('.memory-export-track')[0].querySelectorAll('input')[0].click()");
    await until("document.querySelectorAll('.memory-export-row input:checked').length===20");
    assert.equal(decisionWrites,decisionCountBeforeExportChoice,'export selection must not change adoption');
    await click('書き出すキューを確認');
    await until("document.querySelector('[aria-label=\"書き込み内容\"] tbody')?.children.length===20");
    assert.equal(lastPlan.memory_candidate_ids.includes('overflow-0-0'),true);
    assert.equal(lastPlan.memory_candidate_ids.includes('overflow-0-1'),false);
    await click('信頼度順で選び直す');
    await until("!document.querySelectorAll('.memory-export-track')[0].querySelectorAll('input')[0].checked && document.querySelectorAll('.memory-export-track')[0].querySelectorAll('input')[1].checked");
    await evaluate("document.querySelector('.memory-export-confirm input').click()");
    await click('📁 rekordbox XML を書き出し');
    await until("document.querySelector('#analysis-result').textContent.includes('楽曲 2 ・キュー 20')");
    assert.equal(lastExport.memory_candidate_ids.length,20);
    for(const group of [0,1]) assert.deepEqual(lastExport.memory_candidate_ids.filter(id=>id.startsWith(`overflow-${group}-`)).map(id=>Number(id.split('-')[2])).sort((a,b)=>a-b),topTen);
    assert.equal(candidates.filter(c=>c.accepted).length,30,'all adopted cues remain after exporting 20');
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`Memory export layout overflow at ${width}`);
      await evaluate("document.querySelectorAll('.toast-dismiss').forEach(b=>b.click());document.querySelector('.memory-export-picker').scrollIntoView({block:'start'})");
      const shot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`memory-export-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    const originalFilename='Shaggy__Jeremih__Rick_Ross__Skillibeng-Lottery_4.0-Dirty-86566843.mp3';
    const registeredTitle='Lottery 4.0 (Dirty)', registeredArtist='Shaggy, Jeremih, Rick Ross, Skillibeng';
    const displayName=registeredTitle+' · '+registeredArtist;
    metadataTrack={...batchTracks[0],id:'metadata-track',path:'C:/Music/'+originalFilename,title:registeredTitle,artist:registeredArtist,album:'Lottery 4.0'};
    jobs.push({...jobs[0],id:'metadata',total:1,completed:1,track_path:metadataTrack.path,track_title:registeredTitle,track_artist:registeredArtist});
    candidates=[];
    await call('Page.reload');
    await until("Array.from(document.querySelectorAll('.job-title')).some(e=>e.textContent.includes('Lottery 4.0 (Dirty)'))");
    await evaluate("Array.from(document.querySelectorAll('.job')).find(e=>e.textContent.includes('Lottery 4.0 (Dirty)')).click()");
    await until(`document.querySelector('.result-title')?.textContent===${JSON.stringify(displayName)}`);
    assert.equal(await evaluate(`document.querySelector('.result-title').textContent.includes(${JSON.stringify(originalFilename)})`),false,'registered title replaces the raw filename');
    for(const query of ['Rick Ross','86566843']) {
      await evaluate(`(()=>{const e=document.querySelector('input[aria-label="解析履歴を曲名で検索"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(query)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await until("document.querySelectorAll('.job').length===1");
      assert.equal(await evaluate("document.querySelector('.job-title').textContent"),displayName);
    }
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      await evaluate("document.querySelector('.result-title').scrollIntoView({block:'center'})");
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`registered metadata overflow at ${width}`);
      const shot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`track-metadata-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await click('検索');
    await until("document.querySelector('.rb-item')");
    await evaluate("document.querySelector('.rb-item').click()");
    await until("!document.querySelector('.start-analysis').disabled");
    const presetSelect=async(label,value)=>evaluate(`(()=>{const e=document.querySelector('select[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    const presetMemory=async(label,value)=>{
      await evaluate(`document.querySelector('button[aria-label='+${JSON.stringify(JSON.stringify(label))}+']').click()`);
      await until("document.querySelector('.memory-palette-menu')");
      await evaluate(`document.querySelector('.memory-palette-menu button[data-color="${value}"]').click()`);
    };
    await presetSelect('共通設定のCue種類','HOT');
    await setColor('共通設定 Hot Cue の色','#ff0000');
    await click('目的から選ぶ');
    await until("document.querySelectorAll('.cue-target-options input:checked').length===8");
    assert.equal(await evaluate("document.querySelector('select[aria-label=\"終わりの位置を合わせる小節数\"]').value"),'8');
    for(const target of ['INTRO_START','INTRO_END','OUTRO_END']) await evaluate(`document.querySelector('.cue-target-options input[value="${target}"]').closest('.cue-target-option').querySelector('details').open=true`);
    await presetSelect('イントロの始まりのCue種類','MEMORY');
    await presetMemory('イントロの始まり Memory Cue の色','#00ff00');
    await presetSelect('イントロの終わりのCue種類','BOTH');
    await presetMemory('イントロの終わり Memory Cue の色','NONE');
    await setColor('イントロの終わり Hot Cue の色','#0000ff');
    await presetSelect('アウトロの終わりのCue種類','MEMORY');
    await presetMemory('アウトロの終わり Memory Cue の色','#9900ff');
    const writesBeforePreset=decisionWrites;
    assert.equal(candidates.length,0,'configuring presets does not create or adopt cues');
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      await evaluate("document.querySelector('.cue-target-settings').scrollIntoView({block:'start'})");
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`Cue preset form overflow at ${width}`);
      const shot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`cue-presets-form-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await click('解析を開始 →');
    await until("document.querySelectorAll('[aria-label=\"キュー候補一覧\"] tbody tr').length===8");
    assert.equal(created.params.cue_default.cue_kind,'HOT');
    assert.equal(created.params.cue_default.hot_color,'#ff0000');
    assert.equal(created.params.cue_settings.INTRO_END.memory_color,null);
    assert.equal(created.params.cue_settings.INTRO_END.hot_color,'#0000ff');
    assert.equal(created.params.end_alignment_bars,8);
    assert.equal(decisionWrites,writesBeforePreset,'analysis leaves all presets unadopted');
    assert(candidates.every(c=>c.accepted===null));
    assert.equal(await evaluate("Array.from(document.querySelectorAll('.cue-decision-actions button')).filter(b=>b.textContent==='設定どおりに採用').length"),8);
    await evaluate("Array.from(document.querySelectorAll('.candidate-table tbody tr')).find(r=>r.querySelector('.chip')?.textContent.includes('イントロの終わり')).querySelector('.cue-decision-actions button').click()");
    await until("document.querySelector('.decision-accepted')");
    assert.equal(candidates.find(c=>c.type==='INTRO_END').cue_kind,'BOTH');
    await click('表示中の候補を選ぶ');
    assert.equal(await evaluate("document.querySelector('#bulk-cue-kind').value"),'PRESET');
    await evaluate("document.querySelector('.batch-cue-actions .inline-check input').click()");
    await click('選択した8候補を一括採用');
    await until("document.querySelectorAll('.decision-accepted').length===8");
    assert.equal(candidates.find(c=>c.type==='INTRO_START').cue_kind,'MEMORY');
    assert.equal(candidates.find(c=>c.type==='OUTRO_END').cue_kind,'MEMORY');
    assert.equal(candidates.find(c=>c.type==='CHORUS_START').cue_kind,'HOT');
    assert.equal(await evaluate("document.querySelector('.timeline-marker').style.background"),'rgb(0, 255, 0)');
    await click('書き出すキューを確認');
    await until("document.querySelector('[aria-label=\"書き込み内容\"] tbody')?.children.length===9");
    await click('📁 rekordbox XML を書き出し');
    await until("document.body.textContent.includes('共通設定・目的ごとの色を各Cueに反映')");
    await call('Page.reload');
    await until("document.querySelector('select[aria-label=\"共通設定のCue種類\"]')?.value==='HOT'");
    assert.equal(await evaluate("JSON.parse(localStorage.getItem('aicue.cuePresets')).targets.INTRO_END.memory_color"),null);
    assert.equal(await evaluate("JSON.parse(localStorage.getItem('aicue.cuePresets')).targets.OUTRO_END.memory_color"),'#9900ff');
    await until("document.querySelectorAll('.job').length>0");
    await evaluate("document.querySelectorAll('.job')[0].click()");
    await until("document.querySelectorAll('.decision-accepted').length===8");
    await select('xml-export-mode','EXISTING');
    await until("document.querySelector('.collection-xml-picker')");
    const exportDisabled=()=>evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('rekordbox XML を書き出し')).disabled");
    assert.equal(await exportDisabled(),true,'existing update requires original collection XML and review');
    const uploadSource=async xml=>evaluate(`(()=>{const input=document.querySelector('input[aria-label="元のコレクションXMLを選択"]');const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(xml)}],'original_collection.xml',{type:'application/xml'}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    await uploadSource('<DJ_PLAYLISTS><PRODUCT Name="pyrekordbox"/><COLLECTION/></DJ_PLAYLISTS>');
    await until("document.querySelector('.collection-xml-picker .error')");
    assert.equal(await exportDisabled(),true);
    await uploadSource('<DJ_PLAYLISTS><PRODUCT Name="rekordbox"/><COLLECTION/></DJ_PLAYLISTS>');
    await until("document.querySelector('.collection-xml-name')?.textContent.includes('1288曲')");
    assert.equal(sourceUploads,1);
    await click('書き出すキューを確認');
    await until("document.querySelector('.existing-update-review')?.textContent.includes('既存を維持：3件')");
    assert.equal(await exportDisabled(),true,'preview still requires explicit review');
    assert.equal(await evaluate("document.querySelector('[aria-label=\"書き込み内容\"]').textContent.includes('0:04〜0:06')"),true,'loop endpoint is visible');
    assert.equal(lastPlan.mode,'EXISTING');
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:1050,deviceScaleFactor:1,mobile:width===390});
      await evaluate("document.querySelector('.existing-update-review').scrollIntoView({block:'start'})");
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`existing update review overflow at ${width}`);
      const shot=await call('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(out,`existing-update-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await evaluate("document.querySelector('.existing-update-confirm').click()");
    assert.equal(await exportDisabled(),false);
    existingRace=true;
    await click('📁 rekordbox XML を書き出し');
    await until("document.body.textContent.includes('確認後にライブラリが変わりました') && !document.querySelector('.existing-update-review')");
    assert.equal(await exportDisabled(),true,'a stale review cannot be reused');
    assert.equal(candidates.filter(c=>c.accepted).length,8,'failed export does not change adopted cues');
    existingRace=false;existingConflict=true;
    await click('書き出すキューを確認');
    await until("document.querySelector('.existing-update-review')?.textContent.includes('空き枠が不足')");
    assert.equal(await exportDisabled(),true,'existing capacity conflict blocks export');
    existingConflict=false;
    await click('書き出すキューを確認');
    await until("document.querySelector('.existing-update-confirm')");
    await evaluate("document.querySelector('.existing-update-confirm').click()");
    await click('📁 rekordbox XML を書き出し');
    await until("document.querySelector('.xml-import-guide')?.textContent.includes('このXMLは元の音源を参照します')");
    assert.equal(existingExports,1);
    assert.equal(lastExport.mode,'EXISTING');
    assert.equal(await evaluate("document.querySelector('.xml-import-guide').textContent.includes('トラック → コレクションにインポート')"),true);
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length>0");
    await evaluate("document.querySelectorAll('.job')[0].click()");
    await until("document.querySelector('#xml-export-mode')?.value==='EXISTING' && document.querySelector('.collection-xml-name')?.textContent.includes('original_collection.xml')");
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length>0");
    await click('イントロアウトロ特化');
    assert.equal(await evaluate("document.querySelectorAll('.intro-outro-settings input[type=checkbox]').length"),16);
    assert.equal(await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').checked"),false);
    assert.equal(await evaluate("document.querySelector('#analysis-quality').closest('[hidden]')!==null"),true);
    await evaluate("(()=>{const e=document.querySelector('[aria-label=\"まとめて設定する小節数\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,'4');e.dispatchEvent(new Event('input',{bubbles:true}));})()");
    await click('すべての小節数に適用');
    await until("Array.from(document.querySelectorAll('.intro-outro-bars input')).every(e=>e.value==='4')");
    await input('intro-position-bars','3');
    await until("document.querySelector('.intro-outro-settings input[value=INTRO_BAR_X3]').closest('label').textContent.includes('イントロの9小節目')");
    assert.equal(await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_BAR]').closest('label').textContent.includes('イントロの3小節目')"),true);
    assert.equal(await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_BAR_X2]').closest('label').textContent.includes('イントロの6小節目')"),true);
    await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_BAR_X2]').closest('.cue-target-option').querySelector('summary').click()");
    await presetSelect('イントロの指定小節目×2のCue種類','BOTH');
    await presetMemory('イントロの指定小節目×2 Memory Cue の色','#9900ff');
    await setColor('イントロの指定小節目×2 Hot Cue の色','#ff0000');
    await evaluate("(()=>{const e=document.querySelector('[aria-label=\"イントロ間の小節ごとの小節数\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,'2');e.dispatchEvent(new Event('input',{bubbles:true}));})()");
    await until("document.querySelector('.intro-outro-settings').textContent.includes('イントロ間の2小節ごと')");
    await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_INTERVAL]').closest('.cue-target-option').querySelector('summary').click()");
    await evaluate("(()=>{const e=document.querySelector('select[aria-label=\"イントロ間の小節ごとのCue種類\"]');e.value='HOT';e.dispatchEvent(new Event('change',{bubbles:true}));})()");
    await setColor('イントロ間の小節ごと Hot Cue の色','#00ff00');
    await click('選択を解除');
    assert.equal(await evaluate("document.querySelector('.start-analysis').disabled"),true);
    await click('すべて選ぶ');
    assert.equal(await evaluate("document.querySelector('#analysis-quality').closest('[hidden]')===null"),true);
    await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').click()");
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length>0");
    await click('イントロアウトロ特化');
    await until("document.querySelector('[aria-label=\"イントロ間の小節ごとの小節数\"]').value==='2'");
    assert.equal(await evaluate("document.querySelector('#intro-position-bars').value"),'3');
    await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_BAR_X2]').closest('.cue-target-option').querySelector('summary').click()");
    assert.equal(await evaluate("document.querySelector('select[aria-label=\"イントロの指定小節目×2のCue種類\"]').value"),'BOTH');
    assert.equal(await evaluate("document.querySelector('[aria-label=\"アウトロ間の小節ごとの小節数\"]').value"),'4');
    await evaluate("document.querySelector('.intro-outro-settings input[value=INTRO_INTERVAL]').closest('.cue-target-option').querySelector('summary').click()");
    assert.equal(await evaluate("document.querySelector('input[aria-label=\"イントロ間の小節ごと Hot Cue の色\"]').value"),'#00ff00');
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate("document.querySelector('.cue-mode-switch').scrollIntoView()");
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
      const shot=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,`intro-outro-form-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await click('ファイルパスから');
    await input('audio-path','C:\\Music\\Specialized.wav');
    await click('解析を開始 →');
    await until("document.querySelector('#analysis-result').textContent.includes('イントロアウトロ特化：')");
    assert.equal(created.params.cue_mode,'INTRO_OUTRO');
    assert.equal(created.params.analysis_quality,'STANDARD');
    assert.equal(created.params.cue_targets,undefined);
    assert.equal(created.params.intro_outro.intro_interval_bars,2);
    assert.equal(created.params.intro_outro.intro_position_bars,3);
    assert.equal(created.params.intro_outro.targets.length,15);
    assert.equal(created.params.cue_settings.INTRO_BAR_X2.cue_kind,'BOTH');
    assert.equal(created.params.cue_settings.INTRO_BAR_X2.memory_color,'#9900ff');
    assert.equal(created.params.cue_settings.INTRO_BAR_X2.hot_color,'#ff0000');
    assert.equal(created.params.intro_outro.track_before_bars,4);
    assert.equal(created.params.cue_settings.INTRO_INTERVAL.cue_kind,'HOT');
    assert.equal(created.params.cue_settings.INTRO_INTERVAL.hot_color,'#00ff00');
    assert.equal(candidates.some(c=>['CHORUS_START','VOCAL_START','DROP','BREAK','BUILD'].includes(c.type)),false);
    await until("document.querySelector('.candidate-type-cell').closest('tbody').textContent.includes('イントロ間の2小節ごと')");
    assert.equal(await evaluate("document.querySelector('.candidate-type-cell').closest('tbody').textContent.includes('イントロの9小節目')"),true);
    assert.equal(candidates.filter(c=>c.type==='INTRO_INTERVAL').length,5);
    await click('選択を解除');
    await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').click()");
    await select('analysis-quality','AI');
    assert.equal(await evaluate("document.querySelector('#phrase-length').closest('[hidden]')!==null"),true);
    assert.equal(await evaluate("document.querySelector('.intro-outro-settings').textContent.includes('Verse先頭で代用しません')"),true);
    await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').closest('.cue-target-option').querySelector('summary').click()");
    await presetSelect('歌い始めのCue種類','HOT');
    await setColor('歌い始め Hot Cue の色','#00ff00');
    await call('Page.reload');
    await until("document.querySelector('#analysis-quality')?.value==='AI'");
    await click('イントロアウトロ特化');
    assert.equal(await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').checked"),true);
    assert.equal(await evaluate("document.querySelectorAll('.intro-outro-settings input[type=checkbox]:checked').length"),1);
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate("document.querySelector('.intro-outro-settings input[value=VOCAL_START]').closest('.intro-outro-group').scrollIntoView()");
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
      const shot=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,`vocal-start-form-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await click('ファイルパスから');
    await input('audio-path','C:\\Music\\Vocal.wav');
    const writesBeforeVocal=decisionWrites;
    await click('解析を開始 →');
    await until("document.querySelector('.candidate-type-cell')?.textContent.includes('歌い始め')");
    assert.equal(created.params.analysis_quality,'AI');
    assert.equal(created.params.cue_mode,'INTRO_OUTRO');
    assert.deepEqual(created.params.intro_outro.targets,['VOCAL_START']);
    assert.equal(created.params.cue_settings.VOCAL_START.cue_kind,'HOT');
    assert.equal(created.params.cue_settings.VOCAL_START.hot_color,'#00ff00');
    assert.equal(decisionWrites,writesBeforeVocal);
    assert.equal(candidates.length,1);
    assert.equal(candidates[0].accepted,null);
    jobs.unshift({id:'ai-progress',status:'RUNNING',total:46,completed:0,failed:0,track_path:'C:/Music/Long song.wav',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),params:{analysis_quality:'AI'}});
    await call('Page.reload');
    await until("document.querySelectorAll('.job').length>0");
    await evaluate("document.querySelector('.job').click()");
    await until("document.querySelector('.analysis-progress-info')?.textContent.includes('この曲の音源分離：34%')");
    assert.equal(await evaluate("document.querySelector('.analysis-progress-info').textContent.includes('完了した曲：0/46')"),true);
    assert.equal(await evaluate("document.querySelector('.analysis-progress-info').textContent.includes('1/46曲目：Long song')"),true);
    assert.equal(await evaluate("document.querySelector('.analysis-progress-info').textContent.includes('残り約 3:17')"),true);
    aiProgressPercent=67;
    await until("document.querySelector('progress[aria-label=\"この曲の音源分離\"]')?.value===67");
    for(const width of [1440,390]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate("document.querySelector('.analysis-progress-info').scrollIntoView()");
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
      const shot=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,`ai-progress-${width}.png`),Buffer.from(shot.data,'base64'));
    }
    jobs[0].status='COMPLETED'; jobs[0].completed=46;
    await until("!document.querySelector('.analysis-progress-info')");
    aiAvailable=false;
    await evaluate("localStorage.removeItem('aicue.analysisQuality')");
    await call('Page.reload');
    await until("document.querySelector('#analysis-quality')?.value==='STANDARD' && document.querySelector('#analysis-quality option[value=AI]')?.disabled");
    await click('イントロアウトロ特化');
    assert.equal(await evaluate("document.querySelector('#analysis-quality-help').textContent.includes('歌詞時刻がない場合は省略')"),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: Memory Cue eight-color palette and unset, persisted unset and XML null, menu keyboard controls, MEMORY/HOT CUE dock and audition; playlist-wide selection across pagination, deduplication, unavailable-grid exclusion, two tracks x three purposes, correct track audition, scoped review and drafts, confirmed bulk BOTH adoption, save locks, full-job export, 1440/768/390px layouts; existing purpose/grid/color/audio regressions; no runtime exceptions.');
    console.log('Screenshots: '+out);
  } finally { ws?.close(); browser.kill(); server.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
