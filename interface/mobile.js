(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path, options={}) {
    const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
    const text = await r.text();
    let body;
    try { body = JSON.parse(text); } catch { body = {detail:text}; }
    if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
    return body;
  }
  function setHealth(ok, text) {
    $('healthDot').className = `dot ${ok ? 'ok' : 'bad'}`;
    $('healthText').textContent = text;
  }
  function pill(text, cls='') { return `<span class="pill ${cls}">${esc(text)}</span>`; }
  async function command(payload) {
    return api('/api/command', {method:'POST', body:JSON.stringify({...payload, operator_quote:'mobile surface'})});
  }
  async function ack(id) {
    await api('/api/notifications/ack', {method:'POST', body:JSON.stringify({id})});
    await loadNotifications();
  }
  async function decide(id, decision) {
    const kind = decision === 'APPROVED' ? 'approve' : 'deny';
    const payload = kind === 'approve' ? {kind, id} : {kind, id, because:'operator denied from mobile surface'};
    const out = await command(payload);
    $('quickResult').textContent = out.detail || out.outcome;
    await Promise.all([loadApprovals(), loadStatus()]);
  }
  async function loadStatus() {
    try {
      const [s, sync, unread] = await Promise.all([
        api('/api/status'), api('/api/sync'), api('/api/notifications?state=UNREAD')
      ]);
      setHealth(true, s.halted ? 'Core reachable · HALTED' : 'Core reachable');
      $('metricTasks').textContent = s.tasks?.live ?? '0';
      $('metricApprovals').textContent = (s.approvals_pending || []).length;
      $('metricAlerts').textContent = unread.length;
      $('metricSync').textContent = sync.pull?.ok === false ? 'ERR' : (sync.enabled ? 'ON' : 'OFF');
      $('haltBtn').disabled = !!s.halted;
      $('resumeBtn').disabled = !s.halted;
    } catch (e) {
      setHealth(false, `Core unavailable · ${e.message}`);
      ['metricTasks','metricApprovals','metricAlerts','metricSync'].forEach(id => $(id).textContent='—');
    }
  }
  async function loadState() {
    try {
      const s = await api('/api/state');
      const blocks = [];
      const focus = s.focus || s.active_focus || s.current_focus;
      if (focus) blocks.push(`<div class="item"><div class="muted small">Focus</div><strong>${esc(typeof focus === 'string' ? focus : JSON.stringify(focus))}</strong></div>`);
      if (Array.isArray(s.attention) && s.attention.length) {
        blocks.push(`<div class="item"><div class="muted small">Attention</div>${s.attention.map(x=>`<div>${esc(x.title || x.description || x.id || JSON.stringify(x))}</div>`).join('')}</div>`);
      }
      if (Array.isArray(s.waiting) && s.waiting.length) {
        blocks.push(`<div class="item"><div class="muted small">Waiting</div>${s.waiting.slice(0,8).map(x=>`<div>${esc(x.title || x.description || x.id || JSON.stringify(x))}</div>`).join('')}</div>`);
      }
      $('stateBox').innerHTML = blocks.join('') || `<pre class="small mono muted">${esc(JSON.stringify(s,null,2))}</pre>`;
    } catch(e) { $('stateBox').innerHTML = `<div class="error">${esc(e.message)}</div>`; }
  }
  async function loadNotifications() {
    try {
      const items = await api('/api/notifications');
      if (!items.length) { $('notificationsBox').innerHTML='<div class="empty">No notifications.</div>'; return; }
      $('notificationsBox').innerHTML = items.slice(0,100).map(n => {
        const cls = n.priority === 'IMPORTANT' ? 'important' : '';
        return `<div class="item"><div class="row"><strong>${esc(n.title)}</strong>${pill(n.priority || n.state, cls)}</div><div class="small muted">${esc(n.body || '')}</div><div class="row" style="margin-top:7px"><span class="small muted">${esc(n.source || '')}</span>${n.state==='UNREAD'?`<button class="secondary" data-ack="${esc(n.id)}">Acknowledge</button>`:''}</div></div>`;
      }).join('');
      document.querySelectorAll('[data-ack]').forEach(b => b.onclick=()=>ack(b.dataset.ack));
    } catch(e) { $('notificationsBox').innerHTML=`<div class="error">${esc(e.message)}</div>`; }
  }
  async function loadApprovals() {
    try {
      const items = (await api('/api/approvals')).filter(a => a.state === 'PENDING');
      if (!items.length) { $('approvalsBox').innerHTML='<div class="empty">Nothing waiting for approval.</div>'; return; }
      $('approvalsBox').innerHTML = items.map(a => `<div class="item"><div class="row"><strong>${esc(a.requested_action)}</strong>${pill(a.reversible?'reversible':'irreversible',a.reversible?'':'danger')}</div><div class="small muted">${esc(a.reason || '')}</div><div class="small muted" style="margin-top:4px">${esc(a.consequence || '')}</div><div class="actions" style="margin-top:9px"><button class="primary" data-approve="${esc(a.id)}">Approve</button><button class="danger" data-deny="${esc(a.id)}">Deny</button></div></div>`).join('');
      document.querySelectorAll('[data-approve]').forEach(b => b.onclick=()=>decide(b.dataset.approve,'APPROVED'));
      document.querySelectorAll('[data-deny]').forEach(b => b.onclick=()=>decide(b.dataset.deny,'DENIED'));
    } catch(e) { $('approvalsBox').innerHTML=`<div class="error">${esc(e.message)}</div>`; }
  }
  async function loadTasks() {
    try {
      const items = await api('/api/tasks');
      if (!items.length) { $('tasksBox').innerHTML='<div class="empty">No tasks.</div>'; return; }
      const live = items.filter(t => !['COMPLETED','CANCELLED','FAILED_TERMINAL'].includes(t.status));
      $('tasksBox').innerHTML = live.map(t => `<div class="item"><div class="row"><strong>${esc(t.description)}</strong>${pill(t.status,t.status==='BLOCKED'?'danger':'')}</div><div class="small muted mono">${esc(t.id)}</div>${t.result?`<div class="small muted">${esc(t.result)}</div>`:''}</div>`).join('') || '<div class="empty">No live tasks.</div>';
    } catch(e) { $('tasksBox').innerHTML=`<div class="error">${esc(e.message)}</div>`; }
  }
  async function loadAutomations() {
    try {
      const [schedules, runtime] = await Promise.all([api('/api/schedules'), api('/api/runtime')]);
      $('schedulesBox').innerHTML = schedules.length ? schedules.map(s=>`<div class="item"><div class="row"><strong>${esc(s.id)}</strong>${pill(s.enabled===false?'disabled':s.kind)}</div><div class="small muted mono">${esc(JSON.stringify(s.command || {}))}</div></div>`).join('') : '<div class="empty">No schedules.</div>';
      $('runtimeBox').textContent = JSON.stringify(runtime,null,2);
    } catch(e) { $('schedulesBox').innerHTML=`<div class="error">${esc(e.message)}</div>`; }
  }
  async function loadAll() {
    await Promise.allSettled([loadStatus(), loadState(), loadNotifications(), loadApprovals(), loadTasks(), loadAutomations()]);
  }
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#tabs button').forEach(x=>x.classList.toggle('active',x===b));
    document.querySelectorAll('section').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab));
  });
  document.querySelectorAll('[data-command]').forEach(b => b.onclick = async () => {
    try { const out=await command(JSON.parse(b.dataset.command)); $('quickResult').textContent=out.detail||out.outcome; }
    catch(e){ $('quickResult').textContent=e.message; }
  });
  $('haltBtn').onclick = async()=>{ try{const out=await command({kind:'halt',reason:'operator tapped HALT on mobile surface'});$('quickResult').textContent=out.detail;await loadStatus();}catch(e){$('quickResult').textContent=e.message;} };
  $('resumeBtn').onclick = async()=>{ try{const out=await command({kind:'resume'});$('quickResult').textContent=out.detail;await loadStatus();}catch(e){$('quickResult').textContent=e.message;} };
  $('quickNoteSend').onclick = async()=>{ const text=$('quickNote').value.trim(); if(!text)return; try{const out=await command({kind:'note',text});$('quickNote').value='';$('quickResult').textContent=out.detail; }catch(e){$('quickResult').textContent=e.message;} };
  $('runCommand').onclick = async()=>{
    const kind=$('commandKind').value.trim(); let args={};
    try { args=$('commandArgs').value.trim()?JSON.parse($('commandArgs').value):{}; const out=await command({kind,...args}); $('commandResult').className='small success'; $('commandResult').textContent=JSON.stringify(out); await loadAll(); }
    catch(e){ $('commandResult').className='small error'; $('commandResult').textContent=e.message; }
  };
  $('refresh').onclick=loadAll; $('alertsRefresh').onclick=loadNotifications;
  loadAll();
  setInterval(loadStatus, 15000);
})();
