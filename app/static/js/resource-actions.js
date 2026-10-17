document.addEventListener('DOMContentLoaded', function () {
    const forms = Array.from(document.querySelectorAll('.resource-edit-form'));
    if (!forms.length) {
        return;
    }

    const modals = new Map(forms.map(function (form) {
        const resource = form.dataset.resource;
        return [resource, bootstrap.Modal.getOrCreateInstance(
            document.getElementById('edit-' + resource + '-modal')
        )];
    }));
    const feedback = document.getElementById('resource-action-feedback');
    let activeRow = null;

    document.addEventListener('click', async function (event) {
        const target = event.target instanceof Element ? event.target : null;
        const editButton = target && target.closest('.edit-resource');
        const deleteButton = target && target.closest('.delete-resource');

        if (editButton) {
            activeRow = editButton.closest('tr[data-resource]');
            if (!activeRow) {
                return;
            }
            const form = forms.find(item => item.dataset.resource === activeRow.dataset.resource);
            if (!form) {
                return;
            }
            form.reset();
            form.querySelector('.resource-edit-error').classList.add('d-none');
            Array.from(form.elements).forEach(function (field) {
                if (!field.name) {
                    return;
                }
                const value = activeRow.dataset[datasetKey(field.name)];
                if (field.type === 'checkbox') {
                    field.checked = value === 'true';
                } else if (value !== undefined) {
                    field.value = value;
                }
            });
            modals.get(activeRow.dataset.resource).show();
            return;
        }
        if (!deleteButton) {
            return;
        }

        const row = deleteButton.closest('tr[data-resource]');
        if (!row || !window.confirm('Delete this ' + row.dataset.resource + '? This action cannot be undone.')) {
            return;
        }
        deleteButton.disabled = true;
        try {
            const result = await request(row.dataset.resourceUrl, 'DELETE');
            row.remove();
            addEmptyMessageIfNeeded(row);
            showFeedback(capitalize(row.dataset.resource) + ' deleted successfully.', 'success');
            notifyResourceChange(row.dataset.resource, result);
        } catch (error) {
            showFeedback(error.message || 'The item could not be deleted.', 'danger');
        } finally {
            deleteButton.disabled = false;
        }
    });

    forms.forEach(function (form) {
        form.addEventListener('submit', async function (event) {
            event.preventDefault();
            const saveButton = form.querySelector('[type="submit"]');
            if (!activeRow || !form.reportValidity() || saveButton.disabled) {
                return;
            }
            const errorNotice = form.querySelector('.resource-edit-error');
            errorNotice.classList.add('d-none');
            saveButton.disabled = true;
            try {
                const values = Object.fromEntries(new FormData(form));
                if (form.elements.is_archived) {
                    values.is_archived = form.elements.is_archived.checked;
                }
                const result = await request(activeRow.dataset.resourceUrl, 'PUT', values);
                updateResourceRow(activeRow, result);
                modals.get(form.dataset.resource).hide();
                showFeedback(capitalize(form.dataset.resource) + ' updated successfully.', 'success');
                notifyResourceChange(form.dataset.resource, result);
            } catch (error) {
                errorNotice.textContent = error.message || 'The item could not be updated.';
                errorNotice.classList.remove('d-none');
            } finally {
                saveButton.disabled = false;
            }
        });
    });

    async function request(url, method, body) {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Accept': 'application/json',
                ...(body ? { 'Content-Type': 'application/json' } : {})
            },
            ...(body ? { body: JSON.stringify(body) } : {})
        });
        if (!response.headers.get('content-type')?.includes('application/json')) {
            throw new Error(response.redirected
                ? 'Your session may have expired. Please sign in again.'
                : 'The server returned an unexpected response. Please try again.');
        }
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'The item could not be saved.');
        }
        return result;
    }

    function updateResourceRow(row, item) {
        Object.entries(item).forEach(function (entry) {
            row.dataset[datasetKey(entry[0])] = String(entry[1] ?? '');
        });
        const resource = row.dataset.resource;
        if (resource === 'account') {
            row.querySelector('.account-name').textContent = item.name;
            row.querySelector('.account-type').textContent = item.type;
            row.querySelector('.account-currency').textContent = item.currency;
            row.querySelector('.account-opening-balance').textContent = formatMoney(item.opening_balance, item.currency);
        } else if (resource === 'budget') {
            row.querySelector('.budget-name').textContent = item.name;
            row.querySelector('.budget-category').textContent = item.category || '—';
            row.querySelector('.budget-amount').textContent = formatMoney(item.total_amount);
            row.querySelector('.budget-period').textContent = item.start_date + ' → ' + item.end_date;
        } else if (resource === 'goal') {
            row.querySelector('.goal-name').textContent = item.name;
            row.querySelector('.goal-target').textContent = formatMoney(item.target_amount);
            row.querySelector('.goal-current').textContent = formatMoney(item.current_amount);
            row.querySelector('.goal-status').textContent = item.status;
            const progress = Math.min(Number(item.progress), 100);
            const progressBar = row.querySelector('.goal-progress .progress-bar');
            progressBar.style.width = progress + '%';
            row.querySelector('.goal-progress').setAttribute('aria-valuenow', progress.toFixed(1));
            row.querySelector('.goal-progress-label').textContent = progress.toFixed(1) + '%';
        }
    }

    function addEmptyMessageIfNeeded(removedRow) {
        const body = removedRow.parentElement;
        if (!body || body.querySelector('tr[data-resource]')) {
            return;
        }
        const columns = { account: 5, budget: 5, goal: 6 };
        const labels = {
            account: 'No accounts yet.',
            budget: 'No budgets yet.',
            goal: 'No savings goals yet.'
        };
        const emptyRow = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = columns[removedRow.dataset.resource];
        cell.className = 'text-center text-muted';
        cell.textContent = labels[removedRow.dataset.resource];
        emptyRow.appendChild(cell);
        body.appendChild(emptyRow);
    }

    function showFeedback(message, category) {
        if (!feedback) {
            return;
        }
        feedback.textContent = message;
        feedback.className = 'alert alert-' + category + ' mt-3';
    }

    function notifyResourceChange(resource, detail) {
        const eventName = resource === 'budget'
            ? 'expenseflow:budgets-changed'
            : resource === 'goal'
                ? 'expenseflow:goals-changed'
                : 'expenseflow:account-changed';
        window.dispatchEvent(new CustomEvent(eventName, { detail: detail }));
        localStorage.setItem('expenseflow-dashboard-updated', String(Date.now()));
    }

    function datasetKey(name) {
        return name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    }

    function formatMoney(value, currencyCode) {
        const currency = currencyCode || document.querySelector('[data-currency-code]')?.dataset.currencyCode || 'USD';
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: currency
        }).format(Number(value));
    }

    function capitalize(value) {
        return value.charAt(0).toUpperCase() + value.slice(1);
    }
});
