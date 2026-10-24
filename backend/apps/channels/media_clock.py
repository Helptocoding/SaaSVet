"""One UTC reference for retention, authorization and maintenance: PostgreSQL."""
from django.db import connection


def media_now():
    # clock_timestamp (not transaction start) also works inside short row locks.
    # USE_TZ=True and PostgreSQL are requirements of this application's workers.
    with connection.cursor() as cursor:
        cursor.execute('SELECT clock_timestamp()')
        return cursor.fetchone()[0]
