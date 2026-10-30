async function api(path, body){
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)} : {});
  return r.json();
}
let curPage = null, types = {};
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function renderWidget(w, data){
  let body = '';
  if(w.type==='note'){ body = '<pre>'+esc(w.text||'(空文字卡片)')+'</pre>'; }
  else if(!data || data.ok===false){ body = '<p>unknown：'+esc((data&&data.error)||'读不到')+'</p>'; }
  else if(w.type==='services'){ body = '<p>'+data.up+' / '+data.total+' 在线</p>' + data.items.map(i=>'<div>'+esc(i.name)+' :'+i.port+' <span class="'+(i.up?'up':'down')+'">'+(i.up?'●在线':'○掉线')+'</span></div>').join(''); }
  else if(w.type==='disk'){ body = '<p>已用 '+data.used_pct+'% · 剩余 '+data.free_gb+' GB / 共 '+data.total_gb+' GB</p>'; }
  else if(w.type==='queue'){ body = '<pre>'+esc(JSON.stringify(data.by_status,null,2))+'</pre>' + (data.pending_sample||[]).map(p=>'<div>'+esc(p.queue_name||'')+' '+esc(p.event_type||'')+' '+esc(p.created_at||'')+'</div>').join(''); }
  else if(w.type==='decisions'){ body = '<p>共 '+data.total+' 条</p><pre>'+esc(JSON.stringify(data.by_status,null,2))+'</pre>' + (data.sample||[]).map(s=>'<div>'+esc(s.topic)+' ['+esc(s.status)+']</div>').join(''); }
  else if(w.type==='routine'){ body = (data.recent||[]).map(r=>'<div>['+esc(r.status)+'] '+esc(r.stage)+' '+esc(r.detail)+'</div>').join('') || '<p>暂无</p>'; }
  else if(w.type==='ypp'){ body = '<p>日期 '+esc(data.date)+' · 订阅 '+esc(data.subs)+'（差 '+esc(data.subs_gap)+'）</p><p>诊断观看 '+esc(data.watch_hours_diag)+' 小时</p><p style="color:#fbbf24">'+esc(data.warning)+'</p>'; }
  else { body = '<pre>'+esc(JSON.stringify(data,null,2))+'</pre>'; }
  return '<div class="card"><button class="del" data-wid="'+w.id+'">删</button><h3>'+esc(w.title)+'</h3>'+body+'<div class="src">来源：'+esc((data&&data.source)||'页面配置')+' · '+esc((data&&data.at)||'')+'</div></div>';
}
async function loadPage(id){
  const res = await api('/api/pages/get?id='+encodeURIComponent(id));
  if(!res.ok){ document.getElementById('center').innerHTML = '<p>页面不存在</p>'; return; }
  curPage = res.page;
  document.getElementById('shareHint').textContent = '本页链接：/pages?id='+curPage.id;
  for(const col of ['top','left','center','right']) document.getElementById(col).innerHTML = '';
  for(const w of curPage.widgets||[]){
    let data = null;
    if(w.type!=='note') data = await api('/api/pages/widget?type='+encodeURIComponent(w.type));
    document.getElementById(w.column||'center').innerHTML += renderWidget(w, data);
  }
  document.querySelectorAll('.del').forEach(b=>b.onclick=async()=>{
    await api('/api/pages/widget/delete', {page_id: curPage.id, widget_id: b.dataset.wid});
    loadPage(curPage.id);
  });
}
async function loadList(){
  const res = await api('/api/pages');
  types = res.widget_types||{};
  const sel = document.getElementById('pageSel');
  sel.innerHTML = (res.pages||[]).map(p=>'<option value="'+p.id+'">'+esc(p.title)+'</option>').join('');
  const wt = document.getElementById('wType');
  wt.innerHTML = Object.entries(types).map(([k,v])=>'<option value="'+k+'">'+esc(v)+'</option>').join('');
  const want = new URLSearchParams(location.search).get('id');
  const first = (res.pages||[]).find(p=>p.id===want) || (res.pages||[])[0];
  if(first){ sel.value = first.id; loadPage(first.id); }
  sel.onchange = ()=>loadPage(sel.value);
}
document.getElementById('btnRefresh').onclick = ()=>{ if(curPage) loadPage(curPage.id); };
document.getElementById('btnCreate').onclick = async()=>{
  const t = document.getElementById('newTitle').value.trim();
  const res = await api('/api/pages/create', {title: t});
  if(res.ok){ await loadList(); document.getElementById('pageSel').value = res.page.id; loadPage(res.page.id); }
};
document.getElementById('btnDelete').onclick = async()=>{
  if(!curPage) return;
  if(!confirm('删除页面「'+curPage.title+'」？')) return;
  await api('/api/pages/delete', {id: curPage.id}); await loadList();
};
document.getElementById('btnAdd').onclick = async()=>{
  if(!curPage) return;
  const res = await api('/api/pages/widget/add', {page_id: curPage.id, type: document.getElementById('wType').value, column: document.getElementById('wCol').value, text: document.getElementById('wText').value});
  if(res.ok) loadPage(curPage.id); else alert(res.error||'添加失败');
};
loadList();
