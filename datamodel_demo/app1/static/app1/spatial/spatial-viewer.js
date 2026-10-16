(() => {
  const datasetId = document.body.dataset.datasetId;
  const canvas = document.querySelector('#spatial-canvas');
  const wrap = document.querySelector('#canvas-wrap');
  const context = canvas.getContext('2d');
  const state = {
    metadata: null, points: [], nearestSpacing: null, expression: [], overallExpression: [], gene: null, selected: null,
    view: {x: 0, y: 0, scale: 1}, drag: null, bounds: {xmin: 0, xmax: 100, ymin: 0, ymax: 100},
    rasters: {}, viewer: null, transform: null, imageVisible: true, opacity: .85, expressionRange: {min: 0, max: 1},
    viewportRequest: 0, selectionRequest: 0, viewportTimer: null, viewportSampled: false, viewportTotal: 0
  };
  const $ = (selector) => document.querySelector(selector);
  const api = (path) => fetch(`/api/spatial/${datasetId}/${path}`).then(async (response) => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Spatial request failed.');
    return data;
  });
  const expressionRange = (points) => points.reduce(
    (range, point) => ({min: Math.min(range.min, point.value), max: Math.max(range.max, point.value)}),
    {min: Infinity, max: -Infinity}
  );
  const loadDatasetPicker = () => fetch('/api/spatial/').then(async (response) => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load spatial datasets.');
    const picker = $('#dataset-select');
    picker.replaceChildren(...data.datasets.map(dataset => {
      const option = document.createElement('option');
      option.value = dataset.id;
      option.textContent = dataset.name;
      option.disabled = dataset.reader_available === false;
      return option;
    }));
    if (![...picker.options].some(option => option.value === datasetId)) {
      const option = document.createElement('option');
      option.value = datasetId;
      option.textContent = datasetId;
      picker.add(option);
    }
    picker.value = datasetId;
    picker.addEventListener('change', () => {
      window.location.assign(`/spatial/${encodeURIComponent(picker.value)}/`);
    });
  }).catch(error => {
    $('#dataset-select').replaceChildren(new Option(error.message, ''));
    $('#dataset-select').disabled = true;
  });
  const setMessage = (message, error = false) => {
    $('#canvas-state').textContent = message;
    $('#canvas-state').style.color = error ? '#ed705d' : '';
  };
  const scaleValue = () => state.transform?.scaleX || Math.min(wrap.clientWidth / state.metadata.width, wrap.clientHeight / state.metadata.height) * state.view.scale;
  const toCanvas = (point) => state.transform
    ? {x: state.transform.x + point.x * state.transform.scaleX, y: state.transform.y + point.y * state.transform.scaleY}
    : {x: state.view.x + point.x * scaleValue(), y: state.view.y + point.y * scaleValue()};
  const fromCanvas = (x, y) => {
    if (state.viewer?.world?.getItemCount()) {
      const viewportPoint = state.viewer.viewport.pointFromPixel(new OpenSeadragon.Point(x, y), true);
      return state.viewer.viewport.viewportToImageCoordinates(viewportPoint.x, viewportPoint.y);
    }
    return {x: (x - state.view.x) / scaleValue(), y: (y - state.view.y) / scaleValue()};
  };
  const visibleBounds = () => {
    const first = fromCanvas(0, 0), last = fromCanvas(wrap.clientWidth, wrap.clientHeight);
    const paddingX = Math.abs(last.x - first.x) * .02, paddingY = Math.abs(last.y - first.y) * .02;
    return {
      xmin: Math.max(0, Math.min(first.x, last.x) - paddingX),
      xmax: Math.min(state.metadata.width, Math.max(first.x, last.x) + paddingX),
      ymin: Math.max(0, Math.min(first.y, last.y) - paddingY),
      ymax: Math.min(state.metadata.height, Math.max(first.y, last.y) + paddingY)
    };
  };
  const viewportPath = (path, bounds, extra = {}) => {
    const params = new URLSearchParams({limit: '10000', sample: 'true'});
    Object.entries(bounds).forEach(([key, value]) => params.set(key, value.toFixed(2)));
    Object.entries(extra).forEach(([key, value]) => params.set(key, value));
    return `${path}?${params}`;
  };
  const viewerTransform = () => {
    const viewport = state.viewer.viewport;
    const toPixel = (x, y) => viewport.pixelFromPoint(viewport.imageToViewportCoordinates(x, y), true);
    const origin = toPixel(0, 0), xAxis = toPixel(1, 0), yAxis = toPixel(0, 1);
    return {x: origin.x, y: origin.y, scaleX: xAxis.x - origin.x, scaleY: yAxis.y - origin.y};
  };
  const resize = () => { const ratio = window.devicePixelRatio || 1; canvas.width = wrap.clientWidth * ratio; canvas.height = wrap.clientHeight * ratio; context.setTransform(ratio, 0, 0, ratio, 0, 0); draw(); };
  const layerEnabled = (layerId) => $(`#layers input[data-layer="${layerId}"]`)?.checked || false;
  const syncLayerStatus = (input) => {
    if (!input.disabled) {
      const status = input.closest('.layer-row').querySelector('.availability');
      status.textContent = input.checked ? 'on' : 'off';
      status.dataset.state = input.checked ? 'on' : 'off';
    }
  };
  const updateImageVisibility = () => {
    const item = state.viewer?.world?.getItemAt(0);
    if (item) item.setOpacity(state.imageVisible ? 1 : 0);
  };
  const loadFullImageFallback = () => {
    if (state.imageFallback) return;
    if (state.metadata && state.metadata.display_width * state.metadata.display_height > 16000000) {
      setMessage('Image tiles are unavailable; full-image fallback is disabled for this image size.', true);
      return;
    }
    state.imageFallback = true;
    state.viewer?.destroy();
    state.viewer = null;
    wrap.classList.remove('has-tiled-image');
    const image = new Image();
    image.onload = () => { state.rasters.image = image; draw(); };
    image.onerror = () => setMessage('Could not load tissue image.', true);
    image.src = `/api/spatial/${datasetId}/image/`;
  };
  const openTiledImage = () => {
    if (state.viewer || state.rasters.image || state.imageFallback) return;
    if (!window.OpenSeadragon) { loadFullImageFallback(); return; }
    wrap.classList.add('has-tiled-image');
    state.viewer = OpenSeadragon({
      element: $('#tiled-image-viewer'),
      showNavigationControl: false,
      showNavigator: false,
      animationTime: .2,
      blendTime: 0,
      minZoomImageRatio: .35,
      maxZoomPixelRatio: 8,
      visibilityRatio: .1,
      gestureSettingsMouse: {clickToZoom: false, dblClickToZoom: false, scrollToZoom: true, dragToPan: true}
    });
    state.viewer.addHandler('open', () => {
      updateImageVisibility();
      fit();
      setMessage('Tissue image tiles loaded');
    });
    state.viewer.addHandler('open-failed', loadFullImageFallback);
    state.viewer.addHandler('tile-load-failed', () => {
      setMessage('Image tile failed; loading the full image instead.', true);
      loadFullImageFallback();
    });
    state.viewer.addHandler('animation', () => { draw(); scheduleViewportLoad(); });
    state.viewer.addHandler('zoom', () => {
      state.view.scale = state.viewer.viewport.getZoom() / state.viewer.viewport.getHomeZoom();
      draw();
      scheduleViewportLoad();
    });
    state.viewer.addHandler('resize', resize);
    state.viewer.addHandler('canvas-click', event => {
      if (!event.quick) return;
      const hit = nearestPoint(event.position.x, event.position.y);
      if (hit.point && hit.distance < pointRadius() + 10) showSelection(hit.point);
    });
    state.viewer.addHandler('canvas-move', event => {
      const x = event.position.x, y = event.position.y;
      const coordinate = fromCanvas(x, y);
      $('#coordinate-readout').textContent = `x ${coordinate.x.toFixed(1)} · y ${coordinate.y.toFixed(1)}`;
      const hit = nearestPoint(x, y);
      if (hit.point && hit.distance < pointRadius() + 10) {
        $('#tooltip').hidden = false;
        $('#tooltip').style.left = `${x + 14}px`;
        $('#tooltip').style.top = `${y + 14}px`;
        $('#tooltip').textContent = `${hit.point.id} · ${displayLabel(hit.point)}`;
      } else $('#tooltip').hidden = true;
    });
    state.viewer.open(`/api/spatial/${datasetId}/image.dzi`);
  };
  const startTiledImage = () => {
    try {
      openTiledImage();
    } catch (error) {
      setMessage(`Tiled viewer failed: ${error.message}`, true);
      state.viewer?.destroy();
      state.viewer = null;
      loadFullImageFallback();
    }
  };
  const loadRaster = (layerId) => {
    if (layerId === 'image') {
      if (state.viewer || state.rasters.image || state.imageFallback || state.osdLoadStarted) return;
      if (!window.OpenSeadragon) {
        state.osdLoadStarted = true;
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/openseadragon.min.js';
        script.async = true;
        script.onload = () => window.OpenSeadragon ? startTiledImage() : loadFullImageFallback();
        script.onerror = loadFullImageFallback;
        document.head.append(script);
        return;
      }
      startTiledImage();
      return;
    }
    if (state.rasters[layerId]) return;
    const image = new Image();
    image.onload = () => { state.rasters[layerId] = image; draw(); };
    image.onerror = () => setMessage(`Could not load ${layerId}.`, true);
    image.src = `/api/spatial/${datasetId}/mask/`;
  };
  const displayLabel = (point) => {
    const candidates = [point.annotation, point.cluster, point.id].filter(value => value !== undefined && value !== null && `${value}`.trim() !== '');
    const label = candidates.find(value => !/^[-+]?((\d+\.?\d*)|(\.\d+))$/.test(`${value}`));
    return label ?? point.id;
  };
  const estimateNearestSpacing = (points) => {
    if (points.length < 2) return null;
    const sampleCount = Math.min(points.length, 128);
    const nearestDistances = [];
    for (let sample = 0; sample < sampleCount; sample += 1) {
      const point = points[Math.floor(sample * points.length / sampleCount)];
      let nearest = Infinity;
      for (const candidate of points) {
        if (candidate === point) continue;
        const distance = Math.hypot(point.x - candidate.x, point.y - candidate.y);
        if (distance < nearest) nearest = distance;
      }
      if (Number.isFinite(nearest)) nearestDistances.push(nearest);
    }
    nearestDistances.sort((a, b) => a - b);
    return nearestDistances.length ? nearestDistances[Math.floor(nearestDistances.length / 2)] : null;
  };
  const pointRadius = () => {
    const defaultRadius = 7.3 * Math.sqrt(state.view.scale);
    if (!state.nearestSpacing) return defaultRadius;
    const spacingInCanvasPixels = state.nearestSpacing * scaleValue();
    return Math.min(defaultRadius, Math.max(2, spacingInCanvasPixels * .85));
  };
  const draw = () => {
    if (!state.metadata) return;
    const width = wrap.clientWidth, height = wrap.clientHeight;
    context.clearRect(0, 0, width, height);
    context.save();
    const fallbackScale = Math.min(width / state.metadata.width, height / state.metadata.height) * state.view.scale;
    state.transform = state.viewer?.world?.getItemCount() ? viewerTransform() : {x: state.view.x, y: state.view.y, scaleX: fallbackScale, scaleY: fallbackScale};
    const origin = {x: state.transform.x, y: state.transform.y};
    const imageWidth = state.metadata.width * state.transform.scaleX, imageHeight = state.metadata.height * state.transform.scaleY;
    if (layerEnabled('image') && !state.viewer && state.rasters.image) context.drawImage(state.rasters.image, origin.x, origin.y, imageWidth, imageHeight);
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
      const expression = state.gene
        ? expressionById.get(point.id)
        : layerEnabled('expression') ? overallExpressionById.get(point.id) : null;
      const expressionVisible = Boolean(expression);
      const radius = expressionVisible ? pointRadius() : Math.max(2.8, pointRadius() * .72);
      context.beginPath(); context.arc(position.x, position.y, radius, 0, Math.PI * 2);
      context.fillStyle = expressionVisible ? expressionColor(expression.value) : layerEnabled('cell_annotations') && point.annotation ? annotationColor(point.annotation) : layerEnabled('clusters') ? clusterColor(point.cluster) : '#a9b7bf';
      context.globalAlpha = state.opacity * (state.selected && state.selected.id !== point.id ? .3 : 1); context.fill();
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
  const fit = () => {
    if (!state.metadata) return;
    state.view.scale = 1;
    if (state.viewer?.world?.getItemCount()) state.viewer.viewport.goHome(true);
    else {
      state.view.x = (wrap.clientWidth - state.metadata.width * scaleValue()) / 2;
      state.view.y = (wrap.clientHeight - state.metadata.height * scaleValue()) / 2;
    }
    draw();
  };
  const showSelection = (point) => {
    state.selected = point;
    const label = displayLabel(point);
    $('#selection-readout').textContent = `${point.id} · ${label}`;
    const request = ++state.selectionRequest;
    const renderDetails = (cell) => {
      const details = [`Cell ID: ${cell.id}`, `X: ${cell.x.toFixed(1)}`, `Y: ${cell.y.toFixed(1)}`];
      if (cell.annotation && !/^[-+]?((\d+\.?\d*)|(\.\d+))$/.test(`${cell.annotation}`)) details.push(`Annotation: ${cell.annotation}`);
      if (cell.cluster && !/^[-+]?((\d+\.?\d*)|(\.\d+))$/.test(`${cell.cluster}`)) details.push(`Cluster: ${cell.cluster}`);
      if (cell.genes_detected !== undefined) details.push(`Genes detected: ${cell.genes_detected}`);
      if (cell.total_counts !== undefined) details.push(`Total counts: ${cell.total_counts}`);
      $('#selection-details').textContent = details.join('\n');
    };
    renderDetails(point);
    draw();
    api(`cell/?id=${encodeURIComponent(point.id)}`).then(({cell}) => {
      if (request !== state.selectionRequest || state.selected?.id !== point.id) return;
      state.selected = {...point, ...cell};
      renderDetails(state.selected);
      draw();
    }).catch(() => {});
  };
  const nearestPoint = (x, y) => state.points.reduce((nearest, point) => { const canvasPoint = toCanvas(point), distance = Math.hypot(canvasPoint.x - x, canvasPoint.y - y); return distance < nearest.distance ? {point, distance} : nearest; }, {point: null, distance: 16});
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
      input.addEventListener('change', () => { syncLayerStatus(input); if (layer.id === 'image') { state.imageVisible = input.checked; if (input.checked) loadRaster(layer.id); updateImageVisibility(); } if (input.checked && layer.id === 'tissue_mask') loadRaster(layer.id); if (layer.id === 'expression') scheduleViewportLoad(); draw(); });
      container.append(row);
      if (layer.id === 'image') state.imageVisible = input.checked;
      if (input.checked && layer.id === 'image') loadRaster('image');
    });
  };
  const loadViewport = async () => {
    if (!state.metadata) return;
    const request = ++state.viewportRequest;
    const bounds = visibleBounds();
    try {
      const coordinates = await api(viewportPath('coordinates/', bounds));
      if (request !== state.viewportRequest) return;
      state.points = coordinates.points;
      state.viewportSampled = coordinates.sampled;
      state.viewportTotal = coordinates.total_count ?? coordinates.count;
      state.nearestSpacing = estimateNearestSpacing(state.points);
      $('#empty-state').classList.add('is-hidden');
      const overallMode = layerEnabled('expression') && !state.gene;
      const expressionPath = state.gene
        ? viewportPath('expression/', bounds, {gene: state.gene})
        : overallMode ? viewportPath('expression/', bounds, {overall: 'true'}) : null;
      if (expressionPath) {
        const expression = await api(expressionPath);
        if (request !== state.viewportRequest) return;
        if (overallMode) state.overallExpression = expression.points;
        else state.expression = expression.points;
        const range = expressionRange(expression.points);
        state.expressionRange = {
          min: Number.isFinite(range.min) ? range.min : 0,
          max: Number.isFinite(range.max) ? range.max : 0
        };
        $('#expression-min').textContent = state.expressionRange.min;
        $('#expression-max').textContent = state.expressionRange.max;
        $('#gene-state').textContent = overallMode
          ? `${expression.points.length.toLocaleString()} visible cells · overall expression`
          : `${state.metadata.gene_display_names?.[state.gene] || state.gene} · ${expression.points.length.toLocaleString()} visible cells · ${expression.scale || 'raw counts'}`;
      } else {
        state.expression = [];
        state.overallExpression = [];
        $('#gene-state').textContent = state.gene
          ? `${state.metadata.gene_display_names?.[state.gene] || state.gene} · zoom or pan to load visible values`
          : 'Choose a gene to view raw counts.';
      }
      setMessage(state.viewportSampled
        ? `Displaying ${state.points.length.toLocaleString()} of ${state.viewportTotal.toLocaleString()} visible cells (sampled)`
        : `${state.points.length.toLocaleString()} visible cells`);
      draw();
    } catch (error) {
      if (request !== state.viewportRequest) return;
      $('#empty-state').textContent = error.message;
      setMessage(error.message, true);
    }
  };
  const scheduleViewportLoad = () => {
    clearTimeout(state.viewportTimer);
    state.viewportTimer = setTimeout(loadViewport, 140);
  };
  const loadExpression = () => {
    const rawGene = $('#gene-search').value.trim(); if (!rawGene) return;
    const gene = resolveGeneQuery(rawGene);
    state.gene = gene;
    $('#gene-state').textContent = `Loading ${gene}...`;
    loadViewport();
  };
  const loadOverallExpression = () => {
    $('#gene-state').textContent = 'Loading overall expression...';
    loadViewport();
  };
  const resolveGeneQuery = (gene) => {
    const query = gene.trim();
    if (!query) return query;
    const displayNames = state.metadata?.gene_display_names || {};
    const exactMatch = Object.entries(displayNames).find(([id, label]) => `${label}`.toLowerCase() === query.toLowerCase() || id.toLowerCase() === query.toLowerCase());
    if (exactMatch) return exactMatch[0];
    return query;
  };
  const loadMetadata = () => api('metadata/').then(metadata => {
    state.metadata = metadata; state.bounds = {xmin: 0, xmax: metadata.width, ymin: 0, ymax: metadata.height};
    $('#dataset-name').textContent = metadata.name; $('#dataset-kind').textContent = metadata.synthetic ? 'synthetic' : metadata.platform || 'real data';
    $('#dataset-description').textContent = metadata.description;
    $('#dataset-stats').innerHTML = `<dt>Cells</dt><dd>${metadata.n_bins}</dd><dt>Genes</dt><dd>${metadata.n_genes}</dd><dt>Species</dt><dd>${metadata.species}</dd><dt>Resolution</dt><dd>${metadata.resolution}</dd>`;
    const geneList = $('#gene-list'); const displayNames = metadata.gene_display_names || {}; geneList.replaceChildren(...metadata.genes.map(gene => { const option = document.createElement('option'); option.value = gene; option.textContent = displayNames[gene] || gene; return option; }));
    renderLayers();
    fit();
    scheduleViewportLoad();
  }).catch(error => { $('#empty-state').textContent = error.message; setMessage(error.message, true); });
  $('#gene-submit').addEventListener('click', loadExpression); $('#gene-search').addEventListener('keydown', event => { if (event.key === 'Enter') loadExpression(); });
  $('#layer-opacity').addEventListener('input', event => { state.opacity = Number(event.target.value) / 100; $('#opacity-value').value = `${event.target.value}%`; draw(); });
  $('#fit-view').addEventListener('click', fit); $('#reset-view').addEventListener('click', () => { state.view = {x: 0, y: 0, scale: 1}; fit(); });
  canvas.addEventListener('pointerdown', event => { state.drag = {x: event.clientX, y: event.clientY, viewX: state.view.x, viewY: state.view.y}; wrap.classList.add('is-dragging'); canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event => { const rect = canvas.getBoundingClientRect(), localX = event.clientX - rect.left, localY = event.clientY - rect.top; const coordinate = fromCanvas(localX, localY); $('#coordinate-readout').textContent = `x ${coordinate.x.toFixed(1)} · y ${coordinate.y.toFixed(1)}`; if (state.drag) { state.view.x = state.drag.viewX + event.clientX - state.drag.x; state.view.y = state.drag.viewY + event.clientY - state.drag.y; draw(); scheduleViewportLoad(); } else { const hit = nearestPoint(localX, localY); if (hit.point && hit.distance < pointRadius() + 10) { $('#tooltip').hidden = false; $('#tooltip').style.left = `${localX + 14}px`; $('#tooltip').style.top = `${localY + 14}px`; $('#tooltip').textContent = `${hit.point.id} · ${displayLabel(hit.point)}`; } else $('#tooltip').hidden = true; } });
  canvas.addEventListener('pointerup', event => { if (state.drag) { const rect = canvas.getBoundingClientRect(), hit = nearestPoint(event.clientX - rect.left, event.clientY - rect.top); if (Math.hypot(event.clientX - state.drag.x, event.clientY - state.drag.y) < 5 && hit.point && hit.distance < pointRadius() + 10) showSelection(hit.point); } state.drag = null; wrap.classList.remove('is-dragging'); });
  canvas.addEventListener('wheel', event => { event.preventDefault(); const rect = canvas.getBoundingClientRect(), before = fromCanvas(event.clientX - rect.left, event.clientY - rect.top); state.view.scale = Math.max(.35, Math.min(8, state.view.scale * (event.deltaY < 0 ? 1.12 : .89))); const after = toCanvas(before); state.view.x += event.clientX - rect.left - after.x; state.view.y += event.clientY - rect.top - after.y; draw(); scheduleViewportLoad(); }, {passive: false});
  window.addEventListener('resize', () => { resize(); scheduleViewportLoad(); }); resize(); loadDatasetPicker(); loadMetadata();
})();
