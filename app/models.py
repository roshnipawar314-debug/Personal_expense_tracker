from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import JSON
from werkzeug.security import generate_password_hash, check_password_hash

from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    preferred_currency = db.Column(db.String(10), default='USD')
    first_day_of_month = db.Column(db.Integer, default=1)
    notification_preferences = db.Column(db.JSON, default=dict)
    opening_balance = db.Column(db.Numeric(12, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    accounts = db.relationship('Account', back_populates='user', cascade='all, delete-orphan')
    categories = db.relationship('Category', back_populates='user', cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', back_populates='user', cascade='all, delete-orphan')
    budgets = db.relationship('Budget', back_populates='user', cascade='all, delete-orphan')
    goals = db.relationship('SavingsGoal', back_populates='user', cascade='all, delete-orphan')
    notifications = db.relationship('Notification', back_populates='user', cascade='all, delete-orphan')
    recurring_transactions = db.relationship('RecurringTransaction', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(50), default='Cash')
    currency = db.Column(db.String(10), default='USD')
    opening_balance = db.Column(db.Numeric(12, 2), default=0)
    description = db.Column(db.Text)
    is_archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='accounts')
    transactions = db.relationship('Transaction', back_populates='account', cascade='all, delete-orphan')


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income or expense
    color = db.Column(db.String(20), default='#4F46E5')
    icon = db.Column(db.String(40), default='tag')
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='categories')
    parent = db.relationship('Category', remote_side='Category.id', backref='children')


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income, expense, transfer
    category = db.Column(db.String(120), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    payment_method = db.Column(db.String(50), default='Cash')
    merchant = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text)
    tags = db.Column(db.String(200), default='')
    attachment = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default='completed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='transactions')
    account = db.relationship('Account', back_populates='transactions')


class Budget(db.Model):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(120), nullable=True)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='budgets')


class SavingsGoal(db.Model):
    __tablename__ = 'savings_goals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    target_amount = db.Column(db.Numeric(12, 2), nullable=False)
    current_amount = db.Column(db.Numeric(12, 2), default=0)
    target_date = db.Column(db.Date, nullable=True)
    description = db.Column(db.Text)
    icon = db.Column(db.String(50), default='star')
    status = db.Column(db.String(30), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='goals')


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='notifications')


class RecurringTransaction(db.Model):
    __tablename__ = 'recurring_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(120), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    frequency = db.Column(db.String(30), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    next_due_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='recurring_transactions')
    account = db.relationship('Account')
