from decimal import Decimal
from datetime import datetime

from sqlalchemy import func

from app import db
from app.models import Account, Transaction, Budget, SavingsGoal


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def _dashboard_transactions(user, start_date=None, end_date=None):
    query = Transaction.query.filter(
        Transaction.user_id == user.id,
        func.lower(func.trim(Transaction.type)).in_(('income', 'expense')),
    )
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    return query


def get_dashboard_summary(user, start_date=None, end_date=None):
    items = _dashboard_transactions(user, start_date, end_date).all()
    income = sum(
        (money(t.amount) for t in items if t.type.strip().lower() == 'income'),
        Decimal('0.00'),
    )
    expenses = sum(
        (money(t.amount) for t in items if t.type.strip().lower() == 'expense'),
        Decimal('0.00'),
    )
    total_savings = income - expenses
    account_opening_balances = db.session.query(
        func.sum(Account.opening_balance)
    ).filter_by(user_id=user.id).scalar()
    has_accounts = Account.query.filter_by(user_id=user.id).first() is not None
    # Per-account openings are authoritative when accounts exist; user openings are legacy fallback.
    opening_balance = (
        money(account_opening_balances)
        if has_accounts
        else money(user.opening_balance)
    )
    balance = opening_balance + total_savings
    budget_total = sum((money(b.total_amount) for b in Budget.query.filter_by(user_id=user.id, is_active=True).all()), Decimal('0.00'))
    budget_used = expenses
    remaining_budget = budget_total - budget_used if budget_total else Decimal('0.00')
    savings_rate = ((total_savings / income) * Decimal('100')) if income else Decimal('0.00')

    return {
        'total_income': income,
        'total_expenses': expenses,
        'balance': balance,
        'total_savings': total_savings,
        'monthly_budget_used': budget_used,
        'remaining_monthly_budget': remaining_budget,
        'savings_rate': savings_rate,
        'transactions_count': len(items),
    }


def get_period_transactions(user, start_date=None, end_date=None):
    query = Transaction.query.filter_by(user_id=user.id)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    return query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()


def get_category_totals(user, start_date=None, end_date=None):
    query = _dashboard_transactions(user, start_date, end_date)
    totals = {}
    for item in query.all():
        if item.type.strip().lower() != 'expense':
            continue
        category = item.category or 'Other'
        totals[category] = totals.get(category, Decimal('0.00')) + money(item.amount)
    return totals


def get_income_expense_chart_data(user, start_date=None, end_date=None):
    query = _dashboard_transactions(user, start_date, end_date)
    totals = {'income': Decimal('0.00'), 'expense': Decimal('0.00')}
    for item in query.all():
        if item.type.strip().lower() == 'income':
            totals['income'] += money(item.amount)
        elif item.type.strip().lower() == 'expense':
            totals['expense'] += money(item.amount)
    return totals


def get_monthly_income_expense_chart_data(user):
    transactions = _dashboard_transactions(user).order_by(
        Transaction.date.asc(),
        Transaction.id.asc(),
    ).all()
    totals_by_month = {}
    for transaction in transactions:
        month_key = transaction.date.strftime('%Y-%m')
        month_totals = totals_by_month.setdefault(
            month_key,
            {'income': Decimal('0.00'), 'expense': Decimal('0.00')},
        )
        transaction_type = transaction.type.strip().lower()
        month_totals[transaction_type] += money(transaction.amount)

    month_keys = sorted(totals_by_month)

    return {
        'labels': [
            datetime.strptime(month_key, '%Y-%m').strftime('%b %Y')
            for month_key in month_keys
        ],
        'income': [
            float(totals_by_month[month_key]['income'])
            for month_key in month_keys
        ],
        'expense': [
            float(totals_by_month[month_key]['expense'])
            for month_key in month_keys
        ],
    }


def get_recent_transactions(user, limit=5):
    return Transaction.query.filter_by(user_id=user.id).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).all()


def get_goal_progress(user):
    goals = SavingsGoal.query.filter_by(user_id=user.id).all()
    progress = []
    for goal in goals:
        target = money(goal.target_amount)
        current = money(goal.current_amount)
        pct = (current / target * Decimal('100')) if target else Decimal('0.00')
        progress.append({
            'name': goal.name,
            'current': current,
            'target': target,
            'remaining': max(target - current, Decimal('0.00')),
            'percent': min(pct, Decimal('100.00')),
            'status': goal.status,
        })
    return progress
