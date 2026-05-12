use axum::response::Html;

pub(crate) async fn root() -> Html<&'static str> {
    Html(
        r#"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>RSS Sidecar · Rust</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap');
html,body,html[data-theme="light"],body[data-theme="light"]{color-scheme:light;--bg:#f3efe5;--bg2:#e6dfcf;--card:#fffdf8;--line:#d6ccb7;--text:#25231d;--muted:#726a58;--ok:#1f7a4a;--err:#b44531;--accent:#a96f2e;--shadow:0 16px 34px rgba(42,31,12,.10);--hero-bg:rgba(255,252,245,.86);--hero-border:rgba(132,110,70,.26);--btn-bg:#fffef9;--btn-shadow:0 4px 12px rgba(45,32,8,.07);--btn-shadow-hover:0 8px 18px rgba(45,32,8,.12);--btn-main-from:#f7d79f;--btn-main-to:#efc57f;--btn-main-border:#dca252;--card-border:rgba(120,100,66,.22);--panel:#faf6ec;--dash:#d9cfbc;--heading:#4d4639;--link:#2f4f7b;--input-bg:#fff;--ok-border:#95cfaf;--ok-bg:#eaf8ef;--err-border:#e3a599;--err-bg:#fff1ed;--state-running-text:#145c38;--state-running-border:#8dcaab;--state-running-bg:#e7f6ee;--state-paused-text:#5a5344;--state-paused-border:#c7bca6;--state-paused-bg:#f2ecdf}
html[data-theme="dark"],body[data-theme="dark"]{color-scheme:dark;--bg:#181a1c;--bg2:#22262b;--card:#272c31;--line:#3b434c;--text:#e8edf3;--muted:#aeb8c4;--ok:#57c486;--err:#ef8f7c;--accent:#d7a15f;--shadow:0 16px 34px rgba(0,0,0,.32);--hero-bg:rgba(41,46,52,.88);--hero-border:#4a5561;--btn-bg:#30363d;--btn-shadow:0 4px 12px rgba(0,0,0,.35);--btn-shadow-hover:0 8px 18px rgba(0,0,0,.45);--btn-main-from:#5c4a2f;--btn-main-to:#6d5535;--btn-main-border:#8c6f45;--card-border:#46515d;--panel:#20262c;--dash:#3a434f;--heading:#c6d0da;--link:#8eb8ff;--input-bg:#1f252b;--ok-border:#2d7a56;--ok-bg:#1f3a2e;--err-border:#8f4b43;--err-bg:#3a2725;--state-running-text:#9de7bf;--state-running-border:#2d7a56;--state-running-bg:#1f3a2e;--state-paused-text:#d5dce4;--state-paused-border:#596678;--state-paused-bg:#2d3440}
*{box-sizing:border-box}body{margin:0;color:var(--text);font-family:'IBM Plex Sans','Noto Sans SC','PingFang SC','Microsoft Yahei',sans-serif;background:radial-gradient(1000px 480px at 10% -10%, #d3e4cf 0%, transparent 58%),radial-gradient(760px 380px at 100% 0%, #f3dfba 0%, transparent 52%),linear-gradient(160deg,var(--bg),var(--bg2));min-height:100vh}
html[data-theme="dark"] body,body[data-theme="dark"]{background:radial-gradient(1000px 480px at 10% -10%, #20322b 0%, transparent 58%),radial-gradient(760px 380px at 100% 0%, #433225 0%, transparent 52%),linear-gradient(160deg,var(--bg),var(--bg2))}
.wrap{max-width:1200px;margin:20px auto;padding:0 16px 26px}
.hero{background:var(--hero-bg);border:1px solid var(--hero-border);border-radius:18px;box-shadow:var(--shadow);padding:16px 18px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px}
.title{font-size:24px;font-weight:700;margin:0}.sub{margin:5px 0 0;color:var(--muted);font-size:13px}
.btns{display:flex;gap:10px;flex-wrap:wrap}button{border:1px solid var(--line);border-radius:11px;padding:10px 14px;cursor:pointer;font-weight:600;color:var(--text);background:var(--btn-bg);transition:.16s transform,.16s box-shadow;box-shadow:var(--btn-shadow)}button:hover{transform:translateY(-1px);box-shadow:var(--btn-shadow-hover)}.btn-main{background:linear-gradient(140deg,var(--btn-main-from),var(--btn-main-to));border-color:var(--btn-main-border)}
.theme-btn{min-width:120px}
.auto-ctl{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:11px;background:var(--btn-bg);box-shadow:var(--btn-shadow);font-size:12px}
.auto-ctl input[type="number"]{width:100px;background:var(--input-bg);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:5px 6px}
.auto-ctl input[type="checkbox"]{accent-color:var(--accent)}
.auto-hint{min-width:240px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-top:14px}.card{grid-column:span 12;background:var(--card);border:1px solid var(--card-border);border-radius:16px;box-shadow:var(--shadow);padding:14px}.h{margin:0 0 10px;font-size:17px}.muted{color:var(--muted);font-size:12px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px}.stat b{display:block;font-size:22px;line-height:1.1}
.subs .row{display:grid;grid-template-columns:1fr auto auto auto;gap:10px;align-items:center;padding:10px 0;border-bottom:1px dashed var(--dash)}.subs .row:last-child{border-bottom:none}.subs .action{display:flex;gap:6px;flex-wrap:wrap}
.state-btn{border-radius:999px;padding:6px 12px;font-size:12px;line-height:1.1;font-weight:700;box-shadow:none}
.state-btn.running{color:var(--state-running-text);border-color:var(--state-running-border);background:var(--state-running-bg)}
.state-btn.paused{color:var(--state-paused-text);border-color:var(--state-paused-border);background:var(--state-paused-bg)}
.add-sub{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;margin:0 0 10px}.add-sub input{width:100%;min-width:0;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--input-bg);color:var(--text)}.add-sub button{white-space:nowrap}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:600;border:1px solid}.ok{color:var(--ok);border-color:var(--ok-border);background:var(--ok-bg)}.err{color:var(--err);border-color:var(--err-border);background:var(--err-bg)}
.entries .group{margin:12px 0 16px}.entries .g-title{font-weight:700;font-size:14px;margin:0 0 8px;color:var(--heading)}
.entries article{padding:9px 0;border-bottom:1px dashed var(--dash)}.entries article:last-child{border-bottom:none}.entries a{color:var(--link);text-decoration:none;font-weight:600}.entries a:hover{text-decoration:underline}
.entry-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.entry-actions button{padding:6px 10px;border-radius:8px;font-size:12px}
#mdModal[data-md-theme="light"]{--md-card:#fffdf8;--md-panel:#faf6ec;--md-text:#25231d;--md-muted:#726a58;--md-line:#d6ccb7;--md-link:#2f4f7b;--md-mask:rgba(35,28,18,.36);--md-shadow:0 22px 64px rgba(48,36,14,.18)}#mdModal[data-md-theme="dark"]{--md-card:#1f2429;--md-panel:#161b20;--md-text:#edf2f7;--md-muted:#aeb8c4;--md-line:#404955;--md-link:#9bc4ff;--md-mask:rgba(0,0,0,.62);--md-shadow:0 22px 70px rgba(0,0,0,.45)}.modal{position:fixed;inset:0;display:none;z-index:90}.modal.show{display:block}.modal-mask{position:absolute;inset:0;background:var(--md-mask,rgba(0,0,0,.42))}.modal-panel{position:relative;max-width:900px;max-height:85vh;overflow:auto;margin:5vh auto;background:var(--md-card,var(--card));border:1px solid var(--md-line,var(--card-border));border-radius:14px;box-shadow:var(--md-shadow,var(--shadow));padding:14px 16px}.modal-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px}.modal-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.modal-head h3{margin:0;font-size:18px;color:var(--md-text,var(--text))}.md-theme-btn{min-width:112px;padding:8px 10px}.md-body{line-height:1.75;color:var(--md-text,var(--text));font-size:15px}.md-body.muted{color:var(--md-muted,var(--muted))}.md-body a{color:var(--md-link,var(--link));font-weight:650}.md-body p{margin:0 0 .9em}.md-body blockquote{margin:12px 0;padding:9px 12px;border-left:4px solid var(--md-link,var(--link));background:var(--md-panel,var(--panel));color:var(--md-muted,var(--muted));border-radius:8px}.md-body code{background:var(--md-panel,var(--panel));border:1px solid var(--md-line,var(--line));border-radius:6px;padding:1px 5px}.md-body img{max-width:100%;height:auto}.md-body pre{overflow:auto;background:var(--md-panel,var(--panel));border:1px solid var(--md-line,var(--line));border-radius:8px;padding:10px}
.llm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}.llm-field{min-width:0}.llm-field .muted{display:block;margin-bottom:6px}.llm-grid input{width:100%;min-width:0;padding:10px 11px;border:1px solid var(--line);border-radius:10px;background:var(--input-bg);color:var(--text)}
.llm-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;align-items:center;margin-top:10px}.llm-actions button{width:100%;min-width:0}.llm-result{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;margin-top:10px;max-height:220px;overflow:auto}
@media (min-width:980px){.stats-card{grid-column:span 4}.subs-card{grid-column:span 8}.entries-card{grid-column:span 8}.llm-card{grid-column:span 4}}
@media (max-width:760px){.subs .row{grid-template-columns:1fr auto;grid-template-areas:'name status' 'meta action'}.subs .name{grid-area:name}.subs .meta{grid-area:meta}.subs .status{grid-area:status}.subs .action{grid-area:action}.add-sub{grid-template-columns:1fr}.llm-grid{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap"><section class="hero"><div><h1 class="title">RSS Sidecar · Rust</h1><p class="sub">&#32479;&#19968;&#35746;&#38405;&#20013;&#21488;&#65288;WeChat / Yage&#65289;+ &#19996;&#20843;&#21306;&#26102;&#38388; + &#24191;&#21578;&#25991;&#36339;&#36807;&#65288;&#35268;&#21017; + &#20813;&#36153; LongCat&#65289;</p></div><div class="btns"><button class="btn-main" onclick="refreshAll()">刷新全部订阅</button><button onclick="loadAll()">刷新页面数据</button><button class="btn-main" onclick="location.href='/rss/cleaner'">付费文章清洗器</button><button id="themeToggle" class="theme-btn" onclick="toggleTheme()">Theme</button><div class="auto-ctl"><label><input id="auto_enabled" type="checkbox" onchange="saveAutoRefresh()"> 自动刷新</label><input id="auto_interval_seconds" type="number" min="5" step="1" value="3600" onchange="saveAutoRefresh()">秒<button onclick="saveAutoRefresh()">应用</button></div><div id="auto_hint" class="muted auto-hint"></div></div></section>
<section class="grid"><div class="card stats-card"><h2 class="h">运行概览</h2><div class="stats" id="stats"></div></div><div class="card subs-card"><h2 class="h">订阅列表</h2><div class="add-sub"><input id="new_biz" placeholder="biz (可选)"/><input id="new_name" placeholder="name"/><input id="new_feed_url" placeholder="feed url (https://...)"/><button onclick="createSub()">Add</button></div><div class="subs" id="subs"></div></div><div class="card entries-card"><h2 class="h">最近文章（东八区）</h2><div class="entries" id="entries"></div></div>
<div class="card llm-card"><h2 class="h">LLM 设置</h2><p class="muted">&#36153;&#29992;&#31574;&#30053;&#65306;&#20165;&#20801;&#35768; LongCat-Flash-Lite &#33258;&#21160;&#21442;&#19982;&#24191;&#21578;&#21028;&#23450;&#65307; cleaner &#40664;&#35748;&#26412;&#22320;&#35268;&#21017;&#24555;&#36895;&#28165;&#27927;&#65292;&#21482;&#26377;&#20320;&#28857; LLM &#31934;&#20462;&#26102;&#25165;&#20250;&#35843;&#29992;&#12290;</p><label class="llm-switch"><input id="llm_enabled" type="checkbox"/> 启用免费 LLM 广告判定</label><div class="llm-grid"><div class="llm-field"><div class="muted">API Base</div><input id="llm_api_base" placeholder="https://api.longcat.chat/openai/v1"/></div><div class="llm-field"><div class="muted">API Key</div><input id="llm_api_key" type="password" placeholder="ak-..."/></div><div class="llm-field"><div class="muted">Model</div><input id="llm_model" placeholder="LongCat-Flash-Lite"/></div></div><div class="llm-actions"><button onclick="saveLlm()">保存设置</button><button onclick="testLlm()">测试连接</button></div><div id="llm_result" class="llm-result">这里显示模型连通测试结果。</div></div>
</section></div>
<div id="mdModal" class="modal" aria-hidden="true"><div class="modal-mask" onclick="closePreview()"></div><div class="modal-panel"><div class="modal-head"><h3 id="mdTitle">Markdown Preview</h3><div class="modal-tools"><button id="mdThemeToggle" class="md-theme-btn" onclick="toggleMdPreviewTheme()">预览: 跟随</button><button onclick="closePreview()">关闭</button></div></div><div id="mdBody" class="md-body muted">加载中...</div></div></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
async function j(url,opt){const r=await fetch(url,{headers:{'content-type':'application/json'},...(opt||{})});return await r.json();}
function esc(s){return String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m]));}
function mdToHtml(md){try{return (window.marked&&window.marked.parse)?window.marked.parse(md||''):esc(md||'').replace(/\n/g,'<br/>');}catch(_){return esc(md||'').replace(/\n/g,'<br/>');}}
function closePreview(){const m=document.getElementById('mdModal');if(!m)return;m.classList.remove('show');m.setAttribute('aria-hidden','true');}
const MD_THEME_KEY='wechat_rss_md_preview_theme';
function currentPageTheme(){return document.documentElement.getAttribute('data-theme')==='dark'?'dark':'light';}
function setMdPreviewBtn(mode){const el=document.getElementById('mdThemeToggle');if(!el)return;el.textContent=mode==='dark'?'预览: 暗色':'预览: 明亮';}
function applyMdPreviewTheme(mode){const m=document.getElementById('mdModal');if(!m)return;const next=(mode==='dark'||mode==='light')?mode:currentPageTheme();m.setAttribute('data-md-theme',next);setMdPreviewBtn(next);}
function initMdPreviewTheme(){const saved=localStorage.getItem(MD_THEME_KEY);applyMdPreviewTheme((saved==='dark'||saved==='light')?saved:currentPageTheme());}
function toggleMdPreviewTheme(){const m=document.getElementById('mdModal');const cur=(m&&m.getAttribute('data-md-theme'))||currentPageTheme();const next=cur==='dark'?'light':'dark';localStorage.setItem(MD_THEME_KEY,next);applyMdPreviewTheme(next);}
async function openPreview(id,title){
  const m=document.getElementById('mdModal');const t=document.getElementById('mdTitle');const b=document.getElementById('mdBody');
  if(!m||!t||!b)return;
  initMdPreviewTheme();
  t.textContent=title||'Markdown Preview'; b.textContent='加载中...'; m.classList.add('show'); m.setAttribute('aria-hidden','false');
  try{
    let md='';
    const r=await fetch('/api/articles/'+id+'/markdown');
    if(r.ok){ md=(await r.text())||''; }
    if(!md.trim()){
      const r2=await fetch('/api/articles/'+id);
      if(r2.ok){
        const d=await r2.json();
        const it=d.item||{};
        md=(it.content_markdown||it.summary||'').toString();
      }
    }
    b.classList.remove('muted');
    b.innerHTML=mdToHtml(md&&md.trim()?md:'(暂无可预览正文)');
  }catch(e){
    b.classList.add('muted');
    b.textContent='加载失败: '+((e&&e.message)||String(e));
  }
}
const fmtCN=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
function toCN(v){if(!v)return '';const d=new Date(v);if(Number.isNaN(d.getTime()))return v;return fmtCN.format(d);}
function ts(v){const d=new Date(v||'');return Number.isNaN(d.getTime())?0:d.getTime();}
const THEME_KEY='wechat_rss_theme';
function setThemeBtn(mode){const el=document.getElementById('themeToggle');if(!el)return;el.textContent=mode==='dark'?'Theme: Dark':'Theme: Light';}
function applyTheme(mode){document.documentElement.setAttribute('data-theme',mode);document.body&&document.body.setAttribute('data-theme',mode);setThemeBtn(mode);if(!localStorage.getItem(MD_THEME_KEY))applyMdPreviewTheme(mode);}
function initTheme(){const saved=localStorage.getItem(THEME_KEY);if(saved==='dark'||saved==='light'){applyTheme(saved);return;}const prefers=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;applyTheme(prefers?'dark':'light');}
function toggleTheme(){const cur=document.documentElement.getAttribute('data-theme')==='dark'?'dark':'light';const next=cur==='dark'?'light':'dark';localStorage.setItem(THEME_KEY,next);applyTheme(next);}
function renderAutoHint(status){
  const el=document.getElementById('auto_hint'); if(!el) return;
  if(!status){ el.textContent='自动刷新状态未知'; return; }
  const interval=status.interval_seconds||3600;
  if(!status.enabled){ el.textContent=`自动刷新已关闭（当前间隔 ${interval} 秒）`; return; }
  const next=status.next_run_at?toCN(status.next_run_at):'待计算';
  const last=status.last_run_at?toCN(status.last_run_at):'尚未执行';
  const rs=status.last_status||'idle';
  el.textContent=`自动刷新每 ${interval} 秒 · 下次 ${next} · 上次 ${last} · 状态 ${rs}`;
}
async function loadAutoRefresh(){
  const d=await j('/api/auto-refresh-status');
  if(d.error){ renderAutoHint(null); return; }
  const enabledEl=document.getElementById('auto_enabled');
  const secEl=document.getElementById('auto_interval_seconds');
  if(enabledEl) enabledEl.checked=!!d.enabled;
  if(secEl) secEl.value=String(d.interval_seconds||3600);
  renderAutoHint(d);
}
async function saveAutoRefresh(){
  const enabled=document.getElementById('auto_enabled')?.checked!==false;
  let seconds=Number(document.getElementById('auto_interval_seconds')?.value||3600);
  if(!Number.isFinite(seconds)) seconds=3600;
  seconds=Math.max(5,Math.round(seconds));
  const d=await j('/api/settings/auto-refresh',{method:'POST',body:JSON.stringify({enabled,seconds})});
  if(d.error){ alert('保存自动刷新设置失败: '+d.error); return; }
  await loadAutoRefresh();
}
function statusChip(v){const ok=(v||'').toLowerCase()==='ok';return `<span class="chip ${ok?'ok':'err'}">${ok?'正常':'异常'} · ${esc(v||'n/a')}</span>`;}
function setLlmResult(t){document.getElementById('llm_result').textContent=t||'';}
async function loadLlm(){const d=await j('/api/settings/llm');const it=d.item||{};document.getElementById('llm_enabled').checked=!!it.enabled;document.getElementById('llm_api_base').value=it.api_base||'';document.getElementById('llm_api_key').value=it.api_key||'';document.getElementById('llm_model').value=it.model||'';setLlmResult(`策略: ${it.cost_policy||'free_only'} · 自动判定: ${it.auto_active?'开启':'关闭'} · Key: ${it.api_key_present?'已保存':'未配置'}`);}
async function saveLlm(){const p={enabled:document.getElementById('llm_enabled').checked,api_base:document.getElementById('llm_api_base').value.trim(),api_key:document.getElementById('llm_api_key').value.trim(),model:document.getElementById('llm_model').value.trim()};const d=await j('/api/settings/llm',{method:'POST',body:JSON.stringify(p)});if(d.error)throw new Error(d.error);setLlmResult('保存成功 / Saved');await loadLlm();}
async function testLlm(){const p={api_base:document.getElementById('llm_api_base').value.trim(),api_key:document.getElementById('llm_api_key').value.trim(),model:document.getElementById('llm_model').value.trim()};setLlmResult('测试中...');const d=await j('/api/settings/llm/test',{method:'POST',body:JSON.stringify(p)});if(d.error){setLlmResult('测试失败: '+d.error);return;}const it=d.item||{};setLlmResult(`连接成功
endpoint: ${it.endpoint||''}
model: ${it.model||''}
latency: ${it.latency_ms||0} ms
preview: ${it.preview||''}`);}
async function createSub(){const p={biz:document.getElementById('new_biz').value.trim(),name:document.getElementById('new_name').value.trim(),feed_url:document.getElementById('new_feed_url').value.trim()};if(!p.feed_url){alert('feed_url required');return;}const d=await j('/api/subscriptions',{method:'POST',body:JSON.stringify(p)});if(d.error){alert('create failed: '+d.error);return;}document.getElementById('new_biz').value='';document.getElementById('new_name').value='';document.getElementById('new_feed_url').value='';alert('created');await loadAll();}
async function loadStats(subs,entries){const ok=subs.filter(x=>(x.last_status||'').toLowerCase()==='ok').length;const err=subs.filter(x=>(x.last_status||'').toLowerCase()==='error').length;const enabled=subs.filter(x=>x.enabled===1).length;const stats=[['订阅总数',subs.length],['启用中',enabled],['状态正常',ok],['异常订阅',err],['最近文章',entries.length]];document.getElementById('stats').innerHTML=stats.map(s=>`<div class="stat"><span class="muted">${s[0]}</span><b>${s[1]}</b></div>`).join('');}
async function toggleSub(id){const d=await j('/api/subscriptions/'+id+'/toggle',{method:'POST',body:'{}'});if(d.error){alert('toggle failed: '+d.error);return;}await loadAll();}
async function loadSubs(){const d=await j('/api/subscriptions');const items=d.items||[];document.getElementById('subs').innerHTML=items.map(x=>`<div class="row"><div class="name"><b>${esc(x.name)}</b></div><div class="status"><button class="state-btn ${x.enabled===1?'running':'paused'}" title="${x.enabled===1?'点击暂停':'点击启动'}" onclick="toggleSub(${x.id})">${x.enabled===1?'运行中':'已暂停'}</button></div><div class="meta muted">id=${x.id} · ${statusChip(x.last_status)} · ${esc(toCN(x.last_refresh_at)||'未刷新')}</div><div class="action"><button onclick="refreshOne(${x.id})">刷新</button></div></div>`).join('');return items;}
async function refreshAll(silent){const d=await j('/api/refresh-all',{method:'POST',body:'{}'});if(!silent)alert(d.message||'done');await loadAll();}
function entryTime(x){return ts(x.published_at||x.inserted_at);}
function sortEntries(items){return (items||[]).slice().sort((a,b)=>entryTime(b)-entryTime(a));}
function groupEntries(items){const group={};for(const it of items){const k=it.subscription_name||'未命名';(group[k]||(group[k]=[])).push(it);}return group;}
function renderEntryArticle(x){
  const when=x.published_at_local||toCN(x.published_at)||'';
  return `<article><div class="entry-actions"><a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.title)}</a><button data-id="${esc(x.id)}" data-title="${esc(x.title)}" onclick="openPreviewFromButton(this)">MD 预览</button></div><div class="muted">${esc(when)}</div></article>`;
}
function openPreviewFromButton(btn){openPreview(btn.dataset.id,btn.dataset.title||'Markdown Preview');}
async function loadEntries(){
  const d=await j('/api/entries?days=7&limit=40');
  const items=sortEntries(d.items||[]);
  const group=groupEntries(items);
  const html=Object.keys(group).map(k=>`<div class="group"><div class="g-title">${esc(k)}</div>${sortEntries(group[k]).map(renderEntryArticle).join('')}</div>`).join('');
  document.getElementById('entries').innerHTML=html||'<div class="muted">暂无文章</div>';
  return items;
}
async function refreshOne(id){const d=await j('/api/subscriptions/'+id+'/refresh',{method:'POST',body:'{}'});alert(d.message||'done');await loadAll();}
async function loadAll(){try{const [subs,entries]=await Promise.all([loadSubs(),loadEntries()]);await loadStats(subs,entries);}catch(e){document.getElementById('stats').innerHTML=`<div class="muted">加载失败: ${esc((e&&e.message)||String(e))}</div>`;}try{await loadLlm();}catch(e){setLlmResult('加载失败: '+((e&&e.message)||String(e)));}}
initTheme();
initMdPreviewTheme();
loadAutoRefresh();
setInterval(loadAutoRefresh,15000);
loadAll();
</script></body></html>"#,
    )
}

pub(crate) async fn cleaner_page() -> Html<&'static str> {
    Html(
        r##"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>付费文章 Markdown 清洗器</title>
<style>
html,body,html[data-theme="light"],body[data-theme="light"]{color-scheme:light;--bg:#f4efe4;--card:#fffdf8;--text:#242019;--muted:#746b5a;--line:#d8cdb8;--accent:#9d6a2d;--panel:#faf6ec;--link:#2f4f7b;--shadow:0 18px 48px rgba(42,31,12,.12);--input:#fff;--hero-tint:rgba(255,255,255,.42);--button-shadow:0 5px 14px rgba(0,0,0,.06);--primary-from:#f2c979;--primary-to:#dfa45a;--primary-border:#bd813b;--primary-text:#23190e}
html[data-theme="dark"],body[data-theme="dark"]{color-scheme:dark;--bg:#14181a;--card:#242a2f;--text:#edf2f7;--muted:#aeb8c4;--line:#404955;--accent:#d4a260;--panel:#1b2126;--link:#92bdff;--shadow:0 18px 52px rgba(0,0,0,.36);--input:#171d22;--hero-tint:rgba(255,255,255,.06);--button-shadow:0 5px 14px rgba(0,0,0,.28);--primary-from:#4d3420;--primary-to:#8c663e;--primary-border:#a57947;--primary-text:#fff4dc}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(900px 460px at 8% -12%,rgba(118,165,122,.35),transparent 58%),radial-gradient(760px 420px at 100% 0%,rgba(220,169,91,.28),transparent 55%),var(--bg);color:var(--text);font-family:"Noto Sans SC","Microsoft Yahei",sans-serif}
.wrap{max-width:1280px;margin:22px auto;padding:0 16px 28px}.hero{display:flex;gap:14px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;background:var(--hero-tint);border:1px solid var(--line);box-shadow:var(--shadow);border-radius:22px;padding:18px}.eyebrow{letter-spacing:.18em;color:var(--accent);font-weight:800;font-size:12px}.hero h1{margin:6px 0 8px;font-size:32px}.hero p{margin:0;color:var(--muted);line-height:1.7}.tools{display:flex;gap:10px;flex-wrap:wrap}button,a.btn{border:1px solid var(--line);border-radius:12px;padding:10px 14px;background:var(--card);color:var(--text);font-weight:700;text-decoration:none;cursor:pointer;box-shadow:var(--button-shadow)}button.primary{background:linear-gradient(135deg,var(--primary-from),var(--primary-to));border-color:var(--primary-border);color:var(--primary-text)}.grid{display:grid;grid-template-columns:1fr;gap:16px;margin-top:16px}@media(min-width:980px){.grid{grid-template-columns:1fr 1fr}}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow);padding:16px}.row{display:grid;grid-template-columns:1fr;gap:10px;margin-bottom:12px}@media(min-width:760px){.row{grid-template-columns:1fr 1fr 1fr}}label{display:block;font-size:13px;color:var(--muted);font-weight:700;margin-bottom:6px}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:13px;background:var(--input);color:var(--text);padding:11px 12px;font:inherit}::placeholder{color:var(--muted);opacity:.78}select option{background:var(--card);color:var(--text)}textarea[readonly]{background:var(--panel)}textarea{min-height:560px;resize:vertical;line-height:1.72}.out{white-space:pre-wrap;font-family:"Noto Serif SC","Songti SC",serif}.hint{color:var(--muted);font-size:13px;line-height:1.7}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:7px 10px;color:var(--muted);font-size:12px}.check{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:13px}.check input{width:auto}.status{min-height:22px;color:var(--muted);font-size:13px}.footer{margin-top:12px;color:var(--muted);font-size:12px;line-height:1.6}
</style></head><body><div class="wrap"><section class="hero"><div><div class="eyebrow">BISHU XIFENG MARKDOWN CLEANER</div><h1>付费文章 Markdown 清洗器</h1><p>&#25226;&#20320;&#22312;&#24494;&#20449;&#37324;&#24050;&#36141;&#20080;&#30340;&#25991;&#31456;&#27491;&#25991;&#31896;&#36148;&#36827;&#26469;&#65292;&#40664;&#35748;&#29992;&#26412;&#22320;&#35268;&#21017;&#24555;&#36895;&#28165;&#27927;&#65306;&#20445;&#30041;&#36229;&#38142;&#25509;&#12289;&#21024;&#25481;&#22122;&#22768;&#12289;&#25353;&#30887;&#26641;&#35199;&#39118;&#30340;&#20889;&#20316;&#33410;&#22863;&#26029;&#27573;&#12290;&#22914;&#26524;&#20320;&#30475;&#23436;&#19981;&#28385;&#24847;&#65292;&#20877;&#28857;&#21491;&#20391; LLM &#31934;&#20462;&#12290;</p></div><div class="tools"><a class="btn" href="./">回到 RSS</a><button onclick="toggleTheme()">明暗切换</button></div></section>
<section class="grid"><div class="card"><div class="row"><div><label>标题</label><input id="title" placeholder="例如：财富大洗牌，我该选择，还是努力？"/></div><div><label>来源</label><input id="source" value="记忆承载" placeholder="记忆承载 / 记忆承载3"/></div><div><label>&#21457;&#24067;&#26102;&#38388;</label><input id="published_at" placeholder="2026-05-07 11:27"/></div></div><div class="bar"><select id="format" style="max-width:180px"><option value="auto">自动识别 HTML / 文本</option><option value="text">按纯文本处理</option><option value="html">按 HTML 转 Markdown</option></select><select id="mergeMode" style="max-width:210px"><option value="auto" selected>作者节奏（推荐）</option><option value="preserve">保留原换行</option><option value="smart">合并碎行</option></select></div><label>粘贴微信正文 / HTML</label><textarea id="input" placeholder="在微信文章里复制正文，然后粘贴到这里。若复制出来包含 HTML，也可以直接粘贴。"></textarea><div class="bar"><button class="primary" onclick="cleanNow()">生成 Markdown</button><button onclick="clearAll()">清空</button></div><div class="hint">小提示：如果你从微信桌面版复制出来的是 HTML，保持“自动识别”即可；如果只是普通文本，默认会按记忆承载常见的句末与语义节奏断段，不按长度乱切；如果你已经整理好格式，可切到“保留原换行”；如果复制出来是短碎行，可切到“合并碎行”。</div></div>
<div class="card"><div class="bar"><span class="pill" id="meta">等待生成</span><button onclick="copyMd()">复制 Markdown</button><button onclick="downloadMd()">下载 .md</button><button id="refineBtn" onclick="refineWithLlm()">LLM &#31934;&#20462;</button></div><label>Markdown 结果</label><textarea id="output" class="out" readonly placeholder="生成后的 Markdown 会出现在这里。"></textarea><div class="status" id="status"></div><div class="footer">这个工具适合你已购买后个人整理归档。RSS 订阅库仍只保存公开可抓到的内容；付费全文不自动入库，避免误把试读导流当完整文章。</div></div></section></div>
<script>
const KEY='paid_cleaner_theme';let lastFilename='wechat-paid-article.md';let capturedPasteHtml='';let capturedPasteText='';
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);document.body&&document.body.setAttribute('data-theme',t);localStorage.setItem(KEY,t)}
function initTheme(){const saved=localStorage.getItem(KEY);applyTheme(saved==='dark'||saved==='light'?saved:(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'))}
function toggleTheme(){applyTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark')}
function setStatus(t){document.getElementById('status').textContent=t||''}
function normPasteText(s){return String(s||'').replace(/\r\n?/g,'\n').trim()}
function shouldUseCapturedHtml(text,inputFormat){return !!capturedPasteHtml&&(inputFormat==='auto'||inputFormat==='html')&&normPasteText(text)===normPasteText(capturedPasteText)}
function setupRichPaste(){const el=document.getElementById('input');if(!el)return;el.addEventListener('paste',e=>{const cd=e.clipboardData;if(!cd)return;const html=cd.getData('text/html')||'';const text=cd.getData('text/plain')||'';if(html&&/<a[\s>]/i.test(html)){capturedPasteHtml=html;capturedPasteText=text;const fmt=document.getElementById('format');if(fmt&&fmt.value==='auto')fmt.value='html';setTimeout(()=>setStatus('\u5df2\u6355\u83b7\u5bcc\u6587\u672c\u94fe\u63a5\uff0c\u751f\u6210\u65f6\u4f1a\u4fdd\u7559 Markdown \u8d85\u94fe\u63a5\u3002'),0)}else{capturedPasteHtml='';capturedPasteText=''}});el.addEventListener('input',()=>{if(capturedPasteText&&normPasteText(el.value)!==normPasteText(capturedPasteText)){capturedPasteHtml='';capturedPasteText=''}})}
function buildCleanPayload(){const input=document.getElementById('input');const fmt=document.getElementById('format');let content=input.value;let inputFormat=fmt.value;const usedRichHtml=shouldUseCapturedHtml(content,inputFormat);if(usedRichHtml){content=capturedPasteHtml;inputFormat='html'}return{usedRichHtml,payload:{title:document.getElementById('title').value,source:document.getElementById('source').value,published_at:document.getElementById('published_at').value,content,input_format:inputFormat,merge_mode:document.getElementById('mergeMode').value,smart_merge:document.getElementById('mergeMode').value==='smart'}}}
function applyCleanResult(d){document.getElementById('output').value=d.markdown||'';lastFilename=d.filename||lastFilename;document.getElementById('meta').textContent=`${d.input_format} \u00b7 ${d.line_count} \u884c \u00b7 ${d.char_count} \u5b57`}
async function cleanNow(){const ctx=buildCleanPayload();setStatus('\u672c\u5730\u89c4\u5219\u6e05\u6d17\u4e2d...');const r=await fetch('/api/clean-markdown',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(ctx.payload)});const d=await r.json();if(!d.ok){setStatus('\u5931\u8d25\uff1a'+(d.error||'unknown'));return;}applyCleanResult(d);setStatus(ctx.usedRichHtml?'\u5df2\u7528\u672c\u5730\u89c4\u5219\u751f\u6210\uff0c\u5e76\u4fdd\u7559\u5bcc\u6587\u672c\u91cc\u7684 Markdown \u8d85\u94fe\u63a5\u3002':'\u5df2\u7528\u672c\u5730\u89c4\u5219\u5feb\u901f\u751f\u6210\uff0c\u53ef\u4ee5\u590d\u5236\u6216\u4e0b\u8f7d\u3002')}
async function refineWithLlm(){const ctx=buildCleanPayload();const btn=document.getElementById('refineBtn');const old=btn?btn.textContent:'';if(btn){btn.disabled=true;btn.textContent='LLM \u7cbe\u4fee\u4e2d...'}setStatus('LLM \u7cbe\u4fee\u5904\u7406\u4e2d\uff0c\u957f\u6587\u53ef\u80fd\u9700\u8981\u4e00\u4f1a\u513f...');try{const r=await fetch('/api/clean-markdown/refine',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(ctx.payload)});const d=await r.json();if(!d.ok){setStatus('LLM \u7cbe\u4fee\u5931\u8d25\uff1a'+(d.error||'unknown')+'\u3002\u5f53\u524d\u672c\u5730\u7ed3\u679c\u4e0d\u53d8\u3002');return;}applyCleanResult(d);setStatus('LLM \u7cbe\u4fee\u5b8c\u6210\uff0c\u5df2\u901a\u8fc7\u672a\u6539\u5b57\u6821\u9a8c\u3002')}catch(e){setStatus('LLM \u7cbe\u4fee\u5931\u8d25\uff1a'+((e&&e.message)||String(e))+'\u3002\u5f53\u524d\u672c\u5730\u7ed3\u679c\u4e0d\u53d8\u3002')}finally{if(btn){btn.disabled=false;btn.textContent=old||'LLM \u7cbe\u4fee'}}}
async function copyMd(){const v=document.getElementById('output').value;if(!v){setStatus('还没有 Markdown。');return;}await navigator.clipboard.writeText(v);setStatus('已复制到剪贴板。')}
function downloadMd(){const v=document.getElementById('output').value;if(!v){setStatus('还没有 Markdown。');return;}const blob=new Blob([v],{type:'text/markdown;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=lastFilename;document.body.appendChild(a);a.click();URL.revokeObjectURL(a.href);a.remove();setStatus('已触发下载。')}
function clearAll(){document.getElementById('input').value='';document.getElementById('output').value='';document.getElementById('meta').textContent='\u7b49\u5f85\u751f\u6210';capturedPasteHtml='';capturedPasteText='';setStatus('')}
initTheme();
setupRichPaste();
</script></body></html>"##,
    )
}
