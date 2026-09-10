"""Every model change has its migration (A1: the schema the log lives in is versioned).

No database: `makemigrations --check` needs only the settings module and the app
registry. Django warns that it could not check the migration history against a
live connection; that warning is the expected shape of "no database".

History: `Assertion.seq` carried a help-text change for weeks with no migration,
so a model change with no migration shipped green — CI ran the suite and nothing
ran `makemigrations --check`.
"""

import warnings
from io import StringIO

from django.core.management import call_command


def test_makemigrations_has_nothing_to_write(django_db_blocker) -> None:
    out = StringIO()
    # Unblocked so Django may *try* the consistency check; with no stack up it
    # warns and carries on, which is the whole reason this needs no database.
    with django_db_blocker.unblock(), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit as exc:  # --check exits 1 when a migration is pending
            raise AssertionError(f"Model changes with no migration:\n{out.getvalue()}") from exc
