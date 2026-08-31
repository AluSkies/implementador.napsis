from django import forms

from clients.validators import validar_tamanio_archivo

from .models import Empleado


class EmpleadoForm(forms.ModelForm):
    class Meta:
        model = Empleado
        exclude = ("implementacion", "import_batch", "creado", "actualizado")
        widgets = {
            "fecha_ingreso": forms.DateInput(attrs={"type": "date"}),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, implementacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Los combos de sucursal/jerarquía deben acotarse a la implementación
        # actual: por default Django arma el queryset con TODOS los registros
        # del modelo, lo que filtraría empleados/sucursales de otros clientes.
        if implementacion is not None:
            self.fields["sucursal"].queryset = implementacion.sucursales.all()
            empleados_qs = implementacion.empleados.all()
            if self.instance and self.instance.pk:
                empleados_qs = empleados_qs.exclude(pk=self.instance.pk)
            self.fields["reporta_a"].queryset = empleados_qs
            self.fields["aprobador"].queryset = empleados_qs


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
