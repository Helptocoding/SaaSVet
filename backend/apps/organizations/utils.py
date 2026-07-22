from datetime import time as time_type

SETTING_AUTO_MEDICAL_RECORD = 'auto_create_medical_record'
SETTING_AUTO_INVOICE_ON_DONE = 'auto_create_invoice_on_done'

DEFAULT_ORG_SETTINGS = {
    SETTING_AUTO_MEDICAL_RECORD: False,
    SETTING_AUTO_INVOICE_ON_DONE: False,
    'require_confirmation_before_start': False,
    'allow_anonymous_walkin': False,
    'show_status_change_history': True,
    'require_open_cash_session': False,
    'locale': 'es-MX',
    'currency_code': 'MXN',
    'default_appointment_duration_minutes': 30,
    'appointment_buffer_minutes': 0,
    'allow_emergency_walkin': False,
    'week_starts_on': 1,
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
