"""Local model tests without MySQL, Docker, or optional admin dependencies.

Run: python manage.py test app1 --settings=datamodel_demo.test_settings
The in-memory database is built directly from models (no app migrations yet).
"""

SECRET_KEY = "local-tests-only"
INSTALLED_APPS = ["app1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "app1.test_urls"
USE_TZ = True
MIGRATION_MODULES = {"app1": None}
# Table comments are irrelevant to these backend-independent behavior tests.
SILENCED_SYSTEM_CHECKS = ["models.W046"]
