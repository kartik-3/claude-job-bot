import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

SECRET_KEY = "local-dev-only"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = []

MIDDLEWARE = []

ROOT_URLCONF = "dashboard.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db" / "jobs.sqlite",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
