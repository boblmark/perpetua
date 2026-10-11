

const LS_SNAP='perpetua-demo-dashboard-v3', LS_SET='perpetua-settings-v2', LS_TEN='perpetua-tenants-v1', LS_ACT='perpetua-active-tenant-v1', LS_WARN='perpetua-terminal-warning-ack-v1';
const auth=()=>({});  // 免登录：不再向前端下发任何 token，MCP 调用走服务端 /api/mcp 代理
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const STAGE_META={trend:['趋势输入','Trend',0],select:['选题生成','Select',1],review:['Ask Studio 评审','Review',1],generate:['视频生成','Generate',1],qc:['QC 质检','QC',0],publish:['终审上传','Publish',0],postop:['发布后运营','PostOp',0],evolve:['数据进化','Evolve',1]};
let SNAP=null, TENANTS={}, ACTIVE_TENANT=localStorage.getItem(LS_ACT)||'default', SETTINGS={};
let PIPE_TIMER=null, LOG_TIMER=null, SNAP_TIMER=null;
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600)}
async function api(path,opt={}){
  const r=await fetch(path,{...(opt||{}),headers:{...(opt.headers||{}),...auth()}});
  if(r.status===401){document.getElementById('app').innerHTML='<div class="loading">Token 无效，请刷新页面重试</div>';throw new Error('401');}
  return r.json();
}
function loadSettings(){
  try{SETTINGS=JSON.parse(localStorage.getItem(LS_SET))||{}}catch(e){SETTINGS={}}
  SETTINGS=Object.assign({daily_target:5,virality_threshold:60,plan:'Pro',spike_detector:true,auto_retitle:true,ask_studio_auto:true},SETTINGS);
}
function saveSettings(silent){
  localStorage.setItem(LS_SET,JSON.stringify(SETTINGS));
  api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(SETTINGS)}).catch(()=>{});
  if(!silent)toast('配置已保存 · Settings saved');
}
async function boot(){
  loadSettings();
  try{
    const [snap,ten]=await Promise.all([api('/api/snapshot'),api('/api/tenants')]);
    SNAP=snap; TENANTS=(ten&&ten.tenants)||{};
    try{localStorage.setItem(LS_SNAP,JSON.stringify({at:Date.now(),data:snap}))}catch(e){}
    try{localStorage.setItem(LS_TEN,JSON.stringify(TENANTS))}catch(e){}
  }catch(e){
    try{const c=JSON.parse(localStorage.getItem(LS_SNAP));if(c&&c.data)SNAP=c.data}catch(e2){}
    try{TENANTS=JSON.parse(localStorage.getItem(LS_TEN))||{}}catch(e3){}
    if(!SNAP){document.getElementById('app').innerHTML='<div class="loading">加载失败，请检查网络后刷新</div>';return}
  }
  if(!TENANTS[ACTIVE_TENANT])ACTIVE_TENANT=Object.keys(TENANTS)[0]||'default';
  render();
  startTimers();
}
function startTimers(){
  clearInterval(PIPE_TIMER);clearInterval(LOG_TIMER);clearInterval(SNAP_TIMER);
  const tickPipe=()=>renderPipeline(true);
  const tickLog=()=>{if(window._logVisible!==false)loadLogs(true)};
  const tickSnap=()=>api('/api/snapshot').then(s=>{SNAP=s;renderSnapSections()}).catch(()=>{});
  PIPE_TIMER=setInterval(tickPipe,60000); LOG_TIMER=setInterval(tickLog,10000); SNAP_TIMER=setInterval(tickSnap,60000);
  window._logVisible=true;
}
function tenantOptions(){
  return Object.values(TENANTS).map(t=>{
    const lbl=`${t.name||t.id} · ${t.youtube_channel_name||t.youtube_channel_id||''}`;
    return `<option value="${esc(t.id)}" ${t.id===ACTIVE_TENANT?'selected':''}>${esc(lbl)}</option>`;
  }).join('');
}
function activeTenant(){return TENANTS[ACTIVE_TENANT]||{id:'default',name:'Default Channel',plan:'Pro',status:'active',youtube_channel_name:'@karenvsai'}}
function render(){
  const t=activeTenant(), s=SNAP;
  const upd=s.updatedAt?new Date(s.updatedAt):new Date();
  const updStr=`更新于 ${upd.getMonth()+1}月${upd.getDate()}日 ${String(upd.getHours()).padStart(2,'0')}:${String(upd.getMinutes()).padStart(2,'0')}`;
  const pct=Math.min(100,(s.shortsViews90d/s.shortsGoal*100));
  const remain=((s.shortsGoal-s.shortsViews90d)/1e4);
  const onlineN=(s.health||[]).filter(h=>h.healthy).length, totalN=(s.health||[]).length;
  const deg=(pct/100*360).toFixed(1);
  document.getElementById('app').innerHTML=`
  <div class="tenant-bar">
    <div><div class="tlabel">当前租户 · TENANT</div><select id="tenantSel" onchange="switchTenant(this.value)">${tenantOptions()}</select></div>
    <span class="badge ${t.status==='active'?'active':'suspended'}">${t.status==='active'?'ACTIVE':'SUSPENDED'}</span>
    <span class="badge plan">${esc(t.plan||'Pro')}</span>
  </div>
  <div class="topline">
    <span class="dot-live"></span>
    <div><h1>${esc(s.channelName||'Mark Bobl | Karen vs AI')}</h1>
    <div class="sub">${esc(s.channelId||'@karenvsai')} · ${s.subscriberCount||532} 订阅者 <span class="brand">Perpetua by ViralLoop</span></div></div>
    <div class="actions">
      <button class="btn" id="termBtn" onclick="toggleTerm()">⌁ 终端</button>
      <button class="btn primary" onclick="refreshSnap(this)">⟳ 刷新</button>
    </div>
  </div>
  <div class="term-panel" id="termPanel">
    <div class="term-head"><span>🖥</span><span class="t">服务器终端 Server terminal</span><span class="wd">perpetua:/home/hatch/data</span>
      <span class="sp"><button class="btn" onclick="clearTerm()">清屏 · Clear</button><button class="btn" onclick="toggleTerm()">×</button></span></div>
    <div class="warn-bar" id="warnBar" style="display:none">⚠ 终端直连服务器，请谨慎操作 / Terminal connects directly to server, use with caution <button class="btn" onclick="ackWarn()">我已了解 · Continue</button></div>
    <div class="term-out" id="termOut"><div class="hint">Perpetua shell ready<br>工作目录 · Working directory: /home/hatch/data</div></div>
    <div class="term-in"><span class="p">$</span><input id="termIn" placeholder="输入 shell 命令，回车执行" autocomplete="off"><button class="run" onclick="runTerm()">运行 · Run</button></div>
  </div>
  <div class="context-row"><span class="chip-demo">演示数据 · DEMO</span><span>${updStr}</span><span>每 60 秒自动刷新</span></div>
  <div id="snapSections">${snapSectionsHTML(s,pct,deg,remain,onlineN,totalN)}</div>
  <div class="pipeline-block">
    <div class="pipeline-head"><h3>自动化流水线 · Automation Pipeline</h3><span class="live-badge offline" id="pipeBadge"><span class="dot-live" style="background:currentColor;box-shadow:none"></span>CONNECTING</span></div>
    <div class="pipeline-grid" id="pipeGrid"></div>
    <div class="pipeline-foot">每 60 秒读取 MCP 实际执行记录 · MCP telemetry refreshes every 60 seconds · 点击卡片查看运行日志</div>
  </div>
  <div class="pipeline-block" id="chartsBlock" style="display:none">
    <div class="pipeline-head"><h3>业务图表 · Charts</h3></div>
    <div class="pipeline-grid" id="chartsGrid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))"></div>
  </div>
  <div class="logs-panel card">
    <div class="logs-head"><h3>实时日志 / Live Logs <span class="hint">· 自动刷新 10s</span></h3><span class="log-sync" id="logSync"></span></div>
    <div class="log-tabs" id="logTabs"></div>
    <div class="log-box" id="logBox" style="margin-top:10px"><div class="hint">加载中…</div></div>
  </div>
  <div class="settings-block card">
    <div class="settings-head"><h3>配置 / Settings <span class="en">· ${esc(t.name||'')}</span></h3><span class="badge plan">${esc(SETTINGS.plan)}</span></div>
    <div class="set-row"><label>每日生产目标 · Daily video target</label>
      <div class="set-flex"><input type="range" min="1" max="20" value="${SETTINGS.daily_target}" oninput="setCfg('daily_target',this.value)"><input class="set-num" type="number" min="1" max="20" value="${SETTINGS.daily_target}" oninput="setCfg('daily_target',this.value)"><span class="set-big" id="cfgTargetBig">${SETTINGS.daily_target}</span></div>
      <div class="set-hint">套餐上限：${t.quota? t.quota.videos_per_day:10} / day</div></div>
    <div class="set-row"><label>爆款分数门槛 · Virality threshold</label>
      <div class="set-flex"><input type="range" min="40" max="90" value="${SETTINGS.virality_threshold}" oninput="setCfg('virality_threshold',this.value)"><span class="set-big" id="cfgThrBig">${SETTINGS.virality_threshold}</span></div></div>
    <div class="set-row"><label>套餐 · Plan</label>
      <select class="plan" onchange="setCfg('plan',this.value)">
        <option ${SETTINGS.plan==='Free'?'selected':''}>Free</option><option ${SETTINGS.plan==='Pro'?'selected':''}>Pro</option><option ${SETTINGS.plan==='Enterprise'?'selected':''}>Enterprise</option>
      </select><span class="hint"> Free 3 · Pro 10 · Enterprise 50 / day</span></div>
    ${toggleRow('spike_detector','热点爆发探测','Trend spike detector')}
    ${toggleRow('auto_retitle','自动换标题','Auto retitle')}
    ${toggleRow('ask_studio_auto','Ask Studio 自动问询','Ask Studio auto-ask')}
    <div class="settings-foot"><span class="hint">设置保存在此设备 · Saved on this device</span><button class="btn primary" onclick="saveSettings()">保存配置 · Save</button></div>
    <div class="tm-head"><h3 style="font-size:15px">租户管理 / Tenants</h3><button class="btn" onclick="openModal('mAdd')">＋ 添加租户 · Add tenant</button></div>
    <div id="tmTable"></div>
  </div>`;
  if(!localStorage.getItem(LS_WARN))document.getElementById('warnBar').style.display='flex';
  bindTermInput(); renderLogTabs(); loadLogs(); renderPipeline(); renderCharts(); renderTenantTable();
}
function snapSectionsHTML(s,pct,deg,remain,onlineN,totalN){
  const vids=(s.videos||[]).map(v=>`<tr><td><a href="https://youtube.com/watch?v=${esc(v.videoId)}" target="_blank">${esc(v.title)} <span class="ext">↗</span></a></td><td class="mono">${esc(v.publishedAt)}</td><td class="mono">${Number(v.views).toLocaleString()}</td><td>${v.status==='published'?'<span class="sdot ok"></span>已发布 · Published':'<span class="sdot warn"></span>处理中 · Processing'}</td></tr>`).join('');
  const health=(s.health||[]).map(h=>`<div class="health-row"><div>${esc(h.name)}<div class="d">${esc(h.detail)}</div></div><span class="sdot ${h.healthy?'ok':'bad'}"></span></div>`).join('');
  return `
  <div class="hero-grid">
    <div class="card"><div class="ypp-glow"></div>
      <div class="ypp-top"><div><h3>YPP 进度</h3><div class="en">90-day Shorts views</div></div><span class="goal-pill">目标 · GOAL 3M</span></div>
      <div class="ypp-body">
        <div class="ring" style="background:conic-gradient(var(--primary) 0deg, var(--purple) ${deg}deg, var(--border) ${deg}deg 360deg)"><div class="in"><div class="pct">${pct.toFixed(1)}%</div><div class="lbl">已完成</div></div></div>
        <div><div class="ypp-num">${(s.shortsViews90d/1e3).toFixed(1)}K</div><div class="ypp-sub">/ 3M 次观看</div><div class="ypp-sub">还需 ${remain.toFixed(1)}万次观看解锁下一阶段</div></div>
      </div>
      <div class="ypp-bar"><i></i></div>
    </div>
    <div class="card metrics-panel">
      <div class="metric"><div class="k">今日发布<span class="en">Videos today</span></div><div class="v blue">${s.videosToday}</div></div>
      <div class="metric"><div class="k">近 7 日观看<span class="en">Views 7d</span></div><div class="v">${(s.views7d/1e3).toFixed(1)}K</div></div>
      <div class="metric"><div class="k">爆款率<span class="en">Virality rate</span></div><div class="v">${s.viralityRate}%</div></div>
    </div>
  </div>
  <div class="workspace-grid">
    <div class="card"><h3>最近视频 <span class="en">· Recent videos</span></h3>
      <table class="videos"><tr><th>标题 · Title</th><th>发布时间 · Published</th><th>观看 · Views</th><th>状态 · Status</th></tr>${vids}</table></div>
    <div class="card"><div class="health-head"><h3>系统健康 <span class="en">/ System health</span></h3><span class="cnt">${onlineN}/${totalN} ONLINE</span></div><div style="margin-top:8px">${health}</div></div>
    <div class="card"><h3>${esc(SETTINGS.plan)}</h3><div class="en">当前方案 · Current plan</div>
      <div style="text-align:right;font-size:11px;color:var(--muted)">5/day target</div>
      <div style="margin-top:10px;font-size:13px">套餐额度 · Plan quota</div>
      <div class="quota-num">${s.quotaUsed} / ${s.quotaTotal}</div>
      <div class="quota-bar"><i style="width:${(s.quotaUsed/s.quotaTotal*100).toFixed(0)}%"></i></div>
      <div class="hint">每日 00:00 自动重置 · Resets daily</div></div>
  </div>`;
}
function renderSnapSections(){
  const s=SNAP,pct=Math.min(100,(s.shortsViews90d/s.shortsGoal*100)),deg=(pct/100*360).toFixed(1),remain=((s.shortsGoal-s.shortsViews90d)/1e4);
  const onlineN=(s.health||[]).filter(h=>h.healthy).length;
  const el=document.getElementById('snapSections');
  if(el)el.innerHTML=snapSectionsHTML(s,pct,deg,remain,onlineN,(s.health||[]).length);
}
function toggleRow(key,cn,en){
  return `<div class="toggle-row"><div>${cn}<div class="en hint">${en}</div></div><label class="switch ${SETTINGS[key]?'on':''}"><input type="checkbox" ${SETTINGS[key]?'checked':''} onchange="setCfg('${key}',this.checked)"><span class="tr"></span></label></div>`;
}
function setCfg(k,v){SETTINGS[k]=v;if(k==='daily_target'){const e=document.getElementById('cfgTargetBig');if(e)e.textContent=v}if(k==='virality_threshold'){const e=document.getElementById('cfgThrBig');if(e)e.textContent=v}document.querySelectorAll('.switch').forEach(()=>{});saveSettings(true);renderToggles();}
function renderToggles(){document.querySelectorAll('.toggle-row .switch input').forEach(inp=>{const k=inp.getAttribute('onchange').match(/'(\w+)'/)[1];inp.checked=!!SETTINGS[k];inp.closest('.switch').classList.toggle('on',!!SETTINGS[k])})}
function switchTenant(id){ACTIVE_TENANT=id;localStorage.setItem(LS_ACT,id);render()}
async function refreshSnap(btn){btn.disabled=true;try{SNAP=await api('/api/snapshot/refresh',{method:'POST'});renderSnapSections();toast('已刷新 · Refreshed')}catch(e){}btn.disabled=false}
async function renderPipeline(silent){
  try{
    const d=await api('/api/pipeline?tenant_id='+encodeURIComponent(ACTIVE_TENANT));
    const badge=document.getElementById('pipeBadge');
    if(badge){badge.className='live-badge '+d.overall;badge.innerHTML=`<span class="dot-live" style="background:currentColor;box-shadow:none"></span>${d.overall.toUpperCase()}`}
    document.getElementById('pipeGrid').innerHTML=d.stages.map(st=>{
      const meta=STAGE_META[st.id]||[st.id,st.id,0];
      const dot=st.freshness==='live'?'ok':st.freshness==='stale'?'working':'idle';
      const ago=st.at?timeAgo(st.at):'无数据';
      return `<div class="stage-card ${st.freshness==='stale'?'working':''}" onclick="showStageLogs('${st.id}')" style="cursor:pointer">
        <div class="stage-top"><span class="stage-dot ${dot}"></span><span class="stage-name">${meta[0]}<span class="en">${meta[1]}</span>${meta[2]?'<span class="ai-badge">AI</span>':''}</span></div>
        <div class="stage-count">${st.count||''}</div>
        <div class="stage-detail">${esc(st.detail||'—')}</div>
        <div class="stage-foot">${st.freshness==='live'?'<span class="ok">正常 · OK</span> / ':''}${esc(ago)}</div>
      </div>`;
    }).join('');
  }catch(e){if(!silent){const g=document.getElementById('pipeGrid');if(g)g.innerHTML='<div class="hint">加载失败</div>'}}
  renderPolicyGate(silent);renderDouyin(silent);renderDistributor(silent);renderMatrix(silent);
}
async function renderMatrix(silent){
  const card=document.getElementById('matrixCard');if(!card)return;
  try{
    const d=await api('/api/platform_matrix');
    if(!d.ok){if(!silent)card.innerHTML='<div class="hint">加载失败</div>';return;}
    const ps=d.platforms||{};
    const order=['douyin','xiaohongshu','kuaishou','bilibili','youtube','facebook','tiktok','x'];
    const synced=order.filter(k=>ps[k]&&ps[k].status==='ok').length;
    const cnt=document.getElementById('matrixCnt');
    if(cnt)cnt.textContent=`${synced}/8 已同步`;
    const ago=t=>{if(!t)return'未同步';const s=Math.floor((Date.now()-new Date(t).getTime())/1000);if(s<3600)return Math.floor(s/60)+'分钟前';if(s<86400)return Math.floor(s/3600)+'小时前';return Math.floor(s/86400)+'天前';};
    const tiles=order.map(k=>{
      const p=ps[k]||{};
      const st=p.status==='ok'?'#4ade80':(p.status==='error'?'#f87171':'#fbbf24');
      const vids=(p.videos||[]).slice(0,4).map(v=>`<div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px;align-items:center">
        ${v.cover?`<img src="${esc(v.cover)}" style="width:64px;height:36px;object-fit:cover;border-radius:4px" loading="lazy">`:''}
        <div style="flex:1;min-width:0"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${v.url?`<a href="${esc(v.url)}" target="_blank" style="color:inherit">${esc(v.title||'—')}</a>`:esc(v.title||'—')}</div>
        <div class="hint">${v.views!=null?'▶'+Number(v.views).toLocaleString()+' ':''}${v.likes!=null?'♥'+Number(v.likes).toLocaleString():''}</div></div></div>`).join('');
      const cmts=(p.comments||[]).slice(0,5).map((c,i)=>`<div style="padding:5px 0;border-bottom:1px solid var(--border);font-size:12px">
        <div><b>${esc(c.author||'匿名')}</b> <span class="hint">${c.replied?'已回':'未回'}${c.likes!=null?' · ♥'+c.likes:''}</span></div>
        <div style="color:var(--muted);margin:2px 0">${esc((c.text||'').slice(0,90))}</div>
        <div id="mr-${k}-${i}" style="display:none;margin-top:4px"><textarea id="mrt-${k}-${i}" rows="2" style="width:100%;font-size:12px" placeholder="写回复（进人工待批池）"></textarea>
        <button onclick="matrixReply('${k}','${esc(c.comment_id||'')}','${esc(c.video_url||'')}','${esc((c.author||'').replace(/'/g,""))}','${i}')" style="margin-top:4px;font-size:12px">提交待批</button></div>
        ${c.replied?'':`<a href="javascript:void(0)" onclick="document.getElementById('mr-${k}-${i}').style.display='block';this.style.display='none'" style="font-size:12px">回复</a>`}
      </div>`).join('');
      return `<div style="border:1px solid var(--border);border-radius:8px;padding:10px;min-width:0">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b>${esc(p.name||k)}</b><span style="font-size:11px;color:${st}">●</span></div>
        <div class="hint" style="font-size:11px;margin-bottom:6px">${esc(p.channel||'')}${p.cluster?' · '+esc(p.cluster):''} · ${ago(p.synced_at)}</div>
        ${vids?`<div style="margin-bottom:6px"><div class="hint" style="font-size:11px">最新内容</div>${vids}</div>`:'<div class="hint" style="font-size:11px">暂无内容数据</div>'}
        ${cmts?`<div><div class="hint" style="font-size:11px;margin-top:4px">最新评论</div>${cmts}</div>`:''}
      </div>`;
    }).join('');
    card.innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px">${tiles}</div>
      <div class="hint" style="margin-top:6px;font-size:11px">更新于 ${esc((d.updated_at||'').slice(0,19).replace('T',' '))} · 回复经人工批准后发出（09:00/21:00 批量）</div>`;
  }catch(e){if(!silent)card.innerHTML='<div class="hint">加载失败</div>'}
}
async function matrixReply(platform,comment_id,video_url,author,idx){
  const ta=document.getElementById('mrt-'+platform+'-'+idx);
  const draft=(ta&&ta.value||'').trim();
  if(!draft){alert('先写回复内容');return;}
  try{
    const r=await (await fetch('/api/matrix_reply',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({platform,comment_id,video_url,author,draft})})).json();
    alert(r.ok?('已提交：'+(r.msg||'')):'失败：'+(r.error||''));
    if(r.ok)renderMatrix(true);
  }catch(e){alert('提交失败')}
}
async function renderDistributor(silent){
  const card=document.getElementById('distCard');if(!card)return;
  try{
    const d=await api('/api/distributor');
    const cnt=document.getElementById('distCnt');
    if(cnt)cnt.textContent=`队列 ${d.queue_total} · 拦截 ${d.gate.reject}`;
    const rows=(d.recent_decisions||[]).map(r=>`<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px">
      <span style="color:${r.decision==='accept'?'#4ade80':'#f87171'};font-weight:700">${r.decision==='accept'?'✓':'✗'} ${esc(r.decision)}</span>
      <span class="hint">${esc((r.platforms||[]).join(','))}</span>
      <span style="color:var(--muted)">${esc(r.reason||'')}</span></div>`).join('');
    card.innerHTML=`<div style="display:flex;gap:24px;margin-bottom:8px">
      <div><div class="ypp-num" style="font-size:24px">${d.queue_total}</div><div class="ypp-sub">队列任务</div></div>
      <div><div class="ypp-num" style="font-size:24px">${d.assets_tagged}</div><div class="ypp-sub">已打标签资产</div></div>
      <div><div class="ypp-num" style="font-size:24px;color:#4ade80">${d.gate.accept}</div><div class="ypp-sub">门禁通过</div></div>
      <div><div class="ypp-num" style="font-size:24px;color:#f87171">${d.gate.reject}</div><div class="ypp-sub">门禁拦截</div></div></div>
      ${rows?'<div style="margin-top:4px">'+rows+'</div>':'<div class="hint">暂无门禁决策记录</div>'}`;
  }catch(e){if(!silent)card.innerHTML='<div class="hint">加载失败</div>'}
}
async function renderPolicyGate(silent){
  const card=document.getElementById('policyCard');if(!card)return;
  try{
    const d=await api('/api/policy_gate');
    const cnt=document.getElementById('policyCnt');
    if(cnt)cnt.textContent=`FLAG ${d.flag_total} · 待复核 ${d.manual_pending}`;
    const rows=(d.recent||[]).map(r=>`<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px">
      <span>${esc(r.topic||'—')} <span class="hint">${esc((r.title||'').slice(0,40))}</span></span>
      <span style="white-space:nowrap"><span class="hint">${esc(r.stage||'')}</span> <b style="color:#f87171">${esc((r.rules||[]).join(','))}</b></span></div>`).join('');
    card.innerHTML=`<div style="display:flex;gap:24px;margin-bottom:8px">
      <div><div class="ypp-num" style="font-size:24px">${d.flag_total}</div><div class="ypp-sub">累计 FLAG</div></div>
      <div><div class="ypp-num" style="font-size:24px">${d.manual_pending}</div><div class="ypp-sub">待人工复核</div></div></div>
      ${rows?'<div style="margin-top:4px">'+rows+'</div>':'<div class="hint">暂无 FLAG 记录 · 门运行正常</div>'}`;
  }catch(e){if(!silent)card.innerHTML='<div class="hint">加载失败</div>'}
}
async function renderDouyin(silent){
  const card=document.getElementById('douyinCard');if(!card)return;
  try{
    const d=await api('/api/douyin');
    const cnt=document.getElementById('douyinCnt');
    if(cnt)cnt.textContent=`回齐 ${d.collected}/${d.total}`;
    const names={up:'上集',mid:'中集',down:'下集'};
    const bars=Object.keys(names).map(ep=>{const e=d.episodes[ep]||{total:0,collected:0,failed:0};
      const pct=e.total?Math.round(e.collected/e.total*100):0;
      return `<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
        <span>${names[ep]} <span class="hint">${e.collected}/${e.total}</span></span>
        ${e.failed?`<b style="color:#f87171">失败 ${e.failed}</b>`:''}</div>
        <div class="ypp-bar" style="margin-top:0"><i style="width:${pct}%"></i></div></div>`}).join('');
    const fails=(d.failed||[]).map(f=>`<div style="font-size:12px;color:#f87171;padding:4px 0">✗ ${esc(f.shot)} <span class="hint">${esc(f.error||'')}</span></div>`).join('');
    const gen=d.prompt_gen&&d.prompt_gen.available?'<span class="ok">✓ prompt 生成机制已就绪（douyin_prompt.py · dark_archive）</span>':'<span class="hint">prompt 生成机制未就绪</span>';
    card.innerHTML=bars+fails+`<div style="margin-top:8px;font-size:12px">${gen}</div>`;
  }catch(e){if(!silent)card.innerHTML='<div class="hint">加载失败</div>'}
}
async function showStageLogs(stageId){
  const meta=STAGE_META[stageId]||[stageId,stageId,0];
  let m=document.getElementById('stageLogModal');
  if(!m){
    m=document.createElement('div');m.id='stageLogModal';
    m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
    m.innerHTML='<div style="background:#0f172a;border:1px solid #334155;border-radius:12px;max-width:640px;width:100%;max-height:80vh;overflow:auto;padding:20px;color:#e2e8f0"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><h3 id="slmTitle" style="margin:0"></h3><button onclick="document.getElementById(\'stageLogModal\').style.display=\'none\'" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:6px 14px;cursor:pointer">关闭 · Close</button></div><div id="slmBody"></div></div>';
    document.body.appendChild(m);
  }
  m.style.display='flex';
  document.getElementById('slmTitle').textContent=meta[0]+' · 最近运行';
  document.getElementById('slmBody').innerHTML='<div class="hint">加载中…</div>';
  try{
    const d=await api('/api/oa/stage_logs?stage='+stageId);
    document.getElementById('slmBody').innerHTML=d.count?d.logs.map(l=>'<div style="background:#1e293b;border-radius:8px;padding:10px 12px;margin-bottom:8px"><div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:'+(l.status==='ok'?'#4ade80':'#f87171')+'">'+(l.status==='ok'?'✓ 正常':'✗ 异常')+'</span><span style="color:#64748b;font-size:12px">'+(l.at?l.at.slice(0,19).replace('T',' '):'')+'</span></div><div>'+esc(l.detail||'(无详情)')+'</div><div style="color:#64748b;font-size:12px;margin-top:4px">数量: '+(l.count||0)+'</div></div>').join(''):'<div class="hint">暂无运行记录</div>';
  }catch(e){document.getElementById('slmBody').innerHTML='<div class="hint">加载失败</div>'}
}
async function renderCharts(){
  const blk=document.getElementById('chartsBlock'),grid=document.getElementById('chartsGrid');
  if(!blk||!grid)return;
  try{
    const d=await api('/api/oa/charts');
    let html='';
    if(d.daily_output&&d.daily_output.length){
      const max=Math.max.apply(null,d.daily_output.map(x=>x.count).concat([1]));
      html+='<div class="stage-card"><div class="stage-name">📊 近14天日产量 <span class="en">Daily Output</span></div><div style="display:flex;align-items:flex-end;gap:4px;height:90px;margin:10px 0">'+d.daily_output.map(x=>'<div title="'+x.day+': '+x.count+'" style="flex:1;background:#3b82f6;border-radius:3px 3px 0 0;height:'+(Math.round(x.count/max*80)+4)+'px;min-width:8px"></div>').join('')+'</div><div class="stage-foot">'+d.daily_output[0].day+' ~ '+d.daily_output[d.daily_output.length-1].day+'</div><div class="stage-foot" style="margin-top:6px">每天通过选题评审进入生成的视频数<br>Videos passing review per day</div></div>';
    }
    html+='<div class="stage-card"><div class="stage-name">✅ QC 通过率 <span class="en">QC Pass Rate</span></div><div style="font-size:32px;font-weight:700;color:#4ade80;margin:12px 0">'+(d.qc_rate||0)+'%</div><div class="stage-foot">共 '+(d.qc_total||0)+' 次检查</div><div class="stage-foot" style="margin-top:6px">自动质检通过比例，低说明生成质量有问题<br>Auto-QC pass rate</div></div>';
    if(d.views_trend&&d.views_trend.length){
      const max=Math.max.apply(null,d.views_trend.map(x=>x.views).concat([1]));
      html+='<div class="stage-card"><div class="stage-name">👁 近14天播放趋势 <span class="en">Views Trend</span></div><div style="display:flex;align-items:flex-end;gap:3px;height:90px;margin:10px 0">'+d.views_trend.map(x=>'<div title="'+x.day+': '+x.views+' views" style="flex:1;background:#8b5cf6;border-radius:3px 3px 0 0;height:'+(Math.round(x.views/max*80)+4)+'px;min-width:8px"></div>').join('')+'</div><div class="stage-foot" style="margin-top:6px">每天新发布视频的播放量，越高越受欢迎<br>Daily views of new videos</div></div>';
    }
    if(html){grid.innerHTML=html;blk.style.display='block'}
  }catch(e){}
}
function timeAgo(iso){
  try{const t=new Date(iso).getTime(),d=Date.now()-t;if(d<0)return'刚刚';
    const m=Math.floor(d/60000);if(m<1)return'刚刚';if(m<60)return`${m} 分钟前 · ${m}m ago`;
    const h=Math.floor(m/60);if(h<24)return`${h} 小时前 · ${h}h ago`;return`${Math.floor(h/24)} 天前`}catch(e){return iso}
}
const LOG_TABS=[['all','全部 · All'],['mcp','MCP Server'],['watchdog','Watchdog'],['tunnel','SSH Tunnel'],['poller','WS Poller']];
let curLogTab='all';
function renderLogTabs(){
  document.getElementById('logTabs').innerHTML=LOG_TABS.map(([id,l])=>`<button class="${id===curLogTab?'active':''}" onclick="setLogTab('${id}')">${l}</button>`).join('');
}
function setLogTab(id){curLogTab=id;renderLogTabs();loadLogs()}
async function loadLogs(silent){
  const sync=document.getElementById('logSync');
  if(sync&&!silent){sync.textContent='同步中 · Syncing';sync.classList.add('syncing')}
  try{
    const d=await api('/api/logs?source='+curLogTab+'&lines=120');
    const box=document.getElementById('logBox');
    const names={mcp:'MCP Server',watchdog:'Watchdog',tunnel:'SSH Tunnel',poller:'WS Poller'};
    let html='';
    for(const [sid,txt] of Object.entries(d.logs||{})){
      const lines=String(txt||'').split('\n').filter(l=>l.trim());
      html+=`<div class="log-src">[${names[sid]||sid}]<span class="t">${esc(d.at||'')}</span></div>`;
      html+=lines.map(l=>`<div class="log-line"><span class="lbl">[${names[sid]||sid}]</span> ${esc(l)}</div>`).join('');
    }
    box.innerHTML=html||'<div class="hint">(空)</div>';
    box.scrollTop=box.scrollHeight;
    if(sync){sync.textContent='刷新于 '+d.at;sync.classList.remove('syncing')}
  }catch(e){if(sync){sync.textContent='同步失败';sync.classList.remove('syncing')}}
}
function renderTenantTable(){
  const el=document.getElementById('tmTable');if(!el)return;
  const rows=Object.values(TENANTS).map(t=>{
    const q=t.quota||{};const qv=q.videos_per_day??10;
    return `<tr><td>${esc(t.name||t.id)}<br><span class="hint mono">${esc(t.youtube_channel_id||'')}</span></td>
    <td class="plan-mono">${esc(t.plan||'')}</td>
    <td><span class="badge ${t.status==='active'?'active':'suspended'}">${t.status==='active'?'ACTIVE':'SUSPENDED'}</span></td>
    <td><span id="q-${esc(t.id)}">${qv} / 10</span> <button class="op-btn" onclick="editQuota('${esc(t.id)}')">编辑额度</button></td>
    <td class="hint">${esc(t.created||'')}</td>
    <td><button class="op-btn" onclick="toggleTenant('${esc(t.id)}')">${t.status==='active'?'暂停':'启用'}</button><button class="op-btn del" ${t.id==='default'?'disabled':''} onclick="askDel('${esc(t.id)}')">删除</button></td></tr>`;
  }).join('');
  el.innerHTML=`<table class="tm"><tr><th>租户</th><th>套餐</th><th>状态</th><th>额度</th><th>创建日期</th><th>操作</th></tr>${rows}</table>`;
}
function editQuota(id){
  const el=document.getElementById('q-'+id);
  const cur=(TENANTS[id].quota||{}).videos_per_day??10;
  el.innerHTML=`<input class="set-num" id="qi-${id}" type="number" value="${cur}" style="width:60px"> <button class="op-btn" onclick="saveQuota('${id}')">完成</button>`;
}
async function saveQuota(id){
  const v=parseInt(document.getElementById('qi-'+id).value)||10;
  await api('/api/tenant/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,quota:v})});
  TENANTS[id].quota={videos_per_day:v};renderTenantTable();toast('额度已更新');
}
async function toggleTenant(id){
  const ns=TENANTS[id].status==='active'?'suspended':'active';
  await api('/api/tenant/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,status:ns})});
  TENANTS[id].status=ns;renderTenantTable();render();
}
let delId=null;
function askDel(id){delId=id;openModal('mDel')}
async function delTenantGo(){
  await api('/api/tenant/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:delId})});
  delete TENANTS[delId];closeModal('mDel');renderTenantTable();toast('已删除');
}
async function addTenant(){
  const name=document.getElementById('ntName').value.trim(),ch=document.getElementById('ntCh').value.trim(),plan=document.getElementById('ntPlan').value;
  if(!name){toast('请填写租户名称');return}
  const r=await api('/api/tenant/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,channel_id:ch,plan})});
  if(r.ok){const t=await api('/api/tenants');TENANTS=t.tenants||{};closeModal('mAdd');render();toast('租户已添加')}
  else toast(r.error||'添加失败');
}
function openModal(id){document.getElementById(id).classList.add('open')}
function closeModal(id){document.getElementById(id).classList.remove('open')}
let termHist=[],termHi=-1,termBusy=false;
function toggleTerm(){
  const p=document.getElementById('termPanel'),b=document.getElementById('termBtn');
  p.classList.toggle('open');b.classList.toggle('active');
  if(p.classList.contains('open'))setTimeout(()=>document.getElementById('termIn').focus(),100);
}
function ackWarn(){localStorage.setItem(LS_WARN,'1');document.getElementById('warnBar').style.display='none'}
function clearTerm(){document.getElementById('termOut').innerHTML=''}
function bindTermInput(){
  const inp=document.getElementById('termIn');if(!inp||inp._bound)return;inp._bound=true;
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter')runTerm();
    if(e.key==='ArrowUp'){e.preventDefault();if(termHist.length){termHi=Math.max(0,termHi-1);inp.value=termHist[termHi]||''}}
    if(e.key==='ArrowDown'){e.preventDefault();if(termHist.length){termHi=Math.min(termHist.length,termHi+1);inp.value=termHist[termHi]||''}}
  });
}
function termPrint(html){const t=document.getElementById('termOut');t.insertAdjacentHTML('beforeend',html);t.scrollTop=t.scrollHeight}
async function runTerm(){
  if(termBusy)return;
  const inp=document.getElementById('termIn'),cmd=inp.value.trim();
  if(!cmd)return;
  termHist.push(cmd);termHi=termHist.length;inp.value='';termBusy=true;
  termPrint(`<div class="cmd"><span class="prompt">perpetua:/home/hatch/data$</span> ${esc(cmd)}</div>`);
  termPrint(`<div class="running" id="termRun">running…</div>`);
  try{
    const r=await api('/api/exec',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});
    document.getElementById('termRun')?.remove();
    if(r.blocked)termPrint(`<pre style="color:var(--red)">${esc(r.output)}</pre><div class="exit-bad">exit 126 · BLOCKED</div>`);
    else{termPrint(`<pre>${esc(r.output||'(无输出)')}${r.truncated?'\n...[truncated]':''}</pre><div class="${r.exit_code===0?'exit-ok':'exit-bad'}">exit ${r.exit_code}</div>`)}
}catch(e){document.getElementById('termRun')?.remove();termPrint(`<div class="exit-bad">请求失败</div>`)}
termBusy=false;
}
let chatOpened=false;
function toggleChat(){
const p=document.getElementById('chatPanel');p.classList.toggle('open');
if(p.classList.contains('open')&&!chatOpened){chatOpened=true;
addMsg('a','Perpetua','你好，我可以查询 YPP、配额、健康状态和日志，也能执行热点检测等操作。Hi — ask about YPP, quota, system health, logs, or run an operation.');}
}
function addMsg(who,name,text){
const h=document.getElementById('chatHist');
h.insertAdjacentHTML('beforeend',`<div class="msg ${who}"><div class="who">${esc(name)}</div><div class="b">${esc(text)}</div></div>`);
h.scrollTop=h.scrollHeight;
}
async function sendChat(){
const inp=document.getElementById('chatIn'),msg=inp.value.trim();
if(!msg)return;inp.value='';
addMsg('u','You',msg);
const h=document.getElementById('chatHist');
h.insertAdjacentHTML('beforeend','<div class="typing" id="ctyp"><i></i><i></i><i></i></div>');h.scrollTop=h.scrollHeight;
try{
const r=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
document.getElementById('ctyp')?.remove();
addMsg('a','Perpetua',r.reply||'(无回复)');
}catch(e){document.getElementById('ctyp')?.remove();addMsg('a','Perpetua','请求失败，请稍后重试。')}
}
boot();