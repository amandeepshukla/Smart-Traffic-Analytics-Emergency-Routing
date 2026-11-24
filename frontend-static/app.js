/* Smart Traffic dashboard — dependency-free build for static hosting.
   Talks to the FastAPI backend via WebSocket (falls back to polling). */
(() => {
  'use strict';
  const API = ((window.APP_CONFIG || {}).API_URL || '').replace(/\/$/, '');
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const COLOR = { free: '#22c55e', moderate: '#eab308', heavy: '#f97316', gridlock: '#ef4444', unknown: '#64748b' };
  const levelOf = (c) => (c == null ? 'unknown' : c < 0.3 ? 'free' : c < 0.6 ? 'moderate' : c < 0.85 ? 'heavy' : 'gridlock');
  const colorOf = (c) => COLOR[levelOf(c)];
  const pct = (c) => (c == null ? '—' : Math.round(c * 100) + '%');
  const fmtTime = (s) => {
    if (s == null) return '—';
    const m = Math.floor(s / 60), sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`;
  };

  // ---------------------------------------------------------------- api
  async function req(path, opts = {}) {
    const res = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (!res.ok) {
      let d = res.statusText;
      try { d = (await res.json()).detail || d; } catch (_) { /* ignore */ }
      throw new Error(typeof d === 'string' ? d : JSON.stringify(d));
    }
    return res.json();
  }
  const post = (p, body) => req(p, { method: 'POST', body: JSON.stringify(body) });

  // -------------------------------------------------------------- state
  let state = null, selected = null, selectedRendered = null, camsBuilt = false, formBuilt = false;
  let previewKey = '', previewSeq = 0, previewError = false;

  let toastTimer;
  function toast(msg, kind = 'ok') {
    const t = $('#toast');
    t.textContent = msg; t.className = 'toast ' + kind;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), 3500);
  }
  const guard = (fn, ok) => async () => { try { await fn(); ok && toast(ok); } catch (e) { toast(e.message, 'err'); } };

  // ----------------------------------------------------------- rendering
  function renderKpis(s) {
    const kpi = (label, value, sub, color) =>
      `<div class="kpi"><span class="kpi-label">${label}</span><strong${color ? ` style="color:${color}"` : ''}>${value}</strong>${sub ? `<small>${sub}</small>` : ''}</div>`;
    $('#kpis').innerHTML =
      kpi('Cameras online', `${s.cameras_online}/${s.cameras_total}`, s.cameras_offline ? `${s.cameras_offline} offline` : 'all healthy', s.cameras_offline ? COLOR.heavy : '') +
      kpi('City congestion', pct(s.avg_congestion), s.avg_level, COLOR[s.avg_level]) +
      kpi('Vehicles in view', s.vehicles_in_view, 'across all feeds') +
      kpi('Active ambulances', s.active_missions, '', s.active_missions ? '#ef4444' : '') +
      kpi('Closed junctions', s.closed_junctions, '');
  }

  function renderMap() {
    const nodes = Object.fromEntries(state.nodes.map((n) => [n.id, n]));
    const active = state.missions.filter((m) => m.status === 'enroute');
    let svg = '<svg class="map" viewBox="0 0 100 70" role="img" aria-label="Live road network map">';
    svg += '<defs><pattern id="grid" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M5 0H0V5" fill="none" stroke="#1b2433" stroke-width="0.15"/></pattern></defs><rect width="100" height="70" fill="url(#grid)"/>';
    for (const e of state.edges) {
      const a = nodes[e.a], b = nodes[e.b];
      svg += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#0b0f17" stroke-width="1.9" stroke-linecap="round"/>` +
             `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${colorOf(e.congestion)}" stroke-width="1.05" stroke-linecap="round" opacity="0.92"/>`;
    }
    for (const m of active) {
      if (m.baseline_path.join() !== m.path.join())
        svg += `<polyline class="route-baseline" points="${m.baseline_path.map((id) => nodes[id].x + ',' + nodes[id].y).join(' ')}"/>`;
    }
    for (const m of active) {
      const pts = [m.position.x + ',' + m.position.y, ...m.path.slice(1).map((id) => nodes[id].x + ',' + nodes[id].y)].join(' ');
      svg += `<polyline class="route-glow" points="${pts}"/><polyline class="route-line" points="${pts}"/>`;
    }
    for (const n of state.nodes) {
      const col = COLOR[n.level] || COLOR.unknown, offline = n.camera_status === 'offline';
      svg += `<g class="node" data-id="${n.id}" tabindex="0">`;
      if (selected === n.id) svg += `<circle cx="${n.x}" cy="${n.y}" r="4.6" class="sel-ring"/>`;
      if (n.kind === 'hospital') {
        svg += `<rect x="${n.x - 3}" y="${n.y - 3}" width="6" height="6" rx="1.4" fill="#0f172a" stroke="${col}" stroke-width="0.7"/>` +
               `<path d="M${n.x - 0.5} ${n.y - 1.8}h1v1.3h1.3v1h-1.3v1.3h-1v-1.3h-1.3v-1h1.3z" fill="#38bdf8"/>`;
      } else {
        svg += `<circle cx="${n.x}" cy="${n.y}" r="2.5" fill="#0f172a" stroke="${col}" stroke-width="0.8"${offline ? ' stroke-dasharray="0.8 0.8"' : ''}/>` +
               `<circle cx="${n.x}" cy="${n.y}" r="1.1" fill="${col}" opacity="${offline ? 0.3 : 1}"/>`;
      }
      if (n.closed) svg += `<path d="M${n.x - 2} ${n.y - 2}l4 4m0 -4l-4 4" stroke="#ef4444" stroke-width="0.9" stroke-linecap="round"/>`;
      svg += `<text x="${n.x}" y="${n.y + 6.2}" class="node-label">${esc(n.name)}</text><text x="${n.x}" y="${n.y - 4.2}" class="node-id">${n.id}</text></g>`;
    }
    for (const m of active) {
      svg += `<g class="amb" transform="translate(${m.position.x} ${m.position.y})"><circle r="4.2" class="amb-pulse"/><circle r="2.6" fill="#ef4444" stroke="#fff" stroke-width="0.5"/><path d="M-1.4 -0.45h1v-1h0.8v1h1v0.8h-1v1h-0.8v-1h-1z" fill="#fff"/></g>`;
    }
    $('#map').innerHTML = svg + '</svg>';
  }

  function renderMissions() {
    const nodes = Object.fromEntries(state.nodes.map((n) => [n.id, n]));
    const ms = state.missions;
    $('#missionCount').textContent = ms.filter((m) => m.status === 'enroute').length + ' active';
    if (!ms.length) { $('#missions').innerHTML = '<p class="muted">No ambulances on the road. Dispatch one to see live re-routing.</p>'; return; }
    $('#missions').innerHTML = '<ul class="missions">' + ms.map((m) => `
      <li class="mission ${m.status}">
        <div class="mission-top"><span class="mission-route">${esc(nodes[m.origin]?.name || m.origin)} <i>→</i> ${esc(m.destination_name)}</span>
          <button class="icon-btn" data-cancel="${m.id}" aria-label="Remove mission">✕</button></div>
        ${m.status === 'arrived'
          ? `<p class="arrived">✔ Arrived in ${fmtTime(m.elapsed_s)} (sim time)</p>`
          : `<div class="mission-stats"><div><b>${fmtTime(m.eta_s)}</b><span>ETA</span></div><div><b>${m.remaining_km} km</b><span>left</span></div>
             <div><b>${m.reroutes}</b><span>reroutes</span></div><div><b>${m.waiting_s > 0 ? Math.ceil(m.waiting_s) + 's' : '—'}</b><span>at signal</span></div></div>`}
        ${m.time_saved_s > 1 ? `<p class="saved">⚡ saved ${fmtTime(m.time_saved_s)} vs shortest route</p>` : ''}
        <ul class="events">${m.events.slice(-3).map((e) => `<li>${esc(e.msg)}</li>`).join('')}</ul>
      </li>`).join('') + '</ul>';
  }

  function renderCams() {
    const grid = $('#cams');
    if (!camsBuilt) {
      grid.innerHTML = state.cameras.map((c) => `
        <button class="cam-card" data-cam="${c.node_id}">
          <div class="cam-thumb"><img alt="Camera ${c.node_id}" loading="lazy"><span class="cam-badge"></span></div>
          <div class="cam-meta"><span class="cam-name"><b>${c.node_id}</b> ${esc(c.name)}</span><span class="cam-stat"></span></div>
          <div class="cam-bar"><i></i></div>
        </button>`).join('');
      camsBuilt = true;
      refreshThumbs();
    }
    const label = { online: 'LIVE', calibrating: 'CALIBRATING', offline: 'OFFLINE' };
    for (const c of state.cameras) {
      const el = $(`[data-cam="${c.node_id}"]`, grid);
      if (!el) continue;
      const col = COLOR[c.level] || COLOR.unknown;
      el.classList.toggle('is-selected', selected === c.node_id);
      el.classList.toggle('st-offline', c.status === 'offline');
      const badge = $('.cam-badge', el);
      badge.className = 'cam-badge ' + c.status; badge.textContent = label[c.status] || c.status;
      const stat = $('.cam-stat', el);
      stat.style.color = col; stat.textContent = `${c.count == null ? '—' : c.count + ' veh'} · ${pct(c.congestion)}`;
      const bar = $('.cam-bar i', el);
      bar.style.width = Math.round((c.congestion ?? 0) * 100) + '%'; bar.style.background = col;
    }
  }

  function refreshThumbs() {
    document.querySelectorAll('[data-cam] img').forEach((img) => {
      const id = img.closest('[data-cam]').dataset.cam;
      const url = `${API}/api/cameras/${id}/snapshot.jpg?t=${Date.now()}`;
      const pre = new Image();
      pre.onload = () => { img.src = url; };
      pre.src = url;
    });
  }
  setInterval(refreshThumbs, 1500);

  function renderNodePanel() {
    const host = $('#nodePanel');
    const n = selected && state.nodes.find((x) => x.id === selected);
    if (!n) { host.innerHTML = ''; selectedRendered = null; return; }
    const cam = state.cameras.find((c) => c.node_id === n.id) || {};
    if (selectedRendered !== n.id) { // build the shell (and the MJPEG <img>) only when the selection changes
      host.innerHTML = `<section class="panel node-panel">
        <header class="panel-h"><h2>${n.id} · ${esc(n.name)}</h2><button class="icon-btn" data-close aria-label="Close">✕</button></header>
        <div class="stream"><img alt="Live feed ${n.id}" src="${API}/api/cameras/${n.id}/stream"></div>
        <dl class="metrics"></dl><div class="lanes"></div><div class="btn-row"></div></section>`;
      selectedRendered = n.id;
    }
    const col = COLOR[cam.level] || COLOR.unknown, offline = cam.status === 'offline', jammed = state.overrides[n.id] != null;
    $('.metrics', host).innerHTML =
      `<div><dt>Vehicles</dt><dd>${cam.count ?? '—'}</dd></div><div><dt>Congestion</dt><dd style="color:${col}">${pct(cam.congestion)}</dd></div>` +
      `<div><dt>Flow</dt><dd>${cam.flow_per_min != null ? cam.flow_per_min + '/min' : '—'}</dd></div><div><dt>Detector</dt><dd class="small">${esc(cam.detector || '-')}</dd></div>`;
    $('.lanes', host).innerHTML = (cam.lane_density || []).map((d, i) =>
      `<div class="lane"><span>Lane ${i + 1}</span><div class="lane-bar"><i style="width:${d * 100}%;background:${d > 0.8 ? COLOR.gridlock : d > 0.5 ? COLOR.heavy : COLOR.free}"></i></div><span>${cam.lane_counts[i]}</span></div>`).join('');
    $('.btn-row', host).innerHTML =
      (n.kind === 'junction' ? `<button class="btn danger" data-act="from">🚑 Dispatch from here</button><button class="btn" data-act="close">${n.closed ? 'Reopen junction' : 'Close junction'}</button>` : '') +
      `<button class="btn" data-act="jam">${jammed ? 'Clear jam' : 'Simulate jam'}</button><button class="btn" data-act="cam">${offline ? 'Restore camera' : 'Kill camera'}</button>`;
  }

  // --------------------------------------------------------- dispatch form
  function buildForm() {
    $('#origin').innerHTML += state.nodes.filter((n) => n.kind === 'junction').map((n) => `<option value="${n.id}">${n.id} · ${esc(n.name)}</option>`).join('');
    $('#dest').innerHTML += state.nodes.filter((n) => n.kind === 'hospital').map((n) => `<option value="${n.id}">${n.id} · ${esc(n.name)}</option>`).join('');
    formBuilt = true;
  }

  async function updatePreview() {
    const origin = $('#origin').value, dest = $('#dest').value;
    const box = $('#preview'), btn = $('#dispatchBtn');
    const key = [origin, dest, state.closures.join(',')].join('|');
    if (!origin) { box.classList.add('hidden'); btn.disabled = true; previewKey = ''; return; }
    if (key === previewKey) return;
    previewKey = key;
    const id = ++previewSeq;
    try {
      const r = await req(`/api/route?source=${origin}${dest ? '&destination=' + dest : ''}`);
      if (id !== previewSeq) return;
      const o = r.optimal;
      box.innerHTML = `<div class="preview-main"><strong>${fmtTime(o.eta_s)}</strong><span>${o.distance_km} km · ${o.path.length - 1} roads</span></div>
        <p class="route-names">${o.path_names.map(esc).join(' → ')}</p>${r.time_saved_s > 1 ? `<p class="saved">⚡ ${fmtTime(r.time_saved_s)} faster than the shortest-distance route</p>` : ''}`;
      previewError = false; btn.disabled = false;
    } catch (e) {
      if (id !== previewSeq) return;
      box.innerHTML = `<p class="err">${esc(e.message)}</p>`; previewError = true; btn.disabled = true;
    }
    box.classList.remove('hidden');
  }

  // ------------------------------------------------------------ main loop
  function render() {
    if (!state) return;
    $('#resetBtn').classList.remove('hidden');
    $('#banner').classList.add('hidden');
    if (!formBuilt) buildForm();
    renderKpis(state.summary); renderMap(); renderMissions(); renderCams(); renderNodePanel(); updatePreview();
  }

  function setStatus(kind, text) {
    $('#pill').className = 'pill ' + kind; $('#pillText').textContent = text;
    if (kind === 'offline' && !state) {
      const b = $('#banner');
      b.innerHTML = 'Cannot reach the backend at <code>' + esc(API || location.origin) + '</code>. Check <code>config.js</code> (API_URL) and that the API is running.';
      b.classList.remove('hidden');
    }
  }

  let pollTimer, ws, retries = 0;
  async function poll() {
    try { state = await req('/api/state'); setStatus('polling', 'Live · polling'); render(); }
    catch (_) { setStatus('offline', 'Backend offline'); }
  }
  const startPolling = () => { if (!pollTimer) { poll(); pollTimer = setInterval(poll, 2000); } };
  const stopPolling = () => { clearInterval(pollTimer); pollTimer = null; };

  function connect() {
    try { ws = new WebSocket((API || location.origin).replace(/^http/, 'ws') + '/ws'); } catch (_) { startPolling(); return; }
    ws.onopen = () => { retries = 0; stopPolling(); setStatus('live', 'Live · websocket'); };
    ws.onmessage = (e) => { try { state = JSON.parse(e.data); setStatus('live', 'Live · websocket'); render(); } catch (_) { /* ignore */ } };
    ws.onclose = () => { startPolling(); retries += 1; setTimeout(connect, Math.min(15000, 1000 * 2 ** retries)); };
    ws.onerror = () => ws.close();
  }

  // ------------------------------------------------------------- events
  $('#origin').addEventListener('change', updatePreview);
  $('#dest').addEventListener('change', updatePreview);
  $('#dispatchBtn').addEventListener('click', guard(() =>
    post('/api/dispatch', { origin: $('#origin').value, destination: $('#dest').value || null, sim_speed: Number($('#speed').value) }), 'Ambulance dispatched'));
  $('#resetBtn').addEventListener('click', guard(() => post('/api/simulate/reset', {}), 'Demo reset'));

  const select = (id) => { selected = id === selected ? null : id; if (state) { renderMap(); renderCams(); renderNodePanel(); } };
  $('#map').addEventListener('click', (e) => { const g = e.target.closest('.node'); if (g) select(g.dataset.id); });
  $('#map').addEventListener('keydown', (e) => { const g = e.target.closest('.node'); if (g && e.key === 'Enter') select(g.dataset.id); });
  $('#cams').addEventListener('click', (e) => { const c = e.target.closest('[data-cam]'); if (c) select(c.dataset.cam); });
  $('#missions').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cancel]');
    if (b) guard(() => req('/api/missions/' + b.dataset.cancel, { method: 'DELETE' }))();
  });
  $('#nodePanel').addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) return select(selected);
    const b = e.target.closest('[data-act]');
    if (!b || !selected) return;
    const n = state.nodes.find((x) => x.id === selected), cam = state.cameras.find((c) => c.node_id === selected) || {};
    const act = b.dataset.act;
    if (act === 'from') { $('#origin').value = selected; updatePreview(); }
    else if (act === 'close') guard(() => (n.closed ? req('/api/closures/' + selected, { method: 'DELETE' }) : post('/api/closures', { node_id: selected })), n.closed ? 'Junction reopened' : 'Junction closed — routes will avoid it')();
    else if (act === 'jam') guard(() => post('/api/simulate/congestion', { node_id: selected, level: state.overrides[selected] != null ? null : 0.95 }))();
    else if (act === 'cam') guard(() => post('/api/simulate/camera', { node_id: selected, online: cam.status === 'offline' }))();
  });

  connect();
})();
