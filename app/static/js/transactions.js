document.addEventListener('DOMContentLoaded', function () {
    const editModalElement = document.getElementById('edit-transaction-modal');
    const editForm = document.getElementById('edit-transaction-form');
    if (!editModalElement || !editForm) {
        return;
    }

    const editModal = bootstrap.Modal.getOrCreateInstance(editModalElement);
    const errorNotice = document.getElementById('edit-transaction-error');
    const saveButton = document.getElementById('update-transaction-button');
    let activeRow = null;

    document.addEventListener('click', async function (event) {
        const target = event.target instanceof Element ? event.target : null;
        const editButton = target && target.closest('.edit-transaction');
        const deleteButton = target && target.closest('.delete-transaction');
        if (editButton) {
            activeRow = editButton.closest('tr[data-transaction-id]');
            if (!activeRow) {
                return;
            }
            editForm.elements.type.value = activeRow.dataset.type.trim().toLowerCase();
            editForm.elements.amount.value = activeRow.dataset.amount;
            editForm.elements.category.value = activeRow.dataset.category;
            editForm.elements.account_id.value = activeRow.dataset.accountId;
            editForm.elements.date.value = activeRow.dataset.date;
            editForm.elements.payment_method.value = activeRow.dataset.paymentMethod;
            editForm.elements.title.value = activeRow.dataset.title;
            editForm.elements.description.value = activeRow.dataset.description;
            errorNotice.classList.add('d-none');
            editModal.show();
            return;
        }
        if (!deleteButton) {
            return;
        }

        const row = deleteButton.closest('tr[data-transaction-id]');
        if (!row || !window.confirm('Delete this transaction? This action cannot be undone.')) {
            return;
        }
        deleteButton.disabled = true;
        try {
            const result = await sendRequest(row.dataset.transactionUrl, 'DELETE');
            row.remove();
            showEmptyHistoryMessage(row);
            showFeedback('Transaction deleted successfully.', 'success');
            notifyTransactionChange(result);
        } catch (error) {
            showFeedback(error.message || 'The transaction could not be deleted.', 'danger');
        } finally {
            deleteButton.disabled = false;
        }
    });

    editForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        if (!activeRow || !editForm.reportValidity() || saveButton.disabled) {
            return;
        }
        errorNotice.classList.add('d-none');
        saveButton.disabled = true;
        try {
            const result = await sendRequest(
                activeRow.dataset.transactionUrl,
                'PUT',
                Object.fromEntries(new FormData(editForm))
            );
            updateTransactionRow(activeRow, result.transaction);
            editModal.hide();
            showFeedback('Transaction updated successfully.', 'success');
            notifyTransactionChange(result);
        } catch (error) {
            errorNotice.textContent = error.message || 'The transaction could not be updated.';
            errorNotice.classList.remove('d-none');
        } finally {
            saveButton.disabled = false;
        }
    });

    async function sendRequest(url, method, body) {
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
            throw new Error(result.error || 'The transaction could not be saved.');
        }
        return result;
    }

    function updateTransactionRow(row, transaction) {
        row.dataset.title = transaction.title;
        row.dataset.type = transaction.type;
        row.dataset.category = transaction.category;
        row.dataset.amount = transaction.amount;
        row.dataset.accountId = transaction.account_id || '';
        row.dataset.date = transaction.date;
        row.dataset.paymentMethod = transaction.payment_method;
        row.dataset.description = transaction.description;

        const title = row.querySelector('.transaction-title');
        if (title) {
            title.textContent = transaction.title;
        }
        const typeBadge = row.querySelector('.transaction-type .badge');
        if (typeBadge) {
            typeBadge.className = 'badge ' +
                (transaction.type === 'income' ? 'bg-success' : 'bg-warning') +
                ' text-white';
            typeBadge.textContent = transaction.type;
        }
        const category = row.querySelector('.transaction-category');
        if (category) {
            category.textContent = transaction.category;
        }
        const date = row.querySelector('.transaction-date');
        if (date) {
            date.textContent = transaction.date;
        }
        const amount = row.querySelector('.transaction-amount');
        if (amount) {
            amount.textContent = formatTransactionCurrency(transaction.amount);
        }
        if (row.closest('.transaction-history')) {
            const body = row.parentElement;
            const rows = Array.from(body.querySelectorAll('tr[data-transaction-id]'));
            rows.sort((first, second) =>
                second.dataset.date.localeCompare(first.dataset.date) ||
                Number(second.dataset.transactionId) - Number(first.dataset.transactionId)
            );
            rows.forEach(item => body.appendChild(item));
        }
    }

    function showEmptyHistoryMessage(removedRow) {
        const body = removedRow.parentElement;
        if (!body || body.querySelector('tr[data-transaction-id]')) {
            return;
        }
        const emptyRow = document.createElement('tr');
        const emptyCell = document.createElement('td');
        emptyCell.colSpan = body.closest('#recent-transactions') ? 5 : 6;
        emptyCell.className = 'text-center text-muted';
        emptyCell.textContent = body.closest('#recent-transactions')
            ? 'No transactions yet.'
            : 'No transactions recorded yet.';
        emptyRow.appendChild(emptyCell);
        body.appendChild(emptyRow);
    }

    function formatTransactionCurrency(amount) {
        const currencyCode = document.querySelector('[data-currency-code]')?.dataset.currencyCode ||
            window.expenseFlowCurrency ||
            document.getElementById('reports-page')?.dataset.currency ||
            'USD';
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: currencyCode
        }).format(Number(amount));
    }

    function showFeedback(message, category) {
        const feedback = document.getElementById('transaction-history-feedback') ||
            document.getElementById('transaction-feedback') ||
            document.getElementById('transaction-action-feedback');
        if (feedback) {
            feedback.textContent = message;
            feedback.className = 'alert alert-' + category;
        }
    }

    function notifyTransactionChange(data) {
        if (typeof window.expenseFlowUpdateDashboard === 'function') {
            window.expenseFlowUpdateDashboard(data);
        }
        window.dispatchEvent(new CustomEvent('expenseflow:transaction-changed', { detail: data }));
        localStorage.setItem('expenseflow-dashboard-updated', String(Date.now()));
    }
});
