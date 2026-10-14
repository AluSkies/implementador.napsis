from django import forms
from django.core.validators import FileExtensionValidator
from django.forms import BaseFormSet, formset_factory

from clients.models import Implementacion, PersonaRol, Sucursal
from clients.validators import normalizar_cuits

# Campos de Implementacion que completa el cliente en distintos pasos del wizard.
# Única fuente de verdad: ImplementacionDatosForm (edición completa desde el panel)
# es la unión de los dos, en vez de repetir la lista a mano por tercera vez.
CAMPOS_DATOS_CONTACTO = ["telefono", "mail_contacto"]
CAMPOS_CONFIGURACION = [
    "tipo_firma",
    "liquidador_utilizado",
    "nomenclatura_pdf",
    "cantidad_capitas",
    "segmentacion_liquidador",
    "banner",
    "modelo_recibo",
]


class CamposEmpresaMixin:
    """Suma razón social y CUIT(s) a un form de Implementacion. Esos datos viven en
    Cliente (son de la empresa, no de una ronda puntual), pero se piden junto con los
    de contacto: el implementador puede cargarlos al crear la implementación y, si no
    lo hizo, el cliente los completa en el paso 1."""

    empresa_requerida = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cliente = getattr(self.instance, "cliente", None)
        self.fields["razon_social"] = forms.CharField(
            label="Razón social", max_length=255, required=self.empresa_requerida,
            initial=cliente.razon_social if cliente else "",
            help_text="Con la razón social identifica Napsis a la empresa.",
        )
        self.fields["cuits"] = forms.CharField(
            label="CUIT(s)", max_length=255, required=self.empresa_requerida,
            initial=cliente.cuits if cliente else "",
            help_text="Uno o varios, separados por coma (ej: 30-12345678-9, 30-98765432-1).",
        )
        self.order_fields(["razon_social", "cuits"])

    def clean_cuits(self):
        valor = self.cleaned_data.get("cuits", "")
        return normalizar_cuits(valor) if valor else ""

    def save(self, commit=True):
        implementacion = super().save(commit)
        cliente = implementacion.cliente
        cliente.razon_social = self.cleaned_data["razon_social"]
        cliente.cuits = self.cleaned_data["cuits"]
        cliente.save(update_fields=["razon_social", "cuits", "actualizado"])
        return implementacion


class EmpresaForm(CamposEmpresaMixin, forms.ModelForm):
    """Paso 1 del cliente: datos de la empresa y de contacto. Razón social y CUIT son
    obligatorios (pueden venir ya cargados por el implementador)."""

    empresa_requerida = True

    class Meta:
        model = Implementacion
        fields = CAMPOS_DATOS_CONTACTO


class ImplementacionDatosForm(CamposEmpresaMixin, forms.ModelForm):
    """Edición completa de los datos de contacto/configuración, para uso del
    equipo de implementación desde el panel (no del cliente vía el wizard)."""

    class Meta:
        model = Implementacion
        fields = CAMPOS_DATOS_CONTACTO + CAMPOS_CONFIGURACION


class ModulosForm(forms.Form):
    def __init__(self, *args, modulos_qs=None, activos_ids=None, disabled=False, **kwargs):
        super().__init__(*args, **kwargs)
        activos_ids = activos_ids or set()
        for modulo in modulos_qs:
            self.fields[f"modulo_{modulo.id}"] = forms.BooleanField(
                label=modulo.nombre, required=False, initial=modulo.id in activos_ids,
                disabled=disabled,
            )


class RolForm(forms.Form):
    rol = forms.ChoiceField(choices=PersonaRol.ROL_CHOICES)
    apellido_nombre = forms.CharField(max_length=255, required=False, label="Apellido y Nombre")
    cuil = forms.CharField(max_length=20, required=False, label="CUIL")
    mail = forms.EmailField(required=False, label="Mail")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("apellido_nombre") and not cleaned.get("rol"):
            raise forms.ValidationError("Elegí un rol para la persona cargada.")
        return cleaned


RolFormSet = formset_factory(RolForm, extra=6, can_delete=True)


class _RolesObligatoriosFormSet(BaseFormSet):
    """Variante para el wizard del cliente: no se puede avanzar sin al menos un
    Apoderado/Firmante, un Liquidador y un Admin. de RRHH (los tres son elementales).
    El panel interno usa RolFormSet, sin esta exigencia."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        presentes = {
            f.cleaned_data["rol"] for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("apellido_nombre")
        }
        faltan = [nombre for rol, nombre in PersonaRol.ROL_CHOICES if rol not in presentes]
        if faltan:
            raise forms.ValidationError(
                "Falta cargar al menos una persona para cada rol. Te falta: " + ", ".join(faltan) + "."
            )


RolFormSetObligatorio = formset_factory(
    RolForm, formset=_RolesObligatoriosFormSet, extra=6, can_delete=True
)


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Implementacion
        fields = CAMPOS_CONFIGURACION
        # Sin el checkbox de "borrar": el modelo de recibo es obligatorio, solo se reemplaza.
        widgets = {"modelo_recibo": forms.FileInput}
        help_texts = {
            "tipo_firma": "Digital requiere token físico ENCODE. Electrónica requiere adjuntar imagen de firma hológrafa.",
            "segmentacion_liquidador": "Por defecto 'AREA UNICA' si el liquidador ve todos los recibos sin segmentar.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["modelo_recibo"]
        campo.validators.append(FileExtensionValidator(["pdf"]))
        if not self.instance.modelo_recibo:
            campo.required = True
            campo.label = "Modelo de recibo (PDF, obligatorio)"


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "nombre", "calle", "altura", "piso_depto", "codigo_postal",
            "localidad", "entre_calles", "observaciones",
        ]


SucursalFormSet = formset_factory(SucursalForm, extra=5, can_delete=True)


class LicenciasNovedadesForm(forms.Form):
    """El cliente solo elige qué licencias/novedades activar. La fecha de puesta en
    vigencia la define después el equipo de implementación, no el cliente."""

    def __init__(self, *args, licencias_qs=None, novedades_qs=None, estado_por_licencia=None, estado_por_novedad=None, **kwargs):
        super().__init__(*args, **kwargs)
        estado_por_licencia = estado_por_licencia or {}
        estado_por_novedad = estado_por_novedad or {}

        for licencia in licencias_qs:
            estado = estado_por_licencia.get(licencia.id, {})
            self.fields[f"licencia_{licencia.id}_activo"] = forms.BooleanField(
                label=licencia.nombre, required=False, initial=estado.get("activo", False)
            )

        for novedad in novedades_qs:
            estado = estado_por_novedad.get(novedad.id, {})
            self.fields[f"novedad_{novedad.id}_activo"] = forms.BooleanField(
                label=novedad.nombre, required=False, initial=estado.get("activo", False)
            )


class DocumentosLegajoForm(forms.Form):
    otros_documentos = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label='Otros documentos a configurar',
        help_text=(
            "Uno por línea, con el formato: Nombre del documento: campo 1, campo 2, campo 3. "
            "Ej: Certificado de matrimonio: Fecha de emisión, Adjunto"
        ),
    )

    def __init__(self, *args, tipos_qs=None, estado_por_tipo=None, **kwargs):
        super().__init__(*args, **kwargs)
        estado_por_tipo = estado_por_tipo or {}
        for tipo in tipos_qs:
            estado = estado_por_tipo.get(tipo.id, {})
            self.fields[f"tipo_{tipo.id}_activo"] = forms.BooleanField(
                label=tipo.nombre, required=False, initial=estado.get("activo", False)
            )

    def parse_otros_documentos(self):
        """Devuelve [(nombre, [campo1, campo2, ...]), ...] a partir del textarea libre."""
        resultado = []
        texto = self.cleaned_data.get("otros_documentos", "")
        for linea in texto.splitlines():
            linea = linea.strip()
            if not linea or ":" not in linea:
                continue
            nombre, campos_texto = linea.split(":", 1)
            campos = [c.strip() for c in campos_texto.split(",") if c.strip()]
            if nombre.strip() and campos:
                resultado.append((nombre.strip(), campos))
        return resultado


class PedirRevisionForm(forms.Form):
    mensaje = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="¿Algo puntual que quieras contarnos?",
    )
