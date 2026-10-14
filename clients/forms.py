from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm


class RecuperarClaveForm(PasswordResetForm):
    """Como el de Django, pero también alcanza a las cuentas todavía sin contraseña (clientes
    invitados que no llegaron a crearla): si no, no podrían pedir un link nuevo."""

    def get_users(self, email):
        usuarios = get_user_model()._default_manager.filter(email__iexact=email, is_active=True)
        return (u for u in usuarios if u.email.lower() == email.lower())
