"""Create the first administrator account.

Interactive:   python manage.py create_initial_admin
Non-interactive (values from the environment, for scripted setup):
               TCOS_ADMIN_USERNAME, TCOS_ADMIN_EMAIL, TCOS_ADMIN_FULL_NAME,
               TCOS_ADMIN_PASSWORD

There are no default credentials. The password is never printed. The command
refuses to run when users already exist unless --force is given.
"""

import getpass
import os
import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.services import create_user


class Command(BaseCommand):
    help = "Create the first administrator account (no default credentials)."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--email")
        parser.add_argument("--full-name", dest="full_name")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create another administrator even though users already exist.",
        )

    def handle(self, *args, **options):
        if User.objects.exists() and not options["force"]:
            raise CommandError(
                "Users already exist. Manage accounts in the application, "
                "or pass --force to create an additional administrator."
            )

        username = self._value(options["username"], "TCOS_ADMIN_USERNAME", "Username: ")
        email = self._value(options["email"], "TCOS_ADMIN_EMAIL", "Email address: ")
        full_name = self._value(options["full_name"], "TCOS_ADMIN_FULL_NAME", "Full name: ")
        password = self._password()

        try:
            user = create_user(
                username=username,
                email=email,
                full_name=full_name,
                password=password,
                is_superuser=True,
            )
        except ValidationError as exc:
            raise CommandError("Could not create the account: " + " ".join(exc.messages)) from exc

        self.stdout.write(self.style.SUCCESS(f"Administrator '{user.username}' created."))

    @staticmethod
    def _value(option, env_name, prompt):
        value = option or os.environ.get(env_name)
        if value:
            return value
        if not sys.stdin.isatty():
            raise CommandError(f"Provide the value via {env_name} or the matching option.")
        return input(prompt).strip()

    @staticmethod
    def _password():
        password = os.environ.get("TCOS_ADMIN_PASSWORD")
        if password:
            return password
        if not sys.stdin.isatty():
            raise CommandError("Provide the password via TCOS_ADMIN_PASSWORD or run interactively.")
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Password (again): ")
        if first != second:
            raise CommandError("The passwords did not match.")
        return first
