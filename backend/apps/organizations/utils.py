from datetime import time as time_type

SETTING_AUTO_MEDICAL_RECORD = 'auto_create_medical_record'

DEFAULT_ORG_SETTINGS = {
    SETTING_AUTO_MEDICAL_RECORD: False,
    'require_confirmation_before_start': False,
    'allow_anonymous_walkin': False,
    'show_status_change_history': True,
    'require_open_cash_session': False,
    'allow_post_unpaid': False,
    'credit_default_days': 30,
    'currency_code': 'MXN',
    'default_appointment_duration_minutes': 30,
}


DEFAULT_ORGANIZATION_SCHEDULE = [
    {'weekday': 1, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(18, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 2, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(18, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 3, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(18, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 4, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(18, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 5, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(18, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 6, 'is_closed': False, 'opens_at': time_type(9, 0), 'closes_at': time_type(14, 0), 'has_break': False, 'break_start': None, 'break_end': None},
    {'weekday': 7, 'is_closed': True, 'opens_at': None, 'closes_at': None, 'has_break': False, 'break_start': None, 'break_end': None},
]


def get_org_setting(org, key):
    settings = getattr(org, 'settings', None)
    if settings and hasattr(settings, key):
        return getattr(settings, key)
    return DEFAULT_ORG_SETTINGS[key]


def create_default_schedule(organization):
    from .models import OrganizationSchedule
    for entry in DEFAULT_ORGANIZATION_SCHEDULE:
        OrganizationSchedule.objects.get_or_create(
            organization=organization,
            weekday=entry['weekday'],
            defaults=entry,
        )


def ensure_schedule_integrity(organization):
    from .models import OrganizationSchedule
    existing = set(
        OrganizationSchedule.objects.filter(
            organization=organization
        ).values_list('weekday', flat=True)
    )
    for entry in DEFAULT_ORGANIZATION_SCHEDULE:
        if entry['weekday'] not in existing:
            OrganizationSchedule.objects.get_or_create(
                organization=organization,
                weekday=entry['weekday'],
                defaults=entry,
            )
    return OrganizationSchedule.objects.filter(organization=organization).order_by('weekday')
