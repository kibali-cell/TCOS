"""WSGI entry point. Defaults to production settings so a misconfigured
deployment can never silently run with development settings."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
