(() => {
  const datasetId = document.body.dataset.datasetId;
  const canvas = document.querySelector('#spatial-canvas');
  const wrap = document.querySelector('#canvas-wrap');
  const context = canvas.getContext('2d');
  const state = {
    metadata: null, points: [], expression: [], overallExpression: [], gene: null, selected: null,
    view: {x: 0, y: 0, scale: 1}, drag: null, bounds: {xmin: 0, xmax: 100, ymin: 0, ymax: 100},
    rasters: {}, opacity: .85, expressionRange: {min: 0, max: 1}
  };
  const $ = (selector) => document.querySelector(selector);
  const api = (path) => fetch(`/api/spatial/${datasetId}/${path}`).then(async (response) => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Spatial request failed.');
    return data;
  });
  const setMessage = (message, error = false) => {
    $('#canvas-state').textContent = message;
    $('#canvas-state').style.color = error ? '#ed705d' : '';
  };
  const scaleValue = () => Math.min(wrap.clientWidth / state.metadata.width, wrap.clientHeight / state.metadata.height) * state.view.scale;
  const toCanvas = (point) => ({x: state.view.x + point.x * scaleValue(), y: state.view.y + point.y * scaleValue()});
  const fromCanvas = (x, y) => ({x: (x - state.view.x) / scaleValue(), y: (y - state.view.y) / scaleValue()});
  const resize = () => { const ratio = window.devicePixelRatio || 1; canvas.width = wrap.clientWidth * ratio; canvas.height = wrap.clientHeight * ratio; context.setTransform(ratio, 0, 0, ratio, 0, 0); draw(); };
  const layerEnabled = (layerId) => $(`#layers input[data-layer="${layerId}"]`)?.checked || false;
  const syncLayerStatus = (input) => {
    if (!input.disabled) {
      const status = input.closest('.layer-row').querySelector('.availability');
      status.textContent = input.checked ? 'on' : 'off';
      status.dataset.state = input.checked ? 'on' : 'off';
    }
  };
  const loadRaster = (layerId) => {
    if (state.rasters[layerId]) return;
    const endpoint = layerId === 'tissue_mask' ? 'mask' : 'image';
    const image = new Image();
    image.onload = () => { state.rasters[layerId] = image; draw(); };
    image.onerror = () => setMessage(`Could not load ${layerId}.`, true);
    image.src = `/api/spatial/${datasetId}/${endpoint}/`;
  };
  const draw = () => {
    if (!state.metadata) return;
    const width = wrap.clientWidth, height = wrap.clientHeight;
    context.clearRect(0, 0, width, height);
    context.save();
    const origin = toCanvas({x: 0, y: 0}), imageWidth = state.metadata.width * scaleValue(), imageHeight = state.metadata.height * scaleValue();
    if (layerEnabled('image') && state.rasters.image) context.drawImage(state.rasters.image, origin.x, origin.y, imageWidth, imageHeight);
    if (layerEnabled('tissue_mask') && state.rasters.tissue_mask) { context.globalAlpha = state.opacity; context.drawImage(state.rasters.tissue_mask, origin.x, origin.y, imageWidth, imageHeight); }
    if (state.metadata.synthetic && layerEnabled('coordinates')) {
      context.globalAlpha = .23; context.strokeStyle = '#59c4bd'; context.lineWidth = 1;
      for (let tick = 0; tick <= state.metadata.width; tick += 10) { const a = toCanvas({x: tick, y: 0}), b = toCanvas({x: tick, y: state.metadata.height}); context.beginPath(); context.moveTo(a.x, 0); context.lineTo(b.x, height); context.stroke(); const c = toCanvas({x: 0, y: tick}), d = toCanvas({x: state.metadata.width, y: tick}); context.beginPath(); context.moveTo(0, c.y); context.lineTo(width, d.y); context.stroke(); }
    }
    const showPoints = ['coordinates', 'expression', 'cell_annotations', 'clusters'].some(layerEnabled) || Boolean(state.gene);
    const expressionById = new Map(state.expression.map(point => [point.id, point]));
    const overallExpressionById = new Map(state.overallExpression.map(point => [point.id, point]));
    if (showPoints) state.points.forEach(point => {
      const position = toCanvas(point);
      const expression = layerEnabled('expression') ? overallExpressionById.get(point.id) : expressionById.get(point.id);
      const expressionVisible = Boolean(expression);
      const radius = expressionVisible ? 7.3 * Math.sqrt(state.view.scale) : 5 + (state.view.scale * 1.5);
      context.beginPath(); context.arc(position.x, position.y, radius, 0, Math.PI * 2);
      context.fillStyle = expressionVisible ? expressionColor(expression.value) : layerEnabled('cell_annotations') && point.annotation ? annotationColor(point.annotation) : layerEnabled('clusters') ? clusterColor(point.cluster) : '#a9b7bf';
      context.globalAlpha = state.opacity * (state.selected && state.selected.id !== point.id ? .3 : 1); context.fill();
      if (expressionVisible) { context.globalAlpha *= .7; context.strokeStyle = '#f0f4ed'; context.lineWidth = 1; context.stroke(); }
      if (state.selected && state.selected.id === point.id) { context.globalAlpha = 1; context.strokeStyle = '#f2bb62'; context.lineWidth = 2; context.stroke(); }
    });
    context.globalAlpha = 1;
    context.restore();
  };
  const clusterColors = {'Region A': '#59c4bd', 'Region B': '#f2bb62', 'Region C': '#ed705d'};
  const clusterColor = (cluster) => clusterColors[cluster] || '#a9b7bf';
  const annotationColor = (annotation) => { let hash = 0; for (const character of annotation || '') hash = (hash * 31 + character.charCodeAt(0)) | 0; return `hsl(${Math.abs(hash) % 360} 48% 58%)`; };
  const expressionColor = (value) => {
    const range = state.expressionRange;
    const normalized = range.max === range.min ? 1 : Math.max(0, Math.min(1, (value - range.min) / (range.max - range.min)));
    const low = [38, 111, 176], middle = [250, 197, 78], high = [215, 56, 45];
    const start = normalized < .5 ? low : middle, end = normalized < .5 ? middle : high;
    const fraction = normalized < .5 ? normalized * 2 : (normalized - .5) * 2;
    return `rgb(${start.map((channel, index) => Math.round(channel + (end[index] - channel) * fraction)).join(', ')})`;
  };
  const fit = () => { if (!state.metadata) return; state.view.scale = 1; state.view.x = (wrap.clientWidth - state.metadata.width * scaleValue()) / 2; state.view.y = (wrap.clientHeight - state.metadata.height * scaleValue()) / 2; draw(); };
  const showSelection = (point) => {
    state.selected = point;
    const label = point.annotation || point.cluster || 'Cell';
    $('#selection-readout').textContent = `${point.id} · ${label}`;
    const details = [`Cell ID: ${point.id}`, `X: ${point.x.toFixed(1)}`, `Y: ${point.y.toFixed(1)}`];
    if (point.annotation) details.push(`Annotation: ${point.annotation}`);
    if (point.genes_detected !== undefined) details.push(`Genes detected: ${point.genes_detected}`);
    if (point.total_counts !== undefined) details.push(`Total counts: ${point.total_counts}`);
    $('#selection-details').textContent = details.join('\n');
    draw();
  };
  const nearestPoint = (x, y) => state.points.reduce((nearest, point) => { const canvasPoint = toCanvas(point), distance = Math.hypot(canvasPoint.x - x, canvasPoint.y - y); return distance < nearest.distance ? {point, distance} : nearest; }, {point: null, distance: 15});
  const renderLayers = () => {
    const container = $('#layers'); container.innerHTML = '';
    state.metadata.layers.forEach(layer => {
      const supported = layer.available && layer.renderable !== false;
      const row = document.createElement('label'); row.className = `layer-row${supported ? '' : ' is-unavailable'}`;
      const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.layer = layer.id;
      input.checked = supported && ['coordinates', 'image', 'cell_annotations', 'clusters'].includes(layer.id);
      input.disabled = !supported;
      const name = document.createElement('span'); name.className = 'layer-name'; name.textContent = layer.name;
      const availability = document.createElement('span'); availability.className = 'availability';
      availability.textContent = !layer.available ? 'unavailable' : layer.renderable === false ? 'not rendered' : input.checked ? 'on' : 'off';
      availability.dataset.state = !layer.available ? 'unavailable' : layer.renderable === false ? 'not-rendered' : input.checked ? 'on' : 'off';
      if (layer.renderable === false) row.title = 'This dataset layer is present but is not rendered by this viewer yet.';
      row.append(input, name, availability);
      input.addEventListener('change', () => { syncLayerStatus(input); if (input.checked && ['image', 'tissue_mask'].includes(layer.id)) loadRaster(layer.id); if (input.checked && layer.id === 'expression') loadOverallExpression(); draw(); });
      container.append(row);
      if (input.checked && layer.id === 'image') loadRaster('image');
    });
  };
  const loadCoordinates = () => api('coordinates/?limit=50000').then(data => { state.points = data.points; $('#empty-state').classList.add('is-hidden'); setMessage(`${data.count} cells loaded`); fit(); }).catch(error => { $('#empty-state').textContent = error.message; setMessage(error.message, true); });
  const loadExpression = () => {
    const gene = $('#gene-search').value.trim(); if (!gene) return;
    $('#gene-state').textContent = `Loading ${gene}...`;
    api(`expression/?gene=${encodeURIComponent(gene)}&limit=50000`).then(data => {
      state.gene = data.gene; state.expression = data.points; state.expressionRange = {min: data.min, max: data.max};
      $('#expression-min').textContent = data.min; $('#expression-max').textContent = data.max;
      $('#gene-state').textContent = `${data.gene} · ${data.count} cells · ${data.scale}`;
      draw();
    }).catch(error => {
      state.expression = []; state.gene = null; $('#gene-state').textContent = error.message;
      $('#expression-min').textContent = '0'; $('#expression-max').textContent = '0';
      const expressionLayer = $('#layers input[data-layer="expression"]'); if (expressionLayer) { expressionLayer.checked = false; syncLayerStatus(expressionLayer); }
      draw();
    });
  };
  const loadOverallExpression = () => {
    $('#gene-state').textContent = 'Loading overall expression...';
    api('expression/?overall=true&limit=50000').then(data => {
      state.overallExpression = data.points; state.expressionRange = {min: data.min, max: data.max};
      $('#expression-min').textContent = data.min; $('#expression-max').textContent = data.max;
      $('#gene-state').textContent = `${data.count} cells · overall expression`;
      draw();
    }).catch(error => { state.overallExpression = []; $('#gene-state').textContent = error.message; draw(); });
  };
  const loadMetadata = () => api('metadata/').then(metadata => {
    state.metadata = metadata; state.bounds = {xmin: 0, xmax: metadata.width, ymin: 0, ymax: metadata.height};
    $('#dataset-name').textContent = metadata.name; $('#dataset-kind').textContent = metadata.synthetic ? 'synthetic' : metadata.platform || 'real data';
    $('#dataset-description').textContent = metadata.description;
    $('#dataset-stats').innerHTML = `<dt>Cells</dt><dd>${metadata.n_bins}</dd><dt>Genes</dt><dd>${metadata.n_genes}</dd><dt>Species</dt><dd>${metadata.species}</dd><dt>Resolution</dt><dd>${metadata.resolution}</dd>`;
    const geneList = $('#gene-list'); geneList.replaceChildren(...metadata.genes.map(gene => { const option = document.createElement('option'); option.value = gene; return option; }));
    renderLayers(); return loadCoordinates();
  }).catch(error => { $('#empty-state').textContent = error.message; setMessage(error.message, true); });
  $('#gene-submit').addEventListener('click', loadExpression); $('#gene-search').addEventListener('keydown', event => { if (event.key === 'Enter') loadExpression(); });
  $('#layer-opacity').addEventListener('input', event => { state.opacity = Number(event.target.value) / 100; $('#opacity-value').value = `${event.target.value}%`; draw(); });
  $('#fit-view').addEventListener('click', fit); $('#reset-view').addEventListener('click', () => { state.view = {x: 0, y: 0, scale: 1}; fit(); });
  canvas.addEventListener('pointerdown', event => { state.drag = {x: event.clientX, y: event.clientY, viewX: state.view.x, viewY: state.view.y}; wrap.classList.add('is-dragging'); canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event => { const rect = canvas.getBoundingClientRect(), localX = event.clientX - rect.left, localY = event.clientY - rect.top; const coordinate = fromCanvas(localX, localY); $('#coordinate-readout').textContent = `x ${coordinate.x.toFixed(1)} · y ${coordinate.y.toFixed(1)}`; if (state.drag) { state.view.x = state.drag.viewX + event.clientX - state.drag.x; state.view.y = state.drag.viewY + event.clientY - state.drag.y; draw(); } else { const hit = nearestPoint(localX, localY); if (hit.point && hit.distance < 16) { $('#tooltip').hidden = false; $('#tooltip').style.left = `${localX + 14}px`; $('#tooltip').style.top = `${localY + 14}px`; $('#tooltip').textContent = `${hit.point.id} · ${hit.point.annotation || hit.point.cluster || 'Cell'}`; } else $('#tooltip').hidden = true; } });
  canvas.addEventListener('pointerup', event => { if (state.drag) { const rect = canvas.getBoundingClientRect(), hit = nearestPoint(event.clientX - rect.left, event.clientY - rect.top); if (Math.hypot(event.clientX - state.drag.x, event.clientY - state.drag.y) < 5 && hit.point && hit.distance < 16) showSelection(hit.point); } state.drag = null; wrap.classList.remove('is-dragging'); });
  canvas.addEventListener('wheel', event => { event.preventDefault(); const rect = canvas.getBoundingClientRect(), before = fromCanvas(event.clientX - rect.left, event.clientY - rect.top); state.view.scale = Math.max(.35, Math.min(8, state.view.scale * (event.deltaY < 0 ? 1.12 : .89))); const after = toCanvas(before); state.view.x += event.clientX - rect.left - after.x; state.view.y += event.clientY - rect.top - after.y; draw(); }, {passive: false});
  window.addEventListener('resize', resize); resize(); loadMetadata();
})();
