(() => {
    'use strict';
    document.querySelectorAll('[data-proof-policy]').forEach(panel => {
        const image = panel.querySelector('[name="proof_image_enabled"]');
        const transaction = panel.querySelector('[name="proof_transaction_enabled"]');
        const requirement = panel.querySelector('[name="proof_requirement"]');
        const preview = panel.querySelector('[data-proof-policy-preview]');
        if (!image || !transaction || !requirement || !preview) return;
        const update = () => {
            const types = [image.checked ? 'an image' : '', transaction.checked ? 'a transaction ID' : ''].filter(Boolean);
            preview.textContent = !types.length ? (requirement.value === 'optional' ? 'No proof fields will be shown.' : 'Enable at least one proof type to require proof.') :
                requirement.value === 'optional' ? `Participants may provide ${types.join(' and/or ')}.` :
                `Participants must provide ${types.join(requirement.value === 'either' ? ' or ' : ' and ')}.`;
        };
        panel.addEventListener('change', update); update();
    });
    const root = document.getElementById('paymentModal');
    if (!root) return;
    const byId = id => document.getElementById(id);
    const modal = bootstrap.Modal.getOrCreateInstance(root);
    const form = byId('paymentReportForm');
    const method = byId('paymentMethod');
    const imageInput = byId('paymentImage');
    let data, endpoint, mode, removedImage = false, previewUrl, generation = 0, busy = false, initialized = false;
    const show = (element, visible) => element.classList.toggle('d-none', !visible);
    const node = (tag, text, className) => {
        const element = document.createElement(tag);
        if (text != null) element.textContent = text;
        if (className) element.className = className;
        return element;
    };
    const dateText = value => value ? new Date(value).toLocaleString() : '';
    const selected = () => data.options.find(option => String(option.id) === method.value);
    const clearErrors = () => {
        show(byId('paymentError'), false);
        root.querySelectorAll('[data-payment-error]').forEach(el => { el.textContent = ''; });
        form.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
    };
    const error = message => {
        byId('paymentError').textContent = message;
        show(byId('paymentError'), true);
        byId('paymentError').scrollIntoView({block: 'nearest'});
    };
    const applyErrors = result => {
        clearErrors();
        if (result.errors) Object.entries(result.errors).forEach(([field, message]) => {
            const target = root.querySelector(`[data-payment-error="${field}"]`);
            if (target) target.textContent = message;
            form.elements.namedItem(field)?.classList.add('is-invalid');
        });
        error(result.error || 'Please check the highlighted fields.');
        form.querySelector('.is-invalid')?.focus();
    };
    const imagePreview = url => {
        show(byId('paymentImagePreview'), Boolean(url));
        byId('paymentPreview').src = url || '';
    };
    const appendTransaction = (container, report) => {
        if (!report.transaction_id) return;
        const box = node('div', null, 'payment-summary my-3');
        box.append(node('div', 'Transaction number / ID', 'small text-muted mb-1'));
        if (report.explorer_url) {
            const link = node('a', report.transaction_id, 'font-monospace');
            link.href = report.explorer_url;
            link.target = '_blank'; link.rel = 'noopener noreferrer';
            box.append(link, node('div', 'Open transaction in blockchain explorer ↗', 'small text-muted mt-1'));
        } else box.append(node('div', report.transaction_id, 'font-monospace'));
        const copy = node('button', 'Copy ID', 'btn btn-sm btn-outline-secondary mt-2');
        copy.type = 'button'; copy.dataset.copyValue = report.transaction_id;
        box.append(copy); container.append(box);
    };
    const appendEvidence = (container, report) => {
        appendTransaction(container, report);
        if (report.image_url) {
            const img = node('img', null, 'payment-receipt rounded border');
            img.src = report.image_url; img.alt = 'Submitted payment proof'; img.loading = 'lazy';
            img.addEventListener('error', () => {
                img.replaceWith(node('div', 'Proof image could not be loaded. Close and reopen this modal to retry.', 'alert alert-warning'));
            });
            const toggle = node('button', 'Enlarge image', 'btn btn-sm btn-outline-primary mt-2');
            toggle.type = 'button';
            toggle.addEventListener('click', () => {
                const enlarged = img.style.maxHeight === 'none';
                img.style.maxHeight = enlarged ? '' : 'none';
                toggle.textContent = enlarged ? 'Enlarge image' : 'Fit image';
            });
            container.append(img, toggle);
        }
        if (!report.image_url && !report.transaction_id) container.append(node('p', 'No proof provided.', 'text-muted small'));
    };
    const changeMethod = (reset = false) => {
        const option = selected();
        const destination = byId('paymentDestination');
        destination.replaceChildren();
        show(destination, Boolean(option));
        if (reset) {
            clearErrors(); imageInput.value = ''; removedImage = false;
            const original = Boolean(data.latest && option && data.latest.method.id === option.id);
            byId('paymentTransaction').value = original ? data.latest.transaction_id : '';
            imagePreview(original ? data.latest.image_url : null);
        }
        if (option) {
            destination.append(node('div', option.title, 'fw-semibold'));
            if (option.destination) destination.append(node('div', `${option.destination_label || 'Destination'}: ${option.destination}`));
            if (option.network) destination.append(node('div', `Network: ${option.network}`));
            if (option.details) destination.append(node('div', option.details, 'mt-1'));
            // Only known wallet schemes and HTTP(S) destinations may become links.
            if (/^(https?:|bitcoin:|litecoin:|bitcoincash:|ethereum:|solana:|tron:|binance:|crypto:)/i.test(option.payment_link || '')) {
                const link = node('a', option.link_type === 'uri' ? 'Open wallet ↗' : 'Open payment page ↗', 'btn btn-sm btn-outline-primary mt-2');
                link.href = option.payment_link; link.target = '_blank'; link.rel = 'noopener noreferrer'; destination.append(link);
            }
        }
        show(byId('paymentTransactionField'), Boolean(option?.proof_transaction_enabled));
        show(byId('paymentImageField'), Boolean(option?.proof_image_enabled));
        const required = option?.proof_requirement === 'all';
        const hint = required ? '(required)' : option?.proof_requirement === 'either' ? '(one proof required)' : '(optional)';
        byId('paymentTransactionHint').textContent = hint;
        byId('paymentImageHint').textContent = hint;
        byId('paymentRequirement').textContent = !option ? (data.options.length ? 'Choose a payment method to see its proof requirements.' : 'No payment methods are available. Contact an administrator.') : ({optional: 'Payment proof is optional.', either: 'Provide at least one accepted proof of payment.', all: 'Provide all accepted proofs of payment.'})[option.proof_requirement];
        show(byId('paymentUploadWarning'), !data.upload_ready);
        imageInput.disabled = !data.upload_ready;
        byId('paymentSubmit').disabled = !initialized || !option || busy;
    };
    const render = () => {
        const latest = data.latest;
        const editing = mode === 'report' && data.can_report;
        const reviewing = mode === 'review' && !data.paid;
        byId('paymentModalTitle').textContent = mode === 'review' ? 'Review Payment' : data.paid ? 'View Payment' : (latest || data.pending ? 'Update Payment' : 'Report Payment');
        byId('paymentSubtitle').textContent = `${data.participant} · ${data.test}`;
        const status = byId('paymentStatus');
        status.className = 'alert py-2 ' + (data.paid ? 'alert-success' : latest?.status === 'denied' ? 'alert-danger' : 'alert-info');
        status.textContent = data.paid ? 'Payment Verified' : data.pending ? 'Awaiting Review' : latest?.status === 'denied' ? `Payment Denied: ${latest.denial_reason}` : 'Submit your payment for administrator verification.';
        byId('paymentSummary').replaceChildren(
            node('div', `Amount owed: $${data.amount_owed}`, 'fw-semibold'),
            node('div', `Reported: $${latest?.amount || data.amount_paid}`, 'small text-muted'),
        );
        if (latest) {
            byId('paymentSummary').append(node('div', `Submitted ${dateText(latest.submitted_at)}`, 'small text-muted'));
            if (!editing) {
                byId('paymentSummary').append(node('div', latest.method.title, 'fw-semibold mt-2'));
                if (latest.method.destination) byId('paymentSummary').append(node('div', `Destination: ${latest.method.destination}`, 'small'));
                if (latest.method.network) byId('paymentSummary').append(node('div', `Network: ${latest.method.network}`, 'small'));
            }
        } else if (!editing) byId('paymentSummary').append(node('div', data.legacy_snapshot, 'small mt-2'));
        show(form, editing); show(byId('paymentSubmit'), editing);
        show(byId('paymentApprove'), reviewing); show(byId('paymentDeny'), reviewing && data.pending);
        byId('paymentApprove').lastChild.textContent = data.pending ? 'Approve Payment' : 'Mark Paid';
        const evidence = byId('paymentEvidence'); evidence.replaceChildren(); show(evidence, !editing);
        if (!editing && latest) appendEvidence(evidence, latest);
        if (!editing && !latest) evidence.append(node('p', 'No proof provided.', 'text-muted small'));
        if (editing) {
            if (latest) {
                data.options = data.options.filter(option => option.id !== latest.method.id);
                data.options.unshift({...latest.method, title: `${latest.method.title} (submitted method)`});
            }
            method.replaceChildren(node('option', 'Choose payment method…'));
            method.firstChild.value = '';
            data.options.forEach(option => {
                const item = node('option', option.title); item.value = option.id; method.append(item);
            });
            method.value = String(latest?.method.id || data.preferred_option_id || (data.options.length === 1 ? data.options[0].id : ''));
            byId('paymentAmount').value = latest?.amount || (Number(data.amount_paid) > 0 ? data.amount_paid : data.amount_owed);
            changeMethod(true);
        }
        const history = byId('paymentHistoryContent'); history.replaceChildren();
        data.history.slice(1).forEach(report => {
            const item = node('details', null, 'payment-history-item');
            item.append(node('summary', `$${report.amount} · ${report.status} · ${dateText(report.submitted_at)}`));
            item.append(node('div', report.method.title, 'small fw-semibold mt-2'));
            if (report.method.destination) item.append(node('div', `Destination: ${report.method.destination}`, 'small'));
            if (report.method.network) item.append(node('div', `Network: ${report.method.network}`, 'small'));
            if (report.denial_reason) item.append(node('p', report.denial_reason, 'small text-danger mt-2'));
            if (report.reviewed_at) item.append(node('div', `Reviewed ${dateText(report.reviewed_at)}`, 'small text-muted'));
            appendEvidence(item, report); history.append(item);
        });
        show(byId('paymentHistory'), data.history.length > 1);
        show(byId('paymentContent'), true);
        initialized = true;
        byId('paymentSubmit').disabled = !selected();
    };
    document.addEventListener('click', async event => {
        const trigger = event.target.closest('[data-payment-part]');
        if (!trigger) return;
        const token = ++generation;
        initialized = false;
        endpoint = root.dataset.baseUrl.replace(/0$/, trigger.dataset.paymentPart);
        mode = trigger.dataset.paymentMode;
        form.reset(); clearErrors();
        show(byId('paymentContent'), false); show(byId('paymentLoading'), true);
        ['paymentSubmit', 'paymentApprove', 'paymentDeny', 'paymentDenial'].forEach(id => show(byId(id), false));
        byId('paymentReason').value = ''; byId('paymentDeny').textContent = 'Deny Payment';
        modal.show(trigger);
        try {
            const response = await fetch(endpoint, {headers: {Accept: 'application/json'}});
            if (!response.ok || response.redirected) throw new Error('Unable to load payment details. Refresh the page and try again.');
            const result = await response.json();
            if (token !== generation) return;
            data = result; render();
        } catch (exc) {
            if (token === generation) {
                initialized = false;
                ['paymentSubmit', 'paymentApprove', 'paymentDeny'].forEach(id => show(byId(id), false));
                error(exc.message);
            }
        }
        finally { if (token === generation) show(byId('paymentLoading'), false); }
    });
    root.addEventListener('hidden.bs.modal', () => {
        ++generation;
        if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
    });
    method.addEventListener('change', () => changeMethod(true));
    imageInput.addEventListener('change', () => {
        const file = imageInput.files[0];
        if (!file) return;
        if (file.size > 8 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
            imageInput.value = ''; error('Choose a JPEG, PNG, or WebP image up to 8 MB.'); return;
        }
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = URL.createObjectURL(file); removedImage = false; imagePreview(previewUrl);
    });
    byId('paymentRemoveImage').addEventListener('click', () => { imageInput.value = ''; removedImage = true; imagePreview(null); });
    const dropzone = byId('paymentDropzone');
    ['dragover', 'dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => {
        event.preventDefault(); dropzone.classList.toggle('dragover', type === 'dragover');
        if (type === 'drop' && !imageInput.disabled && event.dataTransfer.files.length) {
            imageInput.files = event.dataTransfer.files; imageInput.dispatchEvent(new Event('change'));
        }
    }));
    const submit = async (action, payload) => {
        if (busy || !initialized) return;
        busy = true; clearErrors();
        payload.set('revision', data.revision);
        payload.set('csrf_token', form.elements.csrf_token.value);
        const buttons = root.querySelectorAll('.modal-footer button, .modal-header button');
        buttons.forEach(button => { button.disabled = true; });
        const hideWhileSaving = event => event.preventDefault();
        root.addEventListener('hide.bs.modal', hideWhileSaving);
        byId('paymentSubmit').textContent = 'Submitting…';
        try {
            const response = await fetch(`${endpoint}/${action}`, {method: 'POST', body: payload, headers: {Accept: 'application/json'}});
            const result = await response.json().catch(() => ({error: 'Unable to save payment. Please try again.'}));
            if (!response.ok || response.redirected) { applyErrors(result); return; }
            // Reload preserves queue filters and pagination; surface any delivery warning.
            sessionStorage.setItem('paymentFeedback', result.message);
            window.location.reload();
        } catch (_) { error('Connection interrupted. Close and reopen this modal to check whether your payment was saved.'); }
        finally {
            busy = false; buttons.forEach(button => { button.disabled = false; });
            byId('paymentSubmit').disabled = !initialized || !selected();
            root.removeEventListener('hide.bs.modal', hideWhileSaving);
            byId('paymentSubmit').textContent = 'Submit Payment for Review';
        }
    };
    form.addEventListener('submit', event => {
        event.preventDefault();
        const payload = new FormData(form);
        payload.set('remove_image', String(removedImage));
        const option = selected();
        if (!option?.proof_transaction_enabled) payload.set('transaction_id', '');
        if (!option?.proof_image_enabled || !imageInput.files.length) payload.delete('image');
        submit('report', payload);
    });
    byId('paymentApprove').addEventListener('click', () => {
        const payload = new FormData(); payload.set('decision', 'approve'); submit('review', payload);
    });
    byId('paymentDeny').addEventListener('click', () => {
        if (byId('paymentDenial').classList.contains('d-none')) {
            show(byId('paymentDenial'), true); byId('paymentReason').focus();
            byId('paymentDeny').textContent = 'Confirm Denial'; return;
        }
        if (!byId('paymentReason').value.trim()) { error('Enter a reason for denial.'); byId('paymentReason').focus(); return; }
        const payload = new FormData(); payload.set('decision', 'deny'); payload.set('reason', byId('paymentReason').value.trim()); submit('review', payload);
    });
    const feedback = sessionStorage.getItem('paymentFeedback');
    if (feedback) {
        sessionStorage.removeItem('paymentFeedback');
        const alert = node('div', feedback, 'alert alert-info'); alert.role = 'status';
        byId('main-content')?.prepend(alert);
    }
})();
