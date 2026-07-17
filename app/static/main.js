/* VaxTrack Main JavaScript */
(function () {
    'use strict';

    // ─── Auto-dismiss alerts ────────────────────────────────────
    document.querySelectorAll('.alert').forEach(function (alert) {
        // Add close button
        var closeBtn = document.createElement('button');
        closeBtn.className = 'alert-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.addEventListener('click', function () { dismissAlert(alert); });
        alert.appendChild(closeBtn);

        // Auto-dismiss after 5 seconds
        setTimeout(function () { dismissAlert(alert); }, 5000);
    });

    function dismissAlert(el) {
        el.style.transition = 'opacity .3s, transform .3s';
        el.style.opacity = '0';
        el.style.transform = 'translateY(-6px)';
        setTimeout(function () { el.remove(); }, 300);
    }

    // ─── Loading overlay on form submit ────────────────────────
    var overlay = document.getElementById('loading-overlay');
    document.querySelectorAll('form:not(.no-loading)').forEach(function (form) {
        form.addEventListener('submit', function () {
            if (overlay) overlay.classList.add('active');
        });
    });

    // ─── Custom confirm dialog ──────────────────────────────────
    var confirmDialog = document.getElementById('confirm-dialog');
    var confirmMessage = document.getElementById('confirm-message');
    var confirmTitle = document.getElementById('confirm-title');
    var confirmYes = document.getElementById('confirm-yes');
    var confirmNo = document.getElementById('confirm-no');
    var pendingForm = null;

    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            e.preventDefault();
            var msg = el.getAttribute('data-confirm') || 'Are you sure?';
            var title = el.getAttribute('data-confirm-title') || 'Confirm Action';
            if (confirmTitle) confirmTitle.textContent = title;
            if (confirmMessage) confirmMessage.textContent = msg;
            pendingForm = el.closest('form') || (el.href ? el : null);
            if (confirmDialog) confirmDialog.classList.add('open');
        });
    });

    if (confirmYes) {
        confirmYes.addEventListener('click', function () {
            if (confirmDialog) confirmDialog.classList.remove('open');
            if (pendingForm) {
                if (pendingForm.tagName === 'FORM') {
                    if (overlay) overlay.classList.add('active');
                    pendingForm.submit();
                } else if (pendingForm.href) {
                    window.location.href = pendingForm.href;
                }
            }
        });
    }
    if (confirmNo) {
        confirmNo.addEventListener('click', function () {
            if (confirmDialog) confirmDialog.classList.remove('open');
            pendingForm = null;
        });
    }

    // ─── Toast helper ───────────────────────────────────────────
    window.showToast = function (msg, type) {
        var container = document.getElementById('toast-container');
        if (!container) return;
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + (type || 'success');
        toast.innerHTML = (type === 'error' ? '&#10060; ' : '&#10004; ') + msg;
        container.appendChild(toast);
        setTimeout(function () {
            toast.style.transition = 'opacity .3s';
            toast.style.opacity = '0';
            setTimeout(function () { toast.remove(); }, 300);
        }, 3500);
    };

    // ─── Modal helpers ──────────────────────────────────────────
    window.openModal = function (id) {
        var m = document.getElementById(id);
        if (m) m.classList.add('open');
    };
    window.closeModal = function (id) {
        var m = document.getElementById(id);
        if (m) m.classList.remove('open');
    };

    // Close modal on backdrop click
    document.querySelectorAll('.modal-backdrop').forEach(function (backdrop) {
        backdrop.addEventListener('click', function (e) {
            if (e.target === backdrop) {
                backdrop.classList.remove('open');
                if (overlay) overlay.classList.remove('active');
            }
        });
    });

    // Close modal with Escape key
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-backdrop.open').forEach(function (m) {
                m.classList.remove('open');
            });
        }
    });

    // ─── Live table search/filter ───────────────────────────────
    var tableFilter = document.getElementById('table-filter');
    if (tableFilter) {
        tableFilter.addEventListener('input', function () {
            var q = this.value.toLowerCase();
            var rows = document.querySelectorAll('[data-filterable] tbody tr');
            rows.forEach(function (row) {
                row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        });
    }

    // ─── Vaccination modal click appointment row ──────────────
    var vaxModal = document.getElementById('vaccination-modal');
    if (vaxModal) {
        document.querySelectorAll('.apt-row[data-apt-id]').forEach(function (row) {
            row.addEventListener('click', function () {
                var aptId   = row.getAttribute('data-apt-id');
                var vaccine = row.getAttribute('data-vaccine');
                var dose    = row.getAttribute('data-dose');
                var scheduled = row.getAttribute('data-scheduled');
                var childId = row.getAttribute('data-child-id');

                document.getElementById('modal-vaccine-name').textContent = vaccine + ', Dose ' + dose;
                document.getElementById('modal-scheduled-date').textContent = 'Scheduled: ' + scheduled;
                document.getElementById('modal-appointment-id').value = aptId;

                // Default date_given to today
                var today = new Date().toISOString().split('T')[0];
                document.getElementById('modal-date-given').value = today;
                document.getElementById('modal-batch').value = '';

                openModal('vaccination-modal');
            });
        });
    }

    // ─── Sidebar toggle ─────────────────────────────────────────
    var sidebar         = document.getElementById('sidebar');
    var sidebarToggle   = document.getElementById('sidebar-toggle');
    var sidebarStrip    = document.getElementById('sidebar-strip');
    var sidebarBackdrop = document.getElementById('sidebar-backdrop');
    var isMobile        = window.innerWidth <= 768;

    function setSidebar(collapsed) {
        if (collapsed) {
            sidebar && sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
            sidebarBackdrop && sidebarBackdrop.classList.remove('show');
        } else {
            sidebar && sidebar.classList.remove('collapsed');
            document.body.classList.remove('sidebar-collapsed');
            if (isMobile) sidebarBackdrop && sidebarBackdrop.classList.add('show');
        }
        if (!isMobile) localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
    }

    // Initialise from localStorage; always start collapsed on mobile
    var initCollapsed = isMobile ? true : localStorage.getItem('sidebarCollapsed') === '1';
    setSidebar(initCollapsed);

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            var isCollapsed = sidebar && sidebar.classList.contains('collapsed');
            setSidebar(!isCollapsed);
        });
    }

    // Hover strip peek sidebar without toggling state
    if (sidebarStrip) {
        sidebarStrip.addEventListener('mouseenter', function () {
            if (sidebar && sidebar.classList.contains('collapsed')) {
                sidebar.classList.add('peeking');
            }
        });
        sidebarStrip.addEventListener('mouseleave', function () {
            sidebar && sidebar.classList.remove('peeking');
        });
    }
    if (sidebar) {
        sidebar.addEventListener('mouseleave', function () {
            if (sidebar.classList.contains('collapsed')) {
                sidebar.classList.remove('peeking');
            }
        });
    }

    // Backdrop click closes sidebar on mobile
    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener('click', function () {
            setSidebar(true);
        });
    }

    // ─── Sidebar active link highlight ─────────────────────────
    var path = window.location.pathname;
    document.querySelectorAll('.sidebar nav a').forEach(function (link) {
        var href = link.getAttribute('href');
        if (!href) return;
        if (href === '/' ? path === '/' : path === href) {
            link.classList.add('active');
        }
    });

    // ─── Animate stat numbers (count-up) ────────────────────────
    document.querySelectorAll('.stat-card .number[data-count]').forEach(function (el) {
        var target = parseInt(el.getAttribute('data-count'), 10);
        var start = 0;
        var duration = 800;
        var step = Math.ceil(target / (duration / 16));
        var timer = setInterval(function () {
            start += step;
            if (start >= target) { start = target; clearInterval(timer); }
            el.textContent = start;
        }, 16);
    });

    // ─── Progress bar animate on load ───────────────────────────
    document.querySelectorAll('.progress-bar[data-width]').forEach(function (bar) {
        bar.style.width = '0%';
        setTimeout(function () {
            bar.style.width = bar.getAttribute('data-width') + '%';
        }, 100);
    });

    // ─── Phone field uppercase for RFID input ───────────────────
    document.querySelectorAll('input[data-uppercase]').forEach(function (el) {
        el.addEventListener('input', function () {
            var pos = this.selectionStart;
            this.value = this.value.toUpperCase();
            this.setSelectionRange(pos, pos);
        });
    });

    // ─── Table row click → navigate ─────────────────────────────
    document.querySelectorAll('tr[data-href]').forEach(function (row) {
        row.style.cursor = 'pointer';
        row.addEventListener('click', function () {
            window.location.href = row.getAttribute('data-href');
        });
    });

    // ─── Tooltips (title attribute fallback) ────────────────────
    document.querySelectorAll('[data-tooltip]').forEach(function (el) {
        var tip = document.createElement('span');
        tip.className = 'tooltip-text';
        tip.textContent = el.getAttribute('data-tooltip');
        el.style.position = 'relative';
        el.appendChild(tip);
    });

    // ─── Smooth scroll ──────────────────────────────────────────
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
        a.addEventListener('click', function (e) {
            var target = document.querySelector(this.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

})();
