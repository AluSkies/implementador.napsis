import secrets
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from catalog.codigos import ConCodigo

from .validators import validar_tamanio_archivo


def generate_token():
    return secrets.token_urlsafe(32)


class Cliente(models.Model):
    """Empresa cliente de Napsis.

    Es la entidad persistente: una misma empresa puede tener varias
    Implementaciones a lo largo del tiempo (la inicial, y más adelante otras
    al sumar un módulo o volver a relevar algo).
    """

    nombre = models.CharField(
        "Nombre de la empresa", max_length=255,
        help_text="Cómo se muestra en el portal (puede ser el nombre de fantasía). La razón social va aparte.",
    )
    razon_social = models.CharField(
        "Razón social", max_length=255, blank=True,
        help_text="Con esto identifica Napsis a la empresa. Si queda vacío, el cliente la completa en el paso 1.",
    )
    cuits = models.CharField(
        "CUIT(s)", max_length=255, blank=True,
        help_text="Uno o varios CUIT, separados por coma (ej: 30-12345678-9, 30-98765432-1).",
    )
    usuario = models.OneToOneField(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="cliente",
        help_text="Cuenta con la que este cliente inicia sesión para completar su implementación.",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Modulo(ConCodigo):
    """Catálogo de módulos contratables (Recibo Digital, Autogestión, etc.).

    Los pasos del wizard dependen del **código** del módulo (no del nombre, que se puede corregir en el
    admin sin romper nada)."""

    RECIBO_DIGITAL = "recibo_digital"
    COMUNICACION = "comunicacion"
    FICHADA = "fichada"
    LEGAJOS = "legajos"
    NOVEDADES = "novedades"

    nombre = models.CharField(max_length=100, unique=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Implementacion(models.Model):
    """Un proceso de relevamiento/implementación puntual de un Cliente.

    El cliente accede vía un link único con token (sin login) para completar
    el wizard de autoservicio. Reemplaza lo que antes eran dos modelos
    separados (Cliente + ImplementationLink): acá vive todo lo relevado en
    ese proceso puntual.
    """

    ESTADO_PENDIENTE = "pendiente"
    ESTADO_CUMPLIDA = "cumplida"
    ESTADO_CANCELADA = "cancelada"
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_CUMPLIDA, "Cumplida"),
        (ESTADO_CANCELADA, "Cancelada"),
    ]

    # Estado "visual": lo que ve el equipo de implementación en el panel. Es un
    # derivado de `estado` + `enviado`, no un campo propio — una sola fuente de
    # verdad, sin dos columnas que puedan quedar inconsistentes entre sí.
    VISUAL_A_COMPLETAR = "a_completar"
    VISUAL_COMPLETADO_CLIENTE = "completado_cliente"
    VISUAL_COMPLETO = "completo"
    VISUAL_CANCELADA = "cancelada"

    VISUAL_LABELS = {
        VISUAL_A_COMPLETAR: "Pendiente - A completar por cliente",
        VISUAL_COMPLETADO_CLIENTE: "Pendiente - Completo por cliente",
        VISUAL_COMPLETO: "Completo",
        VISUAL_CANCELADA: "Cancelada",
    }

    @classmethod
    def filtro_visual(cls, clave):
        """Devuelve el Q() que corresponde a un estado visual, para filtrar el queryset."""
        return {
            cls.VISUAL_A_COMPLETAR: models.Q(estado=cls.ESTADO_PENDIENTE, enviado__isnull=True),
            cls.VISUAL_COMPLETADO_CLIENTE: models.Q(estado=cls.ESTADO_PENDIENTE, enviado__isnull=False),
            cls.VISUAL_COMPLETO: models.Q(estado=cls.ESTADO_CUMPLIDA),
            cls.VISUAL_CANCELADA: models.Q(estado=cls.ESTADO_CANCELADA),
        }[clave]

    @property
    def estado_visual(self):
        if self.estado == self.ESTADO_CANCELADA:
            return self.VISUAL_CANCELADA
        if self.estado == self.ESTADO_CUMPLIDA:
            return self.VISUAL_COMPLETO
        return self.VISUAL_COMPLETADO_CLIENTE if self.enviado else self.VISUAL_A_COMPLETAR

    @property
    def estado_visual_label(self):
        return self.VISUAL_LABELS[self.estado_visual]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="implementaciones")
    token = models.CharField(max_length=64, unique=True, default=generate_token, editable=False)

    # Identificadores para integrar con otros sistemas. El `token` es secreto (es el link del cliente);
    # el `uuid` es público y no revela nada; `origen` + `id_externo` identifican el caso en el sistema que
    # lo originó (por ejemplo el ID del deal en el CRM) y evitan duplicarlo.
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ORIGEN_PORTAL = "portal"
    ORIGEN_HUBSPOT = "hubspot"
    ORIGEN_API = "api"
    ORIGEN_CHOICES = [
        (ORIGEN_PORTAL, "Creada en el portal"),
        (ORIGEN_HUBSPOT, "HubSpot"),
        (ORIGEN_API, "API"),
    ]
    origen = models.CharField(max_length=20, choices=ORIGEN_CHOICES, default=ORIGEN_PORTAL)
    id_externo = models.CharField(
        "ID en el sistema de origen", max_length=100, null=True, blank=True,
        help_text="Por ejemplo, el ID del deal en el CRM. Único por origen.",
    )
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    paso_actual = models.PositiveSmallIntegerField(default=1)
    modulos_editables_por_cliente = models.BooleanField(
        "El cliente puede editar los módulos",
        default=True,
        help_text=(
            "Si está desactivado, el cliente ve en el paso 2 los módulos que precargó "
            "el implementador al generar el link, mostrados de solo lectura."
        ),
    )

    telefono = models.CharField("N° de Teléfono", max_length=50, blank=True)
    mail_contacto = models.EmailField("Mail de contacto", blank=True)

    # Qué decide el cliente y qué deja fijo el equipo. Cuando un dato está bloqueado, el
    # valor lo carga el implementador y el cliente lo ve pero no lo puede cambiar.
    tipo_firma_editable = models.BooleanField("El cliente puede elegir el tipo de firma", default=True)
    nomenclatura_editable = models.BooleanField("El cliente puede definir la nomenclatura de los PDF", default=True)
    segmentacion_editable = models.BooleanField("El cliente puede elegir la segmentación del liquidador", default=True)
    max_roles = models.PositiveSmallIntegerField(
        "Máximo de personas con rol", default=6,
        validators=[MinValueValidator(3), MaxValueValidator(6)],
        help_text="Cuántas personas puede cargar el cliente en el paso de roles (mínimo 3: uno por rol obligatorio).",
    )

    TIPO_FIRMA_CHOICES = [
        ("electronica", "Electrónica"),
        ("digital", "Digital"),
    ]
    tipo_firma = models.CharField(
        "Tipo de firma", max_length=20, choices=TIPO_FIRMA_CHOICES, blank=True
    )
    liquidador_utilizado = models.CharField(
        "Liquidador utilizado", max_length=255, blank=True
    )
    nomenclatura_pdf = models.CharField(
        "Nomenclatura de descarga de archivos PDF", max_length=255, blank=True
    )
    cantidad_capitas = models.PositiveIntegerField(
        "Cantidad de capitas", null=True, blank=True
    )
    segmentacion_liquidador = models.CharField(
        "Segmentación del rol Liquidador", max_length=255, blank=True, default="AREA UNICA"
    )

    banner = models.ImageField(
        "Banner de la Sociedad", upload_to="implementaciones/banners/", blank=True, null=True,
        validators=[validar_tamanio_archivo],
    )
    modelo_recibo = models.FileField(
        "Modelo de recibo (PDF)", upload_to="implementaciones/modelos_recibo/", blank=True, null=True,
        validators=[validar_tamanio_archivo],
    )

    fecha_salida_productivo = models.DateField(
        "Fecha de salida en productivo", null=True, blank=True
    )

    # Pedido de revisión: el cliente le avisa al equipo que necesita que lo contacten.
    revision_solicitada = models.BooleanField(default=False)
    revision_solicitada_en = models.DateTimeField(null=True, blank=True)
    revision_mensaje = models.TextField(blank=True)
    revision_atendida_en = models.DateTimeField(null=True, blank=True)

    creado_por = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="implementaciones_generadas",
    )
    implementador_asignado = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="implementaciones_asignadas",
        help_text="Quien lleva esta implementación. Por defecto, quien la creó; recibe las notificaciones.",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    enviado = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo el cliente envió el relevamiento. No implica que la implementación esté cumplida.",
    )
    cumplida_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)
    expira = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Implementación"
        verbose_name_plural = "Implementaciones"
        ordering = ["-creado"]
        constraints = [
            # Con NULL en `id_externo` no hay restricción (varios casos sin ID externo); MySQL no
            # admite índices parciales, por eso es NULL y no una cadena vacía.
            models.UniqueConstraint(fields=["origen", "id_externo"], name="implementacion_origen_id_externo_unico"),
        ]

    def __str__(self):
        return f"{self.cliente} ({self.get_estado_display()})"

    @property
    def asignado_nombre(self):
        """Nombre de quien lleva la implementación ("" si no tiene asignado)."""
        asignado = self.implementador_asignado
        return (asignado.get_full_name() or asignado.get_username()) if asignado else ""

    def usa_modulo(self, codigo):
        """¿Tiene contratado (y activo) el módulo con ese código?"""
        return self.modulos.filter(activo=True, modulo__codigo=codigo).exists()

    def get_absolute_url(self):
        return reverse("onboarding:wizard_step", kwargs={"token": self.token, "step": 1})

    def pedir_revision(self, mensaje=""):
        """El cliente pide que el equipo de implementación se contacte con él."""
        self.revision_solicitada = True
        self.revision_solicitada_en = timezone.now()
        self.revision_mensaje = mensaje
        self.revision_atendida_en = None
        self.save(update_fields=[
            "revision_solicitada", "revision_solicitada_en",
            "revision_mensaje", "revision_atendida_en",
        ])

    def marcar_revision_atendida(self):
        self.revision_atendida_en = timezone.now()
        self.save(update_fields=["revision_atendida_en"])

    def anular(self):
        """El equipo de implementación cancela esta implementación (ya no queda pendiente)."""
        self.estado = self.ESTADO_CANCELADA
        self.cancelada_en = timezone.now()
        self.save(update_fields=["estado", "cancelada_en"])

    def marcar_cumplida(self):
        """El equipo de implementación termina el trabajo real de implementar al cliente.

        Que el cliente haya enviado el relevamiento (`enviado`) NO significa que la
        implementación esté cumplida — recién ahí arranca el trabajo de Napsis.
        """
        self.estado = self.ESTADO_CUMPLIDA
        self.cumplida_en = timezone.now()
        self.save(update_fields=["estado", "cumplida_en"])


class ImplementacionModulo(models.Model):
    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="modulos"
    )
    modulo = models.ForeignKey(Modulo, on_delete=models.PROTECT)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Módulo de la implementación"
        verbose_name_plural = "Módulos de la implementación"
        unique_together = ("implementacion", "modulo")

    def __str__(self):
        return f"{self.implementacion} - {self.modulo}"


class PersonaRol(models.Model):
    """Apoderado/s, Liquidador y Admin de RRHH declarados en una implementación."""

    ROL_APODERADO = "apoderado"
    ROL_LIQUIDADOR = "liquidador"
    ROL_ADMIN_RRHH = "admin_rrhh"
    ROL_CHOICES = [
        (ROL_APODERADO, "Apoderado / Firmante"),
        (ROL_LIQUIDADOR, "Liquidador"),
        (ROL_ADMIN_RRHH, "Admin. de RRHH"),
    ]

    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="roles"
    )
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    apellido_nombre = models.CharField("Apellido y Nombre", max_length=255)
    cuil = models.CharField("CUIL", max_length=20, blank=True)
    mail = models.EmailField("Mail", blank=True)

    class Meta:
        verbose_name = "Persona / Rol"
        verbose_name_plural = "Personas / Roles"

    def __str__(self):
        return f"{self.apellido_nombre} ({self.get_rol_display()})"


class Sucursal(models.Model):
    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="sucursales"
    )
    nombre = models.CharField(max_length=100, blank=True)
    calle = models.CharField("Calle", max_length=255, blank=True)
    altura = models.CharField("Altura", max_length=20, blank=True)
    piso_depto = models.CharField("Piso/depto", max_length=50, blank=True)
    codigo_postal = models.CharField("CP", max_length=20, blank=True)
    localidad = models.CharField("Localidad", max_length=150, blank=True)
    entre_calles = models.CharField("Entre Calles", max_length=255, blank=True)
    observaciones = models.TextField("Observaciones", blank=True)

    class Meta:
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"

    def __str__(self):
        return self.nombre or f"Sucursal de {self.implementacion}"


class ImplementacionLicencia(models.Model):
    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="licencias"
    )
    tipo_licencia = models.ForeignKey("catalog.TipoLicencia", on_delete=models.PROTECT)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Licencia de la implementación"
        verbose_name_plural = "Licencias de la implementación"
        unique_together = ("implementacion", "tipo_licencia")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_licencia}"


class ImplementacionNovedad(models.Model):
    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="novedades"
    )
    tipo_novedad = models.ForeignKey("catalog.TipoNovedad", on_delete=models.PROTECT)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Novedad de la implementación"
        verbose_name_plural = "Novedades de la implementación"
        unique_together = ("implementacion", "tipo_novedad")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_novedad}"


class ImplementacionTipoDocumento(models.Model):
    """Activación de un TipoDocumento para una implementación puntual.

    La fecha de puesta en vigencia NO es por ítem — es única para toda la
    implementación (`Implementacion.fecha_salida_productivo`).
    """

    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="documentos_legajo"
    )
    tipo_documento = models.ForeignKey("catalog.TipoDocumento", on_delete=models.CASCADE)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Documento de legajo de la implementación"
        verbose_name_plural = "Documentos de legajo de la implementación"
        unique_together = ("implementacion", "tipo_documento")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_documento}"


class ImplementacionVersion(models.Model):
    """Snapshot de cómo estaba una sección de la implementación justo ANTES de un
    cambio, para que el cliente y el equipo puedan consultar versiones anteriores."""

    SECCION_CHOICES = [
        ("datos_contacto", "Datos de contacto"),
        ("modulos", "Módulos"),
        ("roles", "Roles"),
        ("sucursales", "Sucursales"),
        ("licencias_novedades", "Licencias y Novedades"),
        ("documentos", "Documentos de Legajo"),
        ("empleados", "Empleados"),
        ("fecha_implementacion", "Fecha de implementación"),
        ("condiciones", "Condiciones del proceso"),
    ]

    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="versiones"
    )
    seccion = models.CharField(max_length=30, choices=SECCION_CHOICES)
    datos = models.JSONField(encoder=DjangoJSONEncoder)
    editado_por = models.CharField(
        max_length=150, help_text="'Cliente' o el usuario del equipo que hizo el cambio."
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Versión anterior"
        verbose_name_plural = "Versiones anteriores"
        ordering = ["-creado"]

    def __str__(self):
        return f"{self.implementacion} - {self.get_seccion_display()} ({self.creado:%d/%m/%Y %H:%M})"
