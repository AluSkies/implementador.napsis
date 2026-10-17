"""Crea el superusuario inicial del panel a partir de variables de entorno.

Pensado para entornos sin shell interactivo (ej. un contenedor) donde
`manage.py createsuperuser` no se puede correr a mano. Es seguro correrlo en
cada deploy: si el usuario ya existe, no lo toca (no pisa una contraseña que
ya se haya cambiado desde el admin).

Si no están seteadas las variables, no hace nada — en local/Ubuntu con shell
disponible se sigue usando `manage.py createsuperuser` normalmente.
"""

import os

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea el superusuario inicial (DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL) si no existe."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

        if not username or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME/DJANGO_SUPERUSER_PASSWORD no configurados; se omite."
            )
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"El superusuario '{username}' ya existe; no se toca.")
            return

        # create_superuser no valida la contraseña: sin esto se podía arrancar con una de
        # ejemplo ("cambiar") en un admin expuesto a internet. Falla fuerte, a propósito.
        try:
            validate_password(password, User(username=username, email=email))
        except ValidationError as error:
            raise CommandError(
                "DJANGO_SUPERUSER_PASSWORD no es una contraseña aceptable: " + " ".join(error.messages)
            )

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superusuario '{username}' creado."))
