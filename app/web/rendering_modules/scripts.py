"""version: 1.2.0
description: Browser scripts for MP Control web rendering – added profile page JS.
updated: 2026-06-11
"""

# ruff: noqa: E501

from app.web.rendering_modules.sync_center_js import SYNC_CENTER_JS

__all__ = [
    "_js",
]


def _js() -> str:
    return SYNC_CENTER_JS + """
    (function() {
      var errorNode = document.getElementById('interface-error');
      var loadingSelectors = [
        '.' + 'page' + '-loader',
        '.' + 'loading' + '-overlay',
        '.' + 'pre' + 'loader',
        '.' + 'spin' + 'ner'
      ];
      function reportFrontendError(message, source, lineno, colno, stack) {
        var payload = {
          message: String(message || ''),
          source: String(source || ''),
          lineno: lineno || null,
          colno: colno || null,
          stack: String(stack || ''),
          path: location.pathname + location.search,
          user_agent: navigator.userAgent
        };
        try {
          fetch('/web/frontend-error', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify(payload),
            keepalive: true
          }).catch(function(){});
        } catch (sendError) {
          console.error('frontend diagnostics failed', sendError);
        }
      }
      function showInterfaceError() {
        if (errorNode) errorNode.hidden = false;
      }
      function hideLegacyLoadingArtifacts() {
        loadingSelectors.forEach(function(selector) {
          document.querySelectorAll(selector).forEach(function(node) {
            node.setAttribute('hidden', 'hidden');
            node.style.display = 'none';
            node.setAttribute('aria-hidden', 'true');
          });
        });
      }
      window.addEventListener('error', function(event) {
        console.error('web frontend error', event.error || event.message);
        reportFrontendError(event.message, event.filename, event.lineno, event.colno, event.error && event.error.stack);
        showInterfaceError();
      });
      window.addEventListener('unhandledrejection', function(event) {
        var reason = event.reason || {};
        console.error('web frontend rejection', reason);
        reportFrontendError(reason.message || reason, 'unhandledrejection', null, null, reason.stack);
        showInterfaceError();
      });
      document.addEventListener('DOMContentLoaded', function() {
        hideLegacyLoadingArtifacts();
        initSidebar();
        initTableWraps();
      });
      function initSidebar() {
        var toggle = document.querySelector('.sidebar-toggle');
        var sidebar = document.getElementById('sidebar');
        if (!toggle || !sidebar) return;
        function closeNavigation() {
          sidebar.classList.remove('is-open');
          document.body.classList.remove('nav-open');
        }
        toggle.addEventListener('click', function(e) {
          e.stopPropagation();
          sidebar.classList.toggle('is-open');
          document.body.classList.toggle('nav-open', sidebar.classList.contains('is-open'));
        });
        document.addEventListener('click', function(e) {
          if (sidebar.classList.contains('is-open') && !sidebar.contains(e.target) && !e.target.closest('.sidebar-toggle')) {
            closeNavigation();
          }
        });
        document.addEventListener('keydown', function(e) {
          if (e.key === 'Escape' && sidebar.classList.contains('is-open')) {
            closeNavigation();
          }
        });
        window.addEventListener('resize', function() {
          if (window.innerWidth > 900) closeNavigation();
        });
        sidebar.querySelectorAll('a').forEach(function(link) {
          link.addEventListener('click', function() {
            if (window.innerWidth <= 900) closeNavigation();
          });
        });
      }
      function initTableWraps() {
        document.querySelectorAll('.table-wrap').forEach(function(wrap) {
          var table = wrap.querySelector('table');
          if (table && table.scrollWidth > wrap.clientWidth) {
            wrap.style.position = 'relative';
          }
        });
      }
      window.setTimeout(function() {
        hideLegacyLoadingArtifacts();
        var stuckLoader = loadingSelectors.some(function(selector) {
          return Array.prototype.some.call(document.querySelectorAll(selector), function(node) {
            var style = window.getComputedStyle(node);
            return !node.hidden && style.display !== 'none' && style.visibility !== 'hidden';
          });
        });
        if (stuckLoader) {
          reportFrontendError('legacy loading indicator was still visible after timeout', 'loader-failsafe', null, null, '');
          showInterfaceError();
        }
      }, 2000);
    })();
    /* ── Profile Page ── */
    function showProfileToast(message, type) {
      var existing = document.querySelector('.profile-notification');
      if (existing) { existing.remove(); }
      var toast = document.createElement('div');
      toast.className = 'profile-notification ' + (type || 'success');
      toast.textContent = message;
      document.body.appendChild(toast);
      setTimeout(function() {
        toast.style.animation = 'profileToastOut 0.3s ease-in forwards';
        setTimeout(function() { toast.remove(); }, 300);
      }, 3000);
    }
    function validateEmail(email) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    }
    function validatePhone(phone) {
      return !phone || /^\+?[\d\s\-()]{10,20}$/.test(phone);
    }
    async function saveProfile() {
      var data = {};
      var firstName = document.getElementById('pf_first_name');
      var lastName = document.getElementById('pf_last_name');
      var phone = document.getElementById('pf_phone');
      var email = document.getElementById('pf_email');
      var timezone = document.getElementById('pf_timezone');
      if (firstName) data.first_name = firstName.value;
      if (lastName) data.last_name = lastName.value;
      if (phone) data.phone = phone.value;
      if (email) data.email = email.value;
      if (timezone) data.timezone = timezone.value;
      if (data.email && data.email.trim() && !validateEmail(data.email.trim())) {
        showProfileToast('Некорректный формат email', 'error');
        return;
      }
      if (data.phone && data.phone.trim() && !validatePhone(data.phone.trim())) {
        showProfileToast('Некорректный формат телефона', 'error');
        return;
      }
      try {
        var resp = await fetch('/web/settings/profile', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(data)
        });
        if (resp.ok) {
          showProfileToast('Профиль успешно сохранён', 'success');
        } else {
          var err = await resp.text();
          showProfileToast('Ошибка: ' + err, 'error');
        }
      } catch (e) {
        showProfileToast('Ошибка сети: ' + e.message, 'error');
      }
    }
    function navigateTo(url) { window.location.href = url; }
    """
