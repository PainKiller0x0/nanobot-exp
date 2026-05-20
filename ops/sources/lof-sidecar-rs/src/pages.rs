use axum::{
    http::header,
    response::{Html, IntoResponse, Response},
};

pub(crate) async fn dashboard() -> Html<String> {
    Html(
        r##"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nanobot &#x9a7e;&#x9a76;&#x8231;</title>
<style>
:root{--paper:#fffaf0;--ink:#202019;--muted:#6f695d;--line:#e5dccb;--accent:#c26a2e;--accent2:#2f7f72;--ok:#17834f;--warn:#b76a12;--bad:#c43d32;--panel:rgba(255,250,240,.86);--shadow:0 22px 70px rgba(77,54,28,.16);--glow:rgba(194,106,46,.18)}
[data-theme="dark"]{--paper:#111816;--ink:#eef4e8;--muted:#aab6a6;--line:#2d3a34;--accent:#f0a35c;--accent2:#76c7b7;--ok:#76d39a;--warn:#f5c46b;--bad:#ff8278;--panel:rgba(25,34,30,.88);--shadow:0 24px 80px rgba(0,0,0,.34);--glow:rgba(118,199,183,.14)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--ink);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif;background:radial-gradient(920px 620px at -12% -20%,var(--glow),transparent 62%),radial-gradient(780px 520px at 110% 4%,rgba(47,127,114,.16),transparent 58%),linear-gradient(135deg,var(--paper),#edf1df 130%)}[data-theme="dark"] body{background:radial-gradient(920px 620px at -12% -20%,rgba(240,163,92,.14),transparent 62%),radial-gradient(780px 520px at 110% 4%,rgba(118,199,183,.16),transparent 58%),linear-gradient(135deg,#101816,#18211d 130%)}
.wrap{max-width:1240px;margin:0 auto;padding:26px 16px 42px}.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:16px;align-items:stretch}.panel{background:var(--panel);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);backdrop-filter:blur(12px)}.headline{padding:28px;position:relative;overflow:hidden}.headline:after{content:"";position:absolute;right:-80px;top:-90px;width:260px;height:260px;border-radius:50%;background:linear-gradient(135deg,var(--accent),transparent);opacity:.16}.eyebrow{color:var(--accent2);font-weight:900;letter-spacing:.16em;font-size:12px;text-transform:uppercase}.title{font-family:"Georgia","Noto Serif SC",serif;font-size:46px;line-height:1.02;margin:10px 0 12px;letter-spacing:-.04em}.sub{color:var(--muted);line-height:1.75;max-width:760px;margin:0}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}.btn{border:1px solid var(--line);background:var(--ink);color:var(--paper);text-decoration:none;border-radius:999px;padding:10px 14px;font-weight:900;cursor:pointer}.btn.secondary{background:transparent;color:var(--ink)}.btn:hover{transform:translateY(-1px)}.clock{padding:22px;display:flex;flex-direction:column;justify-content:space-between}.time{font-size:34px;font-weight:900;letter-spacing:-.03em}.date{color:var(--muted);margin-top:6px}.statusline{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:6px 10px;font-size:12px;font-weight:900;background:rgba(255,255,255,.28)}.pill.ok{color:var(--ok);border-color:rgba(23,131,79,.36)}.pill.warn{color:var(--warn);border-color:rgba(183,106,18,.36)}.pill.bad{color:var(--bad);border-color:rgba(196,61,50,.36)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-top:14px}.card{grid-column:span 4;padding:18px;position:relative;overflow:hidden}.card.wide{grid-column:span 8}.card.full{grid-column:1/-1}.card h2{font-size:18px;margin:0 0 12px}.metric{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:stretch}.metric>div{border:1px solid var(--line);border-radius:18px;padding:12px;background:rgba(255,255,255,.24);min-width:0;min-height:128px;display:flex;flex-direction:column;justify-content:flex-start}.metricTile{position:relative;overflow:hidden}.metricTile:after{content:"";position:absolute;inset:auto -22px -32px auto;width:80px;height:80px;border-radius:50%;background:var(--glow);opacity:.42}.tileNote{font-size:12px;color:var(--muted);line-height:1.45;margin-top:6px;position:relative;z-index:1}.gauge{height:8px;border-radius:999px;background:rgba(90,100,80,.14);overflow:hidden;border:1px solid var(--line);margin-top:8px;position:relative;z-index:1}.gauge>i{display:block;height:100%;width:0%;background:linear-gradient(90deg,var(--ok),var(--accent));border-radius:inherit}.k{font-size:12px;color:var(--muted);margin-bottom:5px;position:relative;z-index:1}.v{font-size:24px;font-weight:950;letter-spacing:-.03em;position:relative;z-index:1;white-space:nowrap}.statusFold,.detailCard{padding:18px}.statusFold summary,.detailCard summary{display:flex;justify-content:space-between;gap:12px;align-items:center;cursor:pointer;list-style:none}.statusFold summary::-webkit-details-marker,.detailCard summary::-webkit-details-marker{display:none}.statusFold summary h2,.detailCard summary h2{margin:0}.foldHint{color:var(--muted);font-size:12px;font-weight:900;border:1px solid var(--line);border-radius:999px;padding:5px 9px;background:rgba(255,255,255,.18)}.foldHint:before{content:'展开'}.statusFold[open] .foldHint:before,.detailCard[open] .foldHint:before{content:'收起'}.opsMiniGrid{display:grid;grid-template-columns:1.35fr .85fr .85fr;gap:10px;margin-top:12px}.opsMini{border:1px solid var(--line);border-radius:18px;padding:12px;background:rgba(255,255,255,.18);min-width:0}.opsMini h3{font-size:15px;margin:0 0 9px}.opsMini .metric{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.opsMini .metric>div{min-height:76px;padding:10px;border-radius:14px}.opsMini .v{font-size:20px}.opsMini .tileNote{font-size:11px;line-height:1.35}.opsMini .gauge{margin-top:5px}.detailBody{margin-top:12px}.list{display:grid;gap:10px}.item{border:1px solid var(--line);border-radius:17px;padding:12px;background:rgba(255,255,255,.20)}.row{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.name{font-weight:950}.muted{color:var(--muted)}.mini{font-size:12px}.danger{color:var(--bad)}.good{color:var(--ok)}.warnText{color:var(--warn)}.table{width:100%;border-collapse:collapse}.table th,.table td{border-bottom:1px solid var(--line);padding:9px 7px;text-align:left;vertical-align:top}.table th{color:var(--muted);font-size:12px}.table tr:hover{background:rgba(194,106,46,.08)}code,.pre{display:block;white-space:pre-wrap;overflow:auto;border:1px solid var(--line);border-radius:14px;padding:10px;background:rgba(0,0,0,.05);color:var(--ink)}.quick{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.quick a{display:block;border:1px solid var(--line);border-radius:18px;padding:13px;text-decoration:none;color:var(--ink);font-weight:900;background:rgba(255,255,255,.20)}.quick span{display:block;color:var(--muted);font-size:12px;font-weight:700;margin-top:4px}.briefGrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.briefBox{border:1px solid var(--line);border-radius:18px;padding:13px;background:rgba(255,255,255,.22)}.briefTitle{font-size:13px;color:var(--muted);font-weight:800}.briefMain{font-size:22px;font-weight:950;margin:5px 0}.briefNote{font-size:12px;color:var(--muted);line-height:1.5}.digestCols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.timeline{display:grid;gap:8px}.timeitem{display:grid;grid-template-columns:92px 1fr auto;gap:10px;align-items:center;border:1px solid var(--line);border-radius:14px;padding:9px;background:rgba(255,255,255,.18)}.linkline a{color:var(--accent2);font-weight:900;text-decoration:none}.linkline a:hover{text-decoration:underline}.infoGrid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr));align-items:stretch}.infoGrid .item{height:100%}.fade{animation:rise .42s ease both}@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@media(max-width:900px){.hero{grid-template-columns:1fr}.title{font-size:36px}.card,.card.wide{grid-column:1/-1}.metric,.briefGrid,.digestCols,.opsMiniGrid{grid-template-columns:1fr}.time{font-size:28px}.timeitem{grid-template-columns:1fr}}@media(max-width:620px){.wrap{padding:16px 10px 30px}.headline,.clock,.card{padding:16px}.title{font-size:31px}.actions{display:grid}.btn{text-align:center}.table{font-size:12px}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <div class="panel headline fade">
      <div class="eyebrow">Nanobot &#x4e2a;&#x4eba;&#x4e2d;&#x67a2;</div>
      <h1 class="title">&#x4eca;&#x65e5;&#x9a7e;&#x9a76;&#x8231;</h1>
      <p class="sub">&#x628a;&#x6587;&#x7ae0;&#x3001;LOF&#x3001;&#x5b9a;&#x65f6;&#x4efb;&#x52a1;&#x548c;&#x670d;&#x52a1;&#x5668;&#x72b6;&#x6001;&#x538b;&#x6210;&#x4e00;&#x773c;&#x80fd;&#x770b;&#x61c2;&#x7684;&#x6458;&#x8981;&#x3002;&#x4f4e;&#x4ef7;&#x503c;&#x4fe1;&#x606f;&#x8fdb;&#x770b;&#x677f;&#xff0c;&#x9ad8;&#x4ef7;&#x503c;&#x5f02;&#x5e38;&#x518d;&#x6253;&#x6270;&#x4f60;&#x3002;</p>
      <div class="actions">
        <a class="btn" href="/today">打开个人中枢</a>
        <a class="btn secondary" href="/workbench">内容工作台</a>
        <a class="btn secondary" href="/lof">LOF 投资看板</a>
        <a class="btn secondary" href="/sidecars">系统运维</a>
        <button class="btn secondary" onclick="loadAll(true)">&#x5237;&#x65b0;</button>
        <button class="btn secondary" onclick="toggleTheme()">&#x660e;&#x6697;</button>
      </div>
    </div>
    <div class="panel clock fade" style="animation-delay:.06s">
      <div><div class="k">Asia/Shanghai</div><div class="time" id="clock">--:--</div><div class="date" id="date">&#x52a0;&#x8f7d;&#x4e2d;...</div></div>
      <div class="statusline" id="statusline"><span class="pill warn">&#x6b63;&#x5728;&#x8bfb;&#x53d6;&#x72b6;&#x6001;</span></div>
    </div>
  </section>
  <section class="grid">
    <article class="panel card full fade" style="animation-delay:.08s"><h2>&#x4eca;&#x65e5;&#x6458;&#x8981;</h2><div id="todayBrief"></div></article>
    <article class="panel card wide fade" style="animation-delay:.10s"><h2>&#x6295;&#x8d44;&#x96f7;&#x8fbe;</h2><div id="lofRadar"></div></article>
    <article class="panel card fade" style="animation-delay:.12s"><h2>&#x9700;&#x8981;&#x4f60;&#x770b;</h2><div class="list" id="attention"></div></article>
    <details class="panel card full fade statusFold" style="animation-delay:.14s" open><summary><h2>运行状态</h2><span class="foldHint"></span></summary><div class="opsMiniGrid"><div class="opsMini"><h3>&#x7cfb;&#x7edf;&#x4f53;&#x611f;</h3><div class="metric" id="systemMetrics"></div></div><div class="opsMini"><h3>&#x670d;&#x52a1;&#x5065;&#x5eb7;</h3><div class="metric" id="sidecarMetrics"></div></div><div class="opsMini"><h3>&#x5b9a;&#x65f6;&#x4efb;&#x52a1;</h3><div class="metric" id="notifyMetrics"></div></div></div></details>
    <article class="panel card full fade" style="animation-delay:.16s"><h2>&#x5feb;&#x901f;&#x5165;&#x53e3;</h2><div class="quick"><a href="/today">个人中枢<span>今日内容、任务追踪、模型路由先看这里</span></a><a href="/workbench">内容工作台<span>RSS、知识收件箱、热点雷达合并阅读</span></a><a href="/lof">投资看板<span>LOF 实时估值、溢价、报告和手动刷新</span></a><a href="/sidecars">系统运维<span>服务健康、能力矩阵、日志和命令入口</span></a><a href="/model-routes">模型成本<span>OBP 路由、Pro 原因、付费/免费消耗</span></a></div></article>
    <article class="panel card full fade" style="animation-delay:.18s"><h2>&#x4fe1;&#x606f;&#x96f7;&#x8fbe;</h2><div class="list infoGrid" id="infoRadar"></div></article>
    <details class="panel card full fade detailCard" style="animation-delay:.20s"><summary><h2>7 &#x5929;&#x5386;&#x53f2;</h2><span class="foldHint"></span></summary><div class="detailBody" id="historyPanel"></div></details>
    <details class="panel card full fade detailCard" style="animation-delay:.21s"><summary><h2>记忆压缩</h2><span class="foldHint"></span></summary><div class="detailBody" id="compactPanel"></div></details>
    <details class="panel card full fade detailCard" style="animation-delay:.22s"><summary><h2>Nanobot 能力矩阵</h2><span class="foldHint"></span></summary><div class="detailBody"><div class="quick">
      <a href="/inbox">知识收件箱<span>QQ：收一下 + 链接 / 这个值得看吗 + 链接；按需抓取 Markdown，不常驻</span></a>
      <a href="/workbench">内容工作台<span>RSS、知识收件箱、热点雷达合并阅读；本地标记已读/收藏</span></a>
      <a href="/rss/">RSS 文章能力<span>微信、鸭哥、Markdown 预览、广告过滤，仍走 RSS sidecar</span></a>
      <a href="/trends/">热点雷达能力<span>全网热榜、搜索、话题趋势、MCP 风格工具接口，走 Trend sidecar</span></a>
      <a href="/sidecars">服务运维能力<span>内存怎么样 / 服务状态 / cron 任务怎么样；真实数据查询</span></a>
    </div><div class="muted mini" style="margin-top:10px">说明：这些是 Nanobot skill/按需脚本能力，没有独立端口和 health check，所以不会计入下面的 sidecar 服务健康数量。</div></div></details>
    <details class="panel card full fade detailCard" style="animation-delay:.23s"><summary><h2>&#x670d;&#x52a1;&#x77e9;&#x9635;</h2><span class="foldHint"></span></summary><div class="detailBody" style="overflow:auto"><table class="table" id="services"></table></div></details>
  </section>
</div>
<script src="/assets/nb-shell.js" data-prefix="/" data-label="今日驾驶舱" defer></script>
<script>
const root=document.documentElement;
function applyDashboardTheme(mode){const dark=mode==='dark';const value=dark?'dark':'light';root.setAttribute('data-theme',value);root.classList.toggle('dark',dark);if(document.body){document.body.setAttribute('data-theme',value);document.body.classList.toggle('dark',dark)}['dashboardTheme','sidecarShellTheme','lofTheme','theme'].forEach(k=>localStorage[k]=value)}
applyDashboardTheme((localStorage.sidecarShellTheme||localStorage.dashboardTheme)==='dark'?'dark':'light');
const state={system:null,sidecars:null,lof:null,notify:null,rss:null,rssSubs:null,history:null,compact:null};
function toggleTheme(){const dark=root.getAttribute('data-theme')==='dark'||root.classList.contains('dark');applyDashboardTheme(dark?'light':'dark')}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function pill(cls,text){return `<span class="pill ${cls}">${esc(text)}</span>`}
function fmtPct(v){return v==null?'-':Number(v).toFixed(2)+'%'}
function fmtTime(s){if(!s)return '-';try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s}}
function metricTile(k,v,cls='',note='',extra=''){return `<div class="metricTile"><div class="k">${esc(k)}</div><div class="v ${cls}">${esc(v)}</div>${note?`<div class="tileNote">${esc(note)}</div>`:''}${extra||''}</div>`}function metric(k,v,cls=''){return metricTile(k,v,cls)}function metricNote(k,v,n,cls=''){return metricTile(k,v,cls,n)}function briefBox(title,main,note){return `<div class="briefBox"><div class="briefTitle">${esc(title)}</div><div class="briefMain">${esc(main)}</div><div class="briefNote">${esc(note)}</div></div>`}
function num(v){const n=Number(v);return Number.isFinite(n)?n:null}
function clamp(v,min,max){return Math.max(min,Math.min(max,v))}
function loadFeeling(load,cpu){const one=num(load?.one);const cores=Math.max(1,num(cpu?.cores)||1);if(one==null)return {label:'未知',cls:'warnText',note:'暂无 CPU 数据'};const ratio=one/cores;if(ratio<0.35)return {label:'轻快',cls:'good',note:`CPU 1分钟排队 ${one.toFixed(2)} / ${cores}核`};if(ratio<0.75)return {label:'正常',cls:'good',note:`CPU 1分钟排队 ${one.toFixed(2)} / ${cores}核`};return {label:'偏忙',cls:'warnText',note:`CPU 1分钟排队 ${one.toFixed(2)} / ${cores}核`}}
function serviceName(x){const m={nanobot:'\u004e\u0061\u006e\u006f\u0062\u006f\u0074 \u6838\u5fc3',rss:'\u0052\u0053\u0053 \u8ba2\u9605\u770b\u677f',qq:'\u0051\u0051 \u901a\u77e5\u6865',lof:'\u004c\u004f\u0046 \u770b\u677f',notify:'\u5b9a\u65f6\u4efb\u52a1\u6865',reflexio:'\u0052\u0065\u0066\u006c\u0065\u0078\u0069\u006f \u8bb0\u5fc6\u770b\u677f',obp:'\u004f\u0042\u0050 \u515c\u5e95\u6865','podman-public-rule':'\u516c\u7f51\u7aef\u53e3\u5b88\u536b'};return m[x?.id]||x?.name||'-'}
function jobName(j){const m={'yage-ai':'\u9e2d\u54e5 \u0041\u0049 \u8981\u95fb','wechat-sub-1':'\u5fae\u4fe1\u6587\u7ae0\u63a8\u9001\uff1a\u8bb0\u5fc6\u627f\u8f7d','wechat-sub-2':'\u5fae\u4fe1\u6587\u7ae0\u63a8\u9001\uff1a\u8bb0\u5fc6\u627f\u8f7d3','lof-morning':'\u004c\u004f\u0046 \u65e9\u5e02\u62a5\u544a','lof-noon':'\u004c\u004f\u0046 \u5348\u5e02\u62a5\u544a','lof-close':'\u004c\u004f\u0046 \u6536\u76d8\u62a5\u544a','hermes-heartbeat':'\u0048\u0045\u0052\u004d\u0045\u0053 \u5fc3\u8df3\u81ea\u68c0','weather-sz-workday':'\u6df1\u5733\u666e\u901a\u5de5\u4f5c\u65e5\u5929\u6c14','weather-gz-friday-noon':'\u5e7f\u5dde\u4f11\u606f\u65e5\u524d\u5929\u6c14','weather-gz-weekend':'\u5e7f\u5dde\u4f11\u606f\u65e5\u5929\u6c14','weather-sz-monday':'\u6df1\u5733\u9996\u4e2a\u5de5\u4f5c\u65e5\u5929\u6c14'};return m[j?.id]||j?.name||j?.id||'-'}
function statusText(s){const m={silent:'\u9759\u9ed8',sent:'\u5df2\u53d1\u9001',error:'\u9519\u8bef',running:'\u8fd0\u884c\u4e2d',timeout:'\u8d85\u65f6',ok:'\u6b63\u5e38'};return m[s]||s||'-'}
function updateClock(){const now=new Date();document.getElementById('clock').textContent=now.toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});document.getElementById('date').textContent=now.toLocaleDateString('zh-CN',{weekday:'long',year:'numeric',month:'2-digit',day:'2-digit',timeZone:'Asia/Shanghai'})}
async function getJson(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(url+' '+r.status);return r.json()}
async function loadAll(manual=false){const jobs=[['system','/api/system'],['sidecars','/api/sidecars'],['lof','/api/status'],['notify','/api/notify-jobs'],['rss','/rss/api/entries?days=1&limit=8'],['rssSubs','/rss/api/subscriptions'],['history','/api/dashboard-history'],['compact','/api/auto-compact']];await Promise.all(jobs.map(async ([key,url])=>{try{state[key]=await getJson(url)}catch(e){state[key]={ok:false,error:e.message}}}));renderAll(manual)}
function renderAll(manual){renderStatusline(manual);renderSystem();renderSidecars();renderNotify();renderToday();renderAttention();renderLof();renderInfo();renderHistory();renderCompact();renderServices()}
function renderStatusline(manual){const s=state.sidecars?.summary||{};const bad=s.unhealthy||0;const jobs=state.notify?.job_details||[];const jobErr=jobs.filter(j=>j.status?.last_status==='error').length;const lof=state.lof?.last_run?.status;document.getElementById('statusline').innerHTML=[bad?pill('bad',`\u670d\u52a1\u5f02\u5e38 ${bad}`):pill('ok',`\u670d\u52a1 ${s.healthy||0}/${s.total||0}`),jobErr?pill('bad',`\u4efb\u52a1\u9519\u8bef ${jobErr}`):pill('ok','\u4efb\u52a1\u6b63\u5e38'),lof==='ok'?pill('ok','\u004c\u004f\u0046 \u5df2\u5237\u65b0'):pill('warn','\u004c\u004f\u0046 '+(statusText(lof)||'\u672a\u77e5')),manual?pill('warn','\u5df2\u5237\u65b0'):'' ].join('')}
function renderSystem(){const m=state.system?.memory||{};const pressure=loadFeeling(state.system?.loadavg||{},state.system?.cpu||{});const pct=clamp(num(m.used_pct)||0,0,100);const memCls=pct>75?'warnText':'good';const feel=pct>75?'偏紧':pressure.label;const feelCls=pct>75?'warnText':pressure.cls;document.getElementById('systemMetrics').innerHTML=metricNote('当前体感',feel,'内存 + CPU 综合估算',feelCls)+metricTile('内存',`${m.used_mb??'-'} MB`,memCls,`${m.used_pct??'-'}% · 可用 ${m.available_mb??'-'} MB`,`<div class="gauge"><i style="width:${pct}%"></i></div>`)+metricNote('CPU 压力',pressure.label,pressure.note,pressure.cls)}
function renderSidecars(){const s=state.sidecars?.summary||{};document.getElementById('sidecarMetrics').innerHTML=metric('\u603b\u6570',s.total??'-')+metric('\u6b63\u5e38',s.healthy??'-','good')+metric('\u5f02\u5e38',s.unhealthy??'-',(s.unhealthy||0)?'danger':'good')}
function renderNotify(){const jobs=state.notify?.job_details||[];const enabled=jobs.filter(j=>j.enabled).length;const err=jobs.filter(j=>j.status?.last_status==='error').length;const sent=jobs.filter(j=>j.status?.last_sent).length;document.getElementById('notifyMetrics').innerHTML=metric('\u542f\u7528',enabled)+metric('\u9519\u8bef',err,err?'danger':'good')+metric('\u6700\u8fd1\u53d1\u9001',sent)}

function todayKey(){return new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'})}
function dateKey(s){if(!s)return '';try{return new Date(String(s).replace(' +08:00','+08:00')).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'})}catch{return String(s).slice(0,10)}}
function isToday(s){return dateKey(s)===todayKey()}
function hhmm(s){if(!s)return '-';try{return new Date(String(s).replace(' +08:00','+08:00')).toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'})}catch{return String(s).slice(11,16)||'-'}}
function sourceName(e){return e?.subscription_name||e?.source||'RSS'}
function todayJobs(){return (state.notify?.job_details||[]).filter(j=>isToday(j.status?.last_finished_at||j.status?.last_started_at))}
function todaySentJobs(){return todayJobs().filter(j=>j.status?.last_sent)}
function jobBadge(j){const st=j.status?.last_status;return pill(st==='error'?'bad':(j.status?.last_sent?'ok':'warn'),statusText(st))}
function renderToday(){
  const box=document.getElementById('todayBrief'); if(!box)return;
  const jobs=state.notify?.job_details||[];
  const todays=todayJobs();
  const sent=todaySentJobs();
  const errors=jobs.filter(j=>j.status?.last_status==='error');
  const rssItems=(state.rss?.items||[]).slice(0,8);
  const rssSubs=(state.rssSubs?.items||[]);
  const rssOk=rssSubs.filter(x=>(x.last_status||'').toLowerCase()==='ok').length;
  const side=state.sidecars?.summary||{};
  const mem=state.system?.memory||{};
  const lr=state.lof?.last_run||{};
  const rows=state.lof?.last_board?.rows||[];
  const high=rows.filter(r=>(r.rt_premium_pct||0)>=5);
  const lofSent=jobs.filter(j=>String(j.id||'').startsWith('lof-')&&isToday(j.status?.last_finished_at)&&j.status?.last_sent).length;
  const brief=`<div class="briefGrid">
    ${briefBox('信息',`${rssItems.length}篇`,`RSS 订阅 ${rssOk}/${rssSubs.length||0} 正常，鸭哥/微信任务已纳入监控。`)}
    ${briefBox('投资',`${high.length}只`,`实时溢价≥5%；LOF 今日推送 ${lofSent}/3，最新状态 ${statusText(lr.status)}。`)}
    ${briefBox('任务',`${todays.length}次`,`今日已完成触发；发送 ${sent.length}次，错误 ${errors.length}个。`)}
    ${briefBox('系统',`${mem.used_pct??'-'}%`,`服务 ${side.healthy||0}/${side.total||0} 正常，CPU 压力 ${loadFeeling(state.system?.loadavg||{},state.system?.cpu||{}).label}，内存 ${mem.used_mb??'-'} / ${mem.total_mb??'-'} MB。`)}
  </div>`;
  const focus=[];
  errors.slice(0,2).forEach(j=>focus.push(`<div class="item"><div class="name danger">\u4efb\u52a1\u5931\u8d25\uff1a${esc(jobName(j))}</div><div class="muted mini">${esc(j.status?.last_error||j.id)}</div></div>`));
  high.slice(0,2).forEach(r=>focus.push(`<div class="item"><div class="name warnText">${esc(r.code)} ${esc(r.name)} \u9ad8\u6ea2\u4ef7</div><div class="muted mini">\u5b9e\u65f6 ${fmtPct(r.rt_premium_pct)} / \u6700\u65b0 ${fmtPct(r.latest_premium_pct)} / ${esc(r.limit_text||'-')}</div></div>`));
  rssItems.slice(0,3).forEach(e=>focus.push(`<div class="item linkline"><div class="name"><a href="${esc(e.link||'/rss/')}" target="_blank" rel="noopener">${esc(e.title||'\u672a\u547d\u540d\u6587\u7ae0')}</a></div><div class="muted mini">${esc(sourceName(e))} \u00b7 ${esc(e.published_at_local||e.published_at||e.inserted_at||'-')}</div></div>`));
  if(!focus.length)focus.push(`<div class="item"><div class="name good">\u4eca\u5929\u6ca1\u6709\u7ea2\u8272\u4e8b\u9879</div><div class="muted mini">\u4fe1\u606f\u3001\u6295\u8d44\u548c\u7cfb\u7edf\u90fd\u6ca1\u6709\u9700\u8981\u7acb\u523b\u5904\u7406\u7684\u544a\u8b66\u3002</div></div>`);
  const timeline=todays.slice().sort((a,b)=>String(b.status?.last_finished_at||'').localeCompare(String(a.status?.last_finished_at||''))).slice(0,8);
  const timelineHtml=timeline.length?timeline.map(j=>`<div class="timeitem"><div class="muted mini">${hhmm(j.status?.last_finished_at||j.status?.last_started_at)}</div><div><div class="name">${esc(jobName(j))}</div><div class="muted mini">${esc(j.schedule_note||j.schedule||'')}</div></div><div>${jobBadge(j)}</div></div>`).join(''):`<div class="muted">\u4eca\u5929\u8fd8\u6ca1\u6709\u4efb\u52a1\u5b8c\u6210\u8bb0\u5f55\u3002</div>`;
  box.innerHTML=brief+`<div class="digestCols"><div><h2 style="font-size:16px;margin:0 0 10px">今天真正需要处理的 3 件事</h2><div class="list">${focus.slice(0,3).join('')}</div></div><div><h2 style="font-size:16px;margin:0 0 10px">\u4eca\u65e5\u65f6\u95f4\u7ebf</h2><div class="timeline">${timelineHtml}</div></div></div>`;
}
function renderAttention(){const box=document.getElementById('attention');const items=[];(state.sidecars?.items||[]).filter(x=>!x.ok).forEach(x=>items.push({level:'bad',title:`${serviceName(x)} \u5f02\u5e38`,body:x.error||x.check_status||'\u5065\u5eb7\u68c0\u67e5\u5931\u8d25'}));(state.notify?.job_details||[]).filter(j=>j.status?.last_status==='error').forEach(j=>items.push({level:'bad',title:`\u4efb\u52a1\u5931\u8d25\uff1a${jobName(j)}`,body:j.status?.last_error||j.id}));const rows=state.lof?.last_board?.rows||[];rows.filter(r=>(r.rt_premium_pct||0)>=5).slice(0,3).forEach(r=>items.push({level:'warn',title:`\u9ad8\u6ea2\u4ef7\uff1a${r.code} ${r.name}`,body:`\u5b9e\u65f6 ${fmtPct(r.rt_premium_pct)} / \u6700\u65b0 ${fmtPct(r.latest_premium_pct)} / ${r.limit_text||'-'}`}));if(!items.length)items.push({level:'ok',title:'\u6ca1\u6709\u9700\u8981\u7acb\u523b\u5904\u7406\u7684\u544a\u8b66',body:'\u670d\u52a1\u3001\u4efb\u52a1\u548c \u004c\u004f\u0046 \u96f7\u8fbe\u76ee\u524d\u7a33\u5b9a\u3002'});box.innerHTML=items.slice(0,6).map(x=>`<div class="item"><div class="row"><div><div class="name ${x.level==='bad'?'danger':x.level==='warn'?'warnText':'good'}">${esc(x.title)}</div><div class="muted mini">${esc(x.body)}</div></div>${pill(x.level==='bad'?'bad':x.level==='warn'?'warn':'ok',x.level==='bad'?'\u5904\u7406':x.level==='warn'?'\u5173\u6ce8':'\u6b63\u5e38')}</div></div>`).join('')}
function boardAgeMinutes(s){if(!s)return null;const t=new Date(String(s).replace(' +08:00','+08:00')).getTime();if(!Number.isFinite(t))return null;return Math.max(0,(Date.now()-t)/60000)}
function renderLof(){const lr=state.lof?.last_run||{};const board=state.lof?.last_board||{};const all=board.rows||[];const high=all.filter(r=>(r.rt_premium_pct||0)>=5);const rising=all.filter(r=>Number(r.consecutive_days||0)>=3);const age=boardAgeMinutes(board.updated_at);const stale=age!=null&&age>12;const signals=[{title:'高溢价',main:`${high.length}只`,note:'实时溢价 ≥ 5%',cls:high.length?'warnText':'good'},{title:'连续风险',main:`${rising.length}只`,note:'连续 3 天以上高溢价',cls:rising.length?'warnText':'good'},{title:'数据年龄',main:age==null?'-':`${Math.round(age)}m`,note:stale?'可能不是最新行情':'看板数据较新',cls:stale?'warnText':'good'}];const signalHtml=`<div class="briefGrid" style="margin-top:12px">${signals.map(s=>`<div class="briefBox"><div class="briefTitle">${esc(s.title)}</div><div class="briefMain ${s.cls}">${esc(s.main)}</div><div class="briefNote">${esc(s.note)}</div></div>`).join('')}</div>`;const rows=[...all].sort((a,b)=>(b.rt_premium_pct??-999)-(a.rt_premium_pct??-999)).slice(0,6);const table=`<table class="table"><thead><tr><th>代码</th><th>名称</th><th>实时溢价</th><th>最新溢价</th><th>连续</th><th>限额</th></tr></thead><tbody>${rows.map(r=>`<tr><td><a href="https://fund.eastmoney.com/${esc(r.code)}.html" target="_blank">${esc(r.code)}</a></td><td>${esc(r.name)}</td><td class="${(r.rt_premium_pct||0)>=5?'warnText':'good'}">${fmtPct(r.rt_premium_pct)}</td><td>${fmtPct(r.latest_premium_pct)}</td><td>${esc(r.consecutive_days??0)}天</td><td>${esc(r.limit_text||'-')}</td></tr>`).join('')}</tbody></table>`;const report=(lr.report||'').split('\n').slice(0,8).join('\n');document.getElementById('lofRadar').innerHTML=`<div class="row"><div><div class="name">投资信号 · ${esc(lr.tag||'LOF')}</div><div class="muted mini">完成：${fmtTime(lr.finished_at)} · ${lr.duration_ms??'-'}ms · ${statusText(lr.status)} · 看板：${fmtTime(board.updated_at)}</div></div><a class="btn secondary" href="/lof">详情</a></div>${signalHtml}<div style="margin-top:12px;overflow:auto">${table}</div><details style="margin-top:10px"><summary class="muted">报告摘要</summary><code>${esc(report||lr.error||'暂无')}</code></details>`}
function renderInfo(){const jobs=state.notify?.job_details||[];const ids=['yage-ai','wechat-sub-1','wechat-sub-2','hermes-heartbeat'];document.getElementById('infoRadar').innerHTML=ids.map(id=>jobs.find(j=>j.id===id)).filter(Boolean).map(j=>`<div class="item"><div class="row"><div><div class="name">${esc(jobName(j))}</div><div class="muted mini">\u4e0b\u6b21\uff1a${esc((j.next_runs||[])[0]||'-')} \u00b7 \u6700\u8fd1\uff1a${esc(j.status?.last_finished_at||'-')}</div></div>${pill(j.status?.last_status==='error'?'bad':(j.status?.last_sent?'ok':'warn'),statusText(j.status?.last_status))}</div></div>`).join('')||'<div class="muted">\u6682\u65e0\u4efb\u52a1\u6570\u636e</div>'}
function renderHistory(){const box=document.getElementById('historyPanel');if(!box)return;const items=state.history?.items||[];if(!items.length){box.innerHTML='<div class="muted">\u5386\u53f2\u4ece\u73b0\u5728\u5f00\u59cb\u8bb0\u5f55\uff0c\u6682\u65e0\u6837\u672c\u3002</div>';return}const rows=[...items].reverse();box.innerHTML=`<div style="overflow:auto"><table class="table"><thead><tr><th>\u65e5\u671f</th><th>\u5185\u5b58\u5cf0\u503c</th><th>\u670d\u52a1</th><th>\u4efb\u52a1</th><th>\u6587\u7ae0</th><th>LOF</th><th>\u66f4\u65b0</th></tr></thead><tbody>${rows.map(x=>`<tr><td><b>${esc(x.day)}</b></td><td>${esc(x.memory_used_max_mb??x.memory_used_mb??'-')} MB<br><span class="muted mini">\u5f53\u524d ${esc(x.memory_used_mb??'-')} MB / ${esc(x.memory_used_pct??'-')}%</span></td><td>${pill((x.service_unhealthy||0)>0?'bad':'ok',`${x.service_healthy||0}/${x.service_total||0}`)}<br><span class="muted mini">\u5f02\u5e38\u5cf0\u503c ${esc(x.service_unhealthy_max??0)}</span></td><td>${esc(x.task_runs??0)} \u6b21 / \u53d1\u9001 ${esc(x.task_sent??0)}<br><span class="${(x.task_errors_max||0)>0?'danger':'good'} mini">\u9519\u8bef\u5cf0\u503c ${esc(x.task_errors_max??0)}</span></td><td>${esc(x.articles??0)} \u7bc7</td><td>${esc(x.lof_high_premium??0)} \u53ea<br><span class="muted mini">\u5cf0\u503c ${esc(x.lof_high_premium_max??0)}</span></td><td class="mini">${esc(x.updated_at||'-')}</td></tr>`).join('')}</tbody></table></div><div class="muted mini" style="margin-top:8px">${esc(state.history?.note||'\u6bcf\u6b21\u6253\u5f00\u6216\u5237\u65b0\u9a7e\u9a76\u8231\u65f6\u8bb0\u5f55\u4e00\u4efd\u5f53\u65e5\u5feb\u7167\uff0c\u4fdd\u7559\u6700\u8fd1 7 \u5929\u3002')}</div>`}
function compactAction(a){const m={archived:'已压缩',deferred:'已延后',empty:'空会话',failed:'失败'};return m[a]||a||'-'}
function compactTime(s){if(!s)return '-';try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return String(s)}}
function renderCompact(){const box=document.getElementById('compactPanel');if(!box)return;const items=state.compact?.items||[];if(!items.length){box.innerHTML=`<div class="muted">暂无压缩事件。当前线上更像是 Heartbeat 每 30 分钟消耗 token；AutoCompact 只有开启 idleCompactAfterMinutes 后才会记录。</div><div class="muted mini" style="margin-top:8px">日志路径：${esc(state.compact?.path||'/root/.nanobot/workspace/auto_compact_events.jsonl')}</div>`;return}const latest=items[0]||{};const archived=items.filter(x=>x.action==='archived').length;const deferred=items.filter(x=>x.action==='deferred').length;const forced=items.filter(x=>x.forced).length;const rows=items.slice(0,8).map(x=>`<tr><td>${esc(compactTime(x.ts))}</td><td>${pill(x.action==='failed'?'bad':x.action==='deferred'?'warn':'ok',compactAction(x.action))}</td><td>${esc(x.key||'-')}</td><td>${esc(x.pending_messages??'-')} / ${esc(x.threshold_messages??'-')}</td><td>${esc(x.archived_messages??'-')} / ${esc(x.kept_messages??'-')}</td><td>${x.summary?`<details><summary>摘要</summary><code>${esc(x.summary)}</code></details>`:(x.next_check_at?`下次：${esc(compactTime(x.next_check_at))}`:'-')}</td></tr>`).join('');box.innerHTML=`<div class="briefGrid">${briefBox('最近状态',compactAction(latest.action),latest.ts?compactTime(latest.ts):'还没有记录')}${briefBox('已压缩',`${archived}次`,'最近 30 条压缩事件')}${briefBox('已延后',`${deferred}次`,'低消息量不花 token')}${briefBox('强制压缩',`${forced}次`,'达到 12 小时上限')}</div><div style="overflow:auto;margin-top:12px"><table class="table"><thead><tr><th>时间</th><th>动作</th><th>会话</th><th>累计/门槛</th><th>压缩/保留</th><th>内容</th></tr></thead><tbody>${rows}</tbody></table></div><div class="muted mini" style="margin-top:8px">日志路径：${esc(state.compact?.path||'-')}</div>`}
function accessUrl(x){if(!x.homepage_url)return '\u5185\u90e8';try{return new URL(x.homepage_url,location.origin).pathname}catch{return x.homepage_url}}
function renderServices(){const rows=state.sidecars?.items||[];document.getElementById('services').innerHTML=`<thead><tr><th>\u670d\u52a1</th><th>\u72b6\u6001</th><th>\u5165\u53e3</th><th>\u76d1\u542c</th><th>\u5ef6\u8fdf</th><th>\u6700\u8fd1\u544a\u8b66</th></tr></thead><tbody>${rows.map(x=>`<tr><td><b>${esc(serviceName(x))}</b><br><span class="muted mini">${esc(x.id)}</span></td><td>${pill(x.ok?'ok':'bad',x.ok?'\u6b63\u5e38':(x.check_status||'-'))}</td><td>${x.homepage_url?`<a href="${esc(x.homepage_url)}">${esc(accessUrl(x))}</a>`:'\u5185\u90e8'}</td><td>${x.port?(x.public?'0.0.0.0':'127.0.0.1')+':'+x.port:'-'}</td><td>${x.latency_ms??'-'} ms</td><td class="mini">${esc((x.recent_errors||[])[0]||'-')}</td></tr>`).join('')}</tbody>`}
updateClock();setInterval(updateClock,1000);loadAll();setInterval(()=>loadAll(false),60000);
</script>
</body>
</html>"##.to_string(),
    )
}

pub(crate) async fn inbox_page() -> impl IntoResponse {
    Html(
        r##"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>知识收件箱</title>
<style>
:root{--bg:#f7f0e4;--panel:#fffdf7;--text:#202019;--muted:#6f695d;--line:#e4dac8;--soft:#f2eadb;--accent:#b96a33;--accent2:#287f73;--ok:#16844d;--warn:#b76a12;--bad:#c43d32;--shadow:0 22px 70px rgba(73,50,24,.14)}
[data-theme="dark"]{--bg:#101816;--panel:#1b2621;--text:#edf5ea;--muted:#a8b5a4;--line:#304038;--soft:#233029;--accent:#efa35c;--accent2:#77c7b7;--ok:#76d39a;--warn:#f3c468;--bad:#ff8278;--shadow:0 22px 72px rgba(0,0,0,.36)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--text);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif;background:radial-gradient(900px 520px at -8% -18%,rgba(185,106,51,.22),transparent 58%),radial-gradient(740px 460px at 108% 0,rgba(40,127,115,.18),transparent 55%),var(--bg)}.wrap{max-width:1120px;margin:0 auto;padding:26px 16px 42px}.hero{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);padding:22px}.eyebrow{color:var(--accent2);font-size:12px;font-weight:900;letter-spacing:.16em}.title{font-family:Georgia,"Noto Serif SC",serif;font-size:44px;line-height:1.04;margin:8px 0 10px;letter-spacing:-.04em}.sub{color:var(--muted);line-height:1.75;margin:0}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.btn{border:1px solid var(--line);border-radius:999px;padding:10px 14px;background:var(--text);color:var(--bg);font-weight:900;text-decoration:none;cursor:pointer}.btn.secondary{background:transparent;color:var(--text)}.btn.danger{background:transparent;color:var(--bad);border-color:var(--bad)}.btn.small{padding:7px 10px;font-size:12px;box-shadow:none}.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.stat{border:1px solid var(--line);border-radius:18px;padding:14px;background:rgba(255,255,255,.16)}.k{font-size:12px;color:var(--muted);font-weight:800}.v{font-size:30px;font-weight:950;letter-spacing:-.04em}.grid{display:grid;gap:12px;margin-top:14px}.item{display:grid;grid-template-columns:72px minmax(0,1fr);gap:14px;align-items:start;border:1px solid var(--line);border-radius:22px;padding:16px;background:rgba(255,255,255,.16)}.score{width:58px;height:58px;border-radius:18px;display:grid;place-items:center;font-weight:950;font-size:20px;border:1px solid var(--line);background:rgba(255,255,255,.20)}.score.ok{color:var(--ok)}.score.warn{color:var(--warn)}.score.bad{color:var(--bad)}.itemBody{min-width:0}.itemTop{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.name{font-size:19px;font-weight:950;line-height:1.35}.name a{color:var(--text);text-decoration:none}.name a:hover{color:var(--accent2);text-decoration:underline}.meta{color:var(--muted);font-size:13px;line-height:1.6;margin-top:6px}.summary{margin-top:12px;color:var(--text);line-height:1.75}.takeaways{display:grid;gap:8px}.takeaway{border-left:3px solid var(--accent2);padding:8px 10px;background:var(--soft);border-radius:10px}.takeaway b{display:block;margin-bottom:3px;color:var(--accent2)}.plainSummary{white-space:pre-wrap}.itemFooter{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:12px}.tags{display:flex;gap:6px;flex-wrap:wrap}.tag{border:1px solid var(--line);border-radius:999px;padding:4px 8px;color:var(--muted);font-size:12px}.itemActions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.empty{color:var(--muted);padding:24px}.mini{font-size:12px;color:var(--muted);line-height:1.5}.good{color:var(--ok)}.warnText{color:var(--warn)}.danger{color:var(--bad)}@media(max-width:820px){.hero{grid-template-columns:1fr}.title{font-size:34px}.item{grid-template-columns:1fr}.itemTop,.itemFooter{display:block}.itemActions{justify-content:flex-start;margin-top:10px}.stats{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <div class="panel">
      <div class="eyebrow">KNOWLEDGE INBOX</div>
      <h1 class="title">知识收件箱</h1>
      <p class="sub">QQ 里发“收一下 + 链接”会把网页抓成 Markdown；发“这个值得看吗 + 链接”会生成一个轻量决策包。这里负责查看最近收进来的材料，不新增常驻进程。</p>
      <div class="toolbar"><a class="btn" href="/">回到驾驶舱</a><a class="btn secondary" href="/api/inbox" target="_blank">JSON</a><button class="btn secondary" onclick="loadAll()">刷新</button><button class="btn secondary" onclick="toggleTheme()">明暗</button></div>
    </div>
    <div class="panel"><div class="stats" id="stats"><div class="empty">加载中...</div></div><div class="mini" style="margin-top:12px">数据源：/root/.nanobot/data/knowledge-inbox/items.json</div></div>
  </section>
  <section class="grid" id="items"></section>
</div>
<script src="/assets/nb-common.js"></script>
<script>
window.toggleTheme=NB.bindTheme('inboxTheme',{also:['dashboardTheme']});
const esc=NB.esc, stat=NB.stat, fmtTime=NB.fmtTime, host=NB.host;
function cls(score){score=Number(score)||0;return score>=75?'ok':score>=58?'warn':'bad'}
function label(item){return item.decision_label||((Number(item.decision_score)||0)>=75?'值得优先看':((Number(item.decision_score)||0)>=58?'可以稍后看':'扫一眼'))}
function cleanInline(s){return String(s??'').replace(/\*\*/g,'').replace(/^[\s\-•·]+/,'').replace(/\s+/g,' ').trim()}
function summaryHtml(item){
  const raw=String(item.summary||item.description||'暂无摘要').trim();
  const lines=raw.split(/\n+/).map(cleanInline).filter(Boolean);
  const blocks=[];
  for(const line of lines){
    const m=line.match(/^([^：:]{2,14})[：:]\s*(.+)$/);
    if(m&&m[2])blocks.push(`<div class="takeaway"><b>${esc(m[1])}</b><span>${esc(m[2])}</span></div>`);
    else blocks.push(`<div class="plainSummary">${esc(line)}</div>`);
  }
  return blocks.length>1?`<div class="takeaways">${blocks.join('')}</div>`:blocks.join('')||'<div class="plainSummary">暂无摘要</div>';
}
const TECH_WORDS=new Set(['mp.weixin.qq.com','wechat_redirect','scene','biz','mid','idx','javascript','void','cover_image','mmbiz.qpic.cn']);
function usefulKeyword(t){const v=String(t||'').trim().toLowerCase();if(!v||TECH_WORDS.has(v))return false;if(v.includes('qpic.cn')||v.includes('weixin.qq.com'))return false;if(/^[a-z0-9_=-]{12,}$/.test(v))return false;return true}
function sourceLabel(item){const h=String(item.host||host(item.final_url||item.url)).toLowerCase();if(h.includes('mp.weixin.qq.com'))return '微信文章';return item.content_type||'网页'}
function summaryLabel(item){if(item.summary_source==='longcat_free')return 'LongCat 摘要';if(item.summary_source)return item.summary_source;return ''}
function tagHtml(item){
  const raw=[...(item.tags||[]),...(item.keywords||[])].filter(usefulKeyword);
  const tags=[sourceLabel(item),summaryLabel(item),...raw].filter(Boolean).filter((x,i,a)=>a.indexOf(x)===i).slice(0,6);
  return tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('');
}
function render(data){
  const s=data.summary||{};
  document.getElementById('stats').innerHTML=stat('总数',s.total??0,'历史收进来的网页')+stat('今天',s.today??0,'今天新增')+stat('优先读',s.priority??0,'评分 ≥ 75')+stat('可跳过',s.skipped??0,'评分 < 42');
  const items=data.items||[];
  document.getElementById('items').innerHTML=items.length?items.map(item=>{
    const score=Number(item.decision_score)||0;
    const url=item.final_url||item.url||'#';
    const tags=tagHtml(item);
    const itemId=String(item.id||'');
    const title=String(item.title||'未命名网页');
    const pref=Number(item.preference_adjustment||0);
    const taste=(item.auto_base_score!==undefined&&item.auto_base_score!==null)?` · 基础 ${esc(item.auto_base_score)}${pref?` · 偏好 ${pref>0?'+':''}${pref}`:''}`:'';
    const manual=item.manual_score!==undefined&&item.manual_score!==null?' · 手动评分':'';
    return `<article class="item"><div class="score ${cls(score)}">${esc(score)}</div><div class="itemBody"><div class="itemTop"><div><div class="name"><a href="${esc(url)}" target="_blank" rel="noopener">${esc(title)}</a></div><div class="meta">${esc(label(item))} · ${esc(host(url))} · ${fmtTime(item.captured_at)} · ${esc(item.content_chars||0)} 字${taste}${manual}</div></div></div><div class="summary">${summaryHtml(item)}</div><div class="itemFooter"><div class="tags">${tags}</div><div class="itemActions"><a class="btn secondary small" href="${esc(url)}" target="_blank" rel="noopener">原文</a><button class="btn secondary small" data-path="${esc(item.markdown_path||'')}" onclick="NB.copyText(this.dataset.path,this)">复制 Markdown 路径</button><button class="btn secondary small" data-id="${esc(itemId)}" data-title="${esc(title)}" data-score="${esc(score)}" onclick="rateItemFromButton(this)">评分</button><button class="btn danger small" data-id="${esc(itemId)}" data-title="${esc(title)}" onclick="deleteItemFromButton(this)">删除</button></div></div></div></article>`
  }).join(''):'<div class="panel empty">收件箱还是空的。QQ 发“收一下 https://example.com”就能开始积累。</div>'
}
function deleteItemFromButton(btn){deleteItem(btn.dataset.id||'',btn.dataset.title||'未命名网页')}
function rateItemFromButton(btn){rateItem(btn.dataset.id||'',btn.dataset.title||'未命名网页',btn.dataset.score||'')}
async function rateItem(id,title,current){
  if(!id)return alert('这个条目没有 ID，不能评分');
  const value=prompt(`给这条内容打多少分？0-100\n\n${title}`, current||'');
  if(value===null)return;
  const score=Number(value);
  if(!Number.isFinite(score)||score<0||score>100)return alert('评分需要是 0 到 100 的数字');
  const note=prompt('备注（可选）：', '')||'';
  try{
    const r=await fetch('/api/inbox/'+encodeURIComponent(id)+'/rating',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({score:Math.round(score),note})});
    const data=await r.json().catch(()=>({}));
    if(!r.ok||data.ok===false)throw new Error(data.error||'评分失败');
    await loadAll();
  }catch(e){alert('评分失败：'+(e&&e.message?e.message:e))}
}
async function deleteItem(id,title){
  if(!id)return alert('这个条目没有 ID，不能删除');
  if(!confirm(`删除这条收件箱内容？\n\n${title}\n${id}`))return;
  try{
    const r=await fetch('/api/inbox/'+encodeURIComponent(id),{method:'DELETE'});
    const data=await r.json().catch(()=>({}));
    if(!r.ok||data.ok===false)throw new Error(data.error||'删除失败');
    await loadAll();
  }catch(e){alert('删除失败：'+(e&&e.message?e.message:e))}
}
async function loadAll(){try{const r=await fetch('/api/inbox',{cache:'no-store'});render(await r.json())}catch(e){document.getElementById('items').innerHTML='<div class="panel empty danger">读取失败：'+esc(e.message)+'</div>'}}
loadAll();
</script>
</body>
</html>"##,
    )
}

pub(crate) async fn shell_js() -> Response {
    const SHELL_JS: &str = r####"
(() => {
  if (window.__NB_SHELL_READY__) return;
  window.__NB_SHELL_READY__ = true;
  const script = document.currentScript;
  const label = script?.dataset?.label || document.title || 'Sidecar';
  const current = script?.dataset?.prefix || location.pathname.split('/')[1] || '/';
  const links = [
    ['总览','/'],['今日','/today'],['内容','/workbench'],['投资','/lof'],['任务','/tasks'],['模型','/model-routes'],['服务','/sidecars']
  ];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  function applyTheme(mode){
    const dark = mode === 'dark';
    const value = dark ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', value);
    document.documentElement.classList.toggle('dark', dark);
    if (document.body) {
      document.body.setAttribute('data-theme', value);
      document.body.classList.toggle('dark', dark);
    }
    ['sidecarShellTheme','dashboardTheme','obp_theme','lofTheme','theme'].forEach(k => { localStorage[k] = value; });
  }
  function toggleTheme(){
    const cur = document.documentElement.classList.contains('dark') || document.documentElement.getAttribute('data-theme') === 'dark';
    applyTheme(cur ? 'light' : 'dark');
  }
  function build(){
    if (document.getElementById('nb-sidecar-shell')) return;
    document.documentElement.classList.add('nb-skin');
    const savedTheme = localStorage.sidecarShellTheme || localStorage.dashboardTheme || localStorage.lofTheme || localStorage.theme || localStorage.obp_theme || 'light';
    applyTheme(savedTheme === 'dark' ? 'dark' : 'light');
    const style = document.createElement('style');
    style.textContent = `
      html.nb-skin{--nb-bg:#f5efe3;--nb-panel:#fffdf7;--nb-soft:#f1e8d8;--nb-text:#202019;--nb-muted:#6d6658;--nb-line:#e2d7c4;--nb-accent:#b96631;--nb-accent2:#287f72;--nb-ok:#16844d;--nb-warn:#b7791f;--nb-bad:#c43d32;--nb-shadow:0 22px 68px rgba(66,45,22,.13)}html.nb-skin.dark,html.nb-skin[data-theme="dark"]{--nb-bg:#101816;--nb-panel:#1b2621;--nb-soft:#24322b;--nb-text:#edf5ea;--nb-muted:#a9b6a5;--nb-line:#304038;--nb-accent:#f0a35c;--nb-accent2:#78c8b8;--nb-ok:#76d39a;--nb-warn:#f3c468;--nb-bad:#ff8278;--nb-shadow:0 24px 76px rgba(0,0,0,.36)}
      html.nb-skin body{color:var(--nb-text)!important;font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif!important;background:radial-gradient(960px 560px at -10% -12%,rgba(185,106,51,.24),transparent 58%),radial-gradient(760px 520px at 110% 0,rgba(40,127,115,.20),transparent 55%),var(--nb-bg)!important}html.nb-skin.dark body,html.nb-skin[data-theme="dark"] body{background:radial-gradient(960px 560px at -10% -12%,rgba(240,163,92,.16),transparent 58%),radial-gradient(760px 520px at 110% 0,rgba(120,200,184,.14),transparent 55%),var(--nb-bg)!important}
      html.nb-skin .panel,html.nb-skin .card,html.nb-skin .subcard,html.nb-skin .item,html.nb-skin .event,html.nb-skin .dialog,html.nb-skin .modal-card,html.nb-skin .modal-panel{background:var(--nb-panel)!important;border:1px solid var(--nb-line)!important;border-radius:24px!important;box-shadow:var(--nb-shadow)!important;color:var(--nb-text)!important}html.nb-skin .stat,html.nb-skin .briefBox,html.nb-skin .metric>div,html.nb-skin .metric,html.nb-skin .quick a{background:var(--nb-soft)!important;border-color:var(--nb-line)!important;color:var(--nb-text)!important;border-radius:18px!important}
      html.nb-skin .title,html.nb-skin h1{letter-spacing:-.04em}html.nb-skin .muted,html.nb-skin .k,html.nb-skin .sub,html.nb-skin .meta,html.nb-skin .mini,html.nb-skin .desc,html.nb-skin th{color:var(--nb-muted)!important}html.nb-skin a{color:var(--nb-accent2)}html.nb-skin button,html.nb-skin .btn,html.nb-skin a.btn,html.nb-skin .btnlink{border:1px solid var(--nb-line)!important;border-radius:999px!important;font-weight:950!important;box-shadow:none!important;transition:transform .14s ease,background .14s ease,color .14s ease}html.nb-skin button:hover,html.nb-skin .btn:hover,html.nb-skin a.btn:hover{transform:translateY(-1px)}html.nb-skin input,html.nb-skin textarea,html.nb-skin select,html.nb-skin .input,html.nb-skin .ctrl{background:var(--nb-soft)!important;color:var(--nb-text)!important;border:1px solid var(--nb-line)!important;border-radius:16px!important}html.nb-skin table{border-collapse:separate!important;border-spacing:0!important}html.nb-skin th,html.nb-skin td{border-bottom:1px solid var(--nb-line)!important}html.nb-skin pre,html.nb-skin code,.nb-skin .pre{background:var(--nb-soft)!important;color:var(--nb-text)!important;border-color:var(--nb-line)!important}html.nb-skin .ok,html.nb-skin .good{color:var(--nb-ok)!important}html.nb-skin .warn,html.nb-skin .warnText{color:var(--nb-warn)!important}html.nb-skin .bad,html.nb-skin .danger,html.nb-skin .err{color:var(--nb-bad)!important}
      #nb-sidecar-shell{position:fixed;right:14px;top:14px;z-index:2147483000;font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif;color:#17211c}
      .nb-shell-pill{display:flex;align-items:center;gap:8px;border:1px solid rgba(85,100,84,.28);border-radius:999px;background:rgba(255,253,246,.88);box-shadow:0 14px 38px rgba(23,33,28,.16);backdrop-filter:blur(16px);padding:7px 9px;max-width:min(92vw,720px)}
      .nb-shell-brand{border:0;background:#17211c;color:#fff;border-radius:999px;padding:7px 11px;font-weight:950;cursor:pointer;white-space:nowrap}.nb-shell-sub{font-size:12px;color:#60705f;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .nb-shell-menu{display:none;gap:6px;flex-wrap:wrap;align-items:center}.nb-shell-open .nb-shell-menu{display:flex}.nb-shell-link,.nb-shell-btn{border:1px solid rgba(85,100,84,.20);background:rgba(255,255,255,.62);color:#17211c;text-decoration:none;border-radius:999px;padding:7px 10px;font-size:12px;font-weight:900;cursor:pointer}.nb-shell-link:hover,.nb-shell-btn:hover{transform:translateY(-1px)}
      .nb-shell-current{background:#2f7f72;color:#fff;border-color:#2f7f72}.nb-shell-dot{width:8px;height:8px;border-radius:50%;background:#68d391;box-shadow:0 0 0 4px rgba(104,211,145,.16)}
      .dark #nb-sidecar-shell,[data-theme="dark"] #nb-sidecar-shell{color:#e8f4ed}.dark .nb-shell-pill,[data-theme="dark"] .nb-shell-pill{background:rgba(16,24,22,.88);border-color:rgba(148,163,184,.24);box-shadow:0 16px 44px rgba(0,0,0,.36)}.dark .nb-shell-brand,[data-theme="dark"] .nb-shell-brand{background:#e8f4ed;color:#101816}.dark .nb-shell-sub,[data-theme="dark"] .nb-shell-sub{color:#9fb4a7}.dark .nb-shell-link,.dark .nb-shell-btn,[data-theme="dark"] .nb-shell-link,[data-theme="dark"] .nb-shell-btn{background:rgba(31,41,37,.72);border-color:rgba(148,163,184,.20);color:#e8f4ed}.dark .nb-shell-current,[data-theme="dark"] .nb-shell-current{background:#f0a35c;color:#101816;border-color:#f0a35c}
      @media(max-width:760px){#nb-sidecar-shell{left:10px;right:10px;top:auto;bottom:12px}.nb-shell-pill{justify-content:space-between}.nb-shell-sub{display:none}.nb-shell-menu{position:absolute;left:0;right:0;bottom:52px;background:inherit;border:1px solid rgba(85,100,84,.22);border-radius:18px;padding:10px;box-shadow:inherit}.nb-shell-link,.nb-shell-btn{flex:1;text-align:center}}
    `;
    document.head.appendChild(style);
    const root = document.createElement('div');
    root.id = 'nb-sidecar-shell';
    root.innerHTML = `<div class="nb-shell-pill"><button class="nb-shell-brand" type="button">中枢</button><span class="nb-shell-dot"></span><span class="nb-shell-sub">${esc(label)}</span><div class="nb-shell-menu">${links.map(([name,href])=>{const base=href.replace(/\/$/,'');const active=href==='/'?location.pathname==='/' : location.pathname.startsWith(base);return `<a class="nb-shell-link ${active?'nb-shell-current':''}" href="${href}">${name}</a>`}).join('')}<button class="nb-shell-btn" type="button" data-theme>明暗</button></div></div>`;
    document.body.appendChild(root);
    root.querySelector('.nb-shell-brand').addEventListener('click', () => root.classList.toggle('nb-shell-open'));
    root.querySelector('[data-theme]').addEventListener('click', toggleTheme);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
})();
"####;
    (
        [(
            header::CONTENT_TYPE,
            "application/javascript; charset=utf-8",
        )],
        SHELL_JS,
    )
        .into_response()
}

pub(crate) async fn workbench_page() -> impl IntoResponse {
    Html(
        r####"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nanobot 内容工作台</title>
<style>
:root{--bg:#f5efe3;--panel:#fffdf7;--text:#202019;--muted:#6d6658;--line:#e2d7c4;--soft:#f1e8d8;--accent:#b96631;--accent2:#287f72;--ok:#16844d;--warn:#b7791f;--bad:#c43d32;--shadow:0 22px 68px rgba(66,45,22,.13)}[data-theme="dark"]{--bg:#101816;--panel:#1b2621;--text:#edf5ea;--muted:#a9b6a5;--line:#304038;--soft:#24322b;--accent:#f0a35c;--accent2:#78c8b8;--ok:#76d39a;--warn:#f3c468;--bad:#ff8278;--shadow:0 24px 76px rgba(0,0,0,.36)}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(960px 560px at -10% -12%,rgba(185,106,51,.24),transparent 58%),radial-gradient(760px 520px at 110% 0,rgba(40,127,115,.20),transparent 55%),var(--bg);color:var(--text);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif}.wrap{max-width:1280px;margin:0 auto;padding:28px 16px 48px}.hero{display:grid;grid-template-columns:1.35fr .65fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);padding:22px}.eyebrow{color:var(--accent2);font-size:12px;font-weight:950;letter-spacing:.18em}.title{font-family:Georgia,"Noto Serif SC",serif;font-size:48px;line-height:1.02;margin:8px 0 12px;letter-spacing:-.04em}.sub{color:var(--muted);line-height:1.75;margin:0}.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.btn{border:1px solid var(--line);background:var(--text);color:var(--bg);border-radius:999px;padding:10px 14px;font-weight:950;text-decoration:none;cursor:pointer}.btn.secondary{background:transparent;color:var(--text)}.btn.small{padding:7px 10px;font-size:12px}.search{display:flex;gap:8px;margin-top:16px}.input{flex:1;min-width:0;border:1px solid var(--line);border-radius:16px;padding:12px 14px;background:var(--soft);color:var(--text);font-weight:800}.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.stat{background:var(--soft);border:1px solid var(--line);border-radius:18px;padding:14px}.k{color:var(--muted);font-size:12px;font-weight:900}.v{font-size:30px;font-weight:950;letter-spacing:-.04em}.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:14px;margin-top:14px}.rail{display:grid;gap:10px;align-content:start}.filter{width:100%;border:1px solid var(--line);border-radius:18px;background:var(--panel);color:var(--text);padding:13px 14px;text-align:left;cursor:pointer;font-weight:950}.filter.active{background:var(--text);color:var(--bg)}.hint{color:var(--muted);font-size:13px;line-height:1.65}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}.item{background:rgba(255,255,255,.18);border:1px solid var(--line);border-radius:22px;padding:16px;display:flex;flex-direction:column;gap:10px;min-height:210px}.item.read{opacity:.62}.tag{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:12px;font-weight:900;color:var(--accent2);background:var(--soft)}.name{font-size:18px;font-weight:950;line-height:1.35}.name a{color:var(--text);text-decoration:none}.name a:hover{color:var(--accent2);text-decoration:underline}.meta{font-size:12px;color:var(--muted);line-height:1.55}.summary{line-height:1.7;color:var(--text);display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.summary.rich{display:block;overflow:visible}.takeaways{display:grid;gap:7px}.takeaway{border-left:3px solid var(--accent2);background:var(--soft);border-radius:12px;padding:8px 10px;line-height:1.55}.takeaway b{display:block;color:var(--accent2);font-size:12px;margin-bottom:2px}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:auto}.empty{padding:34px;text-align:center;color:var(--muted)}.good{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}@media(max-width:880px){.hero,.layout{grid-template-columns:1fr}.title{font-size:38px}.rail{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.wrap{padding:18px 10px 34px}.title{font-size:32px}.rail{grid-template-columns:1fr}.stats{grid-template-columns:1fr}.toolbar{display:grid}.btn{text-align:center}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <div class="panel">
      <div class="eyebrow">CONTENT WORKBENCH</div>
      <h1 class="title">内容工作台</h1>
      <p class="sub">把 RSS、知识收件箱和热点雷达放到一个阅读流里。先看摘要和来源，再决定打开原文、进入 Markdown 预览、标记已读或留到稍后。</p>
      <div class="toolbar"><a class="btn" href="/">回到驾驶舱</a><a class="btn secondary" href="/rss/">RSS 订阅</a><a class="btn secondary" href="/rss/cleaner">付费文章清洗器</a><a class="btn secondary" href="/inbox">知识收件箱</a><a class="btn secondary" href="/trends/">热点雷达</a><button class="btn secondary" onclick="loadAll(true)">刷新</button><button class="btn secondary" onclick="toggleTheme()">明暗</button></div>
      <div class="search"><input id="q" class="input" placeholder="搜索标题、摘要、来源..." oninput="render()"><button class="btn secondary" onclick="clearSearch()">清空</button></div>
    </div>
    <div class="panel"><div class="stats" id="stats"><div class="empty">加载中...</div></div><p class="hint" id="freshness">正在读取 sidecar 数据。</p></div>
  </section>
  <section class="layout">
    <aside class="rail" id="filters"></aside>
    <main class="panel"><div class="grid" id="items"><div class="empty">加载中...</div></div></main>
  </section>
</div>
<script src="/assets/nb-shell.js" data-prefix="/workbench" data-label="内容工作台" defer></script>
<script>
const root=document.documentElement;
function applyWorkbenchTheme(mode){const dark=mode==='dark';const value=dark?'dark':'light';root.setAttribute('data-theme',value);root.classList.toggle('dark',dark);if(document.body){document.body.setAttribute('data-theme',value);document.body.classList.toggle('dark',dark)}['dashboardTheme','sidecarShellTheme','lofTheme','theme'].forEach(k=>localStorage[k]=value)}
applyWorkbenchTheme((localStorage.sidecarShellTheme||localStorage.dashboardTheme)==='dark'?'dark':'light');
const state={rss:[],inbox:[],trends:[],sidecars:null,active:'all',marks:JSON.parse(localStorage.nbWorkbenchMarks||'{}')};
const filters=[['all','全部'],['rss','RSS 文章'],['inbox','知识收件箱'],['trend','热点雷达'],['saved','已收藏'],['unread','未读']];
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function toggleTheme(){const dark=root.getAttribute('data-theme')==='dark'||root.classList.contains('dark');applyWorkbenchTheme(dark?'light':'dark')}
function saveMarks(){localStorage.nbWorkbenchMarks=JSON.stringify(state.marks)}
async function getJson(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(url+' '+r.status);return r.json()}
function cleanMd(s){return String(s??'').replace(/\[([^\]]+)\]\(([^)]+)\)/g,'$1').replace(/[*_`#>]/g,'').replace(/^\s*[-*+]\s+/gm,'').replace(/\s+/g,' ').trim()}
function strip(s,n=220){const t=cleanMd(s);return t.length>n?t.slice(0,n)+'…':t}
function host(u){try{return new URL(u).host}catch{return ''}}
function time(s){if(!s)return '';try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s}}
function inboxSource(x){const h=host(x.final_url||x.url)||x.host||'';if(String(h).includes('mp.weixin.qq.com'))return '知识收件箱 · 微信文章';return '知识收件箱' + (h?' · '+h:'')}
function parseTakeaways(s){return String(s??'').split(/\n+/).map(line=>line.trim()).filter(Boolean).map(line=>{const m=line.match(/^[-*+]?\s*\*\*([^*：:]+)\*\*[：:]\s*(.+)$/);return m?{label:m[1].trim(),text:cleanMd(m[2])}:null}).filter(Boolean).slice(0,3)}
function summaryHtml(x){if(x.kind==='inbox'){const parts=parseTakeaways(x.summary);if(parts.length){return `<div class="takeaways">${parts.map(p=>`<div class="takeaway"><b>${esc(p.label)}</b><span>${esc(strip(p.text,150))}</span></div>`).join('')}</div>`}}return esc(strip(x.summary,260)||'暂无摘要，建议打开详情查看。')}
function markOf(id){return state.marks[id]||{}}
function toggleMark(id,key){const m=markOf(id);m[key]=!m[key];state.marks[id]=m;saveMarks();render()}
function markFromButton(btn,key){toggleMark(btn.dataset.id,key)}
function normalize(){
  const rss=(state.rss||[]).map(x=>({kind:'rss',id:'rss:'+x.id,title:x.title,summary:x.summary||x.content_markdown,source:x.subscription_name||'RSS',url:x.link,time:x.published_at||x.inserted_at,action:`/rss/`,raw:x}));
  const inbox=(state.inbox||[]).map(x=>({kind:'inbox',id:'inbox:'+(x.id||x.ref_id||x.title),title:x.title,summary:x.summary||x.extractive_summary||x.description||x.note,source:inboxSource(x),url:x.final_url||x.url,time:x.captured_at,action:'/inbox',raw:x}));
  const trends=(state.trends||[]).map((x,i)=>({kind:'trend',id:'trend:'+(x.url||x.title||i),title:x.title,summary:x.summary||x.desc||x.source_name,source:x.source_name||x.source_id||'Trend',url:x.url||x.mobile_url,time:x.updated_at||x.ts,action:'/trends/',raw:x}));
  return [...rss,...inbox,...trends].sort((a,b)=>Date.parse(b.time||0)-Date.parse(a.time||0));
}
function passFilter(x){const m=markOf(x.id);if(state.active==='saved')return !!m.saved;if(state.active==='unread')return !m.read;if(state.active!=='all'&&x.kind!==state.active)return false;const q=document.getElementById('q')?.value.trim().toLowerCase();if(!q)return true;return [x.title,x.summary,x.source,host(x.url)].join(' ').toLowerCase().includes(q)}
function renderFilters(){document.getElementById('filters').innerHTML=filters.map(([k,n])=>`<button class="filter ${state.active===k?'active':''}" onclick="state.active='${k}';render()">${esc(n)}<div class="hint">${filterNote(k)}</div></button>`).join('')+`<div class="panel" style="padding:14px"><div class="k">建议流程</div><p class="hint">先看“未读”，遇到长文进 RSS/Inbox 看 Markdown；热点只做线索，不直接打扰 QQ。</p></div>`}
function filterNote(k){const all=normalize();const c=k==='all'?all.length:k==='saved'?all.filter(x=>markOf(x.id).saved).length:k==='unread'?all.filter(x=>!markOf(x.id).read).length:all.filter(x=>x.kind===k).length;return c+' 条'}
function renderStats(){const side=state.sidecars?.summary||{};document.getElementById('stats').innerHTML=[['RSS',state.rss.length],['收件箱',state.inbox.length],['热点',state.trends.length],['服务',`${side.healthy??'-'}/${side.total??'-'}`]].map(([k,v])=>`<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('')}
function render(){renderStats();renderFilters();const items=normalize().filter(passFilter);document.getElementById('items').innerHTML=items.length?items.map(renderItem).join(''):'<div class="empty">这里暂时没有匹配内容。</div>'}
function renderItem(x){const m=markOf(x.id);const cls=m.read?'item read':'item';const kind={rss:'RSS',inbox:'收件箱',trend:'热点'}[x.kind]||x.kind;const rich=x.kind==='inbox'&&parseTakeaways(x.summary).length?' rich':'';return `<article class="${cls}"><div><span class="tag">${kind}</span></div><div class="name"><a href="${esc(x.url||x.action)}" target="_blank" rel="noopener">${esc(x.title||'(无标题)')}</a></div><div class="meta">${esc(x.source)} · ${esc(time(x.time))} · ${esc(host(x.url))}</div><div class="summary${rich}">${summaryHtml(x)}</div><div class="actions"><a class="btn small" href="${esc(x.url||x.action)}" target="_blank" rel="noopener">原文</a><a class="btn secondary small" href="${esc(x.action)}">详情</a><button class="btn secondary small" data-id="${esc(x.id)}" onclick="markFromButton(this,'read')">${m.read?'取消已读':'标记已读'}</button><button class="btn secondary small" data-id="${esc(x.id)}" onclick="markFromButton(this,'saved')">${m.saved?'取消收藏':'收藏'}</button></div></article>`}
function clearSearch(){document.getElementById('q').value='';render()}
async function loadAll(manual=false){const jobs=[['rss','/rss/api/entries?days=7&limit=40'],['inbox','/api/inbox'],['trends','/trends/api/trends/latest?limit=24'],['sidecars','/api/sidecars']];await Promise.all(jobs.map(async ([k,u])=>{try{const d=await getJson(u);state[k]=d.items||d.entries||d.data||d}catch(e){state[k]=[];console.warn(k,e)}}));document.getElementById('freshness').textContent=(manual?'已刷新 · ':'')+'更新时间：'+new Date().toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});render()}
loadAll();
</script>
</body>
</html>"####,
    )
}

pub(crate) async fn common_js() -> Response {
    const COMMON_JS: &str = r##"window.NB=window.NB||(()=>{const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));function fmtTime(s,f='-'){if(!s)return f;try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s||f}}function host(u,f='-'){try{return new URL(u).host}catch{return f}}function applyTheme(mode,key,also=[]){const dark=mode==='dark';const value=dark?'dark':'light';const root=document.documentElement;root.setAttribute('data-theme',value);root.classList.toggle('dark',dark);if(document.body){document.body.setAttribute('data-theme',value);document.body.classList.toggle('dark',dark)}[key,...also,'sidecarShellTheme','dashboardTheme'].filter(Boolean).forEach(k=>localStorage[k]=value)}function bindTheme(key,opt={}){const root=document.documentElement;const also=opt.also||[];const saved=localStorage.sidecarShellTheme||localStorage.dashboardTheme||localStorage[key]||also.map(k=>localStorage[k]).find(v=>v==='dark'||v==='light')||'light';applyTheme(saved==='dark'?'dark':'light',key,also);return function(){const dark=root.getAttribute('data-theme')==='dark'||root.classList.contains('dark');applyTheme(dark?'light':'dark',key,also)}}function stat(k,v,n=''){return `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="mini">${esc(n)}</div></div>`}function shortList(items,empty='-',cls='pill warn'){return (items||[]).length?(items||[]).map(v=>`<span class="${esc(cls)}">${esc(v)}</span>`).join(' '):`<span class="muted">${esc(empty)}</span>`}function fallbackCopy(text,done){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.left='-9999px';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();done&&done()}function copyText(text,btn){if(!text)return;const done=()=>{if(!btn)return;const old=btn.textContent;btn.textContent='已复制';setTimeout(()=>btn.textContent=old,1200)};if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(done).catch(()=>fallbackCopy(text,done));else fallbackCopy(text,done)}function copyFromButton(btn){return copyText(btn?.dataset?.copy||'',btn)}function cmdHtml(label,text){return `<div class="cmdtop"><span>${esc(label)}</span><button class="copybtn" data-copy="${esc(text||'')}" onclick="NB.copyFromButton(this)">复制</button></div><code>${esc(text||'-')}</code>`}function loadShell(){if(document.querySelector('script[src="/assets/nb-shell.js"]'))return;const sc=document.createElement('script');sc.src='/assets/nb-shell.js';sc.defer=true;sc.dataset.label=document.title||'Nanobot';document.head.appendChild(sc)}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',loadShell);else loadShell();return{esc,fmtTime,host,bindTheme,stat,shortList,copyText,copyFromButton,cmdHtml,fallbackCopy}})();"##;
    (
        [(
            header::CONTENT_TYPE,
            "application/javascript; charset=utf-8",
        )],
        COMMON_JS,
    )
        .into_response()
}

pub(crate) async fn sidecars_page() -> impl IntoResponse {
    Html(
        r##"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nanobot &#x80fd;&#x529b;&#x603b;&#x63a7;&#x53f0;</title>
<style>
:root{--bg:#eef3ea;--panel:#fffdf7;--text:#20231d;--muted:#68705f;--line:#d7decf;--ok:#18864b;--bad:#c13c2f;--warn:#b7791f;--accent:#2f6f88;--shadow:0 18px 45px rgba(35,48,32,.12)}
[data-theme="dark"]{--bg:#141a17;--panel:#202821;--text:#edf5ea;--muted:#a9b6a5;--line:#354035;--ok:#68d391;--bad:#fc8181;--warn:#f6c177;--accent:#7dd3fc;--shadow:0 18px 45px rgba(0,0,0,.28)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(900px 500px at 0 -10%,rgba(102,153,102,.28),transparent 55%),radial-gradient(720px 420px at 100% 0,rgba(47,111,136,.20),transparent 50%),var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft Yahei",sans-serif}.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 34px}.hero{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.title{margin:0;font-size:30px;letter-spacing:-.03em}.sub{margin:8px 0 0;color:var(--muted);line-height:1.6}.toolbar{display:flex;gap:10px;flex-wrap:wrap}button,a.btn{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:12px;padding:10px 13px;box-shadow:var(--shadow);text-decoration:none;font-weight:700;cursor:pointer}.copybtn{box-shadow:none;padding:6px 9px;border-radius:9px;font-size:12px}.cmdtop{display:flex;justify-content:space-between;align-items:center;gap:8px;color:var(--muted);font-size:13px}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}.stat{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:var(--shadow)}.stat b{display:block;font-size:28px}.sectionBlock{margin:20px 0 0}.sectionHead{display:flex;justify-content:space-between;gap:12px;align-items:flex-end;margin:0 0 10px;padding:10px 12px;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.16);cursor:pointer;list-style:none}.sectionHead::-webkit-details-marker{display:none}.sectionHead h2{margin:0;font-size:20px}.sectionHead p{margin:5px 0 0;color:var(--muted);line-height:1.55;font-size:13px}.foldTag{flex:none;border:1px solid var(--line);border-radius:999px;padding:6px 10px;color:var(--accent);font-size:12px;font-weight:900;background:rgba(255,255,255,.16)}.foldTag:before{content:"展开"}.sectionBlock[open] .foldTag:before{content:"收起"}.sectionBlock:not([open]) .sectionHead{margin-bottom:0}.abilityGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;margin-bottom:18px}.abilityCard{background:linear-gradient(180deg,rgba(255,255,255,.20),rgba(255,255,255,.06)),var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:var(--shadow);position:relative;overflow:hidden}.abilityCard:before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--accent)}.abilityCard.ok:before{background:var(--ok)}.abilityCard.bad:before{background:var(--bad)}.abilityTop{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:start}.abilityTop>div{min-width:0}.abilityCard .pill{max-width:120px;justify-content:center;overflow:hidden;text-overflow:ellipsis}.abilityCard .name{font-size:20px;line-height:1.2;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.abilityCard .desc{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin:8px 0 10px}.abilityMeta{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.abilityMeta span{border:1px solid var(--line);border-radius:999px;padding:4px 8px;color:var(--muted);font-size:12px;font-weight:800}.abilityTriggers{margin-top:8px}.abilityTriggers b{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}.abilityActions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.abilityActions a{color:var(--accent);font-weight:800;text-decoration:none}.cmdFold{margin-top:10px;border:1px solid var(--line);border-radius:12px;padding:8px 10px;background:rgba(90,100,80,.08)}.cmdFold summary{cursor:pointer;color:var(--accent);font-weight:800}.cmdFold[open]{background:rgba(90,100,80,.12)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:var(--shadow);position:relative;overflow:hidden}.card:before{content:"";position:absolute;inset:0 0 auto;height:4px;background:var(--accent)}.card.ok:before{background:var(--ok)}.card.bad:before{background:var(--bad)}.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.name{font-size:18px;font-weight:800}.desc{color:var(--muted);margin:7px 0 12px;line-height:1.55}.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:800;border:1px solid var(--line);white-space:nowrap}.pill.ok{color:var(--ok);background:rgba(24,134,75,.08);border-color:rgba(24,134,75,.3)}.pill.bad{color:var(--bad);background:rgba(193,60,47,.08);border-color:rgba(193,60,47,.3)}.pill.warn{color:var(--warn)}.meta{display:grid;grid-template-columns:90px 1fr;gap:6px 8px;color:var(--muted);font-size:13px}.meta b{color:var(--text);font-weight:700;overflow-wrap:anywhere}.cmd{margin-top:12px;display:grid;gap:7px}code{display:block;white-space:pre-wrap;overflow:auto;background:rgba(90,100,80,.12);border:1px solid var(--line);border-radius:10px;padding:8px;color:var(--text);user-select:text}.links{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.links a{color:var(--accent);font-weight:800;text-decoration:none}.links a:hover{text-decoration:underline}.foot{margin-top:16px;color:var(--muted);font-size:13px}.modal{position:fixed;inset:0;background:rgba(0,0,0,.42);display:none;align-items:center;justify-content:center;padding:18px;z-index:20}.modal.show{display:flex}.dialog{width:min(940px,100%);max-height:88vh;overflow:auto;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:22px;box-shadow:0 24px 80px rgba(0,0,0,.35)}.dialogHead{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:18px 18px 12px;border-bottom:1px solid var(--line)}.dialogTitle{margin:0;font-size:22px}.dialogBody{padding:16px 18px 18px}.miniTable{width:100%;border-collapse:collapse;min-width:760px}.miniTable th,.miniTable td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.miniTable th{color:var(--muted);font-size:12px}.pre{display:block;white-space:pre-wrap;overflow:auto;max-height:180px;background:rgba(90,100,80,.12);border:1px solid var(--line);border-radius:10px;padding:8px}.jobDetail{margin-top:8px;border:1px solid var(--line);border-radius:14px;padding:10px 12px;background:rgba(90,100,80,.08)}.jobDetail summary{cursor:pointer;color:var(--accent);font-weight:800}.jobDetail summary:hover{text-decoration:underline}.jobDetail[open]{background:rgba(90,100,80,.12)}.jobDetailBody{margin-top:10px}.miniTable td:nth-child(3){white-space:nowrap}.miniTable td:nth-child(5){white-space:nowrap}@media(max-width:720px){.hero{display:block}.toolbar{margin-top:12px}.stats,.abilityGrid,.portGrid{grid-template-columns:1fr}.abilityTop{grid-template-columns:1fr}.abilityCard .pill{justify-self:start;max-width:100%}.abilityCard .name{white-space:normal}.portHead{display:block}.portHead button{margin-top:10px}.title{font-size:25px}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <div>
      <h1 class="title">Nanobot &#x80fd;&#x529b;&#x603b;&#x63a7;&#x53f0;</h1>
      <p class="sub">&#x628a;&#x80fd;&#x529b;&#x3001;sidecar&#x3001;cron&#x3001;&#x811a;&#x672c;&#x5165;&#x53e3;&#x7edf;&#x4e00;&#x767b;&#x8bb0;&#x548c;&#x89c2;&#x6d4b;&#x3002;&#x9875;&#x9762;&#x53ea;&#x8bfb;&#xff0c;&#x4e0d;&#x65b0;&#x589e;&#x5e38;&#x9a7b;&#x8fdb;&#x7a0b;&#xff0c;&#x4f46;&#x8ba9; nanobot &#x771f;&#x6b63;&#x77e5;&#x9053;&#x81ea;&#x5df1;&#x4f1a;&#x4ec0;&#x4e48;&#x3001;&#x8c01;&#x5728;&#x652f;&#x6491;&#x3001;&#x600e;&#x4e48;&#x56de;&#x6d4b;&#x3002;</p>
    </div>
    <div class="toolbar">
      <button onclick="loadAll()">&#x5237;&#x65b0;&#x72b6;&#x6001;</button>
      <button onclick="toggleTheme()">&#x5207;&#x6362;&#x660e;&#x6697;</button>
      <a class="btn" href="/">&#x56de;&#x5230;&#x9a7e;&#x9a76;&#x8231;</a><a class="btn" href="/lof">LOF &#x770b;&#x677f;</a><a class="btn" href="/api/capabilities" target="_blank">能力 JSON</a><a class="btn" href="/api/sidecars" target="_blank">服务 JSON</a>
    </div>
  </section>
  <section class="stats" id="stats"></section>

  <details class="sectionBlock" open>
    <summary class="sectionHead"><div><h2>能力层：我能做什么</h2><p>这里只展示触发语、入口和运行形态；不再把日志、重启、端口这些服务细节重复摊开。</p></div><span class="foldTag" aria-hidden="true"></span></summary>
    <section class="abilityGrid" id="abilityGrid"></section>
  </details>
  <details class="sectionBlock" open>
    <summary class="sectionHead"><div><h2>支撑服务层：谁在跑</h2><p>这里负责健康状态、端口、日志、重启命令，以及每个服务支撑了哪些能力。</p></div><span class="foldTag" aria-hidden="true"></span></summary>
    <section class="grid" id="grid"></section>
  </details>
  <div class="foot" id="foot">&#x52a0;&#x8f7d;&#x4e2d;...</div>
</div>
<div class="modal" id="notifyModal" onclick="if(event.target.id==='notifyModal')closeNotifyModal()"><div class="dialog"><div class="dialogHead"><div><h2 class="dialogTitle">Notify &#x4efb;&#x52a1;&#x8be6;&#x60c5;</h2><div class="muted" id="notifySub">Loading...</div></div><button onclick="closeNotifyModal()">&#x5173;&#x95ed;</button></div><div class="dialogBody" id="notifyBody"></div></div></div>
<script src="/assets/nb-common.js"></script>
<script>
window.toggleTheme=NB.bindTheme('sidecarTheme');
const esc=NB.esc, cmdHtml=NB.cmdHtml, shortList=NB.shortList;
function pill(ok,text){return `<span class="pill ${ok?'ok':'bad'}">${ok?'\u6b63\u5e38':'\u5f02\u5e38'} \u00b7 ${esc(text||'-')}</span>`}
function accessText(x){
  if(x.homepage_url){try{const u=new URL(x.homepage_url, window.location.origin);return u.origin+u.pathname;}catch(e){return x.homepage_url}}
  return '\u65e0\u516c\u7f51\u5165\u53e3';
}
function listenText(x){
  if(x.port==null)return '-';
  return (x.public?'0.0.0.0':'127.0.0.1')+':'+x.port;
}
function exposureText(x){
  if(x.public)return '\u76f4\u63a5\u516c\u7f51';
  if(x.homepage_url)return '\u7ecf 8093 \u4ee3\u7406';
  return '\u4ec5\u5185\u90e8';
}
function kindText(x){const m={sidecar:'\u5e38\u9a7b sidecar',skill:'Nanobot skill',script:'\u6309\u9700\u811a\u672c',cron:'\u5b9a\u65f6\u4efb\u52a1',gateway:'\u7f51\u5173\u80fd\u529b',mcp:'MCP \u98ce\u683c\u5de5\u5177'};return m[x]||x||'-'}
function healthPill(x){return '<span title="'+esc(x.health_status||'-')+'" class="pill '+(x.ok?'ok':'bad')+'">'+(x.ok?'\u53ef\u7528':'\u5f02\u5e38')+'</span>'}
function commandCards(commands){return (commands||[]).map(c=>cmdHtml(c.label||'\u547d\u4ee4',c.command||'')).join('')}
function supportText(x){return x.service_id?('支撑：'+x.service_id):'按需 / 无常驻服务'}
function renderCapabilities(c){
  const items=c.items||[];
  document.getElementById('abilityGrid').innerHTML=items.map(x=>{
    const detail=[];
    if((x.commands||[]).length) detail.push(commandCards(x.commands));
    if((x.data_paths||[]).length) detail.push(cmdHtml('数据路径',(x.data_paths||[]).join('\n')));
    if(x.notes) detail.push('<div class="desc">'+esc(x.notes)+'</div>');
    const detailHtml=detail.length?'<details class="cmdFold"><summary>命令 / 数据 / 备注</summary><div class="cmd">'+detail.join('')+'</div></details>':'';
    const tools=(x.mcp_tools||[]).length?'<div class="abilityTriggers"><b>MCP / 工具</b>'+shortList(x.mcp_tools,'未暴露')+'</div>':'';
    return '<article class="abilityCard '+(x.ok?'ok':'bad')+'">'
      +'<div class="abilityTop"><div><div class="name">'+esc(x.name)+'</div><div class="desc">'+esc(x.description)+'</div></div>'+healthPill(x)+'</div>'
      +'<div class="abilityMeta"><span>'+esc(x.category||'-')+'</span><span>'+esc(kindText(x.kind))+'</span><span>'+esc(supportText(x))+'</span></div>'
      +'<div class="abilityTriggers"><b>触发语</b>'+shortList(x.trigger_phrases,'未登记')+'</div>'
      +tools
      +'<div class="abilityActions">'+(x.entry_url?'<a href="'+esc(x.entry_url)+'" target="_blank" rel="noopener">打开入口</a>':'')+'</div>'
      +detailHtml
    +'</article>';
  }).join('') || '<article class="abilityCard bad"><div class="name">没有登记能力</div><div class="desc">请检查 /root/.nanobot/capabilities.json。</div></article>';
}
function render(d,c={summary:{}}){
  const s=d.summary||{total:0,healthy:0,unhealthy:0};
  const cs=c.summary||{total:0,enabled:0,healthy:0,degraded:0};
  const caps=c.items||[];
  const supported={};
  caps.forEach(cap=>{if(cap.service_id){(supported[cap.service_id]||(supported[cap.service_id]=[])).push(cap.name)}});
  document.getElementById('stats').innerHTML='<div class="stat"><span>能力总数</span><b>'+cs.total+'</b></div><div class="stat"><span>启用能力</span><b style="color:var(--accent)">'+cs.enabled+'</b></div><div class="stat"><span>能力可用</span><b style="color:var(--ok)">'+cs.healthy+'</b></div><div class="stat"><span>服务总数</span><b>'+s.total+'</b></div><div class="stat"><span>服务正常</span><b style="color:var(--ok)">'+s.healthy+'</b></div><div class="stat"><span>服务异常</span><b style="color:var(--bad)">'+s.unhealthy+'</b></div>';
  renderCapabilities(c);
  document.getElementById('grid').innerHTML=(d.items||[]).map(x=>{
    const supportNames=supported[x.id]||[];
    const actionLinks=(x.homepage_url?'<a href="'+esc(x.homepage_url)+'" target="_blank" rel="noopener">打开页面</a>':'')+(x.id==='notify'?'<a href="#" onclick="openNotifyJobs();return false;">查看任务详情</a>':'');
    const ops='<details class="cmdFold"><summary>日志 / 重启命令</summary><div class="cmd">'+cmdHtml('查看日志',x.logs_command)+cmdHtml('重启服务',x.restart_command)+'</div></details>';
    return '<article class="card '+(x.ok?'ok':'bad')+'">'
      +'<div class="row"><div><div class="name">'+esc(x.name)+'</div><div class="desc">'+esc(x.description)+'</div></div>'+pill(x.ok,x.check_status)+'</div>'
      +'<div class="meta">'
        +'<span>服务 ID</span><b>'+esc(x.id)+'</b>'
        +'<span>支撑能力</span><b>'+shortList(supportNames,'未绑定能力')+'</b>'
        +'<span>访问入口</span><b>'+esc(accessText(x))+'</b>'
        +'<span>服务监听</span><b>'+esc(listenText(x))+'</b>'
        +'<span>暴露方式</span><b>'+esc(exposureText(x))+'</b>'
        +'<span>系统服务</span><b>'+esc(x.unit_status || (x.unit ? '未知' : '未托管'))+'</b>'
        +'<span>延迟</span><b>'+(x.latency_ms==null?'-':x.latency_ms+' ms')+'</b>'
        +'<span>启动</span><b>'+esc(x.active_since||'-')+'</b>'
        +'<span>错误</span><b>'+esc(x.error||'-')+'</b>'
      +'</div>'
      +((x.recent_errors||[]).length?'<div class="cmd">'+cmdHtml('最近告警 / 错误',(x.recent_errors||[]).join('\n'))+'</div>':'')
      +(actionLinks?'<div class="links">'+actionLinks+'</div>':'')
      +ops
    +'</article>';
  }).join('');
  document.getElementById('foot').textContent='最后刷新：'+(d.now || c.now || '-')+'。上方是能力层，下方是支撑服务层；JSON 入口已收口到顶部，页面只读，不会在网页上执行重启。';
}
async function loadAll(){try{const [sr,cr]=await Promise.all([fetch('/api/sidecars',{cache:'no-store'}),fetch('/api/capabilities',{cache:'no-store'})]);render(await sr.json(),await cr.json())}catch(e){document.getElementById('foot').textContent='\u52a0\u8f7d\u5931\u8d25\uff1a'+e.message}}
function notifyStatusPill(st){const s=st||'-';const cls=s==='sent'?'ok':(s==='error'?'bad':(s==='running'?'warn':''));return `<span class="pill ${cls}">${esc(s)}</span>`}
async function openNotifyJobs(){const modal=document.getElementById('notifyModal');modal.classList.add('show');document.getElementById('notifySub').textContent='\u52a0\u8f7d\u4e2d...';document.getElementById('notifyBody').innerHTML='';try{const r=await fetch('/api/notify-jobs',{cache:'no-store'});const d=await r.json();renderNotifyJobs(d)}catch(e){document.getElementById('notifySub').textContent='\u52a0\u8f7d\u5931\u8d25\uff1a'+e.message}}
function closeNotifyModal(){document.getElementById('notifyModal').classList.remove('show')}
function renderNotifyJobs(d){
  const jobs=d.job_details||[];
  document.getElementById('notifySub').textContent=`${d.now||'-'} \u00b7 ${jobs.length} \u4e2a\u4efb\u52a1 \u00b7 ${d.target_set?'QQ \u76ee\u6807\u5df2\u914d\u7f6e':'QQ \u76ee\u6807\u672a\u914d\u7f6e'}`;
  document.getElementById('notifyBody').innerHTML=`<div style="overflow:auto"><table class="miniTable"><thead><tr><th>\u4efb\u52a1</th><th>\u89c4\u5219</th><th>\u4e0b\u6b21\u8fd0\u884c</th><th>\u72b6\u6001</th><th>\u6700\u8fd1\u5b8c\u6210</th><th>\u8be6\u60c5</th></tr></thead><tbody>${jobs.map(j=>`<tr><td><b>${esc(j.name)}</b><br><span class="muted">${esc(j.id)}</span></td><td><code>${esc(j.schedule)}</code><br><span class="muted">${esc(j.schedule_note)}</span></td><td>${esc((j.next_runs||[])[0]||'-')}</td><td>${j.enabled?'<span class="pill ok">\u542f\u7528</span>':'<span class="pill">\u6682\u505c</span>'}<br>${notifyStatusPill(j.status?.last_status)}</td><td>${esc(j.status?.last_finished_at||'-')}</td><td><details class="jobDetail"><summary>\u5c55\u5f00</summary><div class="jobDetailBody"><b>\u672a\u6765\u89e6\u53d1</b><br>${(j.next_runs||[]).map(x=>`<span class="pill warn">${esc(x)}</span>`).join(' ')||'<span class="muted">-</span>'}<br><br><b>\u5b9e\u9645\u547d\u4ee4</b><button class="copybtn" style="margin-left:8px" data-copy="${esc(j.command||'')}" onclick="NB.copyFromButton(this)">\u590d\u5236</button><div class="pre">${esc(j.command||'-')}</div>${j.status?.last_error?`<br><b>\u6700\u8fd1\u9519\u8bef</b><div class="pre">${esc(j.status.last_error)}</div>`:''}${j.status?.last_stdout_preview?`<br><b>\u6700\u8fd1\u8f93\u51fa\u6458\u8981</b><div class="pre">${esc(j.status.last_stdout_preview)}</div>`:''}</div></details></td></tr>`).join('')}</tbody></table></div>`
}
loadAll();setInterval(loadAll,15000);
</script>
</body>
</html>"##,
    )
}

pub(crate) async fn index() -> Html<String> {
    Html(
        r#"<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>LOF Sidecar · Rust</title>
  <style>
    :root{--bg:#f4f7fb;--panel:#ffffff;--fg:#0d1b2a;--muted:#4f5d75;--accent:#0ea5e9;--ok:#16a34a;--err:#dc2626;--warn:#d97706;}
    .dark,[data-theme="dark"]{--bg:#0b1220;--panel:#111b2e;--fg:#e5eefc;--muted:#a2b1cc;--accent:#38bdf8;--ok:#22c55e;--err:#f87171;--warn:#f59e0b;}
    body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,PingFang SC,Microsoft YaHei,sans-serif;background:linear-gradient(135deg,var(--bg),#d9e4f5 140%);color:var(--fg)}
    .dark body,[data-theme="dark"] body{background:linear-gradient(135deg,var(--bg),#1a2945 140%)}
    .wrap{max-width:980px;margin:28px auto;padding:0 16px}
    .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
    .card{background:var(--panel);border-radius:16px;padding:18px;box-shadow:0 10px 28px rgba(2,8,23,.12);margin-bottom:14px}
    button,.btnlink{border:none;border-radius:10px;padding:10px 14px;cursor:pointer;color:#fff;background:var(--accent);font-weight:700;text-decoration:none;display:inline-block}
    .btn2{background:#334155}
    .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
    .k{font-size:12px;color:var(--muted)} .v{font-size:18px;font-weight:700}
    .ok{color:var(--ok)} .err{color:var(--err)} .warn{color:var(--warn)}
    pre{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#e2e8f0;padding:14px;border-radius:12px;max-height:420px;overflow:auto}
    .dark pre,[data-theme="dark"] pre{background:#020617}
    .toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .ctrl{border:1px solid #cbd5e1;border-radius:10px;padding:9px 12px;min-width:220px;background:#fff;color:#0d1b2a}
    .dark .ctrl,[data-theme="dark"] .ctrl{background:#0f172a;color:#e2e8f0;border-color:#334155}
    .statusline{font-size:12px;color:var(--muted)}
    .autoctl{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:12px;user-select:none}
    .autoctl input{width:16px;height:16px;accent-color:var(--accent)}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th,td{padding:8px 6px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:middle}
    .dark th,.dark td,[data-theme="dark"] th,[data-theme="dark"] td{border-bottom-color:#1e293b}
    tbody tr{transition:background-color .12s ease}
    tbody tr:hover{background:rgba(14,165,233,.08)}
    .dark tbody tr:hover,[data-theme="dark"] tbody tr:hover{background:rgba(56,189,248,.14)}
    th{font-size:12px;color:var(--muted)}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
    th.sortable{cursor:pointer;user-select:none}
    th.sortable:hover{color:var(--fg)}
    .histv{display:inline-block;min-width:44px;text-align:right;padding:1px 4px;border-radius:6px;margin-right:2px}
    a.flink{color:var(--accent);text-decoration:none;font-weight:600}
    a.flink:hover{text-decoration:underline}
    .tinybtn{margin-left:6px;border:none;background:#334155;color:#fff;border-radius:8px;padding:2px 7px;font-size:11px;cursor:pointer}
    .tinybtn:hover{opacity:.9}
    .modal{position:fixed;inset:0;background:rgba(2,8,23,.55);display:none;align-items:center;justify-content:center;z-index:30}
    .modal-card{width:min(860px,94vw);max-height:85vh;overflow:auto;background:var(--panel);color:var(--fg);border-radius:14px;padding:14px;box-shadow:0 16px 40px rgba(2,8,23,.35)}
    .modal-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
    .histgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:10px 0}
    .chip{border-radius:8px;padding:7px 9px;background:rgba(148,163,184,.12)}
    .hist-list{display:flex;flex-wrap:wrap;gap:6px}
    @media (max-width:760px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hide-m{display:none}}
  </style>
</head>
<body>
  <script src="/assets/nb-shell.js" data-prefix="/lof" data-label="LOF 雷达" defer></script>
<div class="wrap">
  <div class="top">
    <h2>LOF Sidecar · Rust</h2>
    <div>
      <a class="btnlink btn2" href="/sidecars">Sidecar &#x603b;&#x63a7;&#x53f0;</a>
      <button class="btn2" onclick="toggleTheme()">切换明暗</button>
      <button onclick="runNow()">立即运行(收盘)</button>
    </div>
  </div>

  <div class="card">
    <div class="grid">
      <div><div class="k">总运行</div><div id="total" class="v">-</div></div>
      <div><div class="k">成功</div><div id="succ" class="v ok">-</div></div>
      <div><div class="k">超时</div><div id="tout" class="v warn">-</div></div>
      <div><div class="k">失败</div><div id="err" class="v err">-</div></div>
    </div>
  </div>

  <div class="card">
    <div class="k">最后一次运行</div>
    <div id="meta" class="v">加载中...</div>
  </div>

  <div class="card">
    <div class="k">最新报告</div>
    <pre id="report">加载中...</pre>
  </div>

  <div class="card">
    <div class="toolbar">
      <div class="k">精简看板（关键字段）</div>
      <input id="kw" class="ctrl" placeholder="筛选代码/名称，如 513100 或 纳指" oninput="renderBoard()"/>
      <button id="boardRefreshBtn" class="btn2" onclick="manualBoardRefresh(event)">手动刷新</button>
      <label class="autoctl" title="只在本页面打开时轮询看板接口，不触发行情抓取">
        <input id="boardAutoRefresh" type="checkbox" onchange="toggleBoardAutoRefresh(this.checked)">
        自动刷新
      </label>
      <span id="boardRefreshHint" class="statusline">未开启，勾选后每 30 秒刷新一次</span>
    </div>
    <div style="overflow:auto;margin-top:10px;">
      <table>
        <thead>
          <tr>
            <th class="sortable" data-key="code" data-type="str" onclick="onSort(this)">代码</th>
            <th class="sortable" data-key="name" data-type="str" onclick="onSort(this)">名称</th>
            <th class="sortable" data-key="rt_nav" data-type="num" onclick="onSort(this)">实时估值</th>
            <th class="sortable" data-key="rt_premium_pct" data-type="num" onclick="onSort(this)">实时溢价%</th>
            <th class="sortable" data-key="latest_nav" data-type="num" onclick="onSort(this)">最新估值</th>
            <th class="sortable" data-key="latest_premium_pct" data-type="num" onclick="onSort(this)">最新溢价%</th>
            <th class="sortable" data-key="price" data-type="num" onclick="onSort(this)">现价</th>
            <th class="sortable" data-key="change_pct" data-type="num" onclick="onSort(this)">涨跌%</th>
            <th class="sortable" data-key="amount_wan" data-type="num" onclick="onSort(this)">成交额(万元)</th>
            <th class="sortable" data-key="limit_text" data-type="str" onclick="onSort(this)">限额</th>
            <th class="sortable" data-key="hist_recent" data-type="num" onclick="onSort(this)">历史溢价</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>
</div>

<div id="histModal" class="modal" onclick="if(event.target===this)closeHist()">
  <div class="modal-card">
    <div class="modal-top">
      <div id="histTitle" class="v" style="font-size:20px;">历史溢价详情</div>
      <button class="btn2" onclick="closeHist()">关闭</button>
    </div>
    <div class="toolbar">
      <div class="k">统计窗口</div>
      <select id="histWin" class="ctrl" onchange="renderHistModal()">
        <option value="7">近7天</option>
        <option value="14">近14天</option>
        <option value="30">近30天</option>
      </select>
    </div>
    <div id="histStats" class="histgrid"></div>
    <div class="k" style="margin:8px 0 4px;">明细（从近到远）</div>
    <div id="histSeries" class="hist-list"></div>
  </div>
</div>
<script>
const root=document.documentElement;
function applyLofTheme(mode){
  const dark=mode==='dark';
  const value=dark?'dark':'light';
  root.setAttribute('data-theme',value);
  root.classList.toggle('dark',dark);
  if(document.body){document.body.setAttribute('data-theme',value);document.body.classList.toggle('dark',dark)}
  ['lofTheme','theme','sidecarShellTheme','dashboardTheme'].forEach(k=>localStorage[k]=value);
}
applyLofTheme((localStorage.sidecarShellTheme||localStorage.dashboardTheme||localStorage.lofTheme||localStorage.theme)==='dark'?'dark':'light');
let latestBoard=null;
let sortState={key:'rt_premium_pct',dir:'desc',type:'num'};
let histRow=null;
const BOARD_AUTO_REFRESH_MS=30000;
let boardAutoRefreshTimer=null;
let boardRefreshBusy=false;
function toggleTheme(){const dark=root.getAttribute('data-theme')==='dark'||root.classList.contains('dark');applyLofTheme(dark?'light':'dark')}
function fmt(s){try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s||'-'}}
function esc(s){return String(s??'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]))}
function histClass(v){
  if(v>=5) return 'warn';
  if(v>=0) return 'ok';
  return 'err';
}
function historyVals(points, days){
  const arr=(points||[]).slice(-days).reverse();
  return arr.map(p=>Number(p.premium_pct||0));
}
function historyHtml(points, days){
  const vals=historyVals(points,days);
  if(vals.length===0) return '-';
  return vals.map(v=>`<span class="histv ${histClass(v)}">${v.toFixed(2)}%</span>`).join('');
}
function valueForSort(r, key, days){
  if(key==='hist_recent'){
    const vals=historyVals(r.history,days);
    return vals.length?vals[0]:null;
  }
  return r?.[key];
}
function cmp(a,b,type){
  if(type==='num'){
    const av=(a==null||a==='')?-Infinity:Number(a);
    const bv=(b==null||b==='')?-Infinity:Number(b);
    return av===bv?0:(av>bv?1:-1);
  }
  const as=String(a??'');
  const bs=String(b??'');
  return as.localeCompare(bs,'zh-CN');
}
function onSort(th){
  const key=th.dataset.key, type=th.dataset.type||'str';
  if(sortState.key===key){ sortState.dir = (sortState.dir==='asc'?'desc':'asc'); }
  else{ sortState={key,dir:(type==='num'?'desc':'asc'),type}; }
  renderBoard();
}
function refreshSortHeader(){
  document.querySelectorAll('th.sortable').forEach(th=>{
    const key=th.dataset.key;
    const label=th.textContent.replace(/[↑↓]$/,'');
    th.textContent = key===sortState.key ? `${label}${sortState.dir==='asc'?'↑':'↓'}` : label;
  });
}
function openHist(code){
  if(!latestBoard||!latestBoard.rows) return;
  histRow=(latestBoard.rows||[]).find(x=>String(x.code||'')===String(code||'')) || null;
  if(!histRow) return;
  document.getElementById('histTitle').textContent=`${histRow.code} ${histRow.name} 历史溢价详情`;
  document.getElementById('histModal').style.display='flex';
  renderHistModal();
}
function closeHist(){
  document.getElementById('histModal').style.display='none';
}
function setBoardRefreshHint(text){
  const el=document.getElementById('boardRefreshHint');
  if(el) el.textContent=text;
}
function boardRefreshTime(){
  return new Date().toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});
}
async function safeRefreshBoard(){
  if(boardRefreshBusy) return false;
  boardRefreshBusy=true;
  try{
    await refresh();
    return true;
  }catch(e){
    setBoardRefreshHint(`刷新失败：${e.message||e}`);
    throw e;
  }finally{
    boardRefreshBusy=false;
  }
}
async function manualBoardRefresh(ev){
  const btn=ev?.currentTarget||document.getElementById('boardRefreshBtn');
  const bak=btn?.textContent;
  if(btn){btn.disabled=true;btn.textContent='刷新中...'}
  try{
    const done=await safeRefreshBoard();
    if(done) setBoardRefreshHint(`已手动刷新：${boardRefreshTime()}`);
  }finally{
    if(btn){btn.disabled=false;btn.textContent=bak}
  }
}
function stopBoardAutoRefresh(){
  if(boardAutoRefreshTimer){clearInterval(boardAutoRefreshTimer);boardAutoRefreshTimer=null;}
}
function startBoardAutoRefresh(){
  stopBoardAutoRefresh();
  boardAutoRefreshTimer=setInterval(async()=>{
    const done=await safeRefreshBoard().catch(()=>false);
    if(done) setBoardRefreshHint(`自动刷新中：每 30 秒，上次 ${boardRefreshTime()}`);
  },BOARD_AUTO_REFRESH_MS);
  setBoardRefreshHint('自动刷新中：每 30 秒，只刷新页面看板');
}
function toggleBoardAutoRefresh(enabled){
  localStorage.lofBoardAutoRefresh=enabled?'1':'0';
  if(enabled) startBoardAutoRefresh();
  else{stopBoardAutoRefresh();setBoardRefreshHint('未开启，勾选后每 30 秒刷新一次');}
}
function initBoardAutoRefresh(){
  const box=document.getElementById('boardAutoRefresh');
  const enabled=localStorage.lofBoardAutoRefresh==='1';
  if(box) box.checked=enabled;
  if(enabled) startBoardAutoRefresh();
}
function renderHistModal(){
  const stat=document.getElementById('histStats');
  const series=document.getElementById('histSeries');
  if(!histRow){ stat.innerHTML=''; series.innerHTML=''; return; }
  const win=Number(document.getElementById('histWin')?.value||7);
  const pts=(histRow.history||[]).slice(-win);
  if(!pts.length){
    stat.innerHTML='<div class="k">暂无历史数据</div>';
    series.innerHTML='-';
    return;
  }
  const vals=pts.map(p=>Number(p.premium_pct||0));
  const latest=vals[vals.length-1];
  const avg=vals.reduce((a,b)=>a+b,0)/vals.length;
  const min=Math.min(...vals), max=Math.max(...vals);
  const highDays=vals.filter(v=>v>=5).length;
  stat.innerHTML=`
    <div class="chip"><div class="k">最新</div><div class="${histClass(latest)}"><b>${latest.toFixed(2)}%</b></div></div>
    <div class="chip"><div class="k">均值</div><div><b>${avg.toFixed(2)}%</b></div></div>
    <div class="chip"><div class="k">区间</div><div><b>${min.toFixed(2)}% ~ ${max.toFixed(2)}%</b></div></div>
    <div class="chip"><div class="k">>=5% 天数</div><div><b>${highDays}/${vals.length}</b></div></div>
  `;
  series.innerHTML=pts.slice().reverse().map(p=>{
    const v=Number(p.premium_pct||0);
    return `<span class="histv ${histClass(v)}">${esc(p.date)} ${v.toFixed(2)}%</span>`;
  }).join('');
}
function renderBoard(){
  const tbody=document.getElementById('rows');
  if(!latestBoard||!latestBoard.rows){tbody.innerHTML='<tr><td colspan="11">暂无看板数据，请先点一次“立即运行”。</td></tr>';return}
  const kw=(document.getElementById('kw').value||'').trim().toLowerCase();
  const days=3;
  let rows=(latestBoard.rows||[]).filter(r=>!kw || (r.code||'').toLowerCase().includes(kw) || (r.name||'').toLowerCase().includes(kw));
  rows=[...rows].sort((a,b)=>{
    const av=valueForSort(a,sortState.key,days), bv=valueForSort(b,sortState.key,days);
    const base=cmp(av,bv,sortState.type);
    return sortState.dir==='asc'?base:-base;
  });
  refreshSortHeader();
  tbody.innerHTML=rows.slice(0,80).map(r=>{
    const rp=(r.rt_premium_pct==null)?'-':Number(r.rt_premium_pct).toFixed(2);
    const lp=(r.latest_premium_pct==null)?'-':Number(r.latest_premium_pct).toFixed(2);
    const pCls=(r.rt_premium_pct??-999)>=5?'warn':((r.rt_premium_pct??-999)>=0?'ok':'');
    const ch=(r.change_pct==null)?'-':Number(r.change_pct).toFixed(2);
    const chCls=(r.change_pct??0)>0?'ok':((r.change_pct??0)<0?'err':'');
    const hist=historyHtml(r.history, days);
    const tip=(r.history||[]).slice(-days).reverse().map(x=>`${x.date}:${Number(x.premium_pct).toFixed(2)}%`).join('\\n');
    const fundUrl=`https://fund.eastmoney.com/${encodeURIComponent(String(r.code||''))}.html`;
    return `<tr>
      <td class="mono"><a class="flink" href="${fundUrl}" target="_blank" rel="noopener noreferrer">${esc(r.code)}</a></td>
      <td><a class="flink" href="${fundUrl}" target="_blank" rel="noopener noreferrer">${esc(r.name)}</a></td>
      <td>${r.rt_nav==null?'-':Number(r.rt_nav).toFixed(4)}</td>
      <td class="${pCls}">${rp}</td>
      <td>${r.latest_nav==null?'-':Number(r.latest_nav).toFixed(4)}</td>
      <td>${lp}</td>
      <td>${r.price==null?'-':Number(r.price).toFixed(3)}</td>
      <td class="${chCls}">${ch}</td>
      <td>${r.amount_wan==null?'-':Number(r.amount_wan).toFixed(0)}</td>
      <td>${esc(r.limit_text||'-')}</td>
      <td title="${esc(tip)}">${hist}<button class="tinybtn" onclick="openHist('${String(r.code||'')}')">详情</button></td>
    </tr>`;
  }).join('');
}
async function refresh(){
  const r=await fetch('/api/status',{cache:'no-store'}); const d=await r.json();
  document.getElementById('total').textContent=d.stats?.total_runs ?? 0;
  document.getElementById('succ').textContent=d.stats?.success_runs ?? 0;
  document.getElementById('tout').textContent=d.stats?.timeout_runs ?? 0;
  document.getElementById('err').textContent=d.stats?.error_runs ?? 0;
  const lr=d.last_run;
  if(!lr){document.getElementById('meta').textContent='暂无';document.getElementById('report').textContent='暂无';return}
  document.getElementById('meta').innerHTML=`状态: <b>${lr.status}</b> ｜ 标签: ${lr.tag} ｜ 时长: ${lr.duration_ms}ms ｜ 完成: ${fmt(lr.finished_at)} ｜ 看板更新: ${fmt(d.last_board?.updated_at)}`;
  document.getElementById('report').textContent = lr.report || (lr.error || '空输出');
  latestBoard=d.last_board;
  renderBoard();
}
async function runNow(){
  const btn=event.target; btn.disabled=true; const bak=btn.textContent; btn.textContent='运行中...';
  try{
    await fetch('/api/run',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tag:'收盘'})});
    await safeRefreshBoard();
    setBoardRefreshHint(`已运行并刷新：${boardRefreshTime()}`);
  }finally{btn.disabled=false; btn.textContent=bak}
}
safeRefreshBoard().catch(()=>{});
initBoardAutoRefresh();
</script>
</body></html>"#
            .to_string(),
    )
}

pub(crate) async fn personal_ops_page() -> Html<String> {
    Html(
        r####"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nanobot 个人中枢</title>
<style>
:root{--bg:#f5efe3;--panel:#fffdf7;--soft:#f1e8d8;--text:#202019;--muted:#6d6658;--line:#e2d7c4;--accent:#b96631;--accent2:#287f72;--ok:#16844d;--warn:#b7791f;--bad:#c43d32;--shadow:0 22px 68px rgba(66,45,22,.13)}[data-theme="dark"]{--bg:#101816;--panel:#1b2621;--soft:#24322b;--text:#edf5ea;--muted:#a9b6a5;--line:#304038;--accent:#f0a35c;--accent2:#78c8b8;--ok:#76d39a;--warn:#f3c468;--bad:#ff8278;--shadow:0 24px 76px rgba(0,0,0,.36)}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(900px 520px at -10% -10%,rgba(185,106,51,.22),transparent 58%),radial-gradient(720px 500px at 110% 0,rgba(40,127,115,.18),transparent 55%),var(--bg);color:var(--text);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif}.wrap{max-width:1280px;margin:0 auto;padding:28px 16px 44px}.hero{display:grid;grid-template-columns:1.35fr .65fr;gap:14px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);padding:22px}.eyebrow{font-size:12px;font-weight:950;letter-spacing:.18em;color:var(--accent2)}h1{font-family:Georgia,"Noto Serif SC",serif;font-size:48px;line-height:1.02;margin:8px 0 10px;letter-spacing:-.04em}.sub{color:var(--muted);line-height:1.75;margin:0}.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.btn,button{border:1px solid var(--line);background:var(--text);color:var(--bg);border-radius:999px;padding:10px 14px;font-weight:950;text-decoration:none;cursor:pointer}.btn.secondary,button.secondary{background:transparent;color:var(--text)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-top:14px}.card{grid-column:span 4;background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:16px;box-shadow:var(--shadow)}.card.wide{grid-column:span 8}.card.full{grid-column:1/-1}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.stat{background:var(--soft);border:1px solid var(--line);border-radius:18px;padding:13px}.k{font-size:12px;color:var(--muted);font-weight:900}.v{font-size:28px;font-weight:950;letter-spacing:-.04em}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.tab{background:var(--soft);color:var(--text)}.tab.active{background:var(--text);color:var(--bg)}.section{display:none}.section.active{display:block}.list{display:grid;gap:10px}.item{border:1px solid var(--line);border-radius:18px;padding:13px;background:rgba(255,255,255,.18)}.row{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.name{font-size:17px;font-weight:950;line-height:1.35}.muted{color:var(--muted)}.mini{font-size:12px}.pill{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:12px;font-weight:900;margin:2px 4px 2px 0}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.pill.ok{border-color:color-mix(in srgb,var(--ok) 45%,var(--line));color:var(--ok)}.pill.warn{border-color:color-mix(in srgb,var(--warn) 45%,var(--line));color:var(--warn)}.pill.bad{border-color:color-mix(in srgb,var(--bad) 45%,var(--line));color:var(--bad)}table{width:100%;border-collapse:collapse}th,td{padding:9px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;color:var(--muted)}a{color:var(--accent2);font-weight:900;text-decoration:none}a:hover{text-decoration:underline}code,.pre{white-space:pre-wrap;word-break:break-word;background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:10px;display:block;color:var(--text)}.cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.filterbar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.input{border:1px solid var(--line);border-radius:14px;background:var(--soft);color:var(--text);padding:10px 12px;min-width:240px}.empty{padding:24px;text-align:center;color:var(--muted)}@media(max-width:900px){.hero,.cols{grid-template-columns:1fr}.card,.card.wide{grid-column:1/-1}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:38px}}@media(max-width:560px){.wrap{padding:18px 10px}.stats{grid-template-columns:1fr}.toolbar,.tabs{display:grid}.btn,button{text-align:center}.row{display:block}.input{min-width:0;width:100%}}
</style>
</head>
<body>
<script src="/assets/nb-shell.js" data-prefix="/today" data-label="个人中枢" defer></script>
<div class="wrap">
  <section class="hero">
    <div class="panel"><div class="eyebrow">PERSONAL OPS</div><h1>个人中枢</h1><p class="sub">把“有没有跑、今天有什么、模型为什么花钱”放到一张桌面上。这里不替代 sidecar，只做收口和解释。</p><div class="toolbar"><a class="btn" href="/">回到驾驶舱</a><a class="btn secondary" href="/workbench">内容工作台</a><a class="btn secondary" href="/lof">投资看板</a><a class="btn secondary" href="/sidecars">系统运维</a><button class="secondary" onclick="loadAll(true)">刷新</button><button class="secondary" onclick="toggleTheme()">明暗</button></div></div>
    <div class="panel"><div class="k">状态摘要</div><div class="stats" id="heroStats"><div class="stat"><div class="k">加载中</div><div class="v">...</div></div></div></div>
  </section>
  <div class="panel" style="margin-top:14px"><div class="tabs"><button id="tab-today" class="tab" onclick="showTab('today')">今日收件箱</button><button id="tab-tasks" class="tab" onclick="showTab('tasks')">任务追踪</button><button id="tab-model" class="tab" onclick="showTab('model')">模型路由</button></div></div>
  <section id="sec-today" class="section grid"><article class="card full"><h2>今日重点</h2><div id="todaySummary"></div></article><article class="card wide"><h2>内容流</h2><div class="filterbar"><input id="todayFilter" class="input" placeholder="筛选标题/来源" oninput="renderToday()"></div><div class="list" id="todayItems"></div></article><article class="card"><h2>投资/异常</h2><div class="list" id="todaySignals"></div></article></section>
  <section id="sec-tasks" class="section grid"><article class="card full"><h2>任务追踪</h2><p class="sub">展示配置、最近一次运行、是否发送、未发送原因和一键重跑；Notify 会保留每个任务最近 7 次运行历史。</p><div class="filterbar"><button class="secondary" onclick="taskFilter='all';renderTasks()">全部</button><button class="secondary" onclick="taskFilter='bad';renderTasks()">异常</button><button class="secondary" onclick="taskFilter='sent';renderTasks()">已发送</button><button class="secondary" onclick="taskFilter='silent';renderTasks()">静默</button><input id="taskKw" class="input" placeholder="筛选任务名/id" oninput="renderTasks()"></div><div style="overflow:auto"><table><thead><tr><th>任务</th><th>规则</th><th>最近状态</th><th>下次运行</th><th>解释 / 近7次历史</th><th>操作</th></tr></thead><tbody id="taskRows"></tbody></table></div></article></section>
  <section id="sec-model" class="section grid"><article class="card full"><h2>OBP 模型路由解释</h2><div id="modelSummary"></div></article><article class="card"><h2>来源消耗（本月）</h2><div class="list" id="sourceCosts"></div></article><article class="card"><h2>升级 Pro 的原因</h2><div class="list" id="proReasons"></div></article><article class="card wide"><h2>最近请求</h2><div style="overflow:auto"><table><thead><tr><th>时间</th><th>来源</th><th>路由</th><th>模型</th><th>原因</th><th>成本</th></tr></thead><tbody id="modelRows"></tbody></table></div></article></section>
</div>
<script>
const root=document.documentElement;
function applyTheme(mode){const dark=mode==='dark';const value=dark?'dark':'light';root.setAttribute('data-theme',value);root.classList.toggle('dark',dark);if(document.body){document.body.setAttribute('data-theme',value);document.body.classList.toggle('dark',dark)}['dashboardTheme','sidecarShellTheme','personalOpsTheme'].forEach(k=>localStorage[k]=value)}
applyTheme((localStorage.sidecarShellTheme||localStorage.dashboardTheme||localStorage.personalOpsTheme)==='dark'?'dark':'light');
function toggleTheme(){const dark=root.getAttribute('data-theme')==='dark'||root.classList.contains('dark');applyTheme(dark?'light':'dark')}
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=s=>{if(!s)return '-';try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s||'-'}};
const host=u=>{try{return new URL(u).host}catch{return '-'}};
let DATA={today:null,tasks:null,model:null};let taskFilter='all';let current='today';
function showTab(name){current=name;history.replaceState(null,'','/'+(name==='model'?'model-routes':name));['today','tasks','model'].forEach(x=>{document.getElementById('sec-'+x).classList.toggle('active',x===name);document.getElementById('tab-'+x).classList.toggle('active',x===name)});if(name==='today')renderToday();if(name==='tasks')renderTasks();if(name==='model')renderModel();}
async function getJson(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(url+' '+r.status);return r.json()}
async function loadAll(manual=false){try{const [today,tasks,model]=await Promise.all([getJson('/api/today'),getJson('/api/task-trace'),getJson('/api/model-routes')]);DATA={today,tasks,model};renderHero();renderToday();renderTasks();renderModel();}catch(e){document.getElementById('heroStats').innerHTML=`<div class="stat"><div class="k bad">读取失败</div><div class="mini">${esc(e.message)}</div></div>`}}
function renderHero(){const t=DATA.today||{}, n=DATA.tasks||{}, m=DATA.model||{};const bad=(n.items||[]).filter(j=>['error','timeout'].includes(j.status?.last_status)).length;const sent=(n.items||[]).filter(j=>j.status?.last_sent).length;const pro=(m.recent||[]).filter(x=>String(x.route||'').includes('pro')||String(x.model||'').toLowerCase().includes('pro')).length;document.getElementById('heroStats').innerHTML=`<div class="stat"><div class="k">今日内容</div><div class="v">${(t.rss_items||[]).length+(t.trend_items||[]).length+(t.inbox_items||[]).length}</div></div><div class="stat"><div class="k">任务异常</div><div class="v ${bad?'bad':'ok'}">${bad}</div></div><div class="stat"><div class="k">已推送</div><div class="v">${sent}</div></div><div class="stat"><div class="k">最近 Pro</div><div class="v ${pro?'warn':'ok'}">${pro}</div></div>`}
function renderToday(){const d=DATA.today;if(!d)return;const kw=(document.getElementById('todayFilter')?.value||'').toLowerCase();const items=[];(d.rss_items||[]).forEach(x=>items.push({kind:'RSS',title:x.title,source:x.subscription_name,time:x.published_at_local||x.published_at,url:x.link,summary:x.summary}));(d.trend_items||[]).slice(0,12).forEach(x=>items.push({kind:'热点',title:x.title,source:x.source_name,time:x.last_seen_at,url:x.url||x.mobile_url,summary:x.summary||('热度 '+(x.score??'-')+' / 排名 #'+(x.rank??'-'))}));(d.inbox_items||[]).slice(0,12).forEach(x=>items.push({kind:'收件箱',title:x.title||x.url,source:x.source||host(x.url),time:x.created_at||x.saved_at,url:x.url,summary:x.summary||x.decision||''}));const filtered=items.filter(x=>!kw||String(x.title||'').toLowerCase().includes(kw)||String(x.source||'').toLowerCase().includes(kw));const actions=(d.actions||[]).slice(0,3);const actionCls=x=>x==='bad'?'bad':(x==='warn'?'warn':(x==='ok'?'ok':''));const actionHtml=`<div style="margin-top:12px"><h3 style="margin:0 0 10px">今天真正需要处理的 3 件事</h3><div class="list">${actions.map(a=>`<div class="item"><div class="row"><div><div class="name ${actionCls(a.level)}">${esc(a.title||'-')}</div><div class="mini muted">${esc(a.body||'')}</div></div><a class="pill ${actionCls(a.level)}" href="${esc(a.url||'#')}">${esc(a.action||'打开')}</a></div></div>`).join('')||'<div class="empty">暂无需要处理的事项。</div>'}</div></div>`;document.getElementById('todaySummary').innerHTML=`<div class="stats"><div class="stat"><div class="k">RSS</div><div class="v">${(d.rss_items||[]).length}</div></div><div class="stat"><div class="k">热点</div><div class="v">${(d.trend_items||[]).length}</div></div><div class="stat"><div class="k">收件箱</div><div class="v">${(d.inbox_items||[]).length}</div></div><div class="stat"><div class="k">LOF 高溢价</div><div class="v ${((d.lof_high||[]).length)?'warn':'ok'}">${(d.lof_high||[]).length}</div></div></div>${actionHtml}`;document.getElementById('todayItems').innerHTML=filtered.length?filtered.map(x=>`<div class="item"><div class="row"><div><span class="pill">${esc(x.kind)}</span><span class="pill">${esc(x.source||'-')}</span><div class="name"><a href="${esc(x.url||'#')}" target="_blank" rel="noopener">${esc(x.title||'-')}</a></div><div class="mini muted">${fmt(x.time)}</div></div></div><div class="muted" style="margin-top:8px;line-height:1.6">${esc(String(x.summary||'').slice(0,180))}</div></div>`).join(''):'<div class="empty">今天还没有内容。</div>';document.getElementById('todaySignals').innerHTML=[...(d.lof_high||[]).slice(0,8).map(x=>`<div class="item"><div class="name"><a href="/lof">${esc(x.code)} ${esc(x.name)}</a></div><div class="mini muted">实时溢价 ${Number(x.rt_premium_pct||0).toFixed(2)}%，现价 ${x.price??'-'}</div></div>`),...((d.task_alerts||[]).slice(0,6).map(x=>`<div class="item"><div class="name bad">${esc(x.name||x.id)}</div><div class="mini muted">${esc(x.reason||'-')}</div></div>`))].join('')||'<div class="empty">没有明显异常。</div>'}
function statusPill(s){const cls=s==='sent'||s==='success'?'ok':(s==='error'||s==='timeout'?'bad':(s==='silent'?'warn':''));return `<span class="pill ${cls}">${esc(s||'未运行')}</span>`}
function runHistoryHtml(j){const runs=(j.recent_runs||[]).slice(0,7);if(!runs.length)return '<div class="mini muted" style="margin-top:6px">近7次：从本次部署后开始记录。</div>';return `<details style="margin-top:8px"><summary class="mini muted">近7次运行</summary><div>${runs.map(r=>`<div class="mini"><span class="pill ${r.status==='error'||r.status==='timeout'?'bad':(r.sent?'ok':'warn')}">${esc(r.status||'-')}</span>${esc(fmt(r.finished_at))} · ${esc(r.duration_ms??'-')}ms · ${esc(r.trigger||'-')}${r.error?`<div class="bad">${esc(r.error)}</div>`:''}</div>`).join('')}</div></details>`}
function explainJob(j){const st=j.status||{};if(!j.enabled)return '已暂停，不会自动跑。';if(st.last_error)return '最近失败：'+st.last_error;if(st.last_sent)return '最近一次已发送。';if(st.last_status==='silent')return '脚本正常结束但选择静默，通常是无新内容/不满足条件。';if(!st.last_status)return '还没有运行记录。';return '最近状态：'+st.last_status;}
function renderTasks(){const d=DATA.tasks;if(!d)return;const kw=(document.getElementById('taskKw')?.value||'').toLowerCase();let rows=(d.items||[]).filter(j=>!kw||String(j.name||'').toLowerCase().includes(kw)||String(j.id||'').toLowerCase().includes(kw));if(taskFilter==='bad')rows=rows.filter(j=>['error','timeout'].includes(j.status?.last_status));if(taskFilter==='sent')rows=rows.filter(j=>j.status?.last_sent);if(taskFilter==='silent')rows=rows.filter(j=>j.status?.last_status==='silent');document.getElementById('taskRows').innerHTML=rows.map(j=>`<tr><td><b>${esc(j.name)}</b><br><span class="mini muted">${esc(j.id)}</span></td><td><code>${esc(j.schedule)}</code><div class="mini muted">${esc(j.timezone)} · ${j.timeout_secs||'-'}s</div></td><td>${statusPill(j.status?.last_status)}<div class="mini muted">${esc(j.status?.last_finished_at||j.status?.last_started_at||'-')}</div></td><td>${esc((j.next_runs||[])[0]||'-')}</td><td>${esc(explainJob(j))}${j.status?.last_stdout_preview?`<div class="pre mini">${esc(j.status.last_stdout_preview)}</div>`:''}${runHistoryHtml(j)}</td><td><button class="secondary" onclick="runTask('${esc(j.id)}',this)">重跑</button></td></tr>`).join('')||'<tr><td colspan="6" class="empty">没有匹配任务。</td></tr>'}
async function runTask(id,btn){const old=btn.textContent;btn.disabled=true;btn.textContent='运行中';try{await fetch('/api/task-run/'+encodeURIComponent(id),{method:'POST'});DATA.tasks=await getJson('/api/task-trace');renderTasks();renderHero();}catch(e){alert('重跑失败：'+e.message)}finally{btn.disabled=false;btn.textContent=old}}
function renderModel(){const d=DATA.model;if(!d)return;const paid=d.stats?.paid?.total||{}, free=d.stats?.free?.total||{}, total=d.stats?.total||{};document.getElementById('modelSummary').innerHTML=`<div class="stats"><div class="stat"><div class="k">付费请求</div><div class="v">${paid.requests||0}</div><div class="mini muted">￥${Number(paid.cost_cny||0).toFixed(4)}</div></div><div class="stat"><div class="k">免费请求</div><div class="v ok">${free.requests||0}</div></div><div class="stat"><div class="k">总 tokens</div><div class="v">${total.total_tokens||0}</div></div><div class="stat"><div class="k">最近 Pro</div><div class="v warn">${d.pro_count||0}</div></div></div>`;const sourceBox=document.getElementById('sourceCosts');if(sourceBox){sourceBox.innerHTML=(d.source_costs||[]).map(x=>{const p=x.paid||{}, f=x.free||{}, t=x.total||{};return `<div class="item"><div class="row"><div><div class="name">${esc(x.source||'-')}</div><div class="mini muted">${esc(x.month||'本月')} · 总请求 ${esc(x.total_requests||t.requests||0)} · 总 tokens ${esc(t.total_tokens||0)}</div></div><span class="pill ${Number(x.paid_cost_cny||0)>0?'warn':'ok'}">￥${Number(x.paid_cost_cny||0).toFixed(4)}</span></div><div class="mini muted">付费 ${esc(p.requests||0)} 次 / 免费 ${esc(f.requests||0)} 次</div></div>`}).join('')||'<div class="empty">暂无来源拆分记录。</div>'}document.getElementById('modelRows').innerHTML=(d.recent||[]).map(x=>`<tr><td>${esc(x.time||'-')}</td><td>${esc(x.source||'-')}</td><td>${esc(x.route||'-')}</td><td>${esc(x.model||'-')}<div class="mini muted">请求：${esc(x.requested_model||'-')}</div></td><td>${esc(x.route_reason||'-')}</td><td>￥${Number(x.cost_cny||0).toFixed(5)}<div class="mini muted">${x.prompt_tokens||0}/${x.completion_tokens||0} tokens</div></td></tr>`).join('')||'<tr><td colspan="6" class="empty">暂无模型调用记录。</td></tr>';document.getElementById('proReasons').innerHTML=Object.entries(d.pro_reasons||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="item"><div class="row"><b>${esc(k)}</b><span class="pill warn">${v} 次</span></div></div>`).join('')||'<div class="empty">最近没有升级 Pro。</div>'}
const path=location.pathname;showTab(path.includes('tasks')?'tasks':(path.includes('model-routes')?'model':'today'));loadAll();
</script>
</body></html>"####
            .to_string(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn lof_index_has_manual_and_opt_in_auto_refresh_controls() {
        let Html(html) = index().await;
        assert!(html.contains("boardRefreshBtn"));
        assert!(html.contains("boardAutoRefresh"));
        assert!(html.contains("BOARD_AUTO_REFRESH_MS=30000"));
        assert!(html.contains("applyLofTheme"));
        assert!(html.contains("data-theme"));
        assert!(!html.contains("setInterval(refresh,10000)"));
    }

    #[tokio::test]
    async fn dashboard_prioritizes_digest_money_then_collapsible_status() {
        let Html(html) = dashboard().await;
        let digest = html
            .find("&#x4eca;&#x65e5;&#x6458;&#x8981;")
            .expect("digest card");
        let investment = html
            .find("&#x6295;&#x8d44;&#x96f7;&#x8fbe;")
            .expect("investment radar card");
        let attention = html
            .find("&#x9700;&#x8981;&#x4f60;&#x770b;")
            .expect("attention card");
        let status = html.find("运行状态").expect("mini status fold");
        let quick = html
            .find("&#x5feb;&#x901f;&#x5165;&#x53e3;")
            .expect("quick links card");
        assert!(digest < investment);
        assert!(investment < attention);
        assert!(attention < status);
        let info = html
            .find("&#x4fe1;&#x606f;&#x96f7;&#x8fbe;")
            .expect("info radar card");
        assert!(status < quick);
        assert!(quick < info);
        assert!(html.contains(
            r#"card full fade" style="animation-delay:.18s"><h2>&#x4fe1;&#x606f;&#x96f7;&#x8fbe;"#
        ));
        assert!(html.contains("list infoGrid"));
        assert!(html.contains("opsMiniGrid"));
        assert!(html.contains("detailCard"));
        assert!(html.contains("今天真正需要处理的 3 件事"));
        assert!(html.contains("投资信号"));
        assert!(!html.contains("split('\n').slice(0,8).join('\n')"));
        assert!(html.contains("split('\\n').slice(0,8).join('\\n')"));
    }

    #[tokio::test]
    async fn personal_ops_page_exposes_three_core_workflows() {
        let Html(html) = personal_ops_page().await;
        assert!(html.contains("今日收件箱"));
        assert!(html.contains("任务追踪"));
        assert!(html.contains("OBP 模型路由解释"));
        assert!(html.contains("/api/task-trace"));
        assert!(html.contains("/api/model-routes"));
        assert!(html.contains("今天真正需要处理的 3 件事"));
        assert!(html.contains("sourceCosts"));
        assert!(html.contains("recent_runs"));
    }
}
