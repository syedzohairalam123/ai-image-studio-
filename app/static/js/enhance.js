/* ============================================================
   ENHANCE.JS — Additive interaction layer
   ============================================================
   Self-contained: doesn't modify or replace anything in app.js,
   editor.js, or advanced-ui.js. Safe to include on every page —
   every module below no-ops gracefully if its target elements
   aren't present.
   ============================================================ */

(function () {
  'use strict';

  const prefersReducedMotion = () =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ============================================================
     SCROLL REVEAL
     ============================================================ */

  const ScrollReveal = {
    init() {
      const targets = document.querySelectorAll('.reveal, .reveal-stagger');
      if (!targets.length) return;

      if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
        targets.forEach((el) => el.classList.add('is-visible'));
        return;
      }

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-visible');
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
      );

      targets.forEach((el) => observer.observe(el));
    },
  };

  /* ============================================================
     3D TILT-ON-HOVER
     Works via event delegation, so it automatically applies to
     .tilt-card elements added to the DOM later (e.g. gallery
     items loaded via fetch) with zero extra wiring required.
     ============================================================ */

  const TiltEffect = {
    maxTilt: 8, // degrees
    active: null,

    init() {
      if (prefersReducedMotion() || window.matchMedia('(hover: none)').matches) {
        return; // skip entirely on touch / reduced-motion
      }
      document.addEventListener('pointermove', this.onMove.bind(this), { passive: true });
      document.addEventListener('pointerleave', this.onLeave.bind(this), true);
    },

    onMove(e) {
      const card = e.target.closest && e.target.closest('.tilt-card');
      if (!card) {
        if (this.active && this.active !== card) this.reset(this.active);
        return;
      }
      const inner = card.querySelector('.tilt-card__inner') || card;
      const rect = card.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width; // 0..1
      const py = (e.clientY - rect.top) / rect.height;
      const ry = (px - 0.5) * this.maxTilt * 2;
      const rx = -(py - 0.5) * this.maxTilt * 2;
      card.style.setProperty('--rx', rx.toFixed(2) + 'deg');
      card.style.setProperty('--ry', ry.toFixed(2) + 'deg');
      card.style.setProperty('--glare-x', (px * 100).toFixed(1) + '%');
      card.style.setProperty('--glare-y', (py * 100).toFixed(1) + '%');
      this.active = card;
    },

    onLeave(e) {
      const card = e.target.closest && e.target.closest('.tilt-card');
      if (card) this.reset(card);
    },

    reset(card) {
      card.style.setProperty('--rx', '0deg');
      card.style.setProperty('--ry', '0deg');
      if (this.active === card) this.active = null;
    },
  };

  /* ============================================================
     COMMAND PALETTE (Cmd/Ctrl+K)
     ============================================================ */

  const CommandPalette = {
    items: [
      { label: 'Dashboard', path: '/', keywords: 'home overview', icon: 'M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' },
      { label: 'Generate', path: '/generate', keywords: 'create new image text to image', icon: 'M3 3h18v18H3zM8.5 8.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM21 15l-5-5-11 11' },
      { label: 'Editor', path: '/editor', keywords: 'edit crop filter retouch', icon: 'M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z' },
      { label: 'History', path: '/history', keywords: 'past generations log', icon: 'M12 6v6l4 2' },
      { label: 'Gallery', path: '/gallery', keywords: 'images grid all', icon: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z' },
      { label: 'Favorites', path: '/favorites', keywords: 'liked starred saved', icon: 'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1a5.5 5.5 0 0 0-7.8 7.8L12 21.2l8.8-8.8a5.5 5.5 0 0 0 0-7.8z' },
      { label: 'Collections', path: '/collections', keywords: 'folders albums organize', icon: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z' },
      { label: 'Saved Prompts', path: '/prompts', keywords: 'prompt library templates', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' },
      { label: 'Explore', path: '/explore', keywords: 'discover community browse', icon: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35' },
      { label: 'Styles', path: '/styles', keywords: 'presets categories', icon: 'M12 2l3.1 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.9-1.01z' },
      { label: 'Utilities', path: '/utilities', keywords: 'upscale background remove describe', icon: 'M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7' },
      { label: 'Settings', path: '/settings', keywords: 'account preferences api key', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z' },
      { label: 'Profile', path: '/profile', keywords: 'account user', icon: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 7a4 4 0 1 0 0 8 4 4 0 0 0 0-8z' },
    ],
    selectedIndex: 0,
    filtered: [],
    els: {},

    init() {
      this.buildDom();
      document.addEventListener('keydown', (e) => {
        const isK = e.key === 'k' || e.key === 'K';
        if ((e.metaKey || e.ctrlKey) && isK) {
          e.preventDefault();
          this.toggle();
        } else if (e.key === 'Escape' && this.isOpen()) {
          this.close();
        }
      });
      document.querySelectorAll('[data-cmdk-trigger]').forEach((btn) => {
        btn.addEventListener('click', () => this.open());
      });
    },

    buildDom() {
      if (document.querySelector('.cmdk-overlay')) return;
      const overlay = document.createElement('div');
      overlay.className = 'cmdk-overlay';
      overlay.innerHTML = `
        <div class="cmdk-panel glass-surface" role="dialog" aria-modal="true" aria-label="Command palette">
          <input type="text" class="cmdk-input" placeholder="Jump to… (Generate, Gallery, Settings)" autocomplete="off" spellcheck="false" />
          <div class="cmdk-list"></div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) this.close(); });

      this.els.overlay = overlay;
      this.els.input = overlay.querySelector('.cmdk-input');
      this.els.list = overlay.querySelector('.cmdk-list');

      this.els.input.addEventListener('input', () => this.filter(this.els.input.value));
      this.els.input.addEventListener('keydown', (e) => this.onInputKeydown(e));
    },

    isOpen() {
      return this.els.overlay && this.els.overlay.classList.contains('active');
    },

    toggle() { this.isOpen() ? this.close() : this.open(); },

    open() {
      this.els.overlay.classList.add('active');
      this.els.input.value = '';
      this.filter('');
      setTimeout(() => this.els.input.focus(), 30);
    },

    close() {
      this.els.overlay.classList.remove('active');
    },

    filter(query) {
      const q = query.trim().toLowerCase();
      this.filtered = !q
        ? this.items
        : this.items.filter((it) =>
            (it.label + ' ' + it.keywords).toLowerCase().includes(q)
          );
      this.selectedIndex = 0;
      this.render();
    },

    render() {
      if (!this.filtered.length) {
        this.els.list.innerHTML = '<div class="cmdk-empty">No matches — try a different page name.</div>';
        return;
      }
      this.els.list.innerHTML = this.filtered
        .map(
          (it, i) => `
        <div class="cmdk-item${i === this.selectedIndex ? ' active' : ''}" data-index="${i}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${it.icon}"/></svg>
          <span>${it.label}</span>
          ${i === this.selectedIndex ? '<span class="cmdk-hint">Enter</span>' : ''}
        </div>`
        )
        .join('');
      this.els.list.querySelectorAll('.cmdk-item').forEach((el) => {
        el.addEventListener('click', () => this.go(this.filtered[Number(el.dataset.index)]));
        el.addEventListener('mousemove', () => {
          this.selectedIndex = Number(el.dataset.index);
          this.render();
        });
      });
    },

    onInputKeydown(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.selectedIndex = Math.min(this.selectedIndex + 1, this.filtered.length - 1);
        this.render();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
        this.render();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const item = this.filtered[this.selectedIndex];
        if (item) this.go(item);
      }
    },

    go(item) {
      this.close();
      window.location.href = item.path;
    },
  };

  /* ============================================================
     PER-USER AVATAR GRADIENT
     Computes a stable hue from the username so each person's
     avatar has a distinct, repeatable gradient instead of every
     avatar being an identical flat brand color.
     ============================================================ */

  const AvatarGradient = {
    init() {
      document.querySelectorAll('[data-avatar-seed]').forEach((el) => {
        const seed = el.getAttribute('data-avatar-seed') || '';
        let hash = 0;
        for (let i = 0; i < seed.length; i++) {
          hash = (hash << 5) - hash + seed.charCodeAt(i);
          hash |= 0;
        }
        const hue = Math.abs(hash) % 360;
        el.style.setProperty('--avatar-hue', String(hue));
        el.classList.add('avatar-gradient');
      });
    },
  };

  function init() {
    ScrollReveal.init();
    TiltEffect.init();
    CommandPalette.init();
    AvatarGradient.init();
  }

  window.ScrollReveal = ScrollReveal;
  window.CommandPalette = CommandPalette;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
