from django import forms

from clients.validators import validar_tamanio_archivo

from clients.models import Modulo

from .models import Empleado
from .services import CUIL_RE, formatear_cuil, normalizar_cuil, normalizar_texto


class CuilInput(forms.TextInput):
    """Muestra el CUIL con guiones aunque se guarde con los 11 dígitos."""

    def format_value(self, value):
        return formatear_cuil(value) or None


class CuilField(forms.CharField):
    """CUIL que se acepta con o sin guiones. Para saber si cambió compara los dígitos: escribirlo con
    otro formato no es un cambio (no tiene que dejar un evento ni quitarle la validación a nadie)."""

    widget = CuilInput

    def has_changed(self, initial, data):
        return normalizar_cuil(initial) != normalizar_cuil(data)


class EmpleadoForm(forms.ModelForm):
    cuil = CuilField(label="CUIL", max_length=20, help_text="Con o sin guiones: 20-11111111-2 o 20111111112.")

    class Meta:
        model = Empleado
        exclude = ("implementacion", "import_batch", "creado", "actualizado")
        widgets = {
            "fecha_ingreso": forms.DateInput(attrs={"type": "date"}),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, implementacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.implementacion = implementacion
        # Los combos de sucursal/jerarquía deben acotarse a la implementación
        # actual: por default Django arma el queryset con TODOS los registros
        # del modelo, lo que filtraría empleados/sucursales de otros clientes.
        if implementacion is not None:
            # El wizard de Recibo Digital necesita la fecha de ingreso de todos los empleados.
            if implementacion.usa_modulo(Modulo.RECIBO_DIGITAL):
                self.fields["fecha_ingreso"].required = True
            self.fields["sucursal"].queryset = implementacion.sucursales.all()
            empleados_qs = implementacion.empleados.all()
            if self.instance and self.instance.pk:
                empleados_qs = empleados_qs.exclude(pk=self.instance.pk)
            self.fields["reporta_a"].queryset = empleados_qs
            self.fields["aprobador"].queryset = empleados_qs


    # Mismas reglas que la importación masiva: si no, el mismo empleado cargado a mano y por
    # archivo quedaba duplicado (uno con guiones en el CUIL y el otro sin) y un CUIL repetido
    # daba un error 500 en vez de un aviso.
    def clean_cuil(self):
        cuil = normalizar_cuil(self.cleaned_data["cuil"])
        if not CUIL_RE.match(cuil):
            raise forms.ValidationError("El CUIL tiene que tener 11 dígitos.")
        if self.implementacion is not None:
            repetidos = self.implementacion.empleados.filter(cuil=cuil)
            if self.instance and self.instance.pk:
                repetidos = repetidos.exclude(pk=self.instance.pk)
            if repetidos.exists():
                raise forms.ValidationError("Ya hay un empleado cargado con ese CUIL.")
        return cuil

    def clean_nombre(self):
        return normalizar_texto(self.cleaned_data["nombre"])

    def clean_apellido(self):
        return normalizar_texto(self.cleaned_data["apellido"])


class ImportarArchivoForm(forms.Form):
    archivo = forms.FileField(
        label="Archivo de empleados (.xlsx o .csv)",
        help_text="Usá la plantilla descargable para asegurarte de que las columnas coincidan.",
        validators=[validar_tamanio_archivo],
    )

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError("El archivo debe ser .xlsx o .csv")
        return archivo
