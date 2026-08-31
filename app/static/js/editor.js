/* ============================================================
   EDITOR.JS — Image Editor Application
   ============================================================
   Local tools: crop, resize, rotate, flip, brightness, contrast, saturation
   AI tools: inpaint, outpaint, background replace, retexture
   Versioning: original → v2 → v3 ...
   Masking: brush, erase, size, undo/redo
   Before/After: comparison slider
   ============================================================ */

(function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================

  const EditorState = {
    imageId: null,
    imageUrl: null,
    imageWidth: 0,
    imageHeight: 0,

    // Current tool
    activeTool: null,  // 'crop', 'resize', 'rotate', etc.
    activeTab: 'tools', // 'tools', 'ai', 'versions'

    // Canvas
    zoom: 1,
    panX: 0,
    panY: 0,

    // Local adjustments
    brightness: 1.0,
    contrast: 1.0,
    saturation: 1.0,

    // Crop
    cropActive: false,
    cropRect: null,

    // Masking
    maskMode: false,
    maskTool: 'brush', // 'brush' or 'erase'
    maskBrushSize: 20,
    maskHistory: [],
    maskHistoryIndex: -1,
    maskCanvas: null,
    maskCtx: null,
    isDrawing: false,

    // AI
    aiOperation: null,
    aiPrompt: '',
    outpaintDirection: 'right',

    // Versions
    versions: [],
    currentVersionId: null,
    latestVersionId: null,

    // Comparison
    comparisonMode: false,
    comparisonVersionId: null,

    // Undo/Redo
    undoStack: [],
    redoStack: [],
    maxUndoSteps: 20,

    // Loading
    isProcessing: false,

    // Capabilities
    capabilities: {},
  };

  // ============================================================
  // INITIALIZATION
  // ============================================================

  function init() {
    // Parse image ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const imageId = urlParams.get('id');
    if (imageId) {
      EditorState.imageId = parseInt(imageId);
      loadImageForEditing(EditorState.imageId);
    }

    // Load provider capabilities
    loadCapabilities();

    // Set up event listeners
    setupToolbarEvents();
    setupToolEvents();
    setupPanelEvents();
    setupKeyboardShortcuts();

    // Initialize mask canvas
    initMaskCanvas();
  }

  // ============================================================
  // IMAGE LOADING
  // ============================================================

  async function loadImageForEditing(imageId) {
    showEditorLoading('Loading image...');

    try {
      const resp = await fetch(`/api/v1/editor/images/${imageId}/info`);
      if (!resp.ok) throw new Error('Failed to load image');

      const data = await resp.json();
      const img = data.image;

      EditorState.imageId = img.id;
      EditorState.imageUrl = img.url;
      EditorState.imageWidth = img.width || 512;
      EditorState.imageHeight = img.height || 512;
      EditorState.versions = data.versions || [];
      EditorState.currentVersionId = data.latest_version?.id || null;
      EditorState.latestVersionId = data.latest_version?.id || null;

      // Set canvas image
      const canvasImg = document.getElementById('editor-canvas-img');
      if (canvasImg) {
        canvasImg.src = img.url;
        canvasImg.onload = () => {
          EditorState.imageWidth = canvasImg.naturalWidth;
          EditorState.imageHeight = canvasImg.naturalHeight;
          updateImageInfo();
          fitCanvasToView();
        };
      }

      // Update version list
      renderVersionList();

      // Hide empty state
      hideEditorEmptyState();

    } catch (err) {
      console.error('Failed to load image:', err);
      Toast.error('Failed to load image for editing');
    } finally {
      hideEditorLoading();
    }
  }

  // ============================================================
  // CAPABILITIES
  // ============================================================

  async function loadCapabilities() {
    try {
      const resp = await fetch('/api/v1/editor/capabilities');
      if (resp.ok) {
        const data = await resp.json();
        EditorState.capabilities = data.capabilities || {};
        updateToolAvailability();
      }
    } catch (e) { /* silent */ }
  }

  function updateToolAvailability() {
    // Disable AI tools if provider doesn't support them
    const caps = EditorState.capabilities;
    const hasAI = Object.values(caps).some(c =>
      c.inpainting || c.outpainting || c.image_edit
    );

    document.querySelectorAll('[data-requires-ai]').forEach(el => {
      el.disabled = !hasAI;
      if (!hasAI) {
        el.title = 'Requires a provider with AI editing support';
      }
    });
  }

  // ============================================================
  // TOOLBAR
  // ============================================================

  function setupToolbarEvents() {
    // Upload — bring in a personal image to edit
    document.getElementById('toolbar-upload')?.addEventListener('click', () => {
      document.getElementById('editor-upload-input')?.click();
    });
    document.getElementById('empty-state-upload-btn')?.addEventListener('click', () => {
      document.getElementById('editor-upload-input')?.click();
    });
    document.getElementById('editor-upload-input')?.addEventListener('change', handleImageUpload);

    // Undo
    document.getElementById('toolbar-undo')?.addEventListener('click', undo);
    // Redo
    document.getElementById('toolbar-redo')?.addEventListener('click', redo);
    // Reset
    document.getElementById('toolbar-reset')?.addEventListener('click', resetEdits);
    // Save as New Version
    document.getElementById('toolbar-save-version')?.addEventListener('click', saveAsVersion);
    // Comparison
    document.getElementById('toolbar-compare')?.addEventListener('click', toggleComparison);
    // Download
    document.getElementById('toolbar-download')?.addEventListener('click', downloadCurrent);
  }

  // ============================================================
  // UPLOAD YOUR OWN IMAGE
  // ============================================================

  async function handleImageUpload(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = ''; // allow re-selecting the same file later
    if (!file) return;

    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      window.Toast?.show('Please choose a PNG, JPEG, or WebP image.', 'error');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      window.Toast?.show('Image is too large (max 10MB).', 'error');
      return;
    }

    showEditorLoading('Uploading your image...');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch('/api/v1/utilities/upload', { method: 'POST', body: formData });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || 'Upload failed');
      }

      window.Toast?.show('Image uploaded — ready to edit.', 'success');
      // Reflect the new image in the URL (so refresh/back-button behave)
      // then load it into the canvas exactly like opening from the gallery.
      const url = new URL(window.location.href);
      url.searchParams.set('id', data.image.id);
      window.history.pushState({}, '', url);
      await loadImageForEditing(data.image.id);
    } catch (err) {
      hideEditorLoading();
      window.Toast?.show(err.message || 'Could not upload image.', 'error');
    }
  }

  // ============================================================
  // LEFT PANEL - LOCAL TOOLS
  // ============================================================

  function setupToolEvents() {
    document.querySelectorAll('[data-editor-tool]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tool = btn.dataset.editorTool;
        setActiveTool(tool);
      });
    });
  }

  function setActiveTool(tool) {
    // Toggle off if same tool
    if (EditorState.activeTool === tool) {
      EditorState.activeTool = null;
      document.querySelectorAll('[data-editor-tool]').forEach(b => b.classList.remove('active'));
      hideToolSettings();
      return;
    }

    EditorState.activeTool = tool;

    // Update UI
    document.querySelectorAll('[data-editor-tool]').forEach(b => b.classList.remove('active'));
    document.querySelector(`[data-editor-tool="${tool}"]`)?.classList.add('active');

    // Show tool settings
    showToolSettings(tool);
  }

  function showToolSettings(tool) {
    // Hide all settings
    document.querySelectorAll('.editor-tool-settings').forEach(el => {
      el.style.display = 'none';
    });

    // Show relevant settings
    const settings = document.getElementById(`settings-${tool}`);
    if (settings) {
      settings.style.display = 'block';
    }

    // Activate mask mode for AI tools that need it
    if (tool === 'inpaint') {
      enableMaskMode();
    } else {
      disableMaskMode();
    }
  }

  function hideToolSettings() {
    document.querySelectorAll('.editor-tool-settings').forEach(el => {
      el.style.display = 'none';
    });
    disableMaskMode();
  }

  // ============================================================
  // RIGHT PANEL - TABS
  // ============================================================

  function setupPanelEvents() {
    // Tab switching
    document.querySelectorAll('.editor-panel-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        setActiveTab(tabName);
      });
    });

    // AI tool buttons
    document.querySelectorAll('[data-ai-tool]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tool = btn.dataset.aiTool;
        startAIEdit(tool);
      });
    });

    // AI prompt
    const aiPrompt = document.getElementById('ai-prompt');
    if (aiPrompt) {
      aiPrompt.addEventListener('input', (e) => {
        EditorState.aiPrompt = e.target.value;
      });
    }

    // AI submit
    document.getElementById('ai-submit-btn')?.addEventListener('click', submitAIEdit);

    // Outpaint direction buttons
    document.querySelectorAll('[data-outpaint-dir]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-outpaint-dir]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        EditorState.outpaintDirection = btn.dataset.outpaintDir;
      });
    });

    // Local adjustment sliders
    setupSlider('brightness-slider', 'brightness-value', (val) => {
      EditorState.brightness = val / 100;
      applyPreviewFilters();
    });

    setupSlider('contrast-slider', 'contrast-value', (val) => {
      EditorState.contrast = val / 100;
      applyPreviewFilters();
    });

    setupSlider('saturation-slider', 'saturation-value', (val) => {
      EditorState.saturation = val / 100;
      applyPreviewFilters();
    });

    // Apply local adjustments button
    document.getElementById('apply-local-btn')?.addEventListener('click', applyLocalAdjustments);

    // Resize inputs
    document.getElementById('resize-width')?.addEventListener('input', updateResizeHeight);
    document.getElementById('resize-height')?.addEventListener('input', updateResizeWidth);
    document.getElementById('apply-resize-btn')?.addEventListener('click', applyResize);

    // Rotate
    document.getElementById('apply-rotate-btn')?.addEventListener('click', applyRotate);
    document.querySelectorAll('[data-rotate-angle]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-rotate-angle]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });

    // Flip
    document.getElementById('apply-flip-btn')?.addEventListener('click', applyFlip);
    document.querySelectorAll('[data-flip-dir]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-flip-dir]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });

    // Crop
    document.getElementById('apply-crop-btn')?.addEventListener('click', applyCrop);

    // Masking tools
    setupMaskTools();
  }

  function setActiveTab(tabName) {
    EditorState.activeTab = tabName;

    document.querySelectorAll('.editor-panel-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.editor-panel-tab[data-tab="${tabName}"]`)?.classList.add('active');

    document.querySelectorAll('.editor-panel-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tab-${tabName}`)?.classList.add('active');
  }

  function setupSlider(sliderId, valueId, callback) {
    const slider = document.getElementById(sliderId);
    const valueEl = document.getElementById(valueId);
    if (!slider) return;

    slider.addEventListener('input', () => {
      const val = parseFloat(slider.value);
      if (valueEl) valueEl.textContent = val.toFixed(2);
      callback(val);
    });
  }

  function applyPreviewFilters() {
    const canvasImg = document.getElementById('editor-canvas-img');
    if (!canvasImg) return;

    const filters = [];
    if (EditorState.brightness !== 1.0) filters.push(`brightness(${EditorState.brightness})`);
    if (EditorState.contrast !== 1.0) filters.push(`contrast(${EditorState.contrast})`);
    if (EditorState.saturation !== 1.0) filters.push(`saturate(${EditorState.saturation})`);

    canvasImg.style.filter = filters.length > 0 ? filters.join(' ') : 'none';
  }

  // ============================================================
  // LOCAL EDITING OPERATIONS
  // ============================================================

  async function applyLocalAdjustments() {
    // Check if any adjustment was made
    if (EditorState.brightness === 1.0 && EditorState.contrast === 1.0 && EditorState.saturation === 1.0) {
      Toast.info('No adjustments to apply');
      return;
    }

    // Apply brightness if changed
    if (EditorState.brightness !== 1.0) {
      await applyLocalEdit('brightness', { factor: EditorState.brightness });
    }

    // Apply contrast if changed
    if (EditorState.contrast !== 1.0) {
      await applyLocalEdit('contrast', { factor: EditorState.contrast });
    }

    // Apply saturation if changed
    if (EditorState.saturation !== 1.0) {
      await applyLocalEdit('saturation', { factor: EditorState.saturation });
    }

    // Reset sliders
    resetAdjustmentSliders();

    Toast.success('Adjustments applied!');
  }

  function resetAdjustmentSliders() {
    EditorState.brightness = 1.0;
    EditorState.contrast = 1.0;
    EditorState.saturation = 1.0;

    ['brightness', 'contrast', 'saturation'].forEach(name => {
      const slider = document.getElementById(`${name}-slider`);
      const value = document.getElementById(`${name}-value`);
      if (slider) slider.value = 100;
      if (value) value.textContent = '1.00';
    });

    applyPreviewFilters();
  }

  async function applyResize() {
    const width = parseInt(document.getElementById('resize-width')?.value);
    const height = parseInt(document.getElementById('resize-height')?.value);

    if (!width || !height || width < 1 || height < 1) {
      Toast.warning('Enter valid dimensions');
      return;
    }

    if (width > 4096 || height > 4096) {
      Toast.warning('Maximum dimension is 4096px');
      return;
    }

    const maintainRatio = document.getElementById('resize-ratio')?.checked ?? true;
    await applyLocalEdit('resize', { width, height, maintain_ratio: maintainRatio });
  }

  function updateResizeHeight() {
    const ratio = EditorState.imageWidth / EditorState.imageHeight;
    const widthInput = document.getElementById('resize-width');
    const heightInput = document.getElementById('resize-height');
    if (widthInput && heightInput && document.getElementById('resize-ratio')?.checked) {
      heightInput.value = Math.round(parseInt(widthInput.value) / ratio) || '';
    }
  }

  function updateResizeWidth() {
    const ratio = EditorState.imageWidth / EditorState.imageHeight;
    const widthInput = document.getElementById('resize-width');
    const heightInput = document.getElementById('resize-height');
    if (widthInput && heightInput && document.getElementById('resize-ratio')?.checked) {
      widthInput.value = Math.round(parseInt(heightInput.value) * ratio) || '';
    }
  }

  async function applyRotate() {
    const activeBtn = document.querySelector('[data-rotate-angle].active');
    const angle = parseFloat(activeBtn?.dataset.rotateAngle || 90);
    await applyLocalEdit('rotate', { angle, expand: true });
  }

  async function applyFlip() {
    const activeBtn = document.querySelector('[data-flip-dir].active');
    const direction = activeBtn?.dataset.flipDir || 'horizontal';
    await applyLocalEdit('flip', { direction });
  }

  async function applyCrop() {
    // For now, use full image dimensions (crop UI would need a crop overlay)
    const x = parseInt(document.getElementById('crop-x')?.value) || 0;
    const y = parseInt(document.getElementById('crop-y')?.value) || 0;
    const width = parseInt(document.getElementById('crop-width')?.value) || EditorState.imageWidth;
    const height = parseInt(document.getElementById('crop-height')?.value) || EditorState.imageHeight;

    await applyLocalEdit('crop', { x, y, width, height });
  }

  async function applyLocalEdit(operation, params) {
    if (!EditorState.imageId) {
      Toast.warning('No image loaded');
      return;
    }

    EditorState.isProcessing = true;
    showEditorLoading(`Applying ${operation}...`);

    try {
      const resp = await fetch('/api/v1/editor/local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_id: EditorState.imageId,
          operation: operation,
          params: params,
        }),
      });

      const data = await resp.json();

      if (!resp.ok) throw new Error(data.error || 'Edit failed');

      // Update state with new version
      addUndoState();
      EditorState.currentVersionId = data.version.id;
      updateCanvasImage(data.version.url);
      await refreshVersions();

      Toast.success(`${operation} applied successfully!`);

    } catch (err) {
      Toast.error(err.message || 'Edit failed');
    } finally {
      EditorState.isProcessing = false;
      hideEditorLoading();
    }
  }

  // ============================================================
  // AI EDITING
  // ============================================================

  function startAIEdit(tool) {
    EditorState.aiOperation = tool;

    // Switch to AI tab
    setActiveTab('ai');

    // Show appropriate UI
    document.querySelectorAll('.editor-ai-section').forEach(el => {
      el.style.display = 'none';
    });
    document.getElementById(`ai-section-${tool}`)?.style.display = 'block';

    // Enable mask for inpainting
    if (tool === 'inpaint') {
      enableMaskMode();
    } else {
      disableMaskMode();
    }
  }

  async function submitAIEdit() {
    const operation = EditorState.aiOperation;
    const prompt = EditorState.aiPrompt.trim();

    if (!operation) {
      Toast.warning('Select an AI tool first');
      return;
    }

    if (!prompt) {
      Toast.warning('Enter a prompt describing the desired change');
      return;
    }

    if (!EditorState.imageId) {
      Toast.warning('No image loaded');
      return;
    }

    EditorState.isProcessing = true;
    showEditorLoading('AI processing...');

    try {
      const body = {
        image_id: EditorState.imageId,
        operation: operation,
        prompt: prompt,
        params: {
          provider: 'stub', // Would come from settings
        },
      };

      // Add mask data if inpainting
      if (operation === 'inpaint' && EditorState.maskCanvas) {
        const maskData = EditorState.maskCanvas.toDataURL('image/png');
        body.mask = maskData;
      }

      // Add outpaint direction
      if (operation === 'outpaint') {
        body.params.direction = EditorState.outpaintDirection;
        body.params.extend_percent = 25;
      }

      // Add strength for retexture
      if (operation === 'retexture') {
        body.params.strength = parseFloat(document.getElementById('retexture-strength')?.value || 70) / 100;
      }

      const resp = await fetch('/api/v1/editor/ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await resp.json();

      if (!resp.ok) throw new Error(data.error || 'AI edit failed');

      addUndoState();
      EditorState.currentVersionId = data.version.id;
      updateCanvasImage(data.version.url);
      await refreshVersions();

      // Clear mask
      clearMask();

      Toast.success('AI edit applied!');

    } catch (err) {
      Toast.error(err.message || 'AI edit failed');
    } finally {
      EditorState.isProcessing = false;
      hideEditorLoading();
    }
  }

  // ============================================================
  // MASKING SYSTEM
  // ============================================================

  function initMaskCanvas() {
    const container = document.getElementById('editor-canvas-container');
    if (!container) return;

    const canvas = document.createElement('canvas');
    canvas.id = 'editor-mask-canvas';
    canvas.className = 'editor-mask-canvas';
    canvas.style.display = 'none';
    container.appendChild(canvas);

    EditorState.maskCanvas = canvas;
    EditorState.maskCtx = canvas.getContext('2d');

    // Mouse events
    canvas.addEventListener('mousedown', startMaskDraw);
    canvas.addEventListener('mousemove', drawMask);
    canvas.addEventListener('mouseup', stopMaskDraw);
    canvas.addEventListener('mouseleave', stopMaskDraw);

    // Touch events
    canvas.addEventListener('touchstart', handleTouchStart(startMaskDraw), { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove(drawMask), { passive: false });
    canvas.addEventListener('touchend', stopMaskDraw);
  }

  function setupMaskTools() {
    document.getElementById('mask-brush')?.addEventListener('click', () => {
      EditorState.maskTool = 'brush';
      updateMaskToolUI();
    });

    document.getElementById('mask-erase')?.addEventListener('click', () => {
      EditorState.maskTool = 'erase';
      updateMaskToolUI();
    });

    document.getElementById('mask-size')?.addEventListener('input', (e) => {
      EditorState.maskBrushSize = parseInt(e.target.value);
      document.getElementById('mask-size-value').textContent = e.target.value + 'px';
    });

    document.getElementById('mask-undo')?.addEventListener('click', maskUndo);
    document.getElementById('mask-redo')?.addEventListener('click', maskRedo);
    document.getElementById('mask-clear')?.addEventListener('click', clearMask);
  }

  function enableMaskMode() {
    EditorState.maskMode = true;
    const canvas = EditorState.maskCanvas;
    if (!canvas) return;

    // Size to match image display
    const imgEl = document.getElementById('editor-canvas-img');
    if (imgEl) {
      canvas.width = imgEl.clientWidth;
      canvas.height = imgEl.clientHeight;

      // Position over image
      const rect = imgEl.getBoundingClientRect();
      const containerRect = document.getElementById('editor-canvas-container').getBoundingClientRect();
      canvas.style.left = (rect.left - containerRect.left) + 'px';
      canvas.style.top = (rect.top - containerRect.top) + 'px';
    }

    canvas.style.display = 'block';
    document.getElementById('editor-mask-toolbar')?.classList.add('active');

    saveMaskState();
  }

  function disableMaskMode() {
    EditorState.maskMode = false;
    const canvas = EditorState.maskCanvas;
    if (canvas) {
      canvas.style.display = 'none';
    }
    document.getElementById('editor-mask-toolbar')?.classList.remove('active');
  }

  function startMaskDraw(e) {
    EditorState.isDrawing = true;
    const pos = getMaskPosition(e);
    EditorState.maskCtx.beginPath();
    EditorState.maskCtx.moveTo(pos.x, pos.y);
  }

  function drawMask(e) {
    if (!EditorState.isDrawing) return;

    const pos = getMaskPosition(e);
    const ctx = EditorState.maskCtx;

    ctx.lineWidth = EditorState.maskBrushSize;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (EditorState.maskTool === 'brush') {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = 'rgba(255, 0, 100, 0.5)';
    } else {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = 'rgba(0, 0, 0, 1)';
    }

    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
  }

  function stopMaskDraw() {
    if (EditorState.isDrawing) {
      EditorState.isDrawing = false;
      saveMaskState();
    }
  }

  function getMaskPosition(e) {
    const canvas = EditorState.maskCanvas;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.clientX || (e.touches && e.touches[0]?.clientX) || 0;
    const clientY = e.clientY || (e.touches && e.touches[0]?.clientY) || 0;

    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
    };
  }

  function saveMaskState() {
    const canvas = EditorState.maskCanvas;
    if (!canvas) return;

    // Remove any redo states
    EditorState.maskHistory = EditorState.maskHistory.slice(0, EditorState.maskHistoryIndex + 1);

    // Save current state
    EditorState.maskHistory.push(canvas.toDataURL());
    EditorState.maskHistoryIndex = EditorState.maskHistory.length - 1;

    // Limit history
    if (EditorState.maskHistory.length > 30) {
      EditorState.maskHistory.shift();
      EditorState.maskHistoryIndex--;
    }
  }

  function maskUndo() {
    if (EditorState.maskHistoryIndex > 0) {
      EditorState.maskHistoryIndex--;
      restoreMaskState(EditorState.maskHistory[EditorState.maskHistoryIndex]);
    }
  }

  function maskRedo() {
    if (EditorState.maskHistoryIndex < EditorState.maskHistory.length - 1) {
      EditorState.maskHistoryIndex++;
      restoreMaskState(EditorState.maskHistory[EditorState.maskHistoryIndex]);
    }
  }

  function restoreMaskState(dataUrl) {
    const canvas = EditorState.maskCanvas;
    const ctx = EditorState.maskCtx;
    if (!canvas || !dataUrl) return;

    const img = new Image();
    img.onload = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
    };
    img.src = dataUrl;
  }

  function clearMask() {
    const canvas = EditorState.maskCanvas;
    if (!canvas) return;

    EditorState.maskCtx.clearRect(0, 0, canvas.width, canvas.height);
    saveMaskState();
  }

  function updateMaskToolUI() {
    document.getElementById('mask-brush')?.classList.toggle('active', EditorState.maskTool === 'brush');
    document.getElementById('mask-erase')?.classList.toggle('active', EditorState.maskTool === 'erase');
  }

  // Touch helpers
  function handleTouchStart(handler) {
    return (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      handler(touch);
    };
  }

  function handleTouchMove(handler) {
    return (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      handler(touch);
    };
  }

  // ============================================================
  // VERSIONING
  // ============================================================

  async function refreshVersions() {
    if (!EditorState.imageId) return;

    try {
      const resp = await fetch(`/api/v1/editor/images/${EditorState.imageId}/versions`);
      if (!resp.ok) return;

      const data = await resp.json();
      EditorState.versions = data.versions || [];
      renderVersionList();
    } catch (e) { /* silent */ }
  }

  function renderVersionList() {
    const container = document.getElementById('version-list');
    if (!container) return;

    container.innerHTML = '';

    if (EditorState.versions.length === 0) {
      container.innerHTML = `
        <div class="editor-empty-state" style="padding:var(--space-6);">
          <p class="text-sm text-muted">No version history yet</p>
        </div>
      `;
      return;
    }

    EditorState.versions.forEach(v => {
      const item = document.createElement('div');
      item.className = `editor-version-item ${v.id === EditorState.currentVersionId ? 'active' : ''}`;
      item.onclick = () => loadVersion(v);

      const badgeClass = v.edit_type === 'original' ? 'original' :
                         v.edit_type.startsWith('ai_') ? 'ai' : 'local';
      const badgeText = v.edit_type === 'original' ? 'Original' :
                        v.edit_type.startsWith('ai_') ? 'AI' : 'Local';

      item.innerHTML = `
        <img class="editor-version-thumb" src="${v.url}" alt="v${v.version_number}" loading="lazy">
        <div class="editor-version-info">
          <div class="editor-version-title">Version ${v.version_number}</div>
          <div class="editor-version-meta">${v.edit_description || v.edit_type}</div>
        </div>
        <span class="editor-version-badge ${badgeClass}">${badgeText}</span>
      `;

      container.appendChild(item);
    });
  }

  async function loadVersion(version) {
    EditorState.currentVersionId = version.id;
    updateCanvasImage(version.url);
    renderVersionList();
  }

  async function saveAsVersion() {
    Toast.info('Current state saved as new version');
    await refreshVersions();
  }

  // ============================================================
  // BEFORE/AFTER COMPARISON
  // ============================================================

  function toggleComparison() {
    if (EditorState.comparisonMode) {
      exitComparison();
      return;
    }

    if (EditorState.versions.length < 2) {
      Toast.info('Need at least 2 versions for comparison');
      return;
    }

    // Find the version to compare against (one before current)
    const currentIndex = EditorState.versions.findIndex(v => v.id === EditorState.currentVersionId);
    if (currentIndex <= 0) {
      Toast.info('Cannot compare with the original');
      return;
    }

    const compareVersion = EditorState.versions[currentIndex - 1];
    enterComparison(compareVersion);
  }

  function enterComparison(beforeVersion) {
    EditorState.comparisonMode = true;
    EditorState.comparisonVersionId = beforeVersion.id;

    const canvasContainer = document.getElementById('editor-canvas-container');
    if (!canvasContainer) return;

    const currentVersion = EditorState.versions.find(v => v.id === EditorState.currentVersionId);
    if (!currentVersion) return;

    // Create comparison UI
    const comparison = document.createElement('div');
    comparison.id = 'editor-comparison';
    comparison.className = 'editor-comparison';

    comparison.innerHTML = `
      <div class="editor-comparison-before">
        <img src="${beforeVersion.url}" alt="Before">
      </div>
      <div class="editor-comparison-after">
        <img src="${currentVersion.url}" alt="After">
      </div>
      <div class="editor-comparison-divider" id="comparison-divider">
        <div class="editor-comparison-handle">⇔</div>
      </div>
      <div class="editor-comparison-label before">Before (v${beforeVersion.version_number})</div>
      <div class="editor-comparison-label after">After (v${currentVersion.version_number})</div>
    `;

    // Hide canvas, show comparison
    document.getElementById('editor-canvas-img').style.display = 'none';
    canvasContainer.appendChild(comparison);

    // Setup drag
    setupComparisonDrag(comparison);

    Toast.info('Comparison mode — drag the slider');
  }

  function exitComparison() {
    EditorState.comparisonMode = false;
    EditorState.comparisonVersionId = null;

    const comparison = document.getElementById('editor-comparison');
    if (comparison) comparison.remove();

    document.getElementById('editor-canvas-img').style.display = 'block';
  }

  function setupComparisonDrag(container) {
    const divider = document.getElementById('comparison-divider');
    if (!divider) return;

    let isDragging = false;

    const updatePosition = (clientX) => {
      const rect = container.getBoundingClientRect();
      let x = clientX - rect.left;
      x = Math.max(0, Math.min(x, rect.width));
      const pct = (x / rect.width) * 100;

      divider.style.left = pct + '%';
      container.querySelector('.editor-comparison-before').style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
    };

    divider.addEventListener('mousedown', (e) => {
      isDragging = true;
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (isDragging) updatePosition(e.clientX);
    });

    document.addEventListener('mouseup', () => {
      isDragging = false;
    });

    // Touch support
    divider.addEventListener('touchstart', (e) => {
      isDragging = true;
      e.preventDefault();
    });

    document.addEventListener('touchmove', (e) => {
      if (isDragging) updatePosition(e.touches[0].clientX);
    });

    document.addEventListener('touchend', () => {
      isDragging = false;
    });
  }

  // ============================================================
  // UNDO/REDO
  // ============================================================

  function addUndoState() {
    EditorState.undoStack.push({
      imageUrl: EditorState.imageUrl,
      versionId: EditorState.currentVersionId,
      width: EditorState.imageWidth,
      height: EditorState.imageHeight,
    });

    if (EditorState.undoStack.length > EditorState.maxUndoSteps) {
      EditorState.undoStack.shift();
    }

    // Clear redo stack on new action
    EditorState.redoStack = [];

    updateUndoRedoButtons();
  }

  function undo() {
    if (EditorState.undoStack.length === 0) return;

    const state = EditorState.undoStack.pop();

    // Save current to redo
    EditorState.redoStack.push({
      imageUrl: EditorState.imageUrl,
      versionId: EditorState.currentVersionId,
      width: EditorState.imageWidth,
      height: EditorState.imageHeight,
    });

    // Restore
    EditorState.imageUrl = state.imageUrl;
    EditorState.currentVersionId = state.versionId;
    EditorState.imageWidth = state.width;
    EditorState.imageHeight = state.height;

    updateCanvasImage(state.imageUrl);
    updateUndoRedoButtons();
  }

  function redo() {
    if (EditorState.redoStack.length === 0) return;

    const state = EditorState.redoStack.pop();

    // Save current to undo
    EditorState.undoStack.push({
      imageUrl: EditorState.imageUrl,
      versionId: EditorState.currentVersionId,
      width: EditorState.imageWidth,
      height: EditorState.imageHeight,
    });

    // Restore
    EditorState.imageUrl = state.imageUrl;
    EditorState.currentVersionId = state.versionId;
    EditorState.imageWidth = state.width;
    EditorState.imageHeight = state.height;

    updateCanvasImage(state.imageUrl);
    updateUndoRedoButtons();
  }

  function updateUndoRedoButtons() {
    const undoBtn = document.getElementById('toolbar-undo');
    const redoBtn = document.getElementById('toolbar-redo');

    if (undoBtn) undoBtn.disabled = EditorState.undoStack.length === 0;
    if (redoBtn) redoBtn.disabled = EditorState.redoStack.length === 0;
  }

  function resetEdits() {
    if (EditorState.versions.length === 0) return;

    const original = EditorState.versions.find(v => v.version_number === 1);
    if (original) {
      addUndoState();
      EditorState.currentVersionId = original.id;
      updateCanvasImage(original.url);
      Toast.info('Reset to original');
    }
  }

  // ============================================================
  // CANVAS OPERATIONS
  // ============================================================

  function updateCanvasImage(url) {
    const img = document.getElementById('editor-canvas-img');
    if (!img) return;

    EditorState.imageUrl = url;
    img.src = url;
    img.onload = () => {
      EditorState.imageWidth = img.naturalWidth;
      EditorState.imageHeight = img.naturalHeight;
      updateImageInfo();
      fitCanvasToView();
    };
  }

  function fitCanvasToView() {
    const container = document.getElementById('editor-canvas-container');
    const img = document.getElementById('editor-canvas-img');
    if (!container || !img) return;

    const containerW = container.clientWidth - 32;
    const containerH = container.clientHeight - 32;

    const scaleX = containerW / EditorState.imageWidth;
    const scaleY = containerH / EditorState.imageHeight;
    EditorState.zoom = Math.min(scaleX, scaleY, 1);

    updateZoomDisplay();
  }

  function updateImageInfo() {
    const info = document.getElementById('editor-image-info');
    if (info) {
      info.textContent = `${EditorState.imageWidth} × ${EditorState.imageHeight}px`;
    }
  }

  function updateZoomDisplay() {
    const display = document.getElementById('zoom-level');
    if (display) {
      display.textContent = Math.round(EditorState.zoom * 100) + '%';
    }
  }

  // ============================================================
  // DOWNLOAD
  // ============================================================

  function downloadCurrent() {
    if (!EditorState.currentVersionId) {
      // Download original
      if (EditorState.imageId) {
        window.location.href = `/api/v1/images/${EditorState.imageId}/download`;
      }
      return;
    }

    window.location.href = `/api/v1/editor/versions/${EditorState.currentVersionId}/file`;
  }

  // ============================================================
  // KEYBOARD SHORTCUTS
  // ============================================================

  function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl/Cmd + Z = Undo
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      }

      // Ctrl/Cmd + Shift + Z = Redo
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && e.shiftKey) {
        e.preventDefault();
        redo();
      }

      // Ctrl/Cmd + S = Save version
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveAsVersion();
      }

      // Escape = Cancel/Close
      if (e.key === 'Escape') {
        if (EditorState.comparisonMode) exitComparison();
        if (EditorState.maskMode) disableMaskMode();
        setActiveTool(null);
      }

      // Tool shortcuts
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        switch (e.key) {
          case 'c': setActiveTool('crop'); break;
          case 'r': setActiveTool('rotate'); break;
          case 'f': setActiveTool('flip'); break;
          case 'b': setActiveTool('brightness'); break;
          case 'k': setActiveTool('contrast'); break;
          case 's': setActiveTool('saturation'); break;
        }
      }
    });
  }

  // ============================================================
  // UI HELPERS
  // ============================================================

  function showEditorLoading(text) {
    const loading = document.getElementById('editor-loading');
    const textEl = document.getElementById('editor-loading-text');
    if (loading) loading.style.display = 'flex';
    if (textEl) textEl.textContent = text || 'Processing...';
  }

  function hideEditorLoading() {
    const loading = document.getElementById('editor-loading');
    if (loading) loading.style.display = 'none';
  }

  function hideEditorEmptyState() {
    const empty = document.getElementById('editor-empty-state');
    if (empty) empty.style.display = 'none';
  }

  // ============================================================
  // GLOBAL EXPORTS
  // ============================================================

  window.EditorState = EditorState;
  window.loadImageForEditing = loadImageForEditing;

  // ============================================================
  // INIT ON LOAD
  // ============================================================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
