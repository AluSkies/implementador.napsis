from django import forms
from django.core.validators import FileExtensionValidator
from django.forms import BaseFormSet, formset_factory

from catalog.models import TipoLiquidacion
from clients.models import Implementacion, PersonaRol, Sucursal, UbicacionFirma, geometria_inicial_de_firma
from clients.validators import normalizar_cuits, validar_medidas_banner, validar_medidas_logo, validar_tamanio_archivo
from employees.services import CUIL_RE, normalizar_cuil

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
    "logo",
    "modelo_recibo",
]

AYUDA_BANNER = "Opcional. Tiene que medir entre 1500 × 200 y 1600 × 400 px: si no, Napsis lo rechaza."
AYUDA_LOGO = "Opcional. Puede medir hasta 200 × 200 px: si no, Napsis lo rechaza."


class ImagenesConMedidasMixin:
    """El banner y el logo se validan contra las medidas que acepta el wizard de Napsis, y se
    avisa cuáles son antes de subirlos (nunca se acepta en silencio algo que el destino rechaza)."""

    def _validar_medidas_de_las_imagenes(self):
        for nombre, validador, ayuda in (
            ("banner", validar_medidas_banner, AYUDA_BANNER), ("logo", validar_medidas_logo, AYUDA_LOGO),
        ):
            if nombre in self.fields:
                self.fields[nombre].validators.append(validador)
                self.fields[nombre].help_text = ayuda


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


class ImplementacionDatosForm(ImagenesConMedidasMixin, CamposEmpresaMixin, forms.ModelForm):
    """Edición completa de los datos de contacto/configuración, para uso del
    equipo de implementación desde el panel (no del cliente vía el wizard)."""

    class Meta:
        model = Implementacion
        fields = CAMPOS_DATOS_CONTACTO + CAMPOS_CONFIGURACION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validar_medidas_de_las_imagenes()


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

    def clean_cuil(self):
        cuil = normalizar_cuil(self.cleaned_data.get("cuil", ""))
        if cuil and not CUIL_RE.match(cuil):
            raise forms.ValidationError("El CUIL tiene que tener 11 dígitos.")
        return cuil

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("apellido_nombre") and not cleaned.get("rol"):
            raise forms.ValidationError("Elegí un rol para la persona cargada.")
        return cleaned


RolFormSet = formset_factory(RolForm, extra=6, can_delete=True)


class _RolesObligatoriosFormSet(BaseFormSet):
    """Variante para el wizard del cliente: no se puede avanzar sin al menos un
    Apoderado/Firmante, un Liquidador y un Admin. de RRHH (los tres son elementales).
    Además, el Apoderado/Firmante y el Liquidador tienen que ser empleados de la nómina (Napsis los
    elige de esa lista): se verifica por CUIL contra `cuils_nomina`, si se la pasa. El panel interno
    usa RolFormSet, sin esta exigencia."""

    cuils_nomina = None  # conjunto de CUIL de la nómina cargada; None = no se verifica

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if self.cuils_nomina is not None:
            self._verificar_en_la_nomina()
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

    def _verificar_en_la_nomina(self):
        for form in self.forms:
            datos = form.cleaned_data
            if not datos or datos.get("DELETE") or not datos.get("apellido_nombre"):
                continue
            if datos.get("rol") not in PersonaRol.ROLES_EN_NOMINA:
                continue
            if not datos.get("cuil"):
                form.add_error("cuil", "Este rol sale de la nómina: elegí a la persona de la lista o escribí su CUIL.")
            elif datos["cuil"] not in self.cuils_nomina:
                form.add_error(
                    "cuil",
                    "Este CUIL no está en la nómina. Cargá primero a la persona como empleado (paso de empleados)."
                    if self.cuils_nomina else
                    "Todavía no cargaste la nómina: hacelo primero (paso de empleados) y volvé a elegir a la persona.",
                )


def rol_formset_obligatorio(max_roles, cuils_nomina=None):
    """El formset de roles del wizard, con tantas filas como personas puede cargar el
    cliente en esta implementación (max_roles) y rechazando que se manden más.
    Con `cuils_nomina`, el Apoderado/Firmante y el Liquidador tienen que figurar en esa nómina."""
    formset = formset_factory(
        RolForm, formset=_RolesObligatoriosFormSet, extra=max_roles, max_num=max_roles,
        validate_max=True, can_delete=True,
    )
    formset.cuils_nomina = None if cuils_nomina is None else set(cuils_nomina)
    return formset


class LiquidacionesForm(forms.Form):
    """Qué tipos de liquidación usa la empresa (al menos uno)."""

    tipos_liquidacion = forms.ModelMultipleChoiceField(
        label="Tipos de liquidación que usa la empresa", queryset=TipoLiquidacion.objects.all(),
        widget=forms.CheckboxSelectMultiple, required=False,
        help_text="Elegí todos los que usan. Por cada uno hay que configurar después la firma del recibo.",
    )

    def __init__(self, *args, implementacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        if implementacion is not None:
            self.fields["tipos_liquidacion"].initial = list(
                implementacion.liquidaciones.filter(activo=True).values_list("tipo_liquidacion_id", flat=True)
            )

    def clean_tipos_liquidacion(self):
        tipos = self.cleaned_data["tipos_liquidacion"]
        if not tipos:
            raise forms.ValidationError("Elegí al menos un tipo de liquidación.")
        return tipos


class ConfiguracionForm(ImagenesConMedidasMixin, LiquidacionesForm, forms.ModelForm):
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
        super().__init__(*args, implementacion=kwargs.get("instance"), **kwargs)
        self.order_fields(["tipos_liquidacion"] + CAMPOS_CONFIGURACION)
        self._validar_medidas_de_las_imagenes()
        # Lo que el implementador dejó fijo se muestra pero no se puede cambiar. Con
        # disabled=True Django ignora lo que llegue por POST y conserva el valor guardado,
        # así que tampoco se puede evadir editando el formulario a mano.
        bloqueados = (
            ("tipo_firma", self.instance.tipo_firma_editable),
            ("nomenclatura_pdf", self.instance.nomenclatura_editable),
            ("segmentacion_liquidador", self.instance.segmentacion_editable),
        )
        for nombre, editable in bloqueados:
            if not editable:
                self.fields[nombre].disabled = True
                self.fields[nombre].help_text = "Lo definió Napsis para tu implementación: no se puede cambiar."
        campo = self.fields["modelo_recibo"]
        campo.validators.append(FileExtensionValidator(["pdf"]))
        if not self.instance.modelo_recibo:
            campo.required = True
            campo.label = "Modelo de recibo (PDF, obligatorio)"


# La firma tiene que verse bien sobre el recibo: por debajo de esto queda borrosa.
FIRMA_RESOLUCION_MINIMA = (200, 60)
FIRMA_FORMATOS = ("JPEG", "PNG")
CAMPOS_DE_RECUADRO = ("x", "y", "ancho", "alto")
NOMBRES_DE_RECUADRO = {"x": "izquierda", "y": "arriba", "ancho": "ancho", "alto": "alto"}


class FirmaForm(forms.Form):
    """Imagen de la firma y dónde va sobre el recibo. Los recuadros llegan en % de la página (0 a 100)
    —así los edita una persona—; se guardan como fracciones (0 a 1) para que no dependan del tamaño del PDF."""

    imagen = forms.FileField(
        required=False, label="Imagen de la firma del apoderado", validators=[validar_tamanio_archivo],
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg"}),
        help_text="JPG o PNG. Lo ideal es la firma sobre fondo blanco liso, o un PNG con fondo transparente.",
    )
    pagina = forms.ChoiceField(choices=UbicacionFirma.PAGINA_CHOICES, label="¿En qué página va la firma?")

    def __init__(self, *args, firma=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.firma = firma
        geometria = firma.geometria if firma else geometria_inicial_de_firma()
        for codigo, nombre in UbicacionFirma.ELEMENTOS:
            for campo in CAMPOS_DE_RECUADRO:
                self.fields[f"{codigo}_{campo}"] = forms.FloatField(
                    min_value=0, max_value=100, label=f"{nombre}: {NOMBRES_DE_RECUADRO[campo]}",
                    initial=round(geometria[codigo][campo] * 100, 1),
                    widget=forms.NumberInput(attrs={"step": "0.1", "min": "0", "max": "100"}),
                )
        self.fields["pagina"].initial = firma.pagina if firma else UbicacionFirma.PAGINA_PRIMERA

    @property
    def filas_de_recuadros(self):
        """Para dibujar los campos numéricos de respaldo: [(nombre, [campo x, y, ancho, alto])]."""
        return [
            (nombre, [self[f"{codigo}_{campo}"] for campo in CAMPOS_DE_RECUADRO])
            for codigo, nombre in UbicacionFirma.ELEMENTOS
        ]

    def clean_imagen(self):
        imagen = self.cleaned_data.get("imagen")
        if not imagen:
            return None
        try:
            from PIL import Image

            with Image.open(imagen) as foto:
                formato, (ancho, alto) = foto.format, foto.size
                foto.verify()
        except Exception:
            raise forms.ValidationError("No pudimos leer la imagen. Subí un archivo JPG o PNG.") from None
        finally:
            imagen.seek(0)
        if formato not in FIRMA_FORMATOS:
            raise forms.ValidationError("La imagen tiene que ser JPG o PNG.")
        minimo = FIRMA_RESOLUCION_MINIMA
        if ancho < minimo[0] or alto < minimo[1]:
            raise forms.ValidationError(
                f"La imagen es muy chica ({ancho} × {alto} px): tiene que medir al menos {minimo[0]} × {minimo[1]} px "
                "para que la firma no se vea borrosa."
            )
        return imagen

    def clean(self):
        datos = super().clean()
        if not datos.get("imagen") and not (self.firma and self.firma.imagen):
            self.add_error("imagen", "Subí la imagen de la firma.")
        for codigo, nombre in UbicacionFirma.ELEMENTOS:
            recuadro = {campo: datos.get(f"{codigo}_{campo}") for campo in CAMPOS_DE_RECUADRO}
            if None in recuadro.values():
                continue  # ya tiene su error de campo
            if recuadro["ancho"] < 1 or recuadro["alto"] < 1:
                self.add_error(None, f"{nombre}: el recuadro tiene que medir al menos 1% de la página de ancho y de alto.")
            elif recuadro["x"] + recuadro["ancho"] > 100.05 or recuadro["y"] + recuadro["alto"] > 100.05:
                self.add_error(None, f"{nombre}: el recuadro se sale de la página.")
        return datos

    def geometria(self):
        """Los recuadros como los guarda el modelo: fracciones de 0 a 1."""
        return {
            codigo: {campo: round(self.cleaned_data[f"{codigo}_{campo}"] / 100, 4) for campo in CAMPOS_DE_RECUADRO}
            for codigo, _ in UbicacionFirma.ELEMENTOS
        }


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
    vigencia la define después el equipo de implementación, no el cliente. Las licencias que
    Napsis crea solas (Vacaciones) se muestran tildadas y no se pueden cambiar."""

    def __init__(self, *args, licencias_qs=None, novedades_qs=None, estado_por_licencia=None, estado_por_novedad=None, **kwargs):
        super().__init__(*args, **kwargs)
        estado_por_licencia = estado_por_licencia or {}
        estado_por_novedad = estado_por_novedad or {}

        for licencia in licencias_qs:
            estado = estado_por_licencia.get(licencia.id, {})
            self.fields[f"licencia_{licencia.id}_activo"] = forms.BooleanField(
                label=licencia.nombre, required=False, initial=licencia.automatica or estado.get("activo", False),
                disabled=licencia.automatica,
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


class CondicionesForm(forms.Form):
    """Qué deja fijo el equipo y qué decide el cliente en su proceso. Cada dato se bloquea al
    completarlo: si el implementador elige la firma, queda fija; si la deja sin elegir, la
    decide el cliente. Lo usan el alta de la implementación y la ficha del panel."""

    tipo_firma = forms.ChoiceField(
        label="Tipo de firma", required=False,
        choices=[("", "Que lo elija el cliente")] + list(Implementacion.TIPO_FIRMA_CHOICES),
        help_text="Si elegís una, el cliente no puede cambiarla.",
    )
    nomenclatura_pdf = forms.CharField(
        label="Nomenclatura de los recibos PDF", max_length=255, required=False,
        help_text="Cómo tienen que emitirlos (ej: recibo_{legajo}_{periodo}.pdf). Si la completás, el "
                  "cliente no puede cambiarla; si la dejás vacía, la define él.",
    )
    area_unica = forms.BooleanField(
        label="El liquidador ve todos los recibos (sin segmentar)", required=False,
        help_text="Si lo tildás, el liquidador no se limita a una sucursal o sector, y el cliente no puede "
                  "cambiarlo en el wizard. Si no, el cliente indica cómo segmentarlo.",
    )
    max_roles = forms.IntegerField(
        label="Máximo de personas con rol", min_value=3, max_value=6, required=False, initial=6,
        help_text="Cuántas personas puede cargar el cliente en el paso de roles. Mínimo 3: tiene que "
                  "cargar al menos un Apoderado/Firmante, un Liquidador y un Admin. de RRHH.",
    )

    def __init__(self, *args, implementacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        if implementacion is not None:
            self.initial.update({
                "tipo_firma": "" if implementacion.tipo_firma_editable else implementacion.tipo_firma,
                "nomenclatura_pdf": "" if implementacion.nomenclatura_editable else implementacion.nomenclatura_pdf,
                "area_unica": not implementacion.segmentacion_editable,
                "max_roles": implementacion.max_roles,
            })

    def clean_max_roles(self):
        return self.cleaned_data.get("max_roles") or 6

    def aplicar(self, implementacion):
        """Vuelca las condiciones en la implementación (sin guardarla)."""
        datos = self.cleaned_data
        implementacion.max_roles = datos["max_roles"]

        implementacion.tipo_firma_editable = not datos["tipo_firma"]
        if datos["tipo_firma"]:
            implementacion.tipo_firma = datos["tipo_firma"]

        nomenclatura = datos["nomenclatura_pdf"].strip()
        implementacion.nomenclatura_editable = not nomenclatura
        if nomenclatura:
            implementacion.nomenclatura_pdf = nomenclatura

        implementacion.segmentacion_editable = not datos["area_unica"]
        if datos["area_unica"]:
            implementacion.segmentacion_liquidador = "AREA UNICA"


class FechaImplementacionForm(forms.Form):
    """La fecha en la que el cliente quiere salir en productivo. Es opcional (si no la pide,
    la define el equipo) pero, si la pide, tiene que respetar el mínimo de días hábiles.
    Si el equipo ya había puesto una fecha anterior al mínimo, esa se acepta tal cual."""

    fecha_salida_productivo = forms.DateField(
        label="Fecha en la que querés salir en productivo", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, implementacion, minima, **kwargs):
        super().__init__(*args, **kwargs)
        self.implementacion = implementacion
        self.minima = minima
        campo = self.fields["fecha_salida_productivo"]
        campo.initial = implementacion.fecha_salida_productivo
        campo.widget.attrs["min"] = minima.isoformat()
        campo.help_text = f"Opcional. A partir del {minima:%d/%m/%Y} (10 días hábiles, de lunes a viernes)."

    def clean_fecha_salida_productivo(self):
        fecha = self.cleaned_data.get("fecha_salida_productivo")
        if fecha and fecha < self.minima and fecha != self.implementacion.fecha_salida_productivo:
            raise forms.ValidationError(
                f"La fecha tiene que ser a partir del {self.minima:%d/%m/%Y} (10 días hábiles desde hoy)."
            )
        return fecha


class PedirRevisionForm(forms.Form):
    mensaje = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="¿Algo puntual que quieras contarnos?",
    )
