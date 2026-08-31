/* ============================================================
   ADVANCED UI.JS — Advanced Interactions and User Experience
   ============================================================ */

(function () {
  'use strict';

  /* ---- Advanced Drag and Drop System ---- */
  const AdvancedDragDrop = {
    dropzones: new Map(),
    draggedItem: null,
    dragData: null,

    init() {
      this.setupGlobalListeners();
      this.setupDropzones();
    },

    setupGlobalListeners() {
      document.addEventListener('dragstart', (e) => this.handleDragStart(e));
      document.addEventListener('dragend', (e) => this.handleDragEnd(e));
      document.addEventListener('dragover', (e) => this.handleDragOver(e));
      document.addEventListener('drop', (e) => this.handleDrop(e));
    },

    setupDropzones() {
      document.querySelectorAll('[data-dropzone]').forEach(zone => {
        const zoneId = zone.dataset.dropzone;
        this.dropzones.set(zoneId, {
          element: zone,
          acceptedTypes: zone.dataset.accept || '*',
          onDrop: zone.dataset.onDrop || null
        });

        zone.addEventListener('dragenter', (e) => this.handleDragEnter(e, zone));
        zone.addEventListener('dragleave', (e) => this.handleDragLeave(e, zone));
      });
    },

    handleDragStart(e) {
      const draggable = e.target.closest('[data-draggable]');
      if (!draggable) return;

      this.draggedItem = draggable;
      this.dragData = JSON.parse(draggable.dataset.draggable || '{}');
      
      draggable.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', JSON.stringify(this.dragData));
    },

    handleDragEnd(e) {
      if (this.draggedItem) {
        this.draggedItem.classList.remove('dragging');
        this.draggedItem = null;
        this.dragData = null;
      }
      
      this.dropzones.forEach(zone => {
        zone.element.classList.remove('drag-over');
      });
    },

    handleDragOver(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    },

    handleDragEnter(e, zone) {
      e.preventDefault();
      zone.classList.add('drag-over');
    },

    handleDragLeave(e, zone) {
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove('drag-over');
      }
    },

    handleDrop(e) {
      e.preventDefault();
      
      const dropzone = e.target.closest('[data-dropzone]');
      if (!dropzone) return;

      dropzone.classList.remove('drag-over');
      
      const zoneId = dropzone.dataset.dropzone;
      const zoneConfig = this.dropzones.get(zoneId);
      
      if (zoneConfig && zoneConfig.onDrop) {
        const callback = window[zoneConfig.onDrop];
        if (typeof callback === 'function') {
          callback(this.dragData, dropzone);
        }
      }
    }
  };

  /* ---- Advanced Image Zoom and Pan ---- */
  const AdvancedImageViewer = {
    currentZoom: 1,
    minZoom: 0.1,
    maxZoom: 10,
    isPanning: false,
    startX: 0,
    startY: 0,
    translateX: 0,
    translateY: 0,

    init(containerSelector = '[data-image-viewer]') {
      document.querySelectorAll(containerSelector).forEach(container => {
        this.setupViewer(container);
      });
    },

    setupViewer(container) {
      const image = container.querySelector('img');
      if (!image) return;

      let zoomLevel = 1;
      let panX = 0;
      let panY = 0;
      let isDragging = false;
      let startX, startY;

      // Mouse wheel zoom
      container.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        zoomLevel = Math.max(this.minZoom, Math.min(this.maxZoom, zoomLevel * delta));
        this.updateTransform(image, zoomLevel, panX, panY);
      });

      // Mouse drag pan
      container.addEventListener('mousedown', (e) => {
        if (zoomLevel > 1) {
          isDragging = true;
          startX = e.clientX - panX;
          startY = e.clientY - panY;
          container.style.cursor = 'grabbing';
        }
      });

      document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        panX = e.clientX - startX;
        panY = e.clientY - startY;
        this.updateTransform(image, zoomLevel, panX, panY);
      });

      document.addEventListener('mouseup', () => {
        isDragging = false;
        container.style.cursor = zoomLevel > 1 ? 'grab' : 'default';
      });

      // Double click to reset
      container.addEventListener('dblclick', () => {
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        this.updateTransform(image, zoomLevel, panX, panY);
      });

      // Touch support
      let lastTouchDistance = 0;
      
      container.addEventListener('touchstart', (e) => {
        if (e.touches.length === 2) {
          lastTouchDistance = this.getTouchDistance(e.touches);
        }
      });

      container.addEventListener('touchmove', (e) => {
        if (e.touches.length === 2) {
          e.preventDefault();
          const currentDistance = this.getTouchDistance(e.touches);
          const delta = currentDistance / lastTouchDistance;
          zoomLevel = Math.max(this.minZoom, Math.min(this.maxZoom, zoomLevel * delta));
          lastTouchDistance = currentDistance;
          this.updateTransform(image, zoomLevel, panX, panY);
        }
      });
    },

    updateTransform(image, zoom, panX, panY) {
      image.style.transform = `scale(${zoom}) translate(${panX}px, ${panY}px)`;
      image.style.transformOrigin = 'center center';
    },

    getTouchDistance(touches) {
      const dx = touches[0].clientX - touches[1].clientX;
      const dy = touches[0].clientY - touches[1].clientY;
      return Math.sqrt(dx * dx + dy * dy);
    }
  };

  /* ---- Advanced Keyboard Shortcuts ---- */
  const KeyboardShortcuts = {
    shortcuts: new Map(),

    init() {
      this.setupDefaultShortcuts();
      this.setupCustomShortcuts();
      document.addEventListener('keydown', (e) => this.handleKeyDown(e));
    },

    setupDefaultShortcuts() {
      // Global shortcuts
      this.register('ctrl+/', 'showHelp', () => this.showHelp());
      this.register('escape', 'closeModals', () => this.closeAllModals());
      
      // Navigation
      this.register('alt+h', 'goHome', () => window.location.href = '/');
      this.register('alt+g', 'goGenerate', () => window.location.href = '/generate');
      this.register('alt+e', 'goEditor', () => window.location.href = '/editor');
      this.register('alt+h', 'goHistory', () => window.location.href = '/history');
      this.register('alt+l', 'goGallery', () => window.location.href = '/gallery');
      
      // Actions
      this.register('ctrl+n', 'newImage', () => window.location.href = '/generate');
      this.register('ctrl+s', 'save', () => this.triggerSave());
      this.register('ctrl+d', 'download', () => this.triggerDownload());
    },

    setupCustomShortcuts() {
      document.querySelectorAll('[data-shortcut]').forEach(el => {
        const shortcut = el.dataset.shortcut;
        const action = el.dataset.action;
        if (shortcut && action) {
          this.register(shortcut, action, () => {
            if (el.tagName === 'BUTTON' || el.tagName === 'A') {
              el.click();
            }
          });
        }
      });
    },

    register(keyCombo, name, callback) {
      this.shortcuts.set(keyCombo.toLowerCase(), { name, callback });
    },

    handleKeyDown(e) {
      // Don't trigger shortcuts in input fields
      if (e.target.matches('input, textarea, select, [contenteditable]')) {
        return;
      }

      const keyCombo = this.buildKeyCombo(e);
      const shortcut = this.shortcuts.get(keyCombo);
      
      if (shortcut) {
        e.preventDefault();
        shortcut.callback();
      }
    },

    buildKeyCombo(e) {
      const parts = [];
      if (e.ctrlKey) parts.push('ctrl');
      if (e.altKey) parts.push('alt');
      if (e.shiftKey) parts.push('shift');
      if (e.metaKey) parts.push('meta');
      parts.push(e.key.toLowerCase());
      return parts.join('+');
    },

    showHelp() {
      const helpHTML = `
        <div class="keyboard-shortcuts-help">
          <h3>Keyboard Shortcuts</h3>
          <div class="shortcut-list">
            ${Array.from(this.shortcuts.entries()).map(([key, {name}]) => `
              <div class="shortcut-item">
                <kbd>${this.formatKey(key)}</kbd>
                <span>${name}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
      
      // Show as modal or toast
      Toast.info('Keyboard shortcuts: Ctrl+? for help');
    },

    formatKey(keyCombo) {
      return keyCombo.split('+').map(k => 
        k.length === 1 ? k.toUpperCase() : k.charAt(0).toUpperCase() + k.slice(1)
      ).join(' + ');
    },

    closeAllModals() {
      document.querySelectorAll('.modal-overlay.active').forEach(modal => {
        modal.classList.remove('active');
      });
      document.body.style.overflow = '';
    },

    triggerSave() {
      const saveBtn = document.querySelector('[data-action="save"]');
      if (saveBtn) saveBtn.click();
    },

    triggerDownload() {
      const downloadBtn = document.querySelector('[data-action="download"]');
      if (downloadBtn) downloadBtn.click();
    }
  };

  /* ---- Advanced Toast Notifications ---- */
  const AdvancedToast = {
    container: null,
    queue: [],
    isProcessing: false,

    init() {
      this.container = document.getElementById('toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'toast-container advanced';
        document.body.appendChild(this.container);
      }
    },

    show(message, type = 'info', options = {}) {
      const toast = {
        message,
        type,
        options: {
          duration: options.duration || 4000,
          persistent: options.persistent || false,
          actions: options.actions || [],
          ...options
        },
        id: Date.now()
      };

      this.queue.push(toast);
      this.processQueue();
    },

    processQueue() {
      if (this.isProcessing || this.queue.length === 0) return;

      this.isProcessing = true;
      const toast = this.queue.shift();
      this.renderToast(toast);
    },

    renderToast(toast) {
      const el = document.createElement('div');
      el.className = `toast toast-${toast.type} toast-advanced`;
      el.dataset.toastId = toast.id;
      
      const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
      };

      let actionsHTML = '';
      if (toast.options.actions.length > 0) {
        actionsHTML = `
          <div class="toast-actions">
            ${toast.options.actions.map(action => `
              <button class="btn btn-sm ${action.class || 'btn-ghost'}" 
                      data-action="${action.action}"
                      onclick="AdvancedToast.handleAction(${toast.id}, '${action.action}')">
                ${action.label}
              </button>
            `).join('')}
          </div>
        `;
      }

      el.innerHTML = `
        <div class="toast-content">
          <span class="toast-icon">${icons[toast.type] || icons.info}</span>
          <span class="toast-message">${toast.message}</span>
          ${!toast.options.persistent ? `
            <button class="toast-close" onclick="AdvancedToast.dismiss(${toast.id})">✕</button>
          ` : ''}
        </div>
        ${actionsHTML}
        <div class="toast-progress" style="animation-duration: ${toast.options.duration}ms"></div>
      `;

      this.container.appendChild(el);

      // Animate in
      requestAnimationFrame(() => {
        el.classList.add('toast-enter');
      });

      // Auto dismiss if not persistent
      if (!toast.options.persistent) {
        setTimeout(() => this.dismiss(toast.id), toast.options.duration);
      }
    },

    dismiss(toastId) {
      const el = this.container.querySelector(`[data-toast-id="${toastId}"]`);
      if (el) {
        el.classList.add('toast-exit');
        setTimeout(() => {
          el.remove();
          this.isProcessing = false;
          this.processQueue();
        }, 300);
      }
    },

    handleAction(toastId, action) {
      const toast = this.queue.find(t => t.id === toastId);
      if (toast && toast.options.onAction) {
        toast.options.onAction(action);
      }
      this.dismiss(toastId);
    },

    success(msg, options) { this.show(msg, 'success', options); },
    error(msg, options) { this.show(msg, 'error', { ...options, duration: 6000 }); },
    warning(msg, options) { this.show(msg, 'warning', { ...options, duration: 5000 }); },
    info(msg, options) { this.show(msg, 'info', options); }
  };

  /* ---- Advanced Modal System ---- */
  const AdvancedModal = {
    stack: [],
    activeModal: null,

    show(id, options = {}) {
      const modal = document.getElementById(id);
      if (!modal) return;

      // Add to stack
      this.stack.push({ id, options });
      this.activeModal = modal;

      // Show modal
      modal.classList.add('active');
      document.body.style.overflow = 'hidden';

      // Focus management
      const focusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusable) focusable.focus();

      // Animation
      if (options.animation !== false) {
        modal.querySelector('.modal')?.classList.add('modal-animate-in');
      }

      // Callback
      if (options.onShow) {
        options.onShow(modal);
      }
    },

    hide(id, options = {}) {
      const modal = document.getElementById(id);
      if (!modal) return;

      // Remove from stack
      this.stack = this.stack.filter(m => m.id !== id);
      
      // Set new active modal
      this.activeModal = this.stack.length > 0 
        ? document.getElementById(this.stack[this.stack.length - 1].id)
        : null;

      // Animation
      if (options.animation !== false) {
        modal.querySelector('.modal')?.classList.add('modal-animate-out');
        setTimeout(() => {
          this.finalizeHide(modal);
        }, 200);
      } else {
        this.finalizeHide(modal);
      }

      // Callback
      if (options.onHide) {
        options.onHide(modal);
      }
    },

    finalizeHide(modal) {
      modal.classList.remove('active');
      modal.querySelector('.modal')?.classList.remove('modal-animate-in', 'modal-animate-out');
      
      if (this.stack.length === 0) {
        document.body.style.overflow = '';
      }
    },

    hideAll() {
      this.stack.forEach(({ id }) => this.hide(id, { animation: false }));
      this.stack = [];
    }
  };

  /* ---- Advanced Form Validation ---- */
  const AdvancedForm = {
    validators: new Map(),

    init() {
      this.setupForms();
      this.setupRealTimeValidation();
    },

    setupForms() {
      document.querySelectorAll('[data-validate]').forEach(form => {
        this.setupForm(form);
      });
    },

    setupForm(form) {
      const formId = form.dataset.validate;
      const rules = this.parseValidationRules(form);
      
      this.validators.set(formId, { form, rules });

      form.addEventListener('submit', (e) => {
        if (!this.validateForm(formId)) {
          e.preventDefault();
        }
      });
    },

    parseValidationRules(form) {
      const rules = {};
      form.querySelectorAll('[data-rule]').forEach(field => {
        const fieldName = field.name || field.id;
        rules[fieldName] = this.parseFieldRules(field);
      });
      return rules;
    },

    parseFieldRules(field) {
      const ruleString = field.dataset.rule;
      const rules = [];
      
      ruleString.split('|').forEach(rule => {
        const [name, ...params] = rule.split(':');
        rules.push({ name, params });
      });
      
      return rules;
    },

    setupRealTimeValidation() {
      document.querySelectorAll('[data-rule]').forEach(field => {
        field.addEventListener('blur', () => this.validateField(field));
        field.addEventListener('input', () => {
          if (field.classList.contains('error')) {
            this.validateField(field);
          }
        });
      });
    },

    validateField(field) {
      const rules = this.parseFieldRules(field);
      const value = field.value;
      let isValid = true;
      let errorMessage = '';

      for (const rule of rules) {
        const result = this.applyRule(rule, value);
        if (!result.valid) {
          isValid = false;
          errorMessage = result.message;
          break;
        }
      }

      this.updateFieldStatus(field, isValid, errorMessage);
      return isValid;
    },

    applyRule(rule, value) {
      switch (rule.name) {
        case 'required':
          return { valid: value.trim() !== '', message: 'This field is required' };
        case 'email':
          return { 
            valid: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value), 
            message: 'Please enter a valid email address' 
          };
        case 'min':
          return { 
            valid: value.length >= parseInt(rule.params[0]), 
            message: `Minimum ${rule.params[0]} characters required` 
          };
        case 'max':
          return { 
            valid: value.length <= parseInt(rule.params[0]), 
            message: `Maximum ${rule.params[0]} characters allowed` 
          };
        case 'pattern':
          return { 
            valid: new RegExp(rule.params[0]).test(value), 
            message: 'Invalid format' 
          };
        default:
          return { valid: true };
      }
    },

    updateFieldStatus(field, isValid, errorMessage) {
      field.classList.toggle('error', !isValid);
      field.classList.toggle('success', isValid);
      
      let errorElement = field.parentElement.querySelector('.field-error');
      if (!isValid && !errorElement) {
        errorElement = document.createElement('div');
        errorElement.className = 'field-error';
        field.parentElement.appendChild(errorElement);
      }
      
      if (errorElement) {
        errorElement.textContent = errorMessage;
        errorElement.style.display = isValid ? 'none' : 'block';
      }
    },

    validateForm(formId) {
      const { form, rules } = this.validators.get(formId);
      let isValid = true;

      Object.keys(rules).forEach(fieldName => {
        const field = form.querySelector(`[name="${fieldName}"], [id="${fieldName}"]`);
        if (field && !this.validateField(field)) {
          isValid = false;
        }
      });

      return isValid;
    }
  };

  /* ---- Advanced Loading States ---- */
  const AdvancedLoading = {
    show(container, options = {}) {
      const loader = document.createElement('div');
      loader.className = 'advanced-loader';
      loader.innerHTML = `
        <div class="loader-spinner"></div>
        <div class="loader-text">${options.text || 'Loading...'}</div>
      `;
      
      if (options.overlay) {
        loader.classList.add('loader-overlay');
      }
      
      container.appendChild(loader);
      return loader;
    },

    hide(loader) {
      if (loader) {
        loader.classList.add('loader-exit');
        setTimeout(() => loader.remove(), 300);
      }
    }
  };

  /* ---- Advanced Animations ---- */
  const AdvancedAnimations = {
    observer: null,

    init() {
      this.setupScrollAnimations();
      this.setupHoverAnimations();
    },

    setupScrollAnimations() {
      this.observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('animate-in');
            
            const animation = entry.target.dataset.animate;
            if (animation) {
              entry.target.style.animation = `${animation} 0.6s ease-out forwards`;
            }
          }
        });
      }, { threshold: 0.1 });

      document.querySelectorAll('[data-animate]').forEach(el => {
        this.observer.observe(el);
      });
    },

    setupHoverAnimations() {
      document.querySelectorAll('[data-hover-animate]').forEach(el => {
        const animation = el.dataset.hoverAnimate;
        el.addEventListener('mouseenter', () => {
          el.style.animation = `${animation} 0.3s ease-out`;
        });
        el.addEventListener('mouseleave', () => {
          el.style.animation = '';
        });
      });
    }
  };

  /* ---- Advanced Search/Filter ---- */
  const AdvancedSearch = {
    init() {
      this.setupInstantSearch();
      this.setupAdvancedFilters();
    },

    setupInstantSearch() {
      document.querySelectorAll('[data-instant-search]').forEach(input => {
        const target = input.dataset.target;
        const minChars = parseInt(input.dataset.minChars || 2);
        
        let debounceTimer;
        input.addEventListener('input', () => {
          clearTimeout(debounceTimer);
          
          if (input.value.length < minChars) {
            this.clearSearch(target);
            return;
          }
          
          debounceTimer = setTimeout(() => {
            this.performSearch(target, input.value);
          }, 300);
        });
      });
    },

    performSearch(target, query) {
      const container = document.querySelector(target);
      if (!container) return;

      const items = container.querySelectorAll('[data-searchable]');
      const normalizedQuery = query.toLowerCase();

      items.forEach(item => {
        const text = item.textContent.toLowerCase();
        const matches = text.includes(normalizedQuery);
        item.style.display = matches ? '' : 'none';
        
        if (matches) {
          this.highlightMatch(item, normalizedQuery);
        }
      });
    },

    highlightMatch(item, query) {
      // Remove existing highlights
      item.querySelectorAll('.search-highlight').forEach(el => {
        el.outerHTML = el.textContent;
      });

      // Add new highlights
      const text = item.textContent;
      const regex = new RegExp(`(${query})`, 'gi');
      item.innerHTML = text.replace(regex, '<mark class="search-highlight">$1</mark>');
    },

    clearSearch(target) {
      const container = document.querySelector(target);
      if (!container) return;

      const items = container.querySelectorAll('[data-searchable]');
      items.forEach(item => {
        item.style.display = '';
        item.querySelectorAll('.search-highlight').forEach(el => {
          el.outerHTML = el.textContent;
        });
      });
    },

    setupAdvancedFilters() {
      document.querySelectorAll('[data-advanced-filter]').forEach(filter => {
        this.setupFilter(filter);
      });
    },

    setupFilter(filter) {
      const target = filter.dataset.target;
      const filterType = filter.dataset.filterType;
      
      filter.addEventListener('change', () => {
        this.applyFilters(target);
      });
    },

    applyFilters(target) {
      const container = document.querySelector(target);
      if (!container) return;

      const filters = document.querySelectorAll(`[data-target="${target}"][data-advanced-filter]`);
      const activeFilters = Array.from(filters).map(f => ({
        type: f.dataset.filterType,
        value: f.value
      }));

      const items = container.querySelectorAll('[data-filterable]');
      
      items.forEach(item => {
        let passesFilters = true;
        
        for (const filter of activeFilters) {
          if (!this.itemPassesFilter(item, filter)) {
            passesFilters = false;
            break;
          }
        }
        
        item.style.display = passesFilters ? '' : 'none';
      });
    },

    itemPassesFilter(item, filter) {
      const itemValue = item.dataset[filter.type] || '';
      
      switch (filter.type) {
        case 'category':
          return filter.value === 'all' || itemValue === filter.value;
        case 'date':
          return this.dateFilter(itemValue, filter.value);
        case 'rating':
          return parseInt(itemValue) >= parseInt(filter.value);
        default:
          return true;
      }
    },

    dateFilter(itemValue, filterValue) {
      // Implement date filtering logic
      return true;
    }
  };

  /* ---- Advanced Table/Grid ---- */
  const AdvancedGrid = {
    init() {
      this.setupSortableGrids();
      this.setupResizableColumns();
    },

    setupSortableGrids() {
      document.querySelectorAll('[data-sortable-grid]').forEach(grid => {
        this.setupSortableGrid(grid);
      });
    },

    setupSortableGrid(grid) {
      const headers = grid.querySelectorAll('[data-sort]');
      
      headers.forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
          const sortBy = header.dataset.sort;
          const direction = header.dataset.sortDir || 'asc';
          this.sortGrid(grid, sortBy, direction);
          
          // Update direction for next click
          header.dataset.sortDir = direction === 'asc' ? 'desc' : 'asc';
        });
      });
    },

    sortGrid(grid, sortBy, direction) {
      const items = Array.from(grid.querySelectorAll('[data-grid-item]'));
      
      items.sort((a, b) => {
        const aVal = a.dataset[sortBy] || '';
        const bVal = b.dataset[sortBy] || '';
        
        const comparison = aVal.localeCompare(bVal, undefined, { 
          numeric: true, 
          sensitivity: 'base' 
        });
        
        return direction === 'asc' ? comparison : -comparison;
      });
      
      items.forEach(item => grid.appendChild(item));
    },

    setupResizableColumns() {
      document.querySelectorAll('[data-resizable-cols]').forEach(grid => {
        this.setupResizableColumnsForGrid(grid);
      });
    },

    setupResizableColumnsForGrid(grid) {
      const headers = grid.querySelectorAll('[data-resize]');
      
      headers.forEach(header => {
        const resizer = document.createElement('div');
        resizer.className = 'column-resizer';
        header.appendChild(resizer);
        
        let startX, startWidth;
        
        resizer.addEventListener('mousedown', (e) => {
          startX = e.clientX;
          startWidth = header.offsetWidth;
          document.addEventListener('mousemove', handleMouseMove);
          document.addEventListener('mouseup', handleMouseUp);
        });
        
        const handleMouseMove = (e) => {
          const width = startWidth + (e.clientX - startX);
          header.style.width = `${width}px`;
        };
        
        const handleMouseUp = () => {
          document.removeEventListener('mousemove', handleMouseMove);
          document.removeEventListener('mouseup', handleMouseUp);
        };
      });
    }
  };

  /* ---- Initialize all advanced UI components ---- */
  function init() {
    AdvancedDragDrop.init();
    AdvancedImageViewer.init();
    KeyboardShortcuts.init();
    AdvancedToast.init();
    AdvancedForm.init();
    AdvancedAnimations.init();
    AdvancedSearch.init();
    AdvancedGrid.init();

    // Expose globally
    window.AdvancedDragDrop = AdvancedDragDrop;
    window.AdvancedImageViewer = AdvancedImageViewer;
    window.KeyboardShortcuts = KeyboardShortcuts;
    window.AdvancedToast = AdvancedToast;
    window.AdvancedModal = AdvancedModal;
    window.AdvancedForm = AdvancedForm;
    window.AdvancedLoading = AdvancedLoading;
    window.AdvancedAnimations = AdvancedAnimations;
    window.AdvancedSearch = AdvancedSearch;
    window.AdvancedGrid = AdvancedGrid;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();