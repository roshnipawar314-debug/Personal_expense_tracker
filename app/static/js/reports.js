document.addEventListener('DOMContentLoaded', function () {
    const root = document.getElementById('reports-page');
    if (!root) {
        return;
    }

    const fields = {
        range: document.getElementById('report-range'),
        startDate: document.getElementById('report-start-date'),
        endDate: document.getElementById('report-end-date'),
        customDates: document.getElementById('custom-date-fields'),
        type: document.getElementById('report-type'),
        category: document.getElementById('report-category'),
        account: document.getElementById('report-account'),
        month: document.getElementById('report-month'),
        year: document.getElementById('report-year'),
        search: document.getElementById('transaction-search')
    };
    const errorMessage = document.getElementById('reports-error');
    const loadingMessage = document.getElementById('reports-loading');
    const charts = {};
    let currentFilters = window.expenseFlowInitialReport.filters;
    let searchTimer;

    let currency;
    try {
        currency = new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: root.dataset.currency || 'USD'
        });
    } catch (error) {
        currency = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });
    }

    function formatMoney(value) {
        const amount = Number(value);
        return currency.format(Number.isFinite(amount) ? amount : 0);
    }

    function formatPercent(value, digits = 1) {
        const amount = Number(value);
        return Number.isFinite(amount) ? amount.toFixed(digits) + '%' : '—';
    }

    function chartOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' } },
            scales: { y: { beginAtZero: true, ticks: { callback: value => formatMoney(value) } } }
        };
    }

    function ensureChart(key, canvasId, type, labels, datasets, options = {}) {
        const canvas = document.getElementById(canvasId);
        const chartBox = canvas.parentElement;
        const emptyState = chartBox.querySelector('.report-chart-empty');
        const hasValues = datasets.some(dataset => dataset.data.some(value => Number(value) !== 0));
        canvas.classList.toggle('d-none', !hasValues);
        emptyState.classList.toggle('d-none', hasValues);

        if (!hasValues) {
            if (charts[key]) {
                charts[key].destroy();
                delete charts[key];
            }
            return;
        }
        if (charts[key]) {
            charts[key].destroy();
        }
        charts[key] = new Chart(canvas, {
            type,
            data: { labels, datasets },
            options: { ...chartOptions(), ...options }
        });
    }

    function fillFilters(data) {
        currentFilters = data.filters;
        fields.range.value = data.filters.range;
        fields.type.value = data.filters.type;
        fields.month.value = String(data.filters.month);
        fields.year.value = String(data.filters.year);
        fields.startDate.value = data.filters.start_date;
        fields.endDate.value = data.filters.end_date;
        fields.category.value = data.filters.category;
        fields.account.value = String(data.filters.account_id || '');
        fields.search.value = data.filters.search;
        fields.customDates.classList.toggle('d-none', data.filters.range !== 'custom');
    }

    function renderSummary(data) {
        Object.entries(data.overview).forEach(([key, value]) => {
            const element = document.querySelector('[data-report-summary="' + key + '"]');
            if (!element) {
                return;
            }
            element.textContent = key === 'savings_rate' ? formatPercent(value) : formatMoney(value);
        });

        const monthly = data.monthly_summary;
        document.getElementById('monthly-summary-label').textContent =
            'Selected month compared with the previous month';
        document.getElementById('monthly-summary-range').textContent = monthly.month_label;
        ['income', 'expenses', 'net_cash_flow'].forEach(function (key) {
            document.querySelector('[data-monthly-value="' + key + '"]').textContent =
                formatMoney(monthly[key]);
            const comparison = monthly.comparisons[key];
            const element = document.querySelector('[data-monthly-comparison="' + key + '"]');
            const previousAvailable = comparison.previous_available;
            if (!previousAvailable) {
                element.textContent = 'No previous-month data to compare';
                element.className = 'text-muted small';
                return;
            }
            const change = Number(comparison.change);
            element.textContent = (change > 0 ? '+' : '') + formatMoney(change) +
                ' (' + (comparison.percent === null ? 'from zero' : formatPercent(comparison.percent)) + ') vs previous month';
            element.className = 'small ' + (change > 0 ? 'report-change-positive' : change < 0 ? 'report-change-negative' : 'text-muted');
        });
    }

    function renderCharts(data) {
        const overview = data.overview;
        ensureChart('incomeExpenses', 'income-expenses-report-chart', 'bar',
            ['Income', 'Expenses'], [{
                label: 'Selected period',
                data: [Number(overview.total_income), Number(overview.total_expenses)],
                backgroundColor: ['#16A34A', '#EA580C'],
                borderRadius: 8
            }]);

        ensureChart('spendingTrend', 'spending-trend-report-chart', 'line',
            data.monthly_trend.map(item => item.label), [{
                label: 'Expenses',
                data: data.monthly_trend.map(item => Number(item.expense)),
                borderColor: '#4F46E5',
                backgroundColor: 'rgba(79, 70, 229, 0.12)',
                fill: true,
                tension: 0.35
            }]);

        ensureChart('categories', 'category-report-chart', 'doughnut',
            Object.keys(data.expense_categories),
            [{
                label: 'Expenses by category',
                data: Object.values(data.expense_categories).map(Number),
                backgroundColor: ['#4F46E5', '#06B6D4', '#16A34A', '#EA580C', '#DC2626', '#F59E0B', '#8B5CF6', '#14B8A6']
            }],
            { scales: {} });

        ensureChart('incomeSources', 'income-sources-report-chart', 'doughnut',
            Object.keys(data.income_sources),
            [{
                label: 'Income by source',
                data: Object.values(data.income_sources).map(Number),
                backgroundColor: ['#16A34A', '#06B6D4', '#4F46E5', '#F59E0B', '#8B5CF6', '#14B8A6']
            }],
            { scales: {} });

        ensureChart('budgets', 'budget-usage-report-chart', 'bar',
            data.budgets.map(item => item.name), [
                {
                    label: 'Spent',
                    data: data.budgets.map(item => Number(item.spent)),
                    backgroundColor: '#4F46E5',
                    borderRadius: 6
                },
                {
                    label: 'Remaining',
                    data: data.budgets.map(item => Math.max(Number(item.remaining), 0)),
                    backgroundColor: '#DDE3F0',
                    borderRadius: 6
                }
            ],
            { scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } } });

        ensureChart('savingsTrend', 'savings-trend-report-chart', 'line',
            data.monthly_trend.map(item => item.label), [{
                label: 'Net savings',
                data: data.monthly_trend.map(item => Number(item.savings)),
                borderColor: '#16A34A',
                backgroundColor: 'rgba(22, 163, 74, 0.12)',
                fill: true,
                tension: 0.35
            }],
            { scales: { y: { ticks: { callback: value => formatMoney(value) } } } });
    }

    function renderBudgets(budgets) {
        const list = document.getElementById('budget-performance');
        const empty = document.getElementById('budget-empty');
        list.replaceChildren();
        empty.classList.toggle('d-none', budgets.length > 0);
        budgets.forEach(function (budget) {
            const statusClass = budget.status === 'Over Budget'
                ? 'over-budget'
                : budget.status === 'Near Limit' ? 'near-limit' : 'on-track';
            const row = document.createElement('article');
            row.className = 'report-budget-row';

            const title = document.createElement('div');
            title.className = 'report-budget-title';
            const name = document.createElement('strong');
            name.textContent = budget.name;
            const category = document.createElement('span');
            category.className = 'text-muted small';
            category.textContent = budget.category || 'All categories';
            title.append(name, category);

            const dates = document.createElement('small');
            dates.className = 'text-muted';
            dates.textContent = budget.start_date + ' – ' + budget.end_date;

            const figures = document.createElement('div');
            figures.className = 'report-budget-figures';
            figures.textContent = formatMoney(budget.spent) + ' spent of ' + formatMoney(budget.limit) +
                ' · ' + formatMoney(budget.remaining) + ' remaining';

            const status = document.createElement('span');
            status.className = 'badge report-budget-status ' + statusClass;
            status.textContent = budget.status;

            const progress = document.createElement('div');
            progress.className = 'progress report-budget-progress';
            progress.setAttribute('role', 'progressbar');
            progress.setAttribute('aria-label', budget.name + ' budget used');
            progress.setAttribute('aria-valuenow', String(Math.min(Number(budget.percent), 100)));
            progress.setAttribute('aria-valuemin', '0');
            progress.setAttribute('aria-valuemax', '100');
            const bar = document.createElement('div');
            bar.className = 'progress-bar ' + statusClass;
            bar.style.width = Math.min(Math.max(Number(budget.percent), 0), 100) + '%';
            progress.appendChild(bar);

            const percent = document.createElement('small');
            percent.className = 'report-budget-percent';
            percent.textContent = formatPercent(budget.percent);

            row.append(title, dates, figures, status, progress, percent);
            list.appendChild(row);
        });
    }

    function insightCard(titleText, valueText, detailText, className = '') {
        const card = document.createElement('article');
        card.className = 'report-insight-card ' + className;
        const title = document.createElement('span');
        title.className = 'text-muted small';
        title.textContent = titleText;
        const value = document.createElement('strong');
        value.textContent = valueText;
        const detail = document.createElement('small');
        detail.className = 'text-muted';
        detail.textContent = detailText;
        card.append(title, value, detail);
        return card;
    }

    function renderInsights(insights) {
        const container = document.getElementById('report-insights');
        container.replaceChildren();
        container.appendChild(insightCard(
            'Highest spending category',
            insights.highest_spending_category ? insights.highest_spending_category.name : 'Not enough data',
            insights.highest_spending_category ? formatMoney(insights.highest_spending_category.amount) + ' in this period' : 'No expenses recorded in this period.'
        ));
        container.appendChild(insightCard(
            'Highest expense month',
            insights.highest_expense_month ? insights.highest_expense_month.label : 'Not enough data',
            insights.highest_expense_month ? formatMoney(insights.highest_expense_month.expense) + ' in expenses' : 'No monthly expense data is available.'
        ));
        container.appendChild(insightCard(
            'Average monthly expenses',
            insights.average_monthly_expenses === null
                ? 'Not enough data'
                : formatMoney(insights.average_monthly_expenses),
            insights.average_monthly_expenses === null
                ? 'No expenses were recorded in this period.'
                : 'Based on each month in the selected date range.'
        ));
        container.appendChild(insightCard(
            'Net savings this period',
            formatMoney(insights.total_savings),
            'Income minus expenses for the selected filters.'
        ));

        const changes = document.createElement('article');
        changes.className = 'report-insight-card report-insight-wide';
        const heading = document.createElement('strong');
        heading.textContent = 'Category spending changes';
        changes.appendChild(heading);
        if (!insights.category_changes.length) {
            const empty = document.createElement('small');
            empty.className = 'text-muted';
            empty.textContent = 'Not enough category data to compare with the previous period.';
            changes.appendChild(empty);
        } else {
            insights.category_changes.slice(0, 4).forEach(function (item) {
                const line = document.createElement('small');
                const change = Number(item.change);
                line.className = change > 0 ? 'report-change-negative' : change < 0 ? 'report-change-positive' : 'text-muted';
                line.textContent = item.category + ': ' + (change > 0 ? '+' : '') + formatMoney(change) +
                    ' vs previous period';
                changes.appendChild(line);
            });
        }
        container.appendChild(changes);

        const warningBudgets = insights.budgets_approaching_limit;
        const budgetCard = insightCard(
            'Budgets needing attention',
            !insights.budgets_available
                ? 'No budgets'
                : warningBudgets.length ? warningBudgets.length + ' budget' + (warningBudgets.length === 1 ? '' : 's') : 'All on track',
            !insights.budgets_available
                ? 'There are no active budgets in this report period.'
                : warningBudgets.length
                    ? warningBudgets.map(item => item.name + ' (' + item.status + ')').join(', ')
                    : 'No budget has reached 80% usage.'
        );
        container.appendChild(budgetCard);
    }

    function renderTransactions(data) {
        const body = document.getElementById('report-transactions');
        body.replaceChildren();
        document.getElementById('transaction-result-count').textContent =
            data.total + ' transaction' + (data.total === 1 ? '' : 's');
        document.getElementById('report-page-label').textContent =
            data.pages ? 'Page ' + data.page + ' of ' + data.pages : 'No pages';
        document.getElementById('report-page-prev').disabled = data.page <= 1;
        document.getElementById('report-page-next').disabled = data.page >= data.pages;

        if (!data.items.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 7;
            cell.className = 'text-center text-muted py-4';
            cell.textContent = 'No transactions match these filters.';
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }

        data.items.forEach(function (item) {
            const row = document.createElement('tr');
            row.dataset.transactionId = item.id;
            row.dataset.transactionUrl = root.dataset.transactionUrlTemplate.replace(/0$/, String(item.id));
            row.dataset.title = item.title;
            row.dataset.type = item.type;
            row.dataset.category = item.category;
            row.dataset.amount = item.amount;
            row.dataset.accountId = item.account_id;
            row.dataset.date = item.date;
            row.dataset.paymentMethod = item.payment_method;
            row.dataset.description = item.notes;
            [item.date, item.description, item.category, item.account].forEach(function (value) {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            });
            const typeCell = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge ' + (item.type === 'income' ? 'bg-success' : item.type === 'expense' ? 'bg-warning' : 'bg-secondary') + ' text-white';
            badge.textContent = item.type;
            typeCell.appendChild(badge);
            row.appendChild(typeCell);
            const amount = document.createElement('td');
            amount.className = 'text-end fw-semibold';
            amount.textContent = formatMoney(item.amount);
            row.appendChild(amount);
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
            row.appendChild(actions);
            body.appendChild(row);
        });
    }

    function render(data) {
        fillFilters(data);
        document.getElementById('report-range-label').textContent =
            'Report period: ' + data.filters.start_date + ' to ' + data.filters.end_date;
        renderSummary(data);
        renderCharts(data);
        renderBudgets(data.budgets);
        renderInsights(data.insights);
        renderTransactions(data.transactions);
        document.querySelectorAll('.report-sort-button').forEach(function (button) {
            const marker = button.querySelector('span');
            marker.textContent = data.filters.sort === button.dataset.sort
                ? (data.filters.direction === 'asc' ? ' ↑' : ' ↓')
                : '';
        });
    }

    function queryParams() {
        const params = new URLSearchParams({
            range: fields.range.value,
            type: fields.type.value,
            category: fields.category.value,
            account_id: fields.account.value,
            month: fields.month.value,
            year: fields.year.value,
            search: fields.search.value,
            sort: currentFilters.sort,
            direction: currentFilters.direction,
            page: currentFilters.page,
            page_size: currentFilters.page_size
        });
        if (fields.range.value === 'custom') {
            params.set('start_date', fields.startDate.value);
            params.set('end_date', fields.endDate.value);
        }
        return params;
    }

    async function refreshReport(resetPage = true) {
        if (resetPage) {
            currentFilters.page = 1;
        }
        errorMessage.classList.add('d-none');
        loadingMessage.classList.remove('d-none');
        try {
            const response = await fetch(root.dataset.apiUrl + '?' + queryParams().toString(), {
                headers: { 'Accept': 'application/json' }
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || 'The report could not be updated.');
            }
            render(result);
        } catch (error) {
            errorMessage.textContent = error.message || 'The report could not be updated. Please try again.';
            errorMessage.classList.remove('d-none');
        } finally {
            loadingMessage.classList.add('d-none');
        }
    }

    function exportUrl(url) {
        window.location.assign(url + '?' + queryParams().toString());
    }

    fields.range.addEventListener('change', function () {
        fields.customDates.classList.toggle('d-none', fields.range.value !== 'custom');
        if (fields.range.value !== 'custom') {
            refreshReport();
        }
    });
    fields.startDate.addEventListener('change', () => refreshReport());
    fields.endDate.addEventListener('change', () => refreshReport());
    [fields.type, fields.category, fields.account, fields.month, fields.year].forEach(function (field) {
        field.addEventListener('change', () => refreshReport());
    });
    fields.search.addEventListener('input', function () {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => refreshReport(), 300);
    });
    document.querySelectorAll('.report-sort-button').forEach(function (button) {
        button.addEventListener('click', function () {
            if (currentFilters.sort === button.dataset.sort) {
                currentFilters.direction = currentFilters.direction === 'asc' ? 'desc' : 'asc';
            } else {
                currentFilters.sort = button.dataset.sort;
                currentFilters.direction = button.dataset.sort === 'date' ? 'desc' : 'asc';
            }
            refreshReport();
        });
    });
    document.getElementById('report-page-prev').addEventListener('click', function () {
        currentFilters.page = Math.max(1, currentFilters.page - 1);
        refreshReport(false);
    });
    document.getElementById('report-page-next').addEventListener('click', function () {
        currentFilters.page += 1;
        refreshReport(false);
    });
    document.getElementById('download-csv').addEventListener('click', () => exportUrl(root.dataset.csvUrl));
    document.getElementById('download-pdf').addEventListener('click', () => exportUrl(root.dataset.pdfUrl));
    document.getElementById('print-report').addEventListener('click', () => window.print());
    window.addEventListener('expenseflow:transaction-changed', () => refreshReport());
    window.addEventListener('expenseflow:budgets-changed', () => refreshReport());

    render(window.expenseFlowInitialReport);
});
