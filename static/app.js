// ---------------------------------------------------------------------
// View tabs (3D model / 2D stability diagram)
// ---------------------------------------------------------------------

document.querySelectorAll('.view-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`view-${tab.dataset.view}`).classList.add('active');
    if (tab.dataset.view === '3d' && window.RocketViewer) {
      // canvas was hidden (display:none) while sized, so re-measure on show
      setTimeout(() => window.RocketViewer.resize(), 0);
    }
  });
});

// ---------------------------------------------------------------------
// 3D viewer bootstrap
// ---------------------------------------------------------------------

let viewerReady = false;

function waitForViewer(retries = 40) {
  if (window.RocketViewer) {
    window.RocketViewer.init(document.getElementById('viewer-container'));
    viewerReady = true;
    pushPlaceholderRocket();
  } else if (retries > 0) {
    setTimeout(() => waitForViewer(retries - 1), 50);
  }
}
waitForViewer();

function currentBodyParams() {
  return {
    diameter_mm: parseFloat(document.getElementById('diameter_mm').value) || 98,
    nose_length_mm: parseFloat(document.getElementById('nose_length_mm').value) || 350,
    nose_type: document.getElementById('nose_type').value,
  };
}

function pushPlaceholderRocket() {
  // Shows a reasonable-looking rocket immediately, before the user has
  // run the optimizer, so the 3D view is never empty.
  if (!viewerReady) return;
  const body = currentBodyParams();
  const d = body.diameter_mm;
  const fin = {
    root_chord_mm: d * 1.6, tip_chord_mm: d * 0.6, span_mm: d * 1.0,
    sweep_mm: d * 0.9, thickness_mm: 3.5, count: parseInt(document.getElementById('fin_count').value, 10) || 3,
    position_from_nose_mm: parseFloat(document.getElementById('fin_position_mm').value) || 1350,
  };
  window.RocketViewer.update(body, fin);
}

function pushRocketFromResult(payload, data) {
  if (!viewerReady) return;
  const fg = data.fin_geometry_mm;
  window.RocketViewer.update(payload.body, {
    root_chord_mm: fg.root_chord_mm, tip_chord_mm: fg.tip_chord_mm, span_mm: fg.span_mm,
    sweep_mm: fg.sweep_mm, thickness_mm: fg.thickness_mm, count: fg.count,
    position_from_nose_mm: payload.fins.position_from_nose_mm,
  });
}

// keep the placeholder rocket in sync while the user is still setting up
// body/fin-count/position, before they've run an optimization
['diameter_mm', 'nose_length_mm', 'nose_type', 'fin_count', 'fin_position_mm'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => {
    if (!window.__hasOptimizedOnce) pushPlaceholderRocket();
  });
});

// ---------------------------------------------------------------------
// Viewer toolbar
// ---------------------------------------------------------------------

document.getElementById('vt-iso').addEventListener('click', () => window.RocketViewer && window.RocketViewer.setView('iso'));
document.getElementById('vt-front').addEventListener('click', () => window.RocketViewer && window.RocketViewer.setView('front'));
document.getElementById('vt-top').addEventListener('click', () => window.RocketViewer && window.RocketViewer.setView('top'));

const wireBtn = document.getElementById('vt-wire');
wireBtn.addEventListener('click', () => {
  if (!window.RocketViewer) return;
  const on = window.RocketViewer.toggleWireframe();
  wireBtn.classList.toggle('on', on);
});

const rotateBtn = document.getElementById('vt-rotate');
let autoRotateOn = false;
rotateBtn.addEventListener('click', () => {
  if (!window.RocketViewer) return;
  autoRotateOn = !autoRotateOn;
  window.RocketViewer.setAutoRotate(autoRotateOn);
  rotateBtn.classList.toggle('on', autoRotateOn);
});

// ---------------------------------------------------------------------
// Mass component rows
// ---------------------------------------------------------------------

const componentList = document.getElementById('component-list');

function addComponentRow(name = '', mass = '', cg = '') {
  const row = document.createElement('div');
  row.className = 'component-row';
  row.innerHTML = `
    <input type="text" placeholder="name" class="c-name" value="${name}">
    <input type="number" placeholder="mass g" class="c-mass" value="${mass}">
    <input type="number" placeholder="cg mm" class="c-cg" value="${cg}">
    <button type="button" class="btn btn-icon" title="remove">✕</button>
  `;
  row.querySelector('button').addEventListener('click', () => row.remove());
  componentList.appendChild(row);
}

// sensible defaults so the tool is immediately runnable
addComponentRow('nose + avionics', 240, 180);
addComponentRow('body / payload', 420, 700);
addComponentRow('motor', 350, 1320);

document.getElementById('add-component').addEventListener('click', () => addComponentRow());

// ---------------------------------------------------------------------
// Material custom fields toggle
// ---------------------------------------------------------------------

const materialSelect = document.getElementById('material');
const customRow = document.getElementById('custom-material-row');
materialSelect.addEventListener('change', () => {
  customRow.style.display = materialSelect.value === 'custom' ? 'grid' : 'none';
});

// ---------------------------------------------------------------------
// Build the request payload from current form state
// ---------------------------------------------------------------------

function buildPayload() {
  const components = [...componentList.querySelectorAll('.component-row')].map(row => ({
    name: row.querySelector('.c-name').value || 'component',
    mass_g: parseFloat(row.querySelector('.c-mass').value) || 0,
    cg_from_nose_mm: parseFloat(row.querySelector('.c-cg').value) || 0,
  }));

  let material;
  if (materialSelect.value === 'custom') {
    material = {
      name: 'custom',
      density_kg_m3: parseFloat(document.getElementById('custom_density').value),
      shear_modulus_pa: parseFloat(document.getElementById('custom_shear').value),
    };
  } else {
    material = materialSelect.value;
  }

  return {
    body: {
      diameter_mm: parseFloat(document.getElementById('diameter_mm').value),
      nose_length_mm: parseFloat(document.getElementById('nose_length_mm').value),
      nose_type: document.getElementById('nose_type').value,
    },
    mass: { components },
    fins: {
      count: parseInt(document.getElementById('fin_count').value, 10),
      position_from_nose_mm: parseFloat(document.getElementById('fin_position_mm').value),
      material,
    },
    flight: {
      max_velocity_mps: parseFloat(document.getElementById('max_velocity').value),
      altitude_m: parseFloat(document.getElementById('altitude_m').value),
      safety_factor: parseFloat(document.getElementById('safety_factor').value),
    },
    target: {
      stability_margin_calibers: parseFloat(document.getElementById('target_margin').value),
      margin_tolerance: parseFloat(document.getElementById('margin_tolerance').value),
    },
  };
}

// ---------------------------------------------------------------------
// Diagram rendering
// ---------------------------------------------------------------------

function renderDiagram(payload, data) {
  const svg = document.getElementById('diagram');
  const W = 900, H = 260, midY = 150;
  const marginX = 50;

  const diameter = payload.body.diameter_mm;
  const noseLen = payload.body.nose_length_mm;
  const finPos = payload.fins.position_from_nose_mm;
  const fg = data.fin_geometry_mm;

  const drawLen = Math.max(finPos + fg.root_chord_mm * 1.4, noseLen + diameter * 6);
  const scale = (W - marginX * 2) / drawLen;
  const bodyR = Math.max(6, Math.min(60, diameter * scale / 2));

  const X = mm => marginX + mm * scale;

  const noseTipX = X(0);
  const noseEndX = X(noseLen);
  const bodyEndX = X(drawLen);

  const finRootLEx = X(finPos);
  const finRootTEx = X(finPos + fg.root_chord_mm);
  const finTipLEx = X(finPos + fg.sweep_mm);
  const finTipTEx = X(finPos + fg.sweep_mm + fg.tip_chord_mm);
  const finSpanPx = fg.span_mm * scale;
  const finBottomY = midY + bodyR + finSpanPx;

  const cpX = X(data.stability.cp_from_nose_mm);
  const cgX = X(data.stability.cg_from_nose_mm);

  let svgParts = [];

  // grid baseline
  svgParts.push(`<line x1="${marginX}" y1="${midY}" x2="${bodyEndX}" y2="${midY}" stroke="#1c3550" stroke-width="1" stroke-dasharray="2,3"/>`);

  // nose (tangent curve approximated with quadratic)
  svgParts.push(`<path d="M ${noseTipX} ${midY} Q ${noseTipX + (noseEndX - noseTipX) * 0.55} ${midY - bodyR * 0.15}, ${noseEndX} ${midY - bodyR}
                  L ${noseEndX} ${midY + bodyR}
                  Q ${noseTipX + (noseEndX - noseTipX) * 0.55} ${midY + bodyR * 0.15}, ${noseTipX} ${midY} Z"
                  fill="#16324a" stroke="#45d9c9" stroke-width="1.5"/>`);

  // body tube
  svgParts.push(`<rect x="${noseEndX}" y="${midY - bodyR}" width="${bodyEndX - noseEndX}" height="${bodyR * 2}"
                  fill="#16324a" stroke="#45d9c9" stroke-width="1.5"/>`);

  // fin (single trapezoid shown below body, representative of the fin set)
  const finPath = `M ${finRootLEx} ${midY + bodyR}
                    L ${finTipLEx} ${finBottomY}
                    L ${finTipTEx} ${finBottomY}
                    L ${finRootTEx} ${midY + bodyR} Z`;
  svgParts.push(`<path d="${finPath}" fill="#ff7a45" fill-opacity="0.25" stroke="#ff7a45" stroke-width="1.5"/>`);
  // mirror above for visual symmetry (cosmetic only)
  const finPathTop = `M ${finRootLEx} ${midY - bodyR}
                       L ${finTipLEx} ${midY - bodyR - finSpanPx * 0.55}
                       L ${finTipTEx} ${midY - bodyR - finSpanPx * 0.55}
                       L ${finRootTEx} ${midY - bodyR} Z`;
  svgParts.push(`<path d="${finPathTop}" fill="#ff7a45" fill-opacity="0.12" stroke="#ff7a45" stroke-width="1"/>`);

  // CG marker (orange, filled circle + line)
  svgParts.push(`<line x1="${cgX}" y1="20" x2="${cgX}" y2="${midY + bodyR + 20}" stroke="#ffb38a" stroke-width="1" stroke-dasharray="4,3"/>`);
  svgParts.push(`<circle cx="${cgX}" cy="${midY}" r="5" fill="#ffb38a" stroke="#0a1622" stroke-width="1.5"/>`);
  svgParts.push(`<text x="${cgX}" y="14" fill="#ffb38a" font-size="11" font-family="IBM Plex Mono" text-anchor="middle">CG</text>`);

  // CP marker (teal, filled triangle)
  svgParts.push(`<line x1="${cpX}" y1="20" x2="${cpX}" y2="${midY + bodyR + 20}" stroke="#45d9c9" stroke-width="1" stroke-dasharray="4,3"/>`);
  svgParts.push(`<circle cx="${cpX}" cy="${midY}" r="5" fill="#45d9c9" stroke="#0a1622" stroke-width="1.5"/>`);
  svgParts.push(`<text x="${cpX}" y="14" fill="#45d9c9" font-size="11" font-family="IBM Plex Mono" text-anchor="middle">CP</text>`);

  // margin span label
  const midMarkX = (cpX + cgX) / 2;
  svgParts.push(`<text x="${midMarkX}" y="${midY + bodyR + 36}" fill="#7c93a8" font-size="11" font-family="IBM Plex Mono" text-anchor="middle">${data.stability.margin_calibers.toFixed(2)} cal</text>`);

  svg.innerHTML = svgParts.join('\n');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
}

// ---------------------------------------------------------------------
// Results rendering
// ---------------------------------------------------------------------

let lastPayload = null;
let lastBounds = null; // mm bounds from optimizer, used to size manual sliders

function renderResults(payload, data) {
  const s = data.stability, fl = data.flutter, fg = data.fin_geometry_mm;
  const marginOk = Math.abs(s.margin_calibers - payload.target.stability_margin_calibers) <= payload.target.margin_tolerance + 1e-6;

  const statusHtml = `
    <div class="status-row">
      <div class="status-card ${marginOk ? 'ok' : 'warn'}">
        <div class="label">Stability margin</div>
        <div class="value ${marginOk ? 'ok' : 'warn'}">${s.margin_calibers.toFixed(2)} cal</div>
        <div class="sub">target ${payload.target.stability_margin_calibers.toFixed(2)} ± ${payload.target.margin_tolerance.toFixed(2)}</div>
      </div>
      <div class="status-card ${fl.margin_ok ? 'ok' : 'warn'}">
        <div class="label">Flutter check</div>
        <div class="value ${fl.margin_ok ? 'ok' : 'warn'}">${fl.flutter_velocity_mps.toFixed(0)} m/s</div>
        <div class="sub">needs ≥ ${fl.required_velocity_mps.toFixed(0)} m/s</div>
      </div>
      <div class="status-card">
        <div class="label">Fin set mass</div>
        <div class="value">${s.fin_set_mass_g.toFixed(1)} g</div>
        <div class="sub">${fg.count} fins · ${fg.area_single_fin_cm2.toFixed(1)} cm² each</div>
      </div>
    </div>

    <table class="readout">
      <thead><tr><th>Fin geometry</th><th style="text-align:right;">Value</th></tr></thead>
      <tbody>
        <tr><td>Root chord</td><td class="num">${fg.root_chord_mm.toFixed(1)} mm</td></tr>
        <tr><td>Tip chord</td><td class="num">${fg.tip_chord_mm.toFixed(1)} mm</td></tr>
        <tr><td>Span</td><td class="num">${fg.span_mm.toFixed(1)} mm</td></tr>
        <tr><td>Sweep (LE-LE)</td><td class="num">${fg.sweep_mm.toFixed(1)} mm</td></tr>
        <tr><td>Thickness</td><td class="num">${fg.thickness_mm.toFixed(2)} mm</td></tr>
        <tr><td>Aspect ratio</td><td class="num">${fl.aspect_ratio.toFixed(2)}</td></tr>
        <tr><td>Taper ratio</td><td class="num">${fl.taper_ratio.toFixed(2)}</td></tr>
        <tr><td>CP from nose</td><td class="num">${s.cp_from_nose_mm.toFixed(1)} mm</td></tr>
        <tr><td>CG from nose</td><td class="num">${s.cg_from_nose_mm.toFixed(1)} mm</td></tr>
        <tr><td>Total vehicle mass</td><td class="num">${s.total_mass_g.toFixed(1)} g</td></tr>
      </tbody>
    </table>

    <div class="section-title">Manual fine-tune</div>
    <div class="tune-grid" id="tune-grid"></div>
    <div class="hint">Drag to explore trade-offs around the optimized point. The diagram and readouts above update live; this does not re-run the optimizer.</div>
  `;

  document.getElementById('results-slot').innerHTML = statusHtml;
  buildTuneSliders(payload, fg);
}

function buildTuneSliders(payload, fg) {
  const grid = document.getElementById('tune-grid');
  const specs = [
    { key: 'root_chord_mm', label: 'Root chord', min: fg.root_chord_mm * 0.4, max: fg.root_chord_mm * 1.8, step: 0.5 },
    { key: 'tip_chord_mm', label: 'Tip chord', min: 0, max: fg.root_chord_mm * 1.5, step: 0.5 },
    { key: 'span_mm', label: 'Span', min: fg.span_mm * 0.4, max: fg.span_mm * 1.8, step: 0.5 },
    { key: 'sweep_mm', label: 'Sweep', min: 0, max: fg.root_chord_mm * 1.8, step: 0.5 },
    { key: 'thickness_mm', label: 'Thickness', min: 1, max: 12, step: 0.1 },
  ];

  let html = '';
  specs.forEach(spec => {
    const val = fg[spec.key];
    html += `
      <div class="tlabel">${spec.label}</div>
      <input type="range" class="tune-slider" data-key="${spec.key}" min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${val}">
      <div class="tval" id="tval-${spec.key}">${val.toFixed(1)}</div>
    `;
  });
  grid.innerHTML = html;

  let debounceTimer = null;
  grid.querySelectorAll('.tune-slider').forEach(slider => {
    slider.addEventListener('input', () => {
      document.getElementById(`tval-${slider.dataset.key}`).textContent = parseFloat(slider.value).toFixed(1);
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => evaluateManualTune(payload), 120);
    });
  });
}

async function evaluateManualTune(payload) {
  const grid = document.getElementById('tune-grid');
  const geom = {};
  grid.querySelectorAll('.tune-slider').forEach(slider => {
    geom[slider.dataset.key] = parseFloat(slider.value);
  });

  const evalPayload = JSON.parse(JSON.stringify(payload));
  evalPayload.fins.geometry_mm = geom;

  try {
    const res = await fetch('/api/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(evalPayload),
    });
    const data = await res.json();
    if (!res.ok) return; // silently ignore transient invalid states while dragging
    updateLiveReadouts(evalPayload, data);
    renderDiagram(evalPayload, data);
    pushRocketFromResult(evalPayload, data);
  } catch (e) { /* ignore */ }
}

function updateLiveReadouts(payload, data) {
  // lightweight in-place update of the status cards + key table rows,
  // without rebuilding the sliders (so dragging stays smooth)
  const s = data.stability, fl = data.flutter;
  const marginOk = Math.abs(s.margin_calibers - payload.target.stability_margin_calibers) <= payload.target.margin_tolerance + 1e-6;

  const cards = document.querySelectorAll('.status-card');
  if (cards.length >= 2) {
    cards[0].className = `status-card ${marginOk ? 'ok' : 'warn'}`;
    cards[0].querySelector('.value').className = `value ${marginOk ? 'ok' : 'warn'}`;
    cards[0].querySelector('.value').textContent = `${s.margin_calibers.toFixed(2)} cal`;

    cards[1].className = `status-card ${fl.margin_ok ? 'ok' : 'warn'}`;
    cards[1].querySelector('.value').className = `value ${fl.margin_ok ? 'ok' : 'warn'}`;
    cards[1].querySelector('.value').textContent = `${fl.flutter_velocity_mps.toFixed(0)} m/s`;

    cards[2].querySelector('.value').textContent = `${s.fin_set_mass_g.toFixed(1)} g`;
  }
}

// ---------------------------------------------------------------------
// Submit handler
// ---------------------------------------------------------------------

document.getElementById('design-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('optimize-btn');
  const errSlot = document.getElementById('error-slot');
  errSlot.innerHTML = '';
  btn.disabled = true;
  btn.textContent = 'Optimizing…';
  const engineDot = document.getElementById('engine-dot');
  const engineText = document.getElementById('engine-text');
  engineDot.style.background = '#ffb38a';
  engineDot.style.boxShadow = '0 0 8px #ffb38a';
  engineText.textContent = 'searching design space…';

  const payload = buildPayload();
  lastPayload = payload;

  try {
    const res = await fetch('/api/optimize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      errSlot.innerHTML = `<div class="error-box">${data.error || 'Optimization failed.'}</div>`;
      engineDot.style.background = '#ff5c5c';
      engineDot.style.boxShadow = '0 0 8px #ff5c5c';
      engineText.textContent = 'constraint infeasible';
      return;
    }
    renderResults(payload, data);
    renderDiagram(payload, data);
    pushRocketFromResult(payload, data);
    window.__hasOptimizedOnce = true;
    engineDot.style.background = '#5fd97a';
    engineDot.style.boxShadow = '0 0 8px #5fd97a';
    engineText.textContent = 'optimized';
  } catch (err) {
    errSlot.innerHTML = `<div class="error-box">Request failed: ${err.message}</div>`;
    engineDot.style.background = '#ff5c5c';
    engineDot.style.boxShadow = '0 0 8px #ff5c5c';
    engineText.textContent = 'request failed';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Optimize fins';
  }
});
