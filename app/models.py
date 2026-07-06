"""
SQLAlchemy Models for Group Test Manager
- Clean relationships and constraints.
- Properties for dashboard visibility and cost calculations (no magic numbers).
- Password security via Werkzeug.
- JSON field for flexible lab_test_details (matches original spreadsheet's multiple tests).
"""

from datetime import datetime
from flask_login import UserMixin
from . import db
import json

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    tg_username = db.Column(db.String(80), nullable=True, index=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    participations = db.relationship(
        'Participation', 
        backref='user', 
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    
    def set_password(self, password: str):
        """Hash password using Werkzeug (scrypt or pbkdf2, strong defaults)."""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password, method='scrypt', salt_length=16)
    
    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class GroupTest(db.Model):
    __tablename__ = 'group_tests'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    
    # Original spreadsheet fields
    vendor = db.Column(db.String(120), nullable=True)
    batch_number = db.Column(db.String(100), nullable=True)
    compound = db.Column(db.String(100), nullable=True)
    size = db.Column(db.String(50), nullable=True)  # e.g. "10x 10mg vials"
    
    status = db.Column(db.String(20), default='recruiting', nullable=False, index=True)
    # Allowed: recruiting, testing, closed
    
    # Lab testing costs - flexible itemized (JSON array of objects)
    # Example: [{"name": "MASS, PURITY + ID", "price": 360.0, "vials_needed": 1}, {"name": "STERILITY", "price": 290.0, "vials_needed": 0}]
    lab_test_details = db.Column(db.JSON, nullable=True)
    total_lab_cost = db.Column(db.Float, default=0.0, nullable=False)
    shipping_cost = db.Column(db.Float, default=0.0, nullable=False)  # Shipment to lab
    
    # Admin tracking
    order_number = db.Column(db.String(100), nullable=True)
    quote_number = db.Column(db.String(100), nullable=True)
    
    # Results - only shown to approved participants when status == 'closed'
    results_link = db.Column(db.String(500), nullable=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Configurable refund (from original INPUTS row)
    refund_per_donor = db.Column(db.Float, default=20.0, nullable=False)
    
    # Relationships
    participations = db.relationship(
        'Participation', 
        backref='group_test', 
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Participation.requested_at'
    )
    
    @property
    def approved_participations(self):
        """Query helper for approved only."""
        return self.participations.filter_by(approved=True)
    
    @property
    def num_approved(self) -> int:
        return self.approved_participations.count()
    
    @property
    def num_donors(self) -> int:
        return self.approved_participations.filter_by(vial_donor=True).count()
    
    @property
    def num_non_donors(self) -> int:
        return self.num_approved - self.num_donors
    
    def calculate_costs(self):
        """
        Rigorous cost calculation logic matching & improving on original spreadsheet.
        
        Assumptions (documented for transparency & auditability):
        - Total fixed costs = lab + shipping.
        - Donors (vial providers) receive a fixed refund_per_donor credit (admin configurable, default $20).
        - To keep pool fair: non-donors pay a small uplift to fund the donor refunds.
        - Edge cases handled: 0 participants, 0 donors, 0 non-donors.
        
        Returns dict with all values for templates + admin views.
        """
        n_part = self.num_approved
        n_donors = self.num_donors
        n_non = self.num_non_donors
        
        total_fixed = (self.total_lab_cost or 0.0) + (self.shipping_cost or 0.0)
        refund_per = self.refund_per_donor or 0.0
        total_refund_pool = refund_per * n_donors if n_donors > 0 else 0.0
        
        if n_part == 0:
            return {
                'total_participants': 0,
                'total_donors': 0,
                'total_non_donors': 0,
                'total_fixed_cost': round(total_fixed, 2),
                'total_refund_pool': round(total_refund_pool, 2),
                'base_per_person': 0.0,
                'donor_pays': 0.0,
                'non_donor_pays': 0.0,
                'effective_donor_refund': round(refund_per, 2),
                'message': 'No approved participants yet.'
            }
        
        # Base share of fixed costs
        base_share = total_fixed / n_part
        
        if n_non == 0:
            # All are donors: they still get refund but pool must cover from fixed or admin adjusts refund
            donor_pays = max(0.0, base_share - refund_per)
            non_donor_pays = 0.0
        else:
            # Non-donors fund the refund pool via uplift
            uplift_per_non = total_refund_pool / n_non if n_non > 0 else 0.0
            non_donor_pays = round(base_share + uplift_per_non, 2)
            donor_pays = round(max(0.0, base_share - refund_per), 2)
        
        return {
            'total_participants': n_part,
            'total_donors': n_donors,
            'total_non_donors': n_non,
            'total_fixed_cost': round(total_fixed, 2),
            'total_refund_pool': round(total_refund_pool, 2),
            'base_per_person': round(base_share, 2),
            'donor_pays': donor_pays,
            'non_donor_pays': non_donor_pays,
            'effective_donor_refund': round(refund_per, 2),
            'message': None
        }
    
    def can_user_see(self, user) -> bool:
        """Visibility rule exactly as specified."""
        if user.is_admin:
            return True
        if self.status == 'recruiting':
            return True
        # testing or closed: only approved participants
        if self.status in ('testing', 'closed'):
            return self.participations.filter_by(user_id=user.id, approved=True).first() is not None
        return False
    
    def __repr__(self):
        return f'<GroupTest {self.id} {self.title} [{self.status}]>'


class Participation(db.Model):
    """
    Join/Participation record. Created on request (approved=False), promoted by admin.
    Captures all original spreadsheet columns + payment tracking.
    """
    __tablename__ = 'participations'
    __table_args__ = (
        db.UniqueConstraint('group_test_id', 'user_id', name='_group_test_user_uc'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    group_test_id = db.Column(db.Integer, db.ForeignKey('group_tests.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Core participant data (from request form + admin edits)
    name = db.Column(db.String(120), nullable=True)
    tg_username = db.Column(db.String(80), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    order_status = db.Column(db.String(50), default='pending')  # pending, ordered, received, etc.
    us_based = db.Column(db.Boolean, default=True)
    vial_donor = db.Column(db.Boolean, default=False)
    state = db.Column(db.String(50), nullable=True)
    pay_vial_collector = db.Column(db.Boolean, default=False)
    pay_lab = db.Column(db.Boolean, default=False)
    paid_lab = db.Column(db.Boolean, default=False)          # Admin verification
    payment_verified = db.Column(db.Boolean, default=False)  # Admin can mark as verified
    
    # Simplified payment status (shown to all approved members)
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid, pending, complete
    
    # Financial tracking (admin or future auto)
    amount_owed = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)           # Self-reported by participant
    notes = db.Column(db.Text, nullable=True)
    
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    def update_amount_owed(self, costs_dict):
        """Helper to sync individual owed based on role (donor vs non). Call after approve or recalc."""
        if self.vial_donor:
            self.amount_owed = costs_dict.get('donor_pays', 0.0)
        else:
            self.amount_owed = costs_dict.get('non_donor_pays', 0.0)
    
    def __repr__(self):
        return f'<Participation user={self.user_id} test={self.group_test_id} approved={self.approved}>'