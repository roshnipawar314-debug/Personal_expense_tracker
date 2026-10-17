from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_

from app import db
from app.models import Account, Budget, Category, Transaction


ZERO = Decimal('0.00')
MAX_REPORT_MONTHS = 60


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(month_index, 12)
    return date(year, month_index + 1, 1)


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _parse_iso_date(value: str, label: str) -> date:
    try:
        parsed = datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a valid date in YYYY-MM-DD format.')
    if parsed.isoformat() != value:
        raise ValueError(f'{label} must be a valid date in YYYY-MM-DD format.')
    return parsed


def _date_range(params, today: date) -> tuple[date, date]:
    period = params.get('range', 'this_month')
    current_month = _month_start(today)
    if period == 'this_month':
        return current_month, today
    if period == 'last_month':
        previous_month = _shift_month(current_month, -1)
        return previous_month, _month_end(previous_month)
    if period == 'last_3_months':
        return _shift_month(current_month, -2), today
    if period == 'last_6_months':
        return _shift_month(current_month, -5), today
    if period == 'this_year':
        return date(today.year, 1, 1), today
    if period == 'custom':
        start_value = params.get('start_date', '')
        end_value = params.get('end_date', '')
        if not start_value or not end_value:
            raise ValueError('Choose both a start date and an end date for a custom range.')
        start = _parse_iso_date(start_value, 'Start date')
        end = _parse_iso_date(end_value, 'End date')
        if end < start:
            raise ValueError('End date cannot be earlier than start date.')
        return start, end
    raise ValueError('Choose a valid report date range.')


def _transaction_query(
    user_id: int,
    start: date,
    end: date,
    tx_type: str,
    category: str | None,
    account_id: int | None,
    search: str = '',
):
    query = (
        Transaction.query
        .filter(
            Transaction.user_id == user_id,
            Transaction.date >= start,
            Transaction.date <= end,
        )
        .outerjoin(Account, Transaction.account_id == Account.id)
    )
    if tx_type != 'all':
        query = query.filter(Transaction.type == tx_type)
    if category:
        query = query.filter(Transaction.category == category)
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    if search:
        term = f'%{search.lower()}%'
        query = query.filter(or_(
            func.lower(Transaction.title).like(term),
            func.lower(func.coalesce(Transaction.notes, '')).like(term),
            func.lower(func.coalesce(Transaction.category, '')).like(term),
            func.lower(func.coalesce(Account.name, '')).like(term),
        ))
    return query


def _totals(transactions) -> dict[str, Decimal]:
    values = {'income': ZERO, 'expense': ZERO}
    for transaction in transactions:
        if transaction.type in values:
            values[transaction.type] += Decimal(transaction.amount or 0)
    return values


def _group_amounts(transactions, kind: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for transaction in transactions:
        if transaction.type != kind:
            continue
        category = transaction.category or 'Other'
        totals[category] = totals.get(category, ZERO) + Decimal(transaction.amount or 0)
    return totals


def _comparison(
    current: Decimal,
    previous: Decimal,
    previous_available: bool,
) -> dict[str, str | bool | None]:
    change = current - previous
    percent = (change / previous * Decimal('100')) if previous else None
    return {
        'current': str(current),
        'previous': str(previous),
        'change': str(change),
        'percent': str(percent) if percent is not None else None,
        'previous_available': previous_available,
    }


def _sort_transactions(transactions, sort: str, direction: str):
    sort_keys = {
        'date': lambda item: (item.date, item.id),
        'amount': lambda item: (Decimal(item.amount or 0), item.id),
        'title': lambda item: ((item.title or '').lower(), item.id),
        'category': lambda item: ((item.category or '').lower(), item.id),
        'type': lambda item: ((item.type or '').lower(), item.id),
    }
    key = sort_keys.get(sort)
    if key is None:
        raise ValueError('Choose a valid transaction sort order.')
    return sorted(transactions, key=key, reverse=direction == 'desc')


def build_report_data(
    user_id: int,
    params,
    today: date | None = None,
    include_export: bool = False,
) -> dict:
    today = today or date.today()
    start, end = _date_range(params, today)
    month_count = (
        (end.year - start.year) * 12 + end.month - start.month + 1
    )
    if month_count > MAX_REPORT_MONTHS:
        raise ValueError(f'Report date ranges cannot exceed {MAX_REPORT_MONTHS} months.')

    tx_type = params.get('type', 'all')
    if tx_type not in ('all', 'income', 'expense'):
        raise ValueError('Choose a valid transaction type filter.')

    account_value = params.get('account_id', '').strip()
    account_id = None
    if account_value:
        if not account_value.isdecimal():
            raise ValueError('Choose a valid account.')
        account_id = int(account_value)
        if not Account.query.filter_by(id=account_id, user_id=user_id).first():
            raise ValueError('The selected account is not available.')

    category = params.get('category', '').strip() or None
    if category and not (
        Transaction.query.filter_by(user_id=user_id, category=category).first()
        or Category.query.filter_by(user_id=user_id, name=category).first()
    ):
        raise ValueError('The selected category is not available.')

    try:
        month = int(params.get('month', today.month))
        year = int(params.get('year', today.year))
    except (TypeError, ValueError):
        raise ValueError('Choose a valid report month and year.')
    if not 1 <= month <= 12 or not 1900 <= year <= 9999:
        raise ValueError('Choose a valid report month and year.')

    page_value = params.get('page', '1')
    page_size_value = params.get('page_size', '10')
    if not page_value.isdecimal() or not page_size_value.isdecimal():
        raise ValueError('Page and page size must be positive whole numbers.')
    page = int(page_value)
    page_size = int(page_size_value)
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError('Page must be positive and page size must be between 1 and 100.')

    sort = params.get('sort', 'date')
    direction = params.get('direction', 'desc')
    if direction not in ('asc', 'desc'):
        raise ValueError('Choose a valid transaction sort direction.')

    report_transactions = _transaction_query(
        user_id, start, end, tx_type, category, account_id,
    ).all()
    filtered_totals = _totals(report_transactions)
    net_savings = filtered_totals['income'] - filtered_totals['expense']
    savings_rate = (
        (net_savings / filtered_totals['income'] * Decimal('100')).quantize(Decimal('0.01'))
        if filtered_totals['income'] else ZERO
    )

    budget_rows = Budget.query.filter(
        Budget.user_id == user_id,
        Budget.is_active.is_(True),
        Budget.start_date <= end,
        Budget.end_date >= start,
        *(
            [or_(Budget.category == category, Budget.category.is_(None))]
            if category else []
        ),
    ).order_by(Budget.start_date, Budget.id).all()

    budget_spending_query = _transaction_query(
        user_id, start, end, 'expense', category, account_id,
    )
    expense_transactions = budget_spending_query.all()
    budget_items = []
    for budget in budget_rows:
        budget_start = max(start, budget.start_date)
        budget_end = min(end, budget.end_date)
        spent = sum(
            (
                Decimal(transaction.amount or 0)
                for transaction in expense_transactions
                if budget_start <= transaction.date <= budget_end
                and (not budget.category or (transaction.category or 'Other') == budget.category)
            ),
            ZERO,
        )
        limit = Decimal(budget.total_amount or 0)
        percent = spent / limit * Decimal('100') if limit else ZERO
        status = 'Over Budget' if percent > 100 else 'Near Limit' if percent >= 80 else 'On Track'
        budget_items.append({
            'id': budget.id,
            'name': budget.name,
            'category': budget.category,
            'limit': str(limit),
            'spent': str(spent),
            'remaining': str(limit - spent),
            'percent': str(percent),
            'status': status,
            'start_date': budget.start_date.isoformat(),
            'end_date': budget.end_date.isoformat(),
        })

    total_budget = sum((Decimal(item['limit']) for item in budget_items), ZERO)
    budget_used = sum((Decimal(item.amount or 0) for item in expense_transactions), ZERO)

    month_start = date(year, month, 1)
    month_end = _month_end(month_start)
    previous_month_start = _shift_month(month_start, -1)
    previous_month_end = _month_end(previous_month_start)
    monthly_current_transactions = _transaction_query(
        user_id, month_start, month_end, tx_type, category, account_id,
    ).all()
    monthly_previous_transactions = _transaction_query(
        user_id, previous_month_start, previous_month_end, tx_type, category, account_id,
    ).all()
    monthly_current = _totals(monthly_current_transactions)
    monthly_previous = _totals(monthly_previous_transactions)
    current_net = monthly_current['income'] - monthly_current['expense']
    previous_net = monthly_previous['income'] - monthly_previous['expense']

    previous_period_days = (end - start).days + 1
    previous_period_end = start - timedelta(days=1)
    previous_period_start = previous_period_end - timedelta(days=previous_period_days - 1)
    previous_range_transactions = _transaction_query(
        user_id, previous_period_start, previous_period_end, tx_type, category, account_id,
    ).all()
    previous_range_totals = _totals(previous_range_transactions)

    monthly_points = []
    trend_month = _month_start(start)
    while trend_month <= end:
        trend_end = min(_month_end(trend_month), end)
        trend_start = max(trend_month, start)
        totals = {'income': ZERO, 'expense': ZERO}
        for transaction in report_transactions:
            if trend_start <= transaction.date <= trend_end and transaction.type in totals:
                totals[transaction.type] += Decimal(transaction.amount or 0)
        monthly_points.append({
            'label': trend_month.strftime('%b %Y'),
            'income': str(totals['income']),
            'expense': str(totals['expense']),
            'savings': str(totals['income'] - totals['expense']),
        })
        trend_month = _shift_month(trend_month, 1)

    category_spending = _group_amounts(report_transactions, 'expense')
    income_sources = _group_amounts(report_transactions, 'income')
    previous_categories = _group_amounts(previous_range_transactions, 'expense')
    category_changes = [
        {
            'category': label,
            'current': str(category_spending.get(label, ZERO)),
            'previous': str(previous_categories.get(label, ZERO)),
            'change': str(category_spending.get(label, ZERO) - previous_categories.get(label, ZERO)),
        }
        for label in category_spending.keys() | previous_categories.keys()
    ]
    category_changes.sort(key=lambda item: abs(Decimal(item['change'])), reverse=True)
    highest_category = max(category_spending.items(), key=lambda item: item[1]) if category_spending else None
    highest_month = max(
        (point for point in monthly_points if Decimal(point['expense']) > 0),
        key=lambda point: Decimal(point['expense']),
        default=None,
    )
    has_expense_data = any(transaction.type == 'expense' for transaction in report_transactions)
    average_expenses = (
        sum((Decimal(point['expense']) for point in monthly_points), ZERO) / len(monthly_points)
        if monthly_points and has_expense_data else None
    )

    search = params.get('search', '').strip()[:100]
    if search:
        table_transactions = _transaction_query(
            user_id, start, end, tx_type, category, account_id, search,
        ).all()
    else:
        table_transactions = report_transactions
    table_transactions = _sort_transactions(table_transactions, sort, direction)
    transaction_count = len(table_transactions)
    page_count = (transaction_count + page_size - 1) // page_size
    page_transactions = table_transactions[(page - 1) * page_size:page * page_size]
    account_names = {
        account.id: account.name
        for account in Account.query.filter_by(user_id=user_id).all()
    }

    def serialize_transaction(transaction):
        return {
            'id': transaction.id,
            'date': transaction.date.isoformat(),
            'description': transaction.title,
            'title': transaction.title,
            'category': transaction.category or 'Other',
            'account': account_names.get(transaction.account_id, '—'),
            'account_id': transaction.account_id or '',
            'type': transaction.type,
            'amount': str(transaction.amount),
            'payment_method': transaction.payment_method or 'Cash',
            'notes': transaction.notes or '',
        }

    account_options = [
        {'id': account.id, 'name': account.name}
        for account in Account.query.filter_by(user_id=user_id).order_by(Account.name).all()
    ]
    transaction_categories = {
        category_name or 'Other'
        for (category_name,) in db.session.query(Transaction.category)
        .filter(Transaction.user_id == user_id)
        .distinct()
        .all()
    }
    transaction_categories.update(
        item.name
        for item in Category.query.filter_by(user_id=user_id).all()
    )

    report_data = {
        'filters': {
            'range': params.get('range', 'this_month'),
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'month': month,
            'year': year,
            'type': tx_type,
            'category': category or '',
            'account_id': account_id or '',
            'search': search,
            'sort': sort,
            'direction': direction,
            'page': page,
            'page_size': page_size,
        },
        'overview': {
            'total_income': str(filtered_totals['income']),
            'total_expenses': str(filtered_totals['expense']),
            'net_savings': str(net_savings),
            'savings_rate': str(savings_rate),
            'total_budget': str(total_budget),
            'budget_used': str(budget_used),
        },
        'monthly_summary': {
            'income': str(monthly_current['income']),
            'expenses': str(monthly_current['expense']),
            'net_cash_flow': str(current_net),
            'previous_income': str(monthly_previous['income']),
            'previous_expenses': str(monthly_previous['expense']),
            'previous_net_cash_flow': str(previous_net),
            'month_label': month_start.strftime('%B %Y'),
            'comparisons': {
                'income': _comparison(monthly_current['income'], monthly_previous['income'], bool(monthly_previous_transactions)),
                'expenses': _comparison(monthly_current['expense'], monthly_previous['expense'], bool(monthly_previous_transactions)),
                'net_cash_flow': _comparison(current_net, previous_net, bool(monthly_previous_transactions)),
            },
            'previous_available': bool(monthly_previous_transactions),
        },
        'period_comparison': {
            'previous_start_date': previous_period_start.isoformat(),
            'previous_end_date': previous_period_end.isoformat(),
            'income': _comparison(filtered_totals['income'], previous_range_totals['income'], bool(previous_range_transactions)),
            'expenses': _comparison(filtered_totals['expense'], previous_range_totals['expense'], bool(previous_range_transactions)),
            'previous_available': bool(previous_range_transactions),
        },
        'monthly_trend': monthly_points,
        'expense_categories': {key: str(value) for key, value in category_spending.items()},
        'income_sources': {key: str(value) for key, value in income_sources.items()},
        'budgets': budget_items,
        'transactions': {
            'items': [serialize_transaction(item) for item in page_transactions],
            'total': transaction_count,
            'page': page,
            'page_size': page_size,
            'pages': page_count,
        },
        'insights': {
            'highest_spending_category': (
                {'name': highest_category[0], 'amount': str(highest_category[1])}
                if highest_category else None
            ),
            'highest_expense_month': highest_month,
            'average_monthly_expenses': str(average_expenses) if average_expenses is not None else None,
            'total_savings': str(net_savings),
            'category_changes': category_changes[:5],
            'budgets_available': len(budget_items),
            'budgets_approaching_limit': [
                item for item in budget_items if item['status'] != 'On Track'
            ],
        },
        'options': {
            'accounts': account_options,
            'categories': sorted(transaction_categories),
        },
    }
    if include_export:
        report_data['export_transactions'] = [
            serialize_transaction(item) for item in table_transactions
        ]
    return report_data
