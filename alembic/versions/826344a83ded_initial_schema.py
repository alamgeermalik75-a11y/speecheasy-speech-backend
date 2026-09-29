"""initial_schema

Revision ID: 826344a83ded
Revises: 
Create Date: 2026-09-27 20:07:59.736728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '826344a83ded'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Profiles
    op.create_table(
        'profiles',
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('parent_name', sa.String(), nullable=True),
        sa.Column('child_name', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('patient_uid')
    )
    op.create_index(op.f('ix_profiles_patient_uid'), 'profiles', ['patient_uid'], unique=False)

    # 2. Focus Sound
    op.create_table(
        'focus_sound',
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('sound', sa.String(), nullable=True),
        sa.Column('alphabet_name', sa.String(), nullable=True),
        sa.Column('progress', sa.Numeric(), nullable=False, server_default='0.0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('progress >= 0 AND progress <= 1', name='check_focus_progress_bounds'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('patient_uid')
    )

    # 3. Daily Tips
    op.create_table(
        'daily_tips',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tip_text', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('daily_tips_active_idx', 'daily_tips', ['is_active', 'sort_order'], unique=False)

    # 4. Therapists
    op.create_table(
        'therapists',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('qualification', sa.String(), nullable=True),
        sa.Column('years_of_experience', sa.Integer(), server_default='0', nullable=False),
        sa.Column('languages_spoken', sa.String(), nullable=True),
        sa.Column('rating', sa.Numeric(precision=3, scale=2), server_default='5.0', nullable=False),
        sa.Column('consultation_fee', sa.Numeric(precision=10, scale=2), server_default='0.0', nullable=False),
        sa.Column('doctor_code', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='approved', nullable=False),
        sa.CheckConstraint('years_of_experience >= 0', name='check_years_exp_non_negative'),
        sa.CheckConstraint('consultation_fee >= 0', name='check_fee_non_negative'),
        sa.CheckConstraint('rating >= 0 AND rating <= 5', name='check_therapist_rating_range'),
        sa.CheckConstraint("status IN ('approved', 'pending')", name='check_therapist_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('doctor_code')
    )
    op.create_index(op.f('ix_therapists_doctor_code'), 'therapists', ['doctor_code'], unique=True)

    # 5. Availability
    op.create_table(
        'availability',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.String(), nullable=False),
        sa.Column('day', sa.String(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.CheckConstraint('start_time < end_time', name='check_availability_time_valid'),
        sa.CheckConstraint(
            "day IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')",
            name='check_availability_day_valid'
        ),
        sa.ForeignKeyConstraint(['doctor_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_availability_doctor_id'), 'availability', ['doctor_id'], unique=False)

    # 6. Patients
    op.create_table(
        'patients',
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['doctor_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('patient_uid', 'doctor_id')
    )

    # 7. Patient Requests
    op.create_table(
        'patient_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.String(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('patient_name', sa.String(), nullable=False),
        sa.Column('parent_email', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name='check_patient_request_status'),
        sa.ForeignKeyConstraint(['doctor_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('doctor_id', 'patient_uid', 'status', name='uq_doctor_patient_request_status')
    )
    op.create_index(op.f('ix_patient_requests_doctor_id'), 'patient_requests', ['doctor_id'], unique=False)
    op.create_index(op.f('ix_patient_requests_patient_uid'), 'patient_requests', ['patient_uid'], unique=False)

    # 8. Appointments
    op.create_table(
        'appointments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.String(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('patient_name', sa.String(), nullable=False),
        sa.Column('appointment_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('start_time < end_time', name='check_appointment_time_valid'),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'booked', 'cancelled', 'completed')", name='check_appointment_status_valid'),
        sa.ForeignKeyConstraint(['doctor_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_active_doctor_appointments', 'appointments', ['doctor_id', 'appointment_date', 'start_time'], unique=False)
    op.create_index(op.f('ix_appointments_appointment_date'), 'appointments', ['appointment_date'], unique=False)
    op.create_index(op.f('ix_appointments_doctor_id'), 'appointments', ['doctor_id'], unique=False)
    op.create_index(op.f('ix_appointments_patient_uid'), 'appointments', ['patient_uid'], unique=False)

    # 9. Attempts
    op.create_table(
        'attempts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('alphabet_name', sa.String(), nullable=False),
        sa.Column('level_key', sa.String(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('score >= 0 AND score <= 100', name='check_attempt_score_range'),
        sa.CheckConstraint("level_key IN ('words', 'sentences', 'fillBlanks', 'poems', 'story')", name='check_attempt_level_key'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_attempts_patient_alphabet', 'attempts', ['patient_uid', 'alphabet_name'], unique=False)
    op.create_index('idx_attempts_patient_timestamp', 'attempts', ['patient_uid', 'attempted_at'], unique=False)
    op.create_index(op.f('ix_attempts_patient_uid'), 'attempts', ['patient_uid'], unique=False)

    # 10. Notifications
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('icon', sa.String(), server_default='🏆', nullable=False),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_notifications_patient_created', 'notifications', ['patient_uid', 'created_at'], unique=False)
    op.create_index('idx_notifications_patient_read', 'notifications', ['patient_uid', 'is_read'], unique=False)
    op.create_index(op.f('ix_notifications_patient_uid'), 'notifications', ['patient_uid'], unique=False)

    # 11. Ratings
    op.create_table(
        'ratings',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('doctor_id', sa.String(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='check_rating_range'),
        sa.ForeignKeyConstraint(['doctor_id'], ['therapists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_uid'], ['profiles.patient_uid'], ondelete='CASCADE'),
        sa.UniqueConstraint('doctor_id', 'patient_uid', name='uq_doctor_patient_rating')
    )
    op.create_index(op.f('ix_ratings_patient_uid'), 'ratings', ['patient_uid'], unique=False)


def downgrade() -> None:
    op.drop_table('ratings')
    op.drop_table('notifications')
    op.drop_table('attempts')
    op.drop_table('appointments')
    op.drop_table('patient_requests')
    op.drop_table('patients')
    op.drop_table('availability')
    op.drop_table('therapists')
    op.drop_table('daily_tips')
    op.drop_table('focus_sound')
    op.drop_table('profiles')
