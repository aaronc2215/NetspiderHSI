'use strict';

// reviewQueue.js — Review Queue tab logic for NetspiderHSI 2.0

(function () {
    // Wait for socket.io to be available (defined in scraper.js via preload.js)
    function waitForSocket(cb) {
        if (window.socket) {
            cb(window.socket);
        } else {
            setTimeout(function () { waitForSocket(cb); }, 100);
        }
    }

    const SOURCE_LABELS = {
        'raw_escort_alligator_posts': 'Escort Alligator',
        'raw_eros_posts':             'Eros',
        'raw_mega_personals_posts':   'Mega Personals',
        'raw_rub_ratings_posts':      'Rub Ratings',
        'raw_skipthegames_posts':     'Skip the Games',
        'raw_yesbackpage_posts':      'Yes Back Page'
    };

    const BUCKET_LABELS = { 1: 'Safe', 2: 'False Positive', 3: 'Risky' };
    const BUCKET_COLORS = { 1: '#27ae60', 2: '#e67e22', 3: '#e74c3c' };

    waitForSocket(function (socket) {

        var bucketFilter   = document.getElementById('rq-bucket-filter');
        var sourceFilter   = document.getElementById('rq-source-filter');
        var statusFilter   = document.getElementById('rq-status-filter');
        var refreshBtn     = document.getElementById('rq-refresh-btn');
        var tbody          = document.getElementById('rq-tbody');
        var totalLabel     = document.getElementById('rq-total-label');
        var selectAll      = document.getElementById('rq-select-all');
        var selectedCount  = document.getElementById('rq-selected-count');
        var reviewerNotes  = document.getElementById('rq-reviewer-notes');
        var reviewedBy     = document.getElementById('rq-reviewed-by');
        var confirmRiskyBtn    = document.getElementById('rq-confirm-risky-btn');
        var clearLegitBtn      = document.getElementById('rq-clear-legitimate-btn');
        var markSafeBtn        = document.getElementById('rq-mark-safe-btn');

        if (!bucketFilter) return; // Tab not present in DOM

        // ---- Socket.IO listeners ----

        socket.on('review_queue_data', function (response) {
            if (response.error) {
                showError(response.error);
                return;
            }
            renderTable(response.data || []);
            totalLabel.textContent = 'Total: ' + (response.total || 0) + ' records';
        });

        socket.on('classification_updated', function (response) {
            if (response.error) {
                alert('Update failed: ' + response.error);
                return;
            }
            loadQueue();
        });

        // ---- Event handlers ----

        refreshBtn.addEventListener('click', loadQueue);
        bucketFilter.addEventListener('change', loadQueue);
        sourceFilter.addEventListener('change', loadQueue);
        statusFilter.addEventListener('change', loadQueue);

        selectAll.addEventListener('change', function () {
            var checkboxes = document.querySelectorAll('.rq-row-cb');
            checkboxes.forEach(function (cb) {
                cb.checked = selectAll.checked;
            });
            updateCount();
        });

        confirmRiskyBtn.addEventListener('click', function () { submitAction('confirm_risky'); });
        clearLegitBtn.addEventListener('click',   function () { submitAction('clear_legitimate'); });
        markSafeBtn.addEventListener('click',     function () { submitAction('mark_safe'); });

        // ---- Core functions ----

        function loadQueue() {
            socket.emit('get_review_queue', {
                bucket:        bucketFilter.value  || null,
                source_table:  sourceFilter.value  || null,
                review_status: statusFilter.value  || null,
                limit:  100,
                offset: 0
            });
        }

        function renderTable(data) {
            tbody.innerHTML = '';
            selectAll.checked = false;

            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:16px;">No records found.</td></tr>';
                updateCount();
                return;
            }

            data.forEach(function (row) {
                var tr = document.createElement('tr');

                var bucketColor = BUCKET_COLORS[row.bucket] || '#000';
                var bucketLabel = BUCKET_LABELS[row.bucket] || row.bucket;
                var siteLabel   = SOURCE_LABELS[row.source_table] || row.source_table;

                var ruleScore  = row.rule_score  != null ? parseFloat(row.rule_score).toFixed(1)  : 'N/A';
                var llmScore   = row.llm_score   != null ? parseFloat(row.llm_score).toFixed(1)   : 'N/A';
                var finalScore = row.final_score != null ? parseFloat(row.final_score).toFixed(1) : 'N/A';

                var descPreview  = escHtml(row.description_preview || '');
                var reasoning    = escHtml(row.llm_reasoning || '');
                var classifiedAt = row.classified_at ? row.classified_at.substring(0, 19) : '';

                tr.innerHTML =
                    '<td><input type="checkbox" class="rq-row-cb" value="' + row.id + '"/></td>' +
                    '<td>' + row.id + '</td>' +
                    '<td>' + siteLabel + '</td>' +
                    '<td>' + escHtml(row.city_or_region || '') + '</td>' +
                    '<td>' + ruleScore + '</td>' +
                    '<td>' + llmScore + '</td>' +
                    '<td><strong>' + finalScore + '</strong></td>' +
                    '<td style="color:' + bucketColor + '; font-weight:bold;">' + bucketLabel + '</td>' +
                    '<td>' + escHtml(row.review_status || '') + '</td>' +
                    '<td title="' + descPreview + '" style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' +
                        descPreview.substring(0, 80) +
                    '</td>' +
                    '<td title="' + reasoning + '" style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' +
                        reasoning.substring(0, 60) +
                    '</td>' +
                    '<td>' + classifiedAt + '</td>';

                tbody.appendChild(tr);
            });

            document.querySelectorAll('.rq-row-cb').forEach(function (cb) {
                cb.addEventListener('change', updateCount);
            });
            updateCount();
        }

        function submitAction(action) {
            var checked = Array.from(document.querySelectorAll('.rq-row-cb:checked'));
            if (!checked.length) {
                alert('Select at least one record first.');
                return;
            }
            var notes = reviewerNotes.value.trim();
            var agent = reviewedBy.value.trim() || 'Unknown';

            checked.forEach(function (cb) {
                socket.emit('update_classification', {
                    id:             parseInt(cb.value, 10),
                    action:         action,
                    reviewer_notes: notes,
                    reviewed_by:    agent
                });
            });
        }

        function updateCount() {
            var n = document.querySelectorAll('.rq-row-cb:checked').length;
            selectedCount.textContent = n;
        }

        function showError(msg) {
            tbody.innerHTML = '<tr><td colspan="12" style="color:red; padding:12px;">Error: ' + escHtml(msg) + '</td></tr>';
        }

        function escHtml(str) {
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        // Initial load
        loadQueue();
    });

})();
