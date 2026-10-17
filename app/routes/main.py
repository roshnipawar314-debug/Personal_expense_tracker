import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Transaction, Account, Category, Budget, SavingsGoal, Notification, RecurringTransaction
from app.services.finance_service import (
    get_dashboard_summary,
    get_recent_transactions,
    get_goal_progress,
    get_category_totals,
    get_income_expense_chart_data,
    get_monthly_income_expense_chart_data,
)
from app.services.report_service import build_report_data

main_bp = Blueprint('main', __name__)

TRANSACTION_CATEGORIES = (
    'Food', 'Shopping', 'Travel', 'Bills', 'Education', 'Healthcare',
    'Entertainment', 'Salary', 'Freelance', 'Other',
)
TRANSACTION_TYPES = ('income', 'expense')
PAYMENT_METHODS = ('Cash', 'UPI', 'Card', 'Bank Transfer')
MAX_TRANSACTION_AMOUNT = Decimal('9999999999.99')


def _dashboard_snapshot(user):
    summary = get_dashboard_summary(user)
    chart_totals = get_income_expense_chart_data(user)
    categories = get_category_totals(user)
    monthly_chart = get_monthly_income_expense_chart_data(user)
    recent = get_recent_transactions(user, limit=5)

    return {
        'summary': {
            'total_income': str(summary['total_income']),
            'total_expenses': str(summary['total_expenses']),
            'balance': str(summary['balance']),
            'total_savings': str(summary['total_savings']),
        },
        'income_expense': {key: str(value) for key, value in chart_totals.items()},
        'monthly_chart': monthly_chart,
        'categories': {key: str(value) for key, value in categories.items()},
        'recent_transactions': [
            {
                **_transaction_json(transaction),
                'url': url_for('main.transaction_api', transaction_id=transaction.id),
            }
            for transaction in recent
        ],
        'goals': [
            {
                'name': goal.name,
                'current': str(goal.current_amount or 0),
                'target': str(goal.target_amount),
                'percent': str(min(
                    Decimal(goal.current_amount or 0) / Decimal(goal.target_amount) * Decimal('100'),
                    Decimal('100'),
                ) if goal.target_amount else Decimal('0')),
            }
            for goal in SavingsGoal.query.filter_by(user_id=user.id).all()
        ],
    }


def _available_transaction_categories(user):
    names = set(TRANSACTION_CATEGORIES)
    names.update(
        category.name
        for category in Category.query.filter_by(user_id=user.id).all()
    )
    names.update(
        category
        for (category,) in db.session.query(Transaction.category)
        .filter(Transaction.user_id == user.id, Transaction.category.isnot(None))
        .distinct()
        .all()
        if category
    )
    return sorted(names, key=str.casefold)


def _transaction_json(transaction):
    return {
        'id': transaction.id,
        'title': transaction.title,
        'type': transaction.type,
        'category': transaction.category or 'Other',
        'amount': str(transaction.amount),
        'account_id': transaction.account_id,
        'date': transaction.date.isoformat(),
        'payment_method': transaction.payment_method or 'Cash',
        'description': transaction.notes or '',
    }


def _request_values():
    values = request.get_json(silent=True)
    if not hasattr(values, 'get'):
        raise ValueError('Submit valid details.')
    return values


def _validated_account_values(values):
    name = values.get('name')
    name = name.strip() if isinstance(name, str) else ''
    if not name or len(name) > 120:
        raise ValueError('Account name is required and must be 120 characters or fewer.')

    account_type = values.get('type')
    account_type = account_type.strip() if isinstance(account_type, str) else ''
    if not account_type or len(account_type) > 50:
        raise ValueError('Choose a valid account type.')

    currency = values.get('currency')
    currency = currency.strip().upper() if isinstance(currency, str) else ''
    if not currency or len(currency) > 10:
        raise ValueError('Enter a valid currency code.')

    try:
        opening_balance = Decimal(str(values.get('opening_balance', '0')))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Opening balance must be a valid amount.')
    if (
        not opening_balance.is_finite()
        or abs(opening_balance) > MAX_TRANSACTION_AMOUNT
        or opening_balance.as_tuple().exponent < -2
    ):
        raise ValueError('Opening balance must be within the supported range and have at most two decimal places.')

    description = values.get('description', '')
    if description is None:
        description = ''
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError('Account description must be 2,000 characters or fewer.')

    archived_value = values.get('is_archived', False)
    if isinstance(archived_value, str):
        archived_value = archived_value.strip().lower()
        if archived_value not in ('true', 'false', '1', '0', 'on', 'off'):
            raise ValueError('Choose a valid archived setting.')
        is_archived = archived_value in ('true', '1', 'on')
    elif isinstance(archived_value, bool):
        is_archived = archived_value
    elif isinstance(archived_value, int) and archived_value in (0, 1):
        is_archived = bool(archived_value)
    else:
        raise ValueError('Choose a valid archived setting.')
    return {
        'name': name,
        'type': account_type,
        'currency': currency,
        'opening_balance': opening_balance,
        'description': description.strip(),
        'is_archived': is_archived,
    }


def _validated_budget_values(values):
    name = values.get('name')
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        raise ValueError('Budget name is required.')
    if len(name) > 120:
        raise ValueError('Budget name must be 120 characters or fewer.')

    try:
        amount = Decimal(str(values.get('total_amount', '')))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Budget amount must be a valid number greater than zero.')
    if not amount.is_finite() or amount <= 0:
        raise ValueError('Budget amount must be a valid number greater than zero.')
    if amount > MAX_TRANSACTION_AMOUNT or amount.as_tuple().exponent < -2:
        raise ValueError('Budget amount must be no more than 9,999,999,999.99 with at most two decimal places.')

    start_value = values.get('start_date')
    end_value = values.get('end_date')
    try:
        start_date = datetime.strptime(start_value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError('Start date must be a valid date.')
    if start_date.isoformat() != start_value:
        raise ValueError('Start date must be a valid date.')
    try:
        end_date = datetime.strptime(end_value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError('End date must be a valid date.')
    if end_date.isoformat() != end_value:
        raise ValueError('End date must be a valid date.')
    if end_date < start_date:
        raise ValueError('End date cannot be earlier than start date.')

    category = values.get('category', '')
    if category is None:
        category = ''
    if not isinstance(category, str) or len(category.strip()) > 120:
        raise ValueError('Category must be 120 characters or fewer.')
    return {
        'name': name,
        'category': category.strip() or None,
        'total_amount': amount,
        'start_date': start_date,
        'end_date': end_date,
    }


def _validated_goal_values(values):
    name = values.get('name')
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        raise ValueError('Goal name is required.')
    if len(name) > 120:
        raise ValueError('Goal name must be 120 characters or fewer.')

    amounts = {}
    for key, label, allow_zero in (
        ('target_amount', 'Target amount', False),
        ('current_amount', 'Saved amount', True),
    ):
        try:
            amount = Decimal(str(values.get(key, '0' if allow_zero else '')))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f'{label} must be a valid amount.')
        if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
            raise ValueError(f'{label} must be greater than zero.' if not allow_zero else f'{label} cannot be negative.')
        if amount > MAX_TRANSACTION_AMOUNT or amount.as_tuple().exponent < -2:
            raise ValueError(f'{label} must have at most two decimal places and be within the supported range.')
        amounts[key] = amount

    target_date_value = values.get('target_date', '')
    if target_date_value is None:
        target_date_value = ''
    if not isinstance(target_date_value, str):
        raise ValueError('Deadline must be a valid date.')
    if target_date_value:
        try:
            target_date = datetime.strptime(target_date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValueError('Deadline must be a valid date.')
        if target_date.isoformat() != target_date_value:
            raise ValueError('Deadline must be a valid date.')
    else:
        target_date = None

    description = values.get('description', '')
    if description is None:
        description = ''
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError('Goal description must be 2,000 characters or fewer.')
    icon = values.get('icon', 'star')
    status = values.get('status', 'active')
    if not isinstance(icon, str) or not icon.strip() or len(icon.strip()) > 50:
        raise ValueError('Choose a valid goal icon.')
    if not isinstance(status, str) or not status.strip() or len(status.strip()) > 30:
        raise ValueError('Choose a valid goal status.')

    return {
        'name': name,
        'target_amount': amounts['target_amount'],
        'current_amount': amounts['current_amount'],
        'target_date': target_date,
        'description': description.strip(),
        'icon': icon.strip(),
        'status': status.strip(),
    }


def _validated_transaction(user, values):
    raw_type = values.get('type')
    tx_type = raw_type.strip().lower() if isinstance(raw_type, str) else ''
    if tx_type not in TRANSACTION_TYPES:
        raise ValueError('Choose a valid transaction type.')

    raw_amount = values.get('amount')
    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Enter a valid amount.')
    if not amount.is_finite() or amount <= 0:
        raise ValueError('Amount must be greater than zero.')
    if amount > MAX_TRANSACTION_AMOUNT or amount.as_tuple().exponent < -2:
        raise ValueError('Enter an amount with at most two decimal places.')

    raw_category = values.get('category')
    category = raw_category.strip() if isinstance(raw_category, str) else ''
    if category not in _available_transaction_categories(user):
        raise ValueError('Choose a valid category.')

    raw_account_id = values.get('account_id')
    try:
        account_text = str(raw_account_id).strip()
        if not account_text.isdecimal():
            raise ValueError
        account_id = int(account_text)
    except (TypeError, ValueError):
        raise ValueError('Choose an account.')
    account = Account.query.filter_by(
        id=account_id,
        user_id=user.id,
        is_archived=False,
    ).first()
    if account is None:
        raise ValueError('Choose one of your active accounts.')

    raw_date_value = values.get('date')
    raw_date = raw_date_value.strip() if isinstance(raw_date_value, str) else ''
    try:
        transaction_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError('Choose a valid transaction date.')

    raw_payment_method = values.get('payment_method')
    payment_method = raw_payment_method.strip() if isinstance(raw_payment_method, str) else ''
    if payment_method not in PAYMENT_METHODS:
        raise ValueError('Choose a valid payment method.')

    raw_description = values.get('description', values.get('notes', ''))
    if raw_description is None:
        raw_description = ''
    if not isinstance(raw_description, str) or len(raw_description) > 500:
        raise ValueError('Description must be 500 characters or fewer.')
    description = raw_description.strip()
    raw_title = values.get('title')
    if raw_title is not None and not isinstance(raw_title, str):
        raise ValueError('Title must be valid text.')
    title = (raw_title.strip() if isinstance(raw_title, str) else '') or description or category
    if len(title) > 200:
        raise ValueError('Title must be 200 characters or fewer.')

    return Transaction(
        user_id=user.id,
        account_id=account.id,
        title=title[:200],
        type=tx_type,
        category=category,
        amount=amount,
        date=transaction_date,
        payment_method=payment_method,
        notes=description,
    )


@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now(timezone.utc).date()
    summary = get_dashboard_summary(current_user)
    recent = get_recent_transactions(current_user, limit=5)
    goals = get_goal_progress(current_user)
    categories = get_category_totals(current_user)
    monthly_chart = get_monthly_income_expense_chart_data(current_user)

    return render_template(
        'dashboard.html',
        summary=summary,
        recent_transactions=recent,
        goals=goals,
        categories=categories,
        monthly_chart=monthly_chart,
        currency=current_user.preferred_currency or 'USD',
        dashboard_data_url=url_for('main.dashboard_data'),
        today=today,
        accounts=Account.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Account.name).all(),
        transaction_categories=_available_transaction_categories(current_user),
    )


@main_bp.route('/api/dashboard')
@login_required
def dashboard_data():
    return jsonify(_dashboard_snapshot(current_user))


@main_bp.route('/transactions', methods=['GET', 'POST'])
@login_required
def transactions():
    if request.method == 'POST':
        try:
            values = request.get_json(silent=True) if request.is_json else request.form
            if not hasattr(values, 'get'):
                raise ValueError('Submit valid transaction details.')
            transaction = _validated_transaction(current_user, values)
        except ValueError as error:
            if request.is_json:
                return jsonify({'error': str(error)}), 422
            flash(str(error), 'danger')
            return redirect(url_for('main.transactions'))

        try:
            db.session.add(transaction)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Failed to save a transaction for user %s', current_user.id)
            if request.is_json:
                return jsonify({'error': 'The transaction could not be saved. Please try again.'}), 500
            flash('The transaction could not be saved. Please try again.', 'danger')
            return redirect(url_for('main.transactions'))

        if request.is_json:
            return jsonify(_dashboard_snapshot(current_user)), 201
        flash('Transaction saved successfully.', 'success')
        return redirect(url_for('main.transactions'))

    transactions_list = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    accounts = Account.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Account.name).all()
    categories = Category.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'transactions.html',
        transactions=transactions_list,
        accounts=accounts,
        categories=categories,
        today=datetime.now(timezone.utc).date(),
        transaction_categories=_available_transaction_categories(current_user),
        payment_methods=PAYMENT_METHODS,
    )


@main_bp.route('/api/transactions/<int:transaction_id>', methods=['PUT', 'DELETE'])
@login_required
def transaction_api(transaction_id):
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=current_user.id,
    ).first()
    if transaction is None:
        return jsonify({'error': 'Transaction not found.'}), 404

    if request.method == 'DELETE':
        try:
            db.session.delete(transaction)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                'Failed to delete transaction %s for user %s',
                transaction_id,
                current_user.id,
            )
            return jsonify({'error': 'The transaction could not be deleted. Please try again.'}), 500
        return jsonify(_dashboard_snapshot(current_user))

    values = request.get_json(silent=True)
    if not hasattr(values, 'get'):
        return jsonify({'error': 'Submit valid transaction details.'}), 400
    try:
        updated = _validated_transaction(current_user, values)
    except ValueError as error:
        return jsonify({'error': str(error)}), 422

    for field in (
        'account_id', 'title', 'type', 'category', 'amount', 'date',
        'payment_method', 'notes',
    ):
        setattr(transaction, field, getattr(updated, field))

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            'Failed to update transaction %s for user %s',
            transaction_id,
            current_user.id,
        )
        return jsonify({'error': 'The transaction could not be updated. Please try again.'}), 500

    snapshot = _dashboard_snapshot(current_user)
    snapshot['transaction'] = _transaction_json(transaction)
    return jsonify(snapshot)


@main_bp.route('/accounts', methods=['GET','POST'])
@login_required
def accounts():
    if request.method == 'POST':
        values = request.form.to_dict()
        values.setdefault('currency', current_user.preferred_currency or 'USD')
        try:
            account_values = _validated_account_values(values)
        except ValueError as error:
            flash(str(error), 'danger')
        else:
            account_values.pop('is_archived')
            account = Account(user_id=current_user.id, **account_values)
            try:
                db.session.add(account)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception('Failed to save an account for user %s', current_user.id)
                flash('The account could not be saved. Please try again.', 'danger')
            else:
                flash('Account created.', 'success')
                return redirect(url_for('main.accounts'))
    accounts_list = Account.query.filter_by(user_id=current_user.id).all()
    return render_template('accounts.html', accounts=accounts_list)


@main_bp.route('/api/accounts/<int:account_id>', methods=['PUT', 'DELETE'])
@login_required
def account_api(account_id):
    account = Account.query.filter_by(id=account_id, user_id=current_user.id).first()
    if account is None:
        return jsonify({'error': 'Account not found.'}), 404

    if request.method == 'DELETE':
        has_transactions = Transaction.query.filter_by(
            user_id=current_user.id,
            account_id=account.id,
        ).first() is not None
        has_recurring = RecurringTransaction.query.filter_by(
            user_id=current_user.id,
            account_id=account.id,
        ).first() is not None
        if has_transactions or has_recurring:
            return jsonify({
                'error': 'This account still has transactions or recurring transactions. Reassign them before deleting the account.'
            }), 409
        try:
            db.session.delete(account)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Failed to delete account %s for user %s', account_id, current_user.id)
            return jsonify({'error': 'The account could not be deleted. Please try again.'}), 500
        return jsonify({'deleted_id': account_id})

    try:
        values = _validated_account_values(_request_values())
    except ValueError as error:
        return jsonify({'error': str(error)}), 422
    for field, value in values.items():
        setattr(account, field, value)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Failed to update account %s for user %s', account_id, current_user.id)
        return jsonify({'error': 'The account could not be updated. Please try again.'}), 500
    return jsonify({
        'id': account.id,
        'name': account.name,
        'type': account.type,
        'currency': account.currency,
        'opening_balance': str(account.opening_balance),
        'description': account.description or '',
        'is_archived': account.is_archived,
    })


@main_bp.route('/budgets', methods=['GET','POST'])
@login_required
def budgets():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        amount = request.form.get('total_amount', '').strip()
        start_date_value = request.form.get('start_date', '').strip()
        end_date_value = request.form.get('end_date', '').strip()
        category_value = request.form.get('category', '').strip()

        errors = []
        if not name:
            errors.append('Budget name is required.')
        elif len(name) > 120:
            errors.append('Budget name must be 120 characters or fewer.')

        total_amount = None
        try:
            total_amount = Decimal(amount)
        except (InvalidOperation, TypeError, ValueError):
            errors.append('Budget amount must be a valid number greater than zero.')
        else:
            if not total_amount.is_finite() or total_amount <= 0:
                errors.append('Budget amount must be a valid number greater than zero.')
            elif total_amount > Decimal('9999999999.99') or total_amount.as_tuple().exponent < -2:
                errors.append('Budget amount must be no more than 9,999,999,999.99 with at most two decimal places.')

        start_date = None
        end_date = None
        if not start_date_value:
            errors.append('Start date is required.')
        else:
            try:
                start_date = datetime.strptime(start_date_value, '%Y-%m-%d').date()
            except ValueError:
                errors.append('Start date must be a valid date.')
            else:
                if start_date.isoformat() != start_date_value:
                    start_date = None
                    errors.append('Start date must be a valid date.')

        if not end_date_value:
            errors.append('End date is required.')
        else:
            try:
                end_date = datetime.strptime(end_date_value, '%Y-%m-%d').date()
            except ValueError:
                errors.append('End date must be a valid date.')
            else:
                if end_date.isoformat() != end_date_value:
                    end_date = None
                    errors.append('End date must be a valid date.')

        if start_date and end_date and end_date < start_date:
            errors.append('End date cannot be earlier than start date.')
        if category_value and len(category_value) > 120:
            errors.append('Category must be 120 characters or fewer.')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            budget = Budget(
                user_id=current_user.id,
                name=name,
                category=category_value or None,
                total_amount=total_amount,
                start_date=start_date,
                end_date=end_date,
            )
            try:
                db.session.add(budget)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception('Failed to save a budget for user %s', current_user.id)
                flash('The budget could not be saved. Please try again.', 'danger')
            else:
                flash('Budget created successfully.', 'success')
                return redirect(url_for('main.budgets'))

    budgets_list = Budget.query.filter_by(user_id=current_user.id).order_by(Budget.start_date.desc(), Budget.id.desc()).all()
    return render_template('budgets.html', budgets=budgets_list)


@main_bp.route('/api/budgets/<int:budget_id>', methods=['PUT', 'DELETE'])
@login_required
def budget_api(budget_id):
    budget = Budget.query.filter_by(id=budget_id, user_id=current_user.id).first()
    if budget is None:
        return jsonify({'error': 'Budget not found.'}), 404
    if request.method == 'DELETE':
        try:
            db.session.delete(budget)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Failed to delete budget %s for user %s', budget_id, current_user.id)
            return jsonify({'error': 'The budget could not be deleted. Please try again.'}), 500
        return jsonify({'deleted_id': budget_id})
    try:
        values = _validated_budget_values(_request_values())
    except ValueError as error:
        return jsonify({'error': str(error)}), 422
    for field, value in values.items():
        setattr(budget, field, value)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Failed to update budget %s for user %s', budget_id, current_user.id)
        return jsonify({'error': 'The budget could not be updated. Please try again.'}), 500
    return jsonify({
        'id': budget.id,
        'name': budget.name,
        'category': budget.category or '',
        'total_amount': str(budget.total_amount),
        'start_date': budget.start_date.isoformat(),
        'end_date': budget.end_date.isoformat(),
        'is_active': budget.is_active,
    })


@main_bp.route('/goals', methods=['GET','POST'])
@login_required
def goals():
    if request.method == 'POST':
        try:
            values = _validated_goal_values(request.form)
        except ValueError as error:
            flash(str(error), 'danger')
        else:
            goal = SavingsGoal(user_id=current_user.id, **values)
            try:
                db.session.add(goal)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception('Failed to save a goal for user %s', current_user.id)
                flash('The savings goal could not be saved. Please try again.', 'danger')
            else:
                flash('Savings goal created.', 'success')
                return redirect(url_for('main.goals'))
    goals_list = SavingsGoal.query.filter_by(user_id=current_user.id).all()
    return render_template('goals.html', goals=goals_list)


@main_bp.route('/api/goals/<int:goal_id>', methods=['PUT', 'DELETE'])
@login_required
def goal_api(goal_id):
    goal = SavingsGoal.query.filter_by(id=goal_id, user_id=current_user.id).first()
    if goal is None:
        return jsonify({'error': 'Savings goal not found.'}), 404
    if request.method == 'DELETE':
        try:
            db.session.delete(goal)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Failed to delete goal %s for user %s', goal_id, current_user.id)
            return jsonify({'error': 'The savings goal could not be deleted. Please try again.'}), 500
        return jsonify({'deleted_id': goal_id})
    try:
        values = _validated_goal_values(_request_values())
    except ValueError as error:
        return jsonify({'error': str(error)}), 422
    for field, value in values.items():
        setattr(goal, field, value)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Failed to update goal %s for user %s', goal_id, current_user.id)
        return jsonify({'error': 'The savings goal could not be updated. Please try again.'}), 500
    target = Decimal(goal.target_amount or 0)
    current = Decimal(goal.current_amount or 0)
    progress = min(current / target * Decimal('100'), Decimal('100')) if target else Decimal('0')
    return jsonify({
        'id': goal.id,
        'name': goal.name,
        'target_amount': str(goal.target_amount),
        'current_amount': str(goal.current_amount),
        'target_date': goal.target_date.isoformat() if goal.target_date else '',
        'description': goal.description or '',
        'icon': goal.icon or 'star',
        'status': goal.status,
        'progress': str(progress),
    })


@main_bp.route('/notifications')
@login_required
def notifications():
    notifications_list = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifications_list)


@main_bp.route('/reports')
@login_required
def reports():
    try:
        report_data = build_report_data(current_user.id, request.args)
    except ValueError as error:
        flash(str(error), 'danger')
        report_data = build_report_data(current_user.id, {})
    except SQLAlchemyError:
        current_app.logger.exception('Failed to load reports for user %s', current_user.id)
        flash('Reports could not be loaded. Please try again.', 'danger')
        report_data = build_report_data(current_user.id, {})

    today = datetime.now(timezone.utc).date()
    earliest_transaction = db.session.query(func.min(Transaction.date)).filter(
        Transaction.user_id == current_user.id
    ).scalar()
    first_year = earliest_transaction.year if earliest_transaction else today.year
    years = range(first_year, today.year + 1)
    return render_template(
        'reports.html',
        report_data=report_data,
        years=years,
        current_year=today.year,
        current_month=today.month,
        currency=current_user.preferred_currency or 'USD',
        report_api_url=url_for('main.reports_data'),
        report_csv_url=url_for('main.reports_csv'),
        report_pdf_url=url_for('main.reports_pdf'),
        transaction_url_template=url_for('main.transaction_api', transaction_id=0),
        accounts=Account.query.filter_by(
            user_id=current_user.id,
            is_archived=False,
        ).order_by(Account.name).all(),
        transaction_categories=_available_transaction_categories(current_user),
    )


@main_bp.route('/api/reports')
@login_required
def reports_data():
    try:
        return jsonify(build_report_data(current_user.id, request.args))
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except SQLAlchemyError:
        current_app.logger.exception('Failed to calculate reports for user %s', current_user.id)
        return jsonify({'error': 'Reports could not be calculated. Please try again.'}), 500


@main_bp.route('/reports/export.csv')
@login_required
def reports_csv():
    try:
        report = build_report_data(current_user.id, request.args, include_export=True)
    except ValueError as error:
        return Response(str(error), status=400, mimetype='text/plain')
    except SQLAlchemyError:
        current_app.logger.exception('Failed to export CSV report for user %s', current_user.id)
        return Response('The report could not be exported. Please try again.', status=500, mimetype='text/plain')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ExpenseFlow financial report'])
    writer.writerow(['Date range', report['filters']['start_date'], report['filters']['end_date']])
    writer.writerow(['Total income', report['overview']['total_income']])
    writer.writerow(['Total expenses', report['overview']['total_expenses']])
    writer.writerow(['Net savings', report['overview']['net_savings']])
    writer.writerow(['Savings rate (%)', report['overview']['savings_rate']])
    writer.writerow(['Total budget', report['overview']['total_budget']])
    writer.writerow(['Budget used', report['overview']['budget_used']])
    writer.writerow([])
    writer.writerow(['Date', 'Description', 'Category', 'Account', 'Type', 'Amount'])
    for transaction in report['export_transactions']:
        writer.writerow([
            _safe_csv_cell(transaction['date']),
            _safe_csv_cell(transaction['description']),
            _safe_csv_cell(transaction['category']),
            _safe_csv_cell(transaction['account']),
            _safe_csv_cell(transaction['type']),
            _safe_csv_cell(transaction['amount']),
        ])

    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="expenseflow-report.csv"'},
    )


@main_bp.route('/reports/export.pdf')
@login_required
def reports_pdf():
    try:
        report = build_report_data(current_user.id, request.args, include_export=True)
    except ValueError as error:
        return Response(str(error), status=400, mimetype='text/plain')
    except SQLAlchemyError:
        current_app.logger.exception('Failed to export PDF report for user %s', current_user.id)
        return Response('The report could not be exported. Please try again.', status=500, mimetype='text/plain')

    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph('ExpenseFlow Financial Report', styles['Title']),
        Paragraph(
            f"Date range: {report['filters']['start_date']} to {report['filters']['end_date']}",
            styles['Normal'],
        ),
        Spacer(1, 12),
        Paragraph(
            ' &nbsp; | &nbsp; '.join(
                f'{label}: {report["overview"][key]}'
                for label, key in (
                    ('Income', 'total_income'),
                    ('Expenses', 'total_expenses'),
                    ('Net savings', 'net_savings'),
                    ('Budget', 'total_budget'),
                    ('Budget used', 'budget_used'),
                )
            ),
            styles['Normal'],
        ),
        Spacer(1, 16),
    ]
    rows = [['Date', 'Description', 'Category', 'Account', 'Type', 'Amount']]
    rows.extend([
        [
            item['date'],
            Paragraph(escape(item['description']), styles['BodyText']),
            escape(item['category']),
            escape(item['account']),
            item['type'],
            item['amount'],
        ]
        for item in report['export_transactions']
    ])
    table = Table(rows, repeatRows=1, colWidths=[1.05 * inch, 3.0 * inch, 1.45 * inch, 1.65 * inch, 0.9 * inch, 0.9 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#D1D5DB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7FB')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    document.build(story)
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': 'attachment; filename="expenseflow-report.pdf"'},
    )


def _safe_csv_cell(value):
    text = str(value)
    if text.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + text
    return text
