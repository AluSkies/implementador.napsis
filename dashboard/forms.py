from django import forms
from django.contrib.auth.models import User


class ImplementadorEdicionForm(forms.ModelForm):
    """Datos editables de un implementador. El usuario no se cambia: el historial de
    versiones guarda ese nombre como texto para atribuir cada edición."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nombre", "last_name": "Apellido", "email": "Mail"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.required = True


class ImplementadorAltaForm(ImplementadorEdicionForm):
    class Meta(ImplementadorEdicionForm.Meta):
        fields = ["username", "first_name", "last_name", "email"]
        labels = {**ImplementadorEdicionForm.Meta.labels, "username": "Usuario"}

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese usuario.")
        return username
