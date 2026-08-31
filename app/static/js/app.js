/* ============================================================
   APP.JS — Core Application Logic
   ============================================================ */

(function () {
  'use strict';

  /* ---- Dark Mode ---- */
  const ThemeManager = {
    KEY: 'theme-preference',

    init() {
      const saved = localStorage.getItem(this.KEY);
      if (saved) {
        this.set(saved);
      } else {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        this.set(prefersDark ? 'dark' : 'light');
      }
      // Listen for OS changes
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem(this.KEY)) {
          this.set(e.matches ? 'dark' : 'light');
        }
      });
    },

    get() {
      return document.documentElement.getAttribute('data-theme') || 'light';
    },

    set(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      this.updateToggle(theme);
    },

    toggle() {
      const current = this.get();
      const next = current === 'dark' ? 'light' : 'dark';
      this.set(next);
      localStorage.setItem(this.KEY, next);
    },

    updateToggle(theme) {
      const toggle = document.getElementById('theme-toggle');
      if (toggle) {
        toggle.checked = theme === 'dark';
        const label = toggle.closest('.toggle')?.querySelector('.toggle-label');
        if (label) label.textContent = theme === 'dark' ? 'Dark' : 'Light';
      }
      // Update all theme toggle buttons
      document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
        btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
      });
    }
  };

  /* ---- Mobile Navigation ---- */
  const MobileNav = {
    isOpen: false,

    init() {
      const menuBtn = document.getElementById('mobile-menu-btn');
      const overlay = document.getElementById('drawer-overlay');
      const drawer = document.getElementById('mobile-drawer');

      if (menuBtn) {
        menuBtn.addEventListener('click', () => this.toggle());
      }
      if (overlay) {
        overlay.addEventListener('click', () => this.close());
      }
      // Close on escape
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.isOpen) this.close();
      });
    },

    toggle() {
      this.isOpen ? this.close() : this.open();
    },

    open() {
      this.isOpen = true;
      const drawer = document.getElementById('mobile-drawer');
      const overlay = document.getElementById('drawer-overlay');
      if (drawer) drawer.classList.add('active');
      if (overlay) overlay.classList.add('active');
      document.body.style.overflow = 'hidden';
    },

    close() {
      this.isOpen = false;
      const drawer = document.getElementById('mobile-drawer');
      const overlay = document.getElementById('drawer-overlay');
      if (drawer) drawer.classList.remove('active');
      if (overlay) overlay.classList.remove('active');
      document.body.style.overflow = '';
    }
  };

  /* ---- Toast Notifications ---- */
  const Toast = {
    container: null,

    init() {
      this.container = document.getElementById('toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'toast-container';
        this.container.setAttribute('aria-live', 'polite');
        document.body.appendChild(this.container);
      }
    },

    show(message, type = 'info', duration = 4000) {
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.setAttribute('role', 'alert');

      const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
      };

      toast.innerHTML = `
        <span style="font-size:16px;font-weight:bold;">${icons[type] || icons.info}</span>
        <span>${message}</span>
        <button class="toast-close" aria-label="Dismiss" onclick="this.closest('.toast').remove()">✕</button>
      `;

      this.container.appendChild(toast);

      setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
      }, duration);
    },

    success(msg) { this.show(msg, 'success'); },
    error(msg)   { this.show(msg, 'error', 6000); },
    warning(msg) { this.show(msg, 'warning', 5000); },
    info(msg)    { this.show(msg, 'info'); }
  };

  /* ---- Modal ---- */
  const Modal = {
    show(id) {
      const overlay = document.getElementById(id);
      if (!overlay) return;
      overlay.classList.add('active');
      document.body.style.overflow = 'hidden';
      // Focus trap
      const firstFocusable = overlay.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (firstFocusable) firstFocusable.focus();
    },

    hide(id) {
      const overlay = document.getElementById(id);
      if (!overlay) return;
      overlay.classList.remove('active');
      document.body.style.overflow = '';
    }
  };

  // Close modal on overlay click
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('active')) {
      e.target.classList.remove('active');
      document.body.style.overflow = '';
    }
  });

  /* ---- Dropdown ---- */
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-dropdown-trigger]');
    if (trigger) {
      const menu = trigger.closest('.dropdown')?.querySelector('.dropdown-menu');
      if (menu) {
        const wasActive = menu.classList.contains('active');
        // Close all
        document.querySelectorAll('.dropdown-menu.active').forEach(m => m.classList.remove('active'));
        if (!wasActive) menu.classList.add('active');
      }
      e.stopPropagation();
    }
  });
  document.addEventListener('click', () => {
    document.querySelectorAll('.dropdown-menu.active').forEach(m => m.classList.remove('active'));
  });

  /* ---- FAQ Accordion ---- */
  document.addEventListener('click', (e) => {
    const question = e.target.closest('.faq-question');
    if (question) {
      const item = question.closest('.faq-item');
      if (item) {
        const wasOpen = item.classList.contains('open');
        // Close all
        document.querySelectorAll('.faq-item.open').forEach(i => i.classList.remove('open'));
        if (!wasOpen) item.classList.add('open');
      }
    }
  });

  /* ---- Sidebar Active State ---- */
  function setActiveNav() {
    const path = window.location.pathname;
    document.querySelectorAll('.nav-item').forEach(item => {
      const href = item.getAttribute('href');
      if (href && path === href) {
        item.classList.add('active');
      } else if (href && href !== '/' && path.startsWith(href)) {
        item.classList.add('active');
      }
    });
  }

  /* ---- Intersection Observer for Animations ---- */
  function initScrollAnimations() {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });

    document.querySelectorAll('[data-animate]').forEach(el => observer.observe(el));
  }

  /* ---- Keyboard Navigation ---- */
  function initKeyboardNav() {
    // ESC closes modals, dropdowns
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => {
          m.classList.remove('active');
          document.body.style.overflow = '';
        });
        document.querySelectorAll('.dropdown-menu.active').forEach(m => m.classList.remove('active'));
      }
    });
  }

  /* ---- Init ---- */
  function init() {
    ThemeManager.init();
    MobileNav.init();
    Toast.init();
    setActiveNav();
    initScrollAnimations();
    initKeyboardNav();

    // Expose globally
    window.Toast = Toast;
    window.Modal = Modal;
    window.ThemeManager = ThemeManager;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
