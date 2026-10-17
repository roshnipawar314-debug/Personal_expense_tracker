document.addEventListener('DOMContentLoaded', function () {
    const themeToggle = document.querySelector('.theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function () {
            const root = document.documentElement;
            const current = root.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            root.setAttribute('data-theme', next);
            localStorage.setItem('expense_theme', next);
        });

        const saved = localStorage.getItem('expense_theme');
        if (saved) {
            document.documentElement.setAttribute('data-theme', saved);
        }
    }

    const dashboardHeader = document.querySelector('[data-dashboard-data-url]');
    if (dashboardHeader) {
        const refreshDashboard = function () {
            refreshDashboardData(dashboardHeader.dataset.dashboardDataUrl);
        };
        window.addEventListener('pageshow', refreshDashboard);
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                refreshDashboard();
            }
        });
        window.addEventListener('storage', function (event) {
            if (event.key === 'expenseflow-dashboard-updated') {
                refreshDashboard();
            }
        });
    }

    const transactionModalElement = document.getElementById('transaction-modal');
    const openTransactionButton = document.getElementById('open-transaction-modal');
    const transactionForm = document.getElementById('transaction-form');
    if (!transactionModalElement || !openTransactionButton || !transactionForm) {
        return;
    }

    const transactionModal = bootstrap.Modal.getOrCreateInstance(transactionModalElement);
    const formError = document.getElementById('transaction-form-error');
    const saveButton = document.getElementById('save-transaction-button');
    const feedback = document.getElementById('transaction-feedback');

    openTransactionButton.addEventListener('click', function () {
        formError.classList.add('d-none');
        transactionModal.show();
    });

    transactionModalElement.addEventListener('shown.bs.modal', function () {
        const firstField = transactionForm.querySelector('select, input, textarea');
        if (firstField) {
            firstField.focus();
        }
    });

    if (!saveButton) {
        return;
    }

    const saveButtonLabel = saveButton.querySelector('.save-button-label');
    const saveButtonSpinner = saveButton.querySelector('.spinner-border');
    transactionForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        if (!transactionForm.reportValidity() || saveButton.disabled) {
            return;
        }

        formError.classList.add('d-none');
        feedback.classList.add('d-none');
        saveButton.disabled = true;
        saveButtonLabel.textContent = 'Saving...';
        saveButtonSpinner.classList.remove('d-none');

        try {
            const response = await fetch(transactionForm.action, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(Object.fromEntries(new FormData(transactionForm)))
            });
            if (!response.headers.get('content-type')?.includes('application/json')) {
                throw new Error(response.redirected
                    ? 'Your session may have expired. Please sign in again.'
                    : 'The server returned an unexpected response. Please try again.');
            }
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || 'The transaction could not be saved. Please try again.');
            }

            updateDashboard(result);
            transactionForm.reset();
            formError.classList.add('d-none');
            transactionModal.hide();
            feedback.textContent = 'Transaction saved successfully.';
            feedback.className = 'alert alert-success';
        } catch (error) {
            formError.textContent = error.message || 'The transaction could not be saved. Please try again.';
            formError.classList.remove('d-none');
        } finally {
            saveButton.disabled = false;
            saveButtonLabel.textContent = 'Save Transaction';
            saveButtonSpinner.classList.add('d-none');
        }
    });
});

function updateDashboard(data) {
    document.querySelectorAll('[data-summary-key]').forEach(function (element) {
        const value = Number(data.summary[element.dataset.summaryKey]);
        element.textContent = formatDashboardCurrency(value);
    });

    updateMonthlyDashboardChart(
        window.expenseFlowIncomeChart,
        'incomeOverviewChart',
        data.monthly_chart,
        data.monthly_chart.income
    );
    updateMonthlyDashboardChart(
        window.expenseFlowExpenseChart,
        'expenseOverviewChart',
        data.monthly_chart,
        data.monthly_chart.expense
    );

    if (window.expenseFlowCategoryChart) {
        window.expenseFlowCategoryChart.data.labels = Object.keys(data.categories);
        window.expenseFlowCategoryChart.data.datasets[0].data = Object.values(data.categories).map(Number);
        window.expenseFlowCategoryChart.update();
    }

    function updateMonthlyDashboardChart(chart, canvasId, monthlyData, amounts) {
        if (!chart) {
            return;
        }
        const canvas = document.getElementById(canvasId);
        const hasTransactions = amounts.some(value => Number(value) > 0);
        canvas.classList.toggle('d-none', !hasTransactions);
        canvas.parentElement.querySelector('.dashboard-chart-empty').classList.toggle('d-none', hasTransactions);
        chart.data.labels = monthlyData.labels;
        chart.data.datasets[0].data = amounts.map(Number);
        chart.update();
    }

    const transactionBody = document.getElementById('recent-transactions');
    if (!transactionBody) {
        return;
    }
    transactionBody.replaceChildren();
    if (!data.recent_transactions.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 5;
        cell.className = 'text-center text-muted';
        cell.textContent = 'No transactions yet.';
        row.appendChild(cell);
        transactionBody.appendChild(row);
    } else {
      data.recent_transactions.forEach(function (transaction) {
        const row = document.createElement('tr');
        row.dataset.transactionId = transaction.id;
        row.dataset.transactionUrl = transaction.url;
        row.dataset.title = transaction.title;
        row.dataset.type = transaction.type;
        row.dataset.category = transaction.category;
        row.dataset.amount = transaction.amount;
        row.dataset.accountId = transaction.account_id || '';
        row.dataset.date = transaction.date;
        row.dataset.paymentMethod = transaction.payment_method;
        row.dataset.description = transaction.description;
        const title = document.createElement('td');
        title.textContent = transaction.title;
        const typeCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge ' + (transaction.type.toLowerCase() === 'income' ? 'bg-success' : 'bg-warning') + ' text-white';
        badge.textContent = transaction.type;
        typeCell.appendChild(badge);
        const date = document.createElement('td');
        date.textContent = transaction.date;
        const amount = document.createElement('td');
        amount.textContent = formatDashboardCurrency(transaction.amount);
        const actions = document.createElement('td');
        actions.className = 'text-nowrap';
        const edit = document.createElement('button');
        edit.className = 'btn btn-sm btn-outline-primary edit-transaction me-1';
        edit.type = 'button';
        edit.setAttribute('aria-label', 'Edit transaction');
        edit.innerHTML = '<i class="bi bi-pencil" aria-hidden="true"></i>';
        const remove = document.createElement('button');
        remove.className = 'btn btn-sm btn-outline-danger delete-transaction';
        remove.type = 'button';
        remove.setAttribute('aria-label', 'Delete transaction');
        remove.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i>';
        actions.append(edit, remove);
        row.append(title, typeCell, date, amount, actions);
          transactionBody.appendChild(row);
      });
    }

    const goalsContainer = document.querySelector('.goals-stack');
    if (goalsContainer && Array.isArray(data.goals)) {
        goalsContainer.replaceChildren();
        if (!data.goals.length) {
            const empty = document.createElement('p');
            empty.className = 'text-muted mb-0';
            empty.textContent = 'No goals yet.';
            goalsContainer.appendChild(empty);
        } else {
            data.goals.forEach(function (goal) {
                const card = document.createElement('div');
                card.className = 'goal-card';
                const heading = document.createElement('div');
                heading.className = 'd-flex justify-content-between';
                const name = document.createElement('strong');
                name.textContent = goal.name;
                const percent = document.createElement('span');
                percent.textContent = Number(goal.percent).toFixed(1) + '%';
                heading.append(name, percent);
                const progress = document.createElement('div');
                progress.className = 'progress mt-2';
                const bar = document.createElement('div');
                bar.className = 'progress-bar';
                bar.style.width = Number(goal.percent) + '%';
                progress.appendChild(bar);
                const amounts = document.createElement('small');
                amounts.className = 'text-muted';
                amounts.textContent = formatDashboardCurrency(goal.current) + ' / ' + formatDashboardCurrency(goal.target);
                card.append(heading, progress, amounts);
                goalsContainer.appendChild(card);
            });
        }
    }
}

window.expenseFlowUpdateDashboard = updateDashboard;

function formatDashboardCurrency(value) {
    if (window.expenseFlowFormatCurrency) {
        return window.expenseFlowFormatCurrency.format(Number(value));
    }
    return '$' + Number(value).toFixed(2);
}

async function refreshDashboardData(url) {
    const errorNotice = document.getElementById('dashboard-refresh-error');
    const refreshStatus = document.getElementById('dashboard-refresh-status');
    if (refreshStatus) {
        refreshStatus.textContent = 'Refreshing dashboard data.';
    }
    try {
        const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
        if (!response.ok) {
            throw new Error('Dashboard data could not be refreshed.');
        }
        const data = await response.json();
        if (!data.summary || !data.monthly_chart) {
            throw new Error('The server returned incomplete dashboard data.');
        }
        updateDashboard(data);
        errorNotice.classList.add('d-none');
        errorNotice.textContent = '';
    } catch (error) {
        errorNotice.textContent = error.message || 'Dashboard data could not be refreshed.';
        errorNotice.classList.remove('d-none');
    } finally {
        if (refreshStatus) {
            refreshStatus.textContent = '';
        }
    }
}
