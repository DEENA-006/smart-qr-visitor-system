/**
 * Smart QR Visitor Management System
 * Core Client-side Scripts
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Sidebar Toggle and Close
  const toggleBtn = document.getElementById('mobileMenuToggle');
  const closeBtn = document.getElementById('sidebarCloseBtn');
  const sidebar = document.getElementById('appSidebar');
  const appWrapper = document.querySelector('.app-wrapper');

  function openSidebar() {
    if (sidebar) {
      sidebar.classList.add('open');
      if (appWrapper) appWrapper.classList.remove('sidebar-collapsed');
      try { localStorage.setItem('vms_sidebar_state', 'open'); } catch(e){}
    }
  }

  function closeSidebar() {
    if (sidebar) {
      sidebar.classList.remove('open');
      if (appWrapper) appWrapper.classList.add('sidebar-collapsed');
      try { localStorage.setItem('vms_sidebar_state', 'closed'); } catch(e){}
    }
  }

  function toggleSidebar() {
    if (!sidebar) return;
    if (window.innerWidth <= 992) {
      sidebar.classList.toggle('open');
    } else {
      if (appWrapper && appWrapper.classList.contains('sidebar-collapsed')) {
        openSidebar();
      } else {
        closeSidebar();
      }
    }
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleSidebar();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeSidebar();
    });
  }

  // Close when clicking outside on mobile
  document.addEventListener('click', (e) => {
    if (sidebar && sidebar.classList.contains('open') && window.innerWidth <= 992) {
      if (!sidebar.contains(e.target) && e.target !== toggleBtn && (!toggleBtn || !toggleBtn.contains(e.target))) {
        sidebar.classList.remove('open');
      }
    }
  });

  // Restore saved desktop preference
  try {
    if (window.innerWidth > 992 && localStorage.getItem('vms_sidebar_state') === 'closed') {
      if (appWrapper) appWrapper.classList.add('sidebar-collapsed');
    }
  } catch(e){}

  // 2. Password Visibility Toggle
  const togglePasswordBtns = document.querySelectorAll('.toggle-password-btn');
  togglePasswordBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = btn.closest('.input-with-icon')?.querySelector('input');
      if (input) {
        if (input.type === 'password') {
          input.type = 'text';
          btn.setAttribute('aria-label', 'Hide password');
        } else {
          input.type = 'password';
          btn.setAttribute('aria-label', 'Show password');
        }
      }
    });
  });

  // 3. Dismissible Alert Badges
  const alertCloseBtns = document.querySelectorAll('.alert-close');
  alertCloseBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const alert = btn.closest('.alert');
      if (alert) {
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-4px)';
        setTimeout(() => alert.remove(), 200);
      }
    });
  });

  // Helper: Safely restore a form or button to its original, enabled state
  window.resetSubmitButton = function(formOrButton) {
    if (!formOrButton) return;
    const form = formOrButton.tagName === 'FORM' ? formOrButton : formOrButton.closest('form');
    if (form) {
      delete form.dataset.submitting;
      const btns = form.querySelectorAll('button, input[type="submit"]');
      btns.forEach((btn) => {
        if (btn.dataset.originalText) {
          btn.innerHTML = btn.dataset.originalText;
          delete btn.dataset.originalText;
        }
        btn.disabled = false;
        btn.style.opacity = '';
      });
    } else if (formOrButton.dataset.originalText) {
      formOrButton.innerHTML = formOrButton.dataset.originalText;
      delete formOrButton.dataset.originalText;
      formOrButton.disabled = false;
      formOrButton.style.opacity = '';
    }
  };

  // 4. Form Double-Submit Protection (Robust & Non-Blocking)
  const forms = document.querySelectorAll('form:not([data-no-disable])');
  forms.forEach((form) => {
    form.addEventListener('submit', (e) => {
      // A. Ignore if default was prevented (e.g. confirm cancelled, validation failed, or custom handler)
      if (e.defaultPrevented) return;

      // B. Ignore if HTML5 form constraint validation fails
      if (form.checkValidity && !form.checkValidity()) return;

      // C. Ignore GET forms (search / filters) which should remain interactive
      if (form.method && form.method.toUpperCase() === 'GET') return;

      // D. Prevent duplicate submission while already submitting
      if (form.dataset.submitting === 'true') {
        e.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';

      // E. Identify the submitter button (e.submitter is supported in modern browsers)
      const submitBtn = e.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
      if (submitBtn) {
        submitBtn.dataset.originalText = submitBtn.innerHTML;

        // F. Crucial: Schedule visual disablement asynchronously (setTimeout 0) so the browser's
        // native form submission pipeline queues and dispatches the HTTP request before the button is disabled.
        setTimeout(() => {
          if (form.dataset.submitting === 'true' && !submitBtn.disabled) {
            submitBtn.disabled = true;
            submitBtn.style.opacity = '0.75';
            submitBtn.innerHTML = `
              <svg style="animation: spin 1s linear infinite; width:16px; height:16px; vertical-align: middle; margin-right: 6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                <path d="M12 2a10 10 0 0 1 10 10"></path>
              </svg> Processing...
            `;
          }
        }, 0);

        // G. Safety recovery timer: If after 8 seconds navigation hasn't occurred (e.g. network failure / server lag),
        // restore the button so the form is never permanently stuck
        setTimeout(() => {
          if (form.dataset.submitting === 'true') {
            window.resetSubmitButton(form);
          }
        }, 8000);
      }
    });

    // Reset button state if form is reset
    form.addEventListener('reset', () => {
      window.resetSubmitButton(form);
    });
  });

  // H. BFCACHE / Back Navigation Recovery: Re-enable buttons when page is restored from cache
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-submitting]').forEach((form) => {
      window.resetSubmitButton(form);
    });
  });

  // 5. Demo Account Auto-Fill Helper (Development & Learning convenience)
  window.fillDemoAccount = function(username, password) {
    const identInput = document.getElementById('identifier');
    const passInput = document.getElementById('password');
    if (identInput && passInput) {
      identInput.value = username;
      passInput.value = password;
      identInput.focus();
    }
  };
});
