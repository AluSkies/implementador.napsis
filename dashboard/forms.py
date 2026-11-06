from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from . import services as cuentas
from .models import GrupoDeTrabajo

AYUDA_DE_ROLES = (
    "Implementador: ve y actúa solo sobre las implementaciones que tiene asignadas. "
    "Supervisor: además ve las de los integrantes de sus grupos y las reparte entre ellos. "
    "Admin: ve todo y administra las cuentas y los grupos."
)


class ImplementadorEdicionForm(forms.ModelForm):
    """Datos editables de una cuenta del equipo. El usuario no se cambia: el historial de
    versiones guarda ese nombre como texto para atribuir cada edición."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nombre", "last_name": "Apellido", "email": "Mail"}

    rol = forms.ChoiceField(label="Rol", choices=cuentas.ROLES, help_text=AYUDA_DE_ROLES)

    def __init__(self, *args, quien=None, **kwargs):
        """`quien`: la cuenta que hace el cambio (el Admin). Nadie puede cambiarse su propio rol."""
        super().__init__(*args, **kwargs)
        self.quien = quien
        for campo in self.fields.values():
            campo.required = True
        if self.instance.pk:
            self.fields["rol"].initial = cuentas.rol_de(self.instance)
            if quien is not None and self.instance.pk == quien.pk:
                self.fields["rol"].disabled = True
                self.fields["rol"].help_text = "No podés cambiar tu propio rol: pedile a otro admin que lo haga."

    def clean_rol(self):
        rol = self.cleaned_data["rol"]
        if self.instance.pk:
            error = cuentas.error_de_cambio_de_rol(self.instance, rol, self.quien)
            if error:
                raise forms.ValidationError(error)
        return rol

    def save(self, commit=True):
        usuario = super().save(commit)
        self.sale_del_grupo = None  # el grupo del que salió, si el cambio de rol lo sacó de uno
        if commit:
            self.sale_del_grupo = cuentas.asignar_rol(usuario, self.cleaned_data["rol"], por=self.quien)
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


def _nombre(usuario):
    return usuario.get_full_name() or usuario.get_username()


class _SupervisorField(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return _nombre(usuario) + ("" if usuario.is_active else " · de baja")


class GrupoForm(forms.Form):
    """Alta y edición de un grupo de trabajo: nombre, supervisor a cargo e integrantes."""

    nombre = forms.CharField(label="Nombre del grupo", max_length=80)
    supervisor = _SupervisorField(
        label="Supervisor a cargo", queryset=User.objects.none(), empty_label="Elegir supervisor",
        help_text="Ve las implementaciones de los integrantes. Solo cuentas con rol Supervisor.",
    )
    # La pantalla no usa el widget para dibujarlo (es una tabla con buscador: ver `filas_de_integrantes` y
    # `_integrantes.html`), pero sí para leer lo que llega: las casillas se llaman `integrantes`.
    integrantes = forms.ModelMultipleChoiceField(
        label="Integrantes", queryset=User.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Un implementador integra un solo grupo: tildar a uno de otro grupo lo mueve.",
    )

    def __init__(self, *args, grupo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.grupo = grupo
        supervisores = cuentas.supervisores_posibles()
        if grupo is not None:  # el supervisor actual sigue valiendo aunque esté dado de baja
            supervisores = User.objects.filter(Q(pk__in=supervisores.values("pk")) | Q(pk=grupo.supervisor_id))
            self.initial = {
                "nombre": grupo.nombre, "supervisor": grupo.supervisor_id,
                "integrantes": list(grupo.membresias.values_list("usuario_id", flat=True)),
            }
        self.fields["supervisor"].queryset = supervisores.order_by("first_name", "username")
        self.fields["integrantes"].queryset = cuentas.integrantes_posibles()

    def filas_de_integrantes(self):
        """Los implementadores que se pueden sumar, para dibujar la tabla: nombre, grupo en el que están hoy, si están de
        baja y si están tildados (lo que llegó en el formulario, o los del grupo si todavía no se envió). Primero los
        tildados, después los activos, por nombre."""
        valor = self["integrantes"].value() or []
        tildados = {str(pk) for pk in valor}
        filas = []
        for cuenta in self.fields["integrantes"].queryset:
            membresia = getattr(cuenta, "membresia", None)
            filas.append({
                "pk": cuenta.pk, "nombre": _nombre(cuenta), "usuario": cuenta.get_username(),
                "grupo": membresia.grupo.nombre if membresia is not None else "",
                "de_baja": not cuenta.is_active, "marcado": str(cuenta.pk) in tildados,
            })
        return sorted(filas, key=lambda f: (not f["marcado"], f["de_baja"], f["nombre"].lower()))

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetidos = GrupoDeTrabajo.objects.filter(nombre__iexact=nombre)
        if self.grupo is not None:
            repetidos = repetidos.exclude(pk=self.grupo.pk)
        if repetidos.exists():
            raise forms.ValidationError("Ya hay un grupo con ese nombre.")
        return nombre
