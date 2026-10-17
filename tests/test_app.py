from datetime import date

import pytest

from app import create_app
from app import db
from app.models import Account, Budget, SavingsGoal, Transaction, User


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    application = create_app()
    application.config.update(TESTING=True)
    with application.app_context():
        db.drop_all()
        db.create_all()
        user = User(full_name='Test User', email='test@example.com')
        user.set_password('test-password')
        db.session.add(user)
        db.session.flush()
        db.session.add(Account(user_id=user.id, name='Everyday', type='Cash', opening_balance=0))
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def logged_in_client(app):
    client = app.test_client()
    client.post('/auth/login', data={'email': 'test@example.com', 'password': 'test-password'})
    return client


def test_create_app(app):
    assert app is not None


def test_login_page_loads(app):
    client = app.test_client()
    response = client.get('/auth/login')
    assert response.status_code == 200


def test_dashboard_requires_login(app):
    client = app.test_client()
    response = client.get('/dashboard')
    assert response.status_code == 302


def test_add_transaction_updates_dashboard_and_transactions_page(app):
    client = logged_in_client(app)
    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert b'id="open-transaction-modal"' in dashboard.data
    assert b'id="transaction-form"' in dashboard.data
    assert b'Income Overview' in dashboard.data
    assert b'Expense Overview' in dashboard.data
    assert b'No income transactions available yet.' in dashboard.data
    assert b'No expense transactions available yet.' in dashboard.data
    assert b'id="incomeOverviewChart"' in dashboard.data
    assert b'id="expenseOverviewChart"' in dashboard.data
    assert b'#2563EB' in dashboard.data
    assert b'#F97316' in dashboard.data
    assert b"indexAxis: 'x'" in dashboard.data
    assert b"text: 'Month'" in dashboard.data
    assert b"text: 'Amount (' + chartCurrency + ')'" in dashboard.data
    assert b'moneyFormatter.format(item.parsed.y)' in dashboard.data
    assert b'id="incomeExpenseChart"' not in dashboard.data
    empty_snapshot = client.get('/api/dashboard').get_json()
    assert empty_snapshot['monthly_chart'] == {
        'labels': [],
        'income': [],
        'expense': [],
    }

    response = client.post('/transactions', json={
        'type': 'expense',
        'amount': '42.75',
        'category': 'Food',
        'account_id': '1',
        'date': date.today().isoformat(),
        'payment_method': 'Card',
        'description': 'Weekly groceries',
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data['summary']['total_expenses'] == '42.75'
    assert data['summary']['total_savings'] == '-42.75'
    assert data['income_expense']['expense'] == '42.75'
    assert data['categories']['Food'] == '42.75'
    assert data['recent_transactions'][0]['title'] == 'Weekly groceries'
    assert data['monthly_chart']['income'][-1] == 0.0
    assert data['monthly_chart']['expense'][-1] == 42.75

    income_response = client.post('/transactions', json={
        'type': 'income',
        'amount': '150.25',
        'category': 'Salary',
        'account_id': '1',
        'date': date.today().isoformat(),
        'payment_method': 'Bank Transfer',
        'description': 'Monthly salary',
    })
    assert income_response.status_code == 201
    income_data = income_response.get_json()
    assert income_data['summary']['total_income'] == '150.25'
    assert income_data['summary']['balance'] == '107.50'
    assert income_data['summary']['total_savings'] == '107.50'
    assert income_data['income_expense'] == {'income': '150.25', 'expense': '42.75'}
    assert income_data['monthly_chart']['income'][-1] == 150.25
    assert income_data['monthly_chart']['expense'][-1] == 42.75

    with app.app_context():
        transactions = Transaction.query.order_by(Transaction.id).all()
        assert len(transactions) == 2
        assert transactions[0].user_id == 1
        assert transactions[0].account_id == 1
        assert transactions[0].amount == 42.75

    updated_dashboard = client.get('/dashboard')
    assert b'150.25' in updated_dashboard.data
    assert b'107.50' in updated_dashboard.data
    assert b'150.25' in updated_dashboard.data
    assert b'42.75' in updated_dashboard.data
    transactions_page = client.get('/transactions')
    assert b'Weekly groceries' in transactions_page.data
    assert b'Monthly salary' in transactions_page.data
    assert b'Food' in transactions_page.data


def test_dashboard_data_normalizes_types_and_groups_all_years_for_one_user(app):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').one()
        user.opening_balance = 500
        db.session.add_all([
            Transaction(
                user_id=user.id,
                account_id=1,
                title='Year-end pay',
                type='Income',
                amount=325,
                date=date(2025, 12, 30),
            ),
            Transaction(
                user_id=user.id,
                account_id=1,
                title='January groceries',
                type='expense',
                amount=120.50,
                category='Food',
                date=date(2026, 1, 2),
            ),
            Transaction(
                user_id=user.id,
                account_id=1,
                title='October groceries',
                type=' EXPENSE ',
                amount=30,
                category='Food',
                date=date(2026, 10, 3),
            ),
            Transaction(
                user_id=user.id,
                account_id=1,
                title='Transfer',
                type='transfer',
                amount=999,
                date=date(2026, 10, 4),
            ),
        ])
        other_user = User(full_name='Other User', email='other@example.com')
        other_user.set_password('test-password')
        db.session.add(other_user)
        db.session.flush()
        other_account = Account(user_id=other_user.id, name='Other', type='Cash')
        db.session.add(other_account)
        db.session.flush()
        db.session.add(Transaction(
            user_id=other_user.id,
            account_id=other_account.id,
            title='Private income',
            type='income',
            amount=10000,
            date=date(2026, 10, 5),
        ))
        db.session.commit()

    response = logged_in_client(app).get('/api/dashboard')
    assert response.status_code == 200
    data = response.get_json()
    assert data['summary']['total_income'] == '325.00'
    assert data['summary']['total_expenses'] == '150.50'
    assert data['summary']['total_savings'] == '174.50'
    assert data['summary']['balance'] == '174.50'
    assert data['categories'] == {'Food': '150.50'}
    assert data['monthly_chart'] == {
        'labels': ['Dec 2025', 'Jan 2026', 'Oct 2026'],
        'income': [325.0, 0.0, 0.0],
        'expense': [0.0, 120.5, 30.0],
    }


def test_dashboard_monthly_charts_update_with_inr_income_and_expense_mutations(app):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').one()
        user.preferred_currency = 'INR'
        db.session.commit()

    client = logged_in_client(app)
    income_response = client.post('/transactions', json={
        'type': 'income',
        'amount': '1000.00',
        'category': 'Salary',
        'account_id': '1',
        'date': '2025-12-15',
        'payment_method': 'Bank Transfer',
        'description': 'Test income',
    })
    assert income_response.status_code == 201
    income_data = income_response.get_json()
    assert income_data['monthly_chart'] == {
        'labels': ['Dec 2025'],
        'income': [1000.0],
        'expense': [0.0],
    }
    assert income_data['summary']['total_income'] == '1000.00'

    expense_response = client.post('/transactions', json={
        'type': 'expense',
        'amount': '500.00',
        'category': 'Food',
        'account_id': '1',
        'date': '2026-01-05',
        'payment_method': 'Card',
        'description': 'Test expense',
    })
    assert expense_response.status_code == 201
    expense_data = expense_response.get_json()
    assert expense_data['monthly_chart'] == {
        'labels': ['Dec 2025', 'Jan 2026'],
        'income': [1000.0, 0.0],
        'expense': [0.0, 500.0],
    }
    assert expense_data['summary'] == {
        'total_income': '1000.00',
        'total_expenses': '500.00',
        'balance': '500.00',
        'total_savings': '500.00',
    }

    with app.app_context():
        transactions = Transaction.query.order_by(Transaction.id).all()
        income_id, expense_id = (transaction.id for transaction in transactions)
    edit_response = client.put(f'/api/transactions/{income_id}', json={
        'type': 'income',
        'amount': '1200.00',
        'category': 'Salary',
        'account_id': '1',
        'date': '2026-02-01',
        'payment_method': 'Bank Transfer',
        'description': 'Updated test income',
    })
    assert edit_response.status_code == 200
    edited_data = edit_response.get_json()
    assert edited_data['monthly_chart'] == {
        'labels': ['Jan 2026', 'Feb 2026'],
        'income': [0.0, 1200.0],
        'expense': [500.0, 0.0],
    }

    delete_response = client.delete(f'/api/transactions/{expense_id}')
    assert delete_response.status_code == 200
    dashboard_response = client.get('/api/dashboard')
    assert dashboard_response.status_code == 200
    persisted_data = dashboard_response.get_json()
    assert persisted_data['monthly_chart'] == {
        'labels': ['Feb 2026'],
        'income': [1200.0],
        'expense': [0.0],
    }
    dashboard_page = client.get('/dashboard')
    assert b'INR' in dashboard_page.data


def test_edit_and_delete_transaction_refresh_dashboard_data(app):
    client = logged_in_client(app)
    response = client.post('/transactions', json={
        'type': 'expense',
        'amount': '25.00',
        'category': 'Food',
        'account_id': '1',
        'date': '2026-10-01',
        'payment_method': 'Cash',
        'description': 'Initially an expense',
    })
    assert response.status_code == 201
    with app.app_context():
        transaction_id = Transaction.query.one().id

    edit_response = client.put(f'/api/transactions/{transaction_id}', json={
        'type': 'INCOME',
        'amount': '125.75',
        'category': 'Salary',
        'account_id': '1',
        'date': '2025-12-01',
        'payment_method': 'Bank Transfer',
        'description': 'Updated income',
        'title': 'Updated income',
    })
    assert edit_response.status_code == 200
    updated_data = edit_response.get_json()
    assert updated_data['transaction']['type'] == 'income'
    assert updated_data['summary']['total_income'] == '125.75'
    assert updated_data['summary']['total_expenses'] == '0.00'
    assert updated_data['monthly_chart'] == {
        'labels': ['Dec 2025'],
        'income': [125.75],
        'expense': [0.0],
    }

    delete_response = client.delete(f'/api/transactions/{transaction_id}')
    assert delete_response.status_code == 200
    deleted_data = delete_response.get_json()
    assert deleted_data['summary']['total_income'] == '0.00'
    assert deleted_data['monthly_chart'] == {
        'labels': [],
        'income': [],
        'expense': [],
    }
    with app.app_context():
        assert Transaction.query.count() == 0


def test_transaction_mutation_api_is_user_scoped(app):
    client = logged_in_client(app)
    with app.app_context():
        other_user = User(full_name='Other User', email='other@example.com')
        other_user.set_password('test-password')
        db.session.add(other_user)
        db.session.flush()
        other_transaction = Transaction(
            user_id=other_user.id,
            title='Private expense',
            type='expense',
            amount=50,
            date=date.today(),
        )
        db.session.add(other_transaction)
        db.session.commit()
        transaction_id = other_transaction.id

    assert client.put(
        f'/api/transactions/{transaction_id}',
        json={'type': 'income'},
    ).status_code == 404
    assert client.delete(f'/api/transactions/{transaction_id}').status_code == 404
    with app.app_context():
        assert Transaction.query.count() == 1


def test_accounts_budgets_and_goals_can_be_updated_and_deleted_safely(app):
    client = logged_in_client(app)
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').one()
        account = Account(user_id=user.id, name='Travel card', type='Bank', opening_balance=10)
        budget = Budget(
            user_id=user.id,
            name='Old budget',
            category='Food',
            total_amount=100,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        goal = SavingsGoal(
            user_id=user.id,
            name='Old goal',
            target_amount=500,
            current_amount=50,
            target_date=date(2027, 1, 1),
            description='Old note',
        )
        db.session.add_all([account, budget, goal])
        db.session.commit()
        account_id, budget_id, goal_id = account.id, budget.id, goal.id

    for path, markers in (
        ('/accounts', (b'edit-account-modal', b'edit-resource')),
        ('/budgets', (b'edit-budget-modal', b'edit-resource')),
        ('/goals', (b'edit-goal-modal', b'goal-progress')),
    ):
        page = client.get(path)
        assert page.status_code == 200
        for marker in markers:
            assert marker in page.data

    account_response = client.put(f'/api/accounts/{account_id}', json={
        'name': 'Travel savings',
        'type': 'Savings',
        'currency': 'INR',
        'opening_balance': '250.75',
        'description': 'Updated account',
        'is_archived': False,
    })
    assert account_response.status_code == 200
    assert account_response.get_json()['name'] == 'Travel savings'
    assert client.get('/api/dashboard').get_json()['summary']['balance'] == '250.75'

    budget_response = client.put(f'/api/budgets/{budget_id}', json={
        'name': 'Revised food plan',
        'category': 'Food',
        'total_amount': '425.50',
        'start_date': '2026-11-01',
        'end_date': '2026-11-30',
    })
    assert budget_response.status_code == 200
    assert budget_response.get_json()['total_amount'] == '425.50'
    with app.app_context():
        saved_budget = db.session.get(Budget, budget_id)
        assert saved_budget.name == 'Revised food plan'
        assert saved_budget.start_date == date(2026, 11, 1)
        assert saved_budget.end_date == date(2026, 11, 30)

    goal_response = client.put(f'/api/goals/{goal_id}', json={
        'name': 'New home fund',
        'target_amount': '1200.00',
        'current_amount': '375.25',
        'target_date': '2027-06-15',
        'description': 'Updated goal details',
        'icon': 'house',
        'status': 'active',
    })
    assert goal_response.status_code == 200
    assert goal_response.get_json()['progress'] == '31.27083333333333333333333333'
    dashboard_goals = client.get('/api/dashboard').get_json()['goals']
    assert dashboard_goals == [{
        'name': 'New home fund',
        'current': '375.25',
        'target': '1200.00',
        'percent': '31.27083333333333333333333333',
    }]
    with app.app_context():
        saved_goal = db.session.get(SavingsGoal, goal_id)
        assert saved_goal.target_date == date(2027, 6, 15)
        assert saved_goal.description == 'Updated goal details'

    assert client.delete(f'/api/budgets/{budget_id}').status_code == 200
    assert client.delete(f'/api/goals/{goal_id}').status_code == 200
    assert client.delete(f'/api/accounts/{account_id}').status_code == 200
    with app.app_context():
        assert Budget.query.count() == 0
        assert SavingsGoal.query.count() == 0
        assert Account.query.filter_by(name='Travel savings').count() == 0


def test_account_with_transactions_cannot_be_deleted_until_reassigned(app):
    client = logged_in_client(app)
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').one()
        account = Account(user_id=user.id, name='Temporary', type='Cash')
        db.session.add(account)
        db.session.flush()
        transaction = Transaction(
            user_id=user.id,
            account_id=account.id,
            title='Linked expense',
            type='expense',
            category='Food',
            amount=10,
            date=date(2026, 10, 1),
            payment_method='Cash',
        )
        db.session.add(transaction)
        db.session.commit()
        account_id, transaction_id = account.id, transaction.id

    blocked = client.delete(f'/api/accounts/{account_id}')
    assert blocked.status_code == 409
    assert 'Reassign them before deleting' in blocked.get_json()['error']
    with app.app_context():
        assert db.session.get(Account, account_id) is not None
        assert db.session.get(Transaction, transaction_id) is not None

    reassigned = client.put(f'/api/transactions/{transaction_id}', json={
        'type': 'expense',
        'amount': '10.00',
        'category': 'Food',
        'account_id': '1',
        'date': '2026-10-01',
        'payment_method': 'Cash',
        'description': 'Linked expense',
        'title': 'Linked expense',
    })
    assert reassigned.status_code == 200
    assert client.delete(f'/api/accounts/{account_id}').status_code == 200
    with app.app_context():
        assert Transaction.query.one().account_id == 1


def test_resource_mutations_are_user_scoped_and_reject_invalid_values(app):
    client = logged_in_client(app)
    with app.app_context():
        other_user = User(full_name='Other User', email='resource-owner@example.com')
        other_user.set_password('test-password')
        db.session.add(other_user)
        db.session.flush()
        account = Account(user_id=other_user.id, name='Private account', type='Cash')
        budget = Budget(
            user_id=other_user.id,
            name='Private budget',
            total_amount=100,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        goal = SavingsGoal(user_id=other_user.id, name='Private goal', target_amount=100)
        db.session.add_all([account, budget, goal])
        db.session.commit()
        ids = account.id, budget.id, goal.id

    account_id, budget_id, goal_id = ids
    valid_account = {
        'name': 'Changed',
        'type': 'Cash',
        'currency': 'USD',
        'opening_balance': '0',
        'description': '',
    }
    assert client.put(f'/api/accounts/{account_id}', json=valid_account).status_code == 404
    assert client.delete(f'/api/accounts/{account_id}').status_code == 404
    assert client.put(f'/api/budgets/{budget_id}', json={
        'name': 'Changed',
        'total_amount': '200',
        'start_date': '2026-11-01',
        'end_date': '2026-11-30',
    }).status_code == 404
    assert client.delete(f'/api/budgets/{budget_id}').status_code == 404
    assert client.put(f'/api/goals/{goal_id}', json={
        'name': 'Changed',
        'target_amount': '200',
        'current_amount': '0',
    }).status_code == 404
    assert client.delete(f'/api/goals/{goal_id}').status_code == 404

    with app.app_context():
        own_goal = SavingsGoal(user_id=1, name='Valid goal', target_amount=100)
        own_budget = Budget(
            user_id=1,
            name='Valid budget',
            total_amount=100,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        db.session.add_all([own_goal, own_budget])
        db.session.commit()
        own_goal_id, own_budget_id = own_goal.id, own_budget.id

    assert client.put(f'/api/budgets/{own_budget_id}', json={
        'name': 'Invalid range',
        'total_amount': '100',
        'start_date': '2026-11-30',
        'end_date': '2026-11-01',
    }).status_code == 422
    assert client.put(f'/api/goals/{own_goal_id}', json={
        'name': 'Invalid goal',
        'target_amount': '0',
        'current_amount': '-1',
        'target_date': 'not-a-date',
    }).status_code == 422
    with app.app_context():
        assert db.session.get(Budget, own_budget_id).name == 'Valid budget'
        assert db.session.get(SavingsGoal, own_goal_id).name == 'Valid goal'


@pytest.mark.parametrize(
    ('updates', 'message'),
    [
        ({'amount': '0'}, 'Amount must be greater than zero.'),
        ({'type': 'transfer'}, 'Choose a valid transaction type.'),
        ({'category': 'Invalid'}, 'Choose a valid category.'),
        ({'date': 'not-a-date'}, 'Choose a valid transaction date.'),
        ({'account_id': '999'}, 'Choose one of your active accounts.'),
    ],
)
def test_invalid_transaction_is_rejected(app, updates, message):
    client = logged_in_client(app)
    payload = {
        'type': 'expense',
        'amount': '12.50',
        'category': 'Food',
        'account_id': '1',
        'date': date.today().isoformat(),
        'payment_method': 'Cash',
        'description': '',
    }
    payload.update(updates)
    response = client.post('/transactions', json=payload)
    assert response.status_code == 422
    assert response.get_json()['error'] == message
    with app.app_context():
        assert Transaction.query.count() == 0


def test_transaction_cannot_use_another_users_account(app):
    client = logged_in_client(app)
    with app.app_context():
        other_user = User(full_name='Other User', email='other@example.com')
        other_user.set_password('test-password')
        db.session.add(other_user)
        db.session.flush()
        other_account = Account(user_id=other_user.id, name='Private', type='Bank')
        db.session.add(other_account)
        db.session.commit()
        other_account_id = other_account.id

    response = client.post('/transactions', json={
        'type': 'income',
        'amount': '100',
        'category': 'Salary',
        'account_id': str(other_account_id),
        'date': date.today().isoformat(),
        'payment_method': 'Bank Transfer',
        'description': 'Payday',
    })
    assert response.status_code == 422
    with app.app_context():
        assert Transaction.query.count() == 0


def test_budget_form_converts_dates_and_persists_for_logged_in_user(app):
    client = logged_in_client(app)
    start = date(2026, 10, 1)
    end = date(2026, 10, 31)
    response = client.post('/budgets', data={
        'name': 'October Food Plan',
        'category': 'Food',
        'total_amount': '450.25',
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
    })
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/budgets')

    page = client.get(response.headers['Location'])
    assert b'Budget created successfully.' in page.data
    assert b'October Food Plan' in page.data
    assert b'Food' in page.data
    assert b'$450.25' in page.data
    assert b'2026-10-01' in page.data
    assert b'2026-10-31' in page.data

    with app.app_context():
        budget = Budget.query.one()
        assert budget.user_id == 1
        assert budget.name == 'October Food Plan'
        assert budget.category == 'Food'
        assert budget.total_amount == 450.25
        assert budget.start_date == start
        assert budget.end_date == end
        assert isinstance(budget.start_date, date)
        assert isinstance(budget.end_date, date)

    refreshed_page = client.get('/budgets')
    assert b'October Food Plan' in refreshed_page.data


def test_budget_category_is_optional(app):
    client = logged_in_client(app)
    response = client.post('/budgets', data={
        'name': 'General plan',
        'category': '',
        'total_amount': '75',
        'start_date': '2026-10-01',
        'end_date': '2026-10-15',
    })
    assert response.status_code == 302
    with app.app_context():
        budget = Budget.query.one()
        assert budget.category is None


@pytest.mark.parametrize(
    ('updates', 'message'),
    [
        ({'name': ''}, 'Budget name is required.'),
        ({'total_amount': 'abc'}, 'Budget amount must be a valid number greater than zero.'),
        ({'total_amount': '0'}, 'Budget amount must be a valid number greater than zero.'),
        ({'start_date': ''}, 'Start date is required.'),
        ({'start_date': '2026-02-30'}, 'Start date must be a valid date.'),
        ({'end_date': ''}, 'End date is required.'),
        ({'end_date': 'not-a-date'}, 'End date must be a valid date.'),
        ({'end_date': '2026-09-30'}, 'End date cannot be earlier than start date.'),
    ],
)
def test_invalid_budget_is_not_saved(app, updates, message):
    client = logged_in_client(app)
    payload = {
        'name': 'Valid budget',
        'category': '',
        'total_amount': '100',
        'start_date': '2026-10-01',
        'end_date': '2026-10-31',
    }
    payload.update(updates)
    response = client.post('/budgets', data=payload)
    assert response.status_code == 200
    assert message.encode() in response.data
    assert b'Budget created successfully.' not in response.data
    with app.app_context():
        assert Budget.query.count() == 0


def test_budgets_are_scoped_to_the_logged_in_user(app):
    first_client = logged_in_client(app)
    first_client.post('/budgets', data={
        'name': 'Private budget',
        'category': '',
        'total_amount': '100',
        'start_date': '2026-10-01',
        'end_date': '2026-10-31',
    })

    with app.app_context():
        other_user = User(full_name='Other User', email='other@example.com')
        other_user.set_password('test-password')
        db.session.add(other_user)
        db.session.commit()

    other_client = app.test_client()
    other_client.post('/auth/login', data={
        'email': 'other@example.com',
        'password': 'test-password',
    })
    other_page = other_client.get('/budgets')
    assert b'Private budget' not in other_page.data


def seed_report_data(app):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').one()
        second_account = Account(user_id=user.id, name='Bank', type='Bank', opening_balance=0)
        db.session.add(second_account)
        db.session.flush()
        db.session.add_all([
            Transaction(
                user_id=user.id, account_id=1, title='October salary',
                type='income', category='Salary', amount=2000,
                date=date(2026, 10, 5), payment_method='Bank Transfer',
            ),
            Transaction(
                user_id=user.id, account_id=1, title='Groceries',
                type='expense', category='Food', amount=100,
                date=date(2026, 10, 6), payment_method='Card',
            ),
            Transaction(
                user_id=user.id, account_id=second_account.id, title='Train trip',
                type='expense', category='Travel', amount=300,
                date=date(2026, 10, 7), payment_method='UPI',
            ),
            Transaction(
                user_id=user.id, account_id=1, title='September salary',
                type='income', category='Salary', amount=1500,
                date=date(2026, 9, 5), payment_method='Bank Transfer',
            ),
            Transaction(
                user_id=user.id, account_id=1, title='September groceries',
                type='expense', category='Food', amount=50,
                date=date(2026, 9, 6), payment_method='Card',
            ),
        ])
        db.session.add_all([
            Budget(
                user_id=user.id, name='Food plan', category='Food',
                total_amount=120, start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 31),
            ),
            Budget(
                user_id=user.id, name='General plan', category=None,
                total_amount=500, start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 31),
            ),
        ])
        db.session.commit()


def test_reports_use_actual_filtered_transactions_budgets_and_comparisons(app):
    seed_report_data(app)
    client = logged_in_client(app)
    response = client.get(
        '/api/reports?range=custom&start_date=2026-10-01&end_date=2026-10-31&month=10&year=2026'
    )
    assert response.status_code == 200
    report = response.get_json()
    assert report['overview']['total_income'] == '2000.00'
    assert report['overview']['total_expenses'] == '400.00'
    assert report['overview']['net_savings'] == '1600.00'
    assert report['overview']['savings_rate'] == '80.00'
    assert report['overview']['total_budget'] == '620.00'
    assert report['overview']['budget_used'] == '400.00'
    assert report['monthly_summary']['net_cash_flow'] == '1600.00'
    assert report['monthly_summary']['comparisons']['income']['previous'] == '1500.00'
    assert report['monthly_summary']['comparisons']['expenses']['previous'] == '50.00'
    assert report['expense_categories'] == {'Food': '100.00', 'Travel': '300.00'}
    assert report['income_sources'] == {'Salary': '2000.00'}
    assert report['insights']['highest_spending_category'] == {'name': 'Travel', 'amount': '300.00'}
    assert {item['name']: item['status'] for item in report['budgets']} == {
        'Food plan': 'Near Limit',
        'General plan': 'Near Limit',
    }
    assert report['transactions']['total'] == 3

    filtered = client.get(
        '/api/reports?range=custom&start_date=2026-10-01&end_date=2026-10-31&month=10&year=2026'
        '&type=expense&category=Food&account_id=1'
    ).get_json()
    assert filtered['overview']['total_income'] == '0.00'
    assert filtered['overview']['total_expenses'] == '100.00'
    assert filtered['expense_categories'] == {'Food': '100.00'}
    assert filtered['transactions']['total'] == 1
    assert filtered['transactions']['items'][0]['account'] == 'Everyday'


def test_reports_search_sort_pagination_and_exports_follow_filters(app):
    seed_report_data(app)
    client = logged_in_client(app)
    params = (
        'range=custom&start_date=2026-10-01&end_date=2026-10-31&month=10&year=2026'
        '&search=trip&sort=amount&direction=asc'
    )
    search_result = client.get('/api/reports?' + params).get_json()
    assert search_result['transactions']['total'] == 1
    assert search_result['transactions']['items'][0]['description'] == 'Train trip'

    paginated = client.get(
        '/api/reports?range=custom&start_date=2026-10-01&end_date=2026-10-31'
        '&month=10&year=2026&page_size=2&page=2&sort=amount&direction=asc'
    ).get_json()
    assert paginated['transactions']['pages'] == 2
    assert len(paginated['transactions']['items']) == 1
    assert paginated['transactions']['items'][0]['amount'] == '2000.00'

    csv_response = client.get('/reports/export.csv?' + params)
    assert csv_response.status_code == 200
    assert csv_response.mimetype == 'text/csv'
    assert b'2026-10-01,2026-10-31' in csv_response.data
    assert b'Train trip' in csv_response.data
    assert b'Groceries' not in csv_response.data

    pdf_response = client.get('/reports/export.pdf?' + params)
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == 'application/pdf'
    assert pdf_response.data.startswith(b'%PDF')


def test_report_transaction_actions_recalculate_data_and_export_latest_values(app):
    seed_report_data(app)
    client = logged_in_client(app)
    page = client.get('/reports')
    assert page.status_code == 200
    assert b'data-transaction-url-template=' in page.data
    assert b'edit-transaction-modal' in page.data
    assert b'Actions' in page.data
    report_script = client.get('/static/js/reports.js').data
    assert b'edit-transaction' in report_script
    assert b'delete-transaction' in report_script

    with app.app_context():
        groceries = Transaction.query.filter_by(title='Groceries').one()
        groceries_id = groceries.id
    update = client.put(f'/api/transactions/{groceries_id}', json={
        'type': 'expense',
        'amount': '225.50',
        'category': 'Food',
        'account_id': '1',
        'date': '2026-10-06',
        'payment_method': 'Card',
        'description': 'Updated groceries',
        'title': 'Updated groceries',
    })
    assert update.status_code == 200

    filters = (
        'range=custom&start_date=2026-10-01&end_date=2026-10-31'
        '&month=10&year=2026&type=expense&category=Food&account_id=1'
    )
    edited_report = client.get('/api/reports?' + filters).get_json()
    assert edited_report['overview']['total_expenses'] == '225.50'
    assert edited_report['expense_categories'] == {'Food': '225.50'}
    assert edited_report['transactions']['items'][0]['description'] == 'Updated groceries'
    csv_response = client.get('/reports/export.csv?' + filters)
    assert b'Updated groceries' in csv_response.data
    assert b'225.50' in csv_response.data

    deleted = client.delete(f'/api/transactions/{groceries_id}')
    assert deleted.status_code == 200
    empty_filtered_report = client.get('/api/reports?' + filters).get_json()
    assert empty_filtered_report['overview']['total_expenses'] == '0.00'
    assert empty_filtered_report['transactions']['total'] == 0
    with app.app_context():
        assert db.session.get(Transaction, groceries_id) is None


@pytest.mark.parametrize(
    'query',
    [
        '?range=custom&start_date=2026-10-31&end_date=2026-10-01',
        '?range=custom&start_date=bad&end_date=2026-10-31',
        '?range=custom&start_date=2026-10-01',
        '?type=transfer',
        '?account_id=999',
        '?month=13',
    ],
)
def test_reports_reject_invalid_filters(app, query):
    client = logged_in_client(app)
    response = client.get('/api/reports' + query)
    assert response.status_code == 400
    assert 'error' in response.get_json()


def test_reports_page_loads_with_database_based_report_data(app):
    seed_report_data(app)
    client = logged_in_client(app)
    response = client.get('/reports')
    assert response.status_code == 200
    assert b'Financial reports' in response.data
    assert b'Income vs expenses' in response.data
    assert b'reports.js' in response.data


def test_empty_report_uses_non_misleading_insight_states(app):
    client = logged_in_client(app)
    response = client.get('/api/reports')
    assert response.status_code == 200
    report = response.get_json()
    assert report['insights']['highest_spending_category'] is None
    assert report['insights']['highest_expense_month'] is None
    assert report['insights']['average_monthly_expenses'] is None
    assert report['insights']['budgets_available'] == 0
    assert report['insights']['budgets_approaching_limit'] == []


def test_report_exports_and_data_require_authentication(app):
    client = app.test_client()
    assert client.get('/api/reports').status_code == 302
    assert client.get('/reports/export.csv').status_code == 302
    assert client.get('/reports/export.pdf').status_code == 302
