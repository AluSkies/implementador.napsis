from django import forms
from django.contrib.auth.models import User

from automatizacion.actores import es_supervisor

from . import services as cuentas


class ImplementadorEdicionForm(forms.ModelForm):
    """Datos editables de un implementador. El usuario no se cambia: el historial de
    versiones guarda ese nombre como texto para atribuir cada edición."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nombre", "last_name": "Apellido", "email": "Mail"}

    rol = forms.ChoiceField(
        label="Rol", choices=cuentas.ROLES,
        help_text="El supervisor asigna las implementaciones a los demás y puede actuar sobre todas; "
                  "el implementador ve todas pero solo actúa sobre las que tiene asignadas.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.required = True
        if self.instance.pk:
            self.fields["rol"].initial = cuentas.ROL_SUPERVISOR if es_supervisor(self.instance) else cuentas.ROL_IMPLEMENTADOR

    def save(self, commit=True):
        usuario = super().save(commit)
        if commit:
            cuentas.asignar_rol(usuario, self.cleaned_data["rol"])
        return usuario


class ImplementadorAltaForm(ImplementadorEdicionForm):
    class Meta(ImplementadorEdicionForm.Meta):
        fields = ["username", "first_name", "last_name", "email"]
        labels = {**ImplementadorEdicionForm.Meta.labels, "username": "Usuario"}

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese usuario.")
        return username
