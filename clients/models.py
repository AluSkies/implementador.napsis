import secrets
import uuid
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from catalog.codigos import ConCodigo

from .validators import validar_pdf, validar_tamanio_archivo


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
    # Una devolución al cliente no es un estado más: la implementación vuelve a "a completar" y
    # lleva la marca "Devuelta, ronda N" mientras la ronda siga abierta.
    VISUAL_A_COMPLETAR = "a_completar"
    VISUAL_COMPLETADO_CLIENTE = "completado_cliente"
    VISUAL_VALIDADA = "validada"
    VISUAL_COMPLETO = "completo"
    VISUAL_CANCELADA = "cancelada"

    VISUAL_LABELS = {
        VISUAL_A_COMPLETAR: "Pendiente - A completar por cliente",
        VISUAL_COMPLETADO_CLIENTE: "Documentación completa - Pendiente de validación",
        VISUAL_VALIDADA: "Validada - Pendiente de configurar",
        VISUAL_COMPLETO: "Completo",
        VISUAL_CANCELADA: "Cancelada",
    }

    # «Implementación sin movimiento»: una implementación pendiente a la que nadie le hizo nada en tantos días.
    # No es un estado más (la implementación sigue donde estaba): es una marca derivada del último evento.
    DIAS_SIN_MOVIMIENTO = 7
    SIN_MOVIMIENTO = "sin_movimiento"
    SIN_MOVIMIENTO_LABEL = "Implementación sin movimiento"

    @classmethod
    def opciones_de_filtro_de_estado(cls):
        """Lo que se puede elegir en el filtro «Estado» del listado: los estados visibles y la marca."""
        return [*cls.VISUAL_LABELS.items(), (cls.SIN_MOVIMIENTO, cls.SIN_MOVIMIENTO_LABEL)]

    @classmethod
    def limite_sin_movimiento(cls, ahora=None):
        """Lo último que puede haber pasado para que ya cuente como sin movimiento."""
        return (ahora or timezone.now()) - timedelta(days=cls.DIAS_SIN_MOVIMIENTO)

    @classmethod
    def filtro_visual(cls, clave):
        """Devuelve el Q() que corresponde a un estado visual, para filtrar el queryset."""
        return {
            cls.VISUAL_A_COMPLETAR: models.Q(estado=cls.ESTADO_PENDIENTE, enviado__isnull=True),
            cls.VISUAL_COMPLETADO_CLIENTE: models.Q(
                estado=cls.ESTADO_PENDIENTE, enviado__isnull=False, validada_en__isnull=True,
            ),
            cls.VISUAL_VALIDADA: models.Q(estado=cls.ESTADO_PENDIENTE, enviado__isnull=False, validada_en__isnull=False),
            cls.VISUAL_COMPLETO: models.Q(estado=cls.ESTADO_CUMPLIDA),
            cls.VISUAL_CANCELADA: models.Q(estado=cls.ESTADO_CANCELADA),
        }[clave]

    @property
    def estado_visual(self):
        if self.estado == self.ESTADO_CANCELADA:
            return self.VISUAL_CANCELADA
        if self.estado == self.ESTADO_CUMPLIDA:
            return self.VISUAL_COMPLETO
        if not self.enviado:
            return self.VISUAL_A_COMPLETAR
        return self.VISUAL_VALIDADA if self.validada_en else self.VISUAL_COMPLETADO_CLIENTE

    @property
    def estado_visual_label(self):
        return self.VISUAL_LABELS[self.estado_visual]

    @property
    def ultimo_movimiento(self):
        """Cuándo fue lo último que pasó en la implementación: el último evento (cualquier acción del
        cliente o del equipo, un comentario, un envío) o, si no tuvo ninguno, cuándo se creó."""
        if hasattr(self, "movimiento_en"):  # viene anotado en los listados (evita una consulta por fila)
            return self.movimiento_en
        from automatizacion.models import EventoImplementacion

        ultimo = EventoImplementacion.objects.filter(implementacion=self).order_by("-momento").values_list(
            "momento", flat=True,
        ).first()
        return max(ultimo, self.creado) if ultimo else self.creado

    @property
    def sin_movimiento(self):
        return self.estado == self.ESTADO_PENDIENTE and self.ultimo_movimiento <= self.limite_sin_movimiento()

    @property
    def dias_sin_movimiento(self):
        return max((timezone.now() - self.ultimo_movimiento).days, 0)

    @property
    def ronda_abierta(self):
        """La devolución al cliente que todavía no respondió (None si no hay). Una implementación
        con ronda abierta nunca está enviada: devolverla la saca del envío."""
        if hasattr(self, "_ronda_abierta"):
            return self._ronda_abierta
        return self.rondas.filter(respondida_en__isnull=True).order_by("-numero").first()

    @property
    def marca_de_devolucion(self):
        """«Devuelta, ronda N» mientras el cliente tiene pendiente responder una devolución; si no, ''."""
        if hasattr(self, "ronda_abierta_numero"):  # viene anotado en los listados (evita una consulta por fila)
            numero = self.ronda_abierta_numero
        else:
            ronda = self.ronda_abierta
            numero = ronda.numero if ronda else None
        return f"Devuelta, ronda {numero}" if numero else ""

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
    logo = models.ImageField(
        "Logo de la Sociedad", upload_to="implementaciones/logos/", blank=True, null=True,
        validators=[validar_tamanio_archivo],
    )
    modelo_recibo = models.FileField(
        "Modelo de recibo (PDF)", upload_to="implementaciones/modelos_recibo/", blank=True, null=True,
        validators=[validar_tamanio_archivo, validar_pdf],
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
    validada_en = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo el equipo validó la documentación y la dejó lista para configurar. Se borra si se devuelve al cliente.",
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

    @property
    def firma(self):
        """La ubicación de la firma que vale para todos los tipos de liquidación (None si todavía no se cargó)."""
        return self.firmas.filter(tipo_liquidacion__isnull=True).first()

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


def geometria_inicial_de_firma():
    """Dónde arrancan las tres firmas sobre el recibo (fracciones de la página, de 0 a 1)."""
    return {
        "empresa": {"x": 0.08, "y": 0.82, "ancho": 0.25, "alto": 0.08},
        "conforme": {"x": 0.38, "y": 0.82, "ancho": 0.25, "alto": 0.08},
        "disconforme": {"x": 0.68, "y": 0.82, "ancho": 0.25, "alto": 0.08},
    }


class UbicacionFirma(models.Model):
    """Dónde quiere el cliente que vaya su firma sobre su modelo de recibo.

    Es solo la **intención del cliente**: la imagen de la firma del apoderado y, sobre la página del
    recibo, tres recuadros (la firma de la empresa y los del empleado en conformidad y en
    disconformidad), con posición y tamaño relativos a la página. El portal no la traduce a Napsis:
    el equipo la valida, la devuelve o la corrige, y quien configura la lleva a Napsis.

    Los archivos no se pisan ni se borran: al subir otra imagen la anterior sigue guardada."""

    PAGINA_PRIMERA = "primera"
    PAGINA_ULTIMA = "ultima"
    PAGINA_TODAS = "todas"
    PAGINA_CHOICES = [
        (PAGINA_PRIMERA, "Primera página"),
        (PAGINA_ULTIMA, "Última página"),
        (PAGINA_TODAS, "Todas las páginas"),
    ]

    ESTADO_PROPUESTA = "propuesta"
    ESTADO_VALIDADA = "validada"
    ESTADO_OBSERVADA = "observada"
    ESTADO_CHOICES = [
        (ESTADO_PROPUESTA, "Propuesta por el cliente"),
        (ESTADO_VALIDADA, "Validada"),
        (ESTADO_OBSERVADA, "Observada"),
    ]

    ELEMENTOS = [
        ("empresa", "Firma de la empresa"),
        ("conforme", "Empleado en conformidad"),
        ("disconforme", "Empleado en disconformidad"),
    ]

    # Catálogo cerrado de motivos: lo que se registra es el código (estable), no el texto.
    MOTIVOS = [
        ("ilegible", "La firma no se lee bien"),
        ("baja_calidad", "La imagen es de baja calidad"),
        ("tamano_excesivo", "La firma quedó demasiado grande o demasiado chica"),
        ("superpone_texto", "Se superpone con el texto del recibo"),
        ("no_replicable", "No se puede replicar así en Napsis"),
        ("otro", "Otro motivo"),
    ]

    implementacion = models.ForeignKey(Implementacion, on_delete=models.CASCADE, related_name="firmas")
    # Vacío = vale para todos los tipos de liquidación (hoy es el único caso que ofrece la pantalla).
    tipo_liquidacion = models.ForeignKey(
        "catalog.TipoLiquidacion", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
    )
    pagina = models.CharField(max_length=10, choices=PAGINA_CHOICES, default=PAGINA_PRIMERA)
    imagen = models.ImageField(
        "Imagen de la firma", upload_to="implementaciones/firmas/", blank=True, null=True,
        validators=[validar_tamanio_archivo],
    )
    imagen_sha256 = models.CharField(max_length=64, blank=True)
    # {"empresa": {"x", "y", "ancho", "alto"}, "conforme": {...}, "disconforme": {...}}, de 0 a 1.
    geometria = models.JSONField(default=geometria_inicial_de_firma)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=ESTADO_PROPUESTA)
    motivos = models.JSONField(default=list, blank=True, help_text="Códigos del catálogo, si fue observada.")
    comentario = models.TextField(blank=True)
    propuesta_por = models.CharField(max_length=150, blank=True)
    validada_por = models.CharField(max_length=150, blank=True)
    validada_en = models.DateTimeField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ubicación de la firma"
        verbose_name_plural = "Ubicaciones de la firma"
        constraints = [
            models.UniqueConstraint(fields=["implementacion", "tipo_liquidacion"], name="firma_unica_por_tipo"),
        ]

    def __str__(self):
        return f"{self.implementacion} - firma ({self.get_estado_display()})"

    @property
    def motivos_texto(self):
        nombres = dict(self.MOTIVOS)
        return [nombres.get(codigo, codigo) for codigo in self.motivos]


class ComentarioInterno(models.Model):
    """Una nota del equipo sobre una implementación. **Privada**: el cliente nunca la ve (no aparece en
    ninguna pantalla ni mail del cliente ni en la configuración congelada). Solo se agrega: no se edita
    ni se borra, así queda el hilo de lo que se fue hablando."""

    MAX_LARGO = 2000

    implementacion = models.ForeignKey(Implementacion, on_delete=models.CASCADE, related_name="comentarios")
    autor = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    autor_nombre = models.CharField(max_length=150, help_text="Quién lo escribió (queda aunque se borre la cuenta).")
    texto = models.TextField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Comentario interno"
        verbose_name_plural = "Comentarios internos"
        ordering = ["-creado", "-id"]

    def __str__(self):
        return f"{self.implementacion} - {self.autor_nombre} ({self.creado:%d/%m/%Y %H:%M})"


class RondaRevision(models.Model):
    """Una devolución al cliente: qué tiene que corregir o completar antes de que se valide.

    Se queda para siempre (es el historial de idas y vueltas); se cierra cuando el cliente vuelve a enviar."""

    implementacion = models.ForeignKey(Implementacion, on_delete=models.CASCADE, related_name="rondas")
    numero = models.PositiveIntegerField()
    motivo = models.TextField()
    # {código del paso: observación}; el código es estable aunque cambie el orden de los pasos.
    observaciones = models.JSONField(default=dict, blank=True)
    devuelta_por = models.CharField(max_length=150, help_text="Usuario del equipo que la devolvió.")
    devuelta_en = models.DateTimeField(auto_now_add=True)
    respondida_en = models.DateTimeField(null=True, blank=True, help_text="Cuándo el cliente volvió a enviar.")

    class Meta:
        verbose_name = "Ronda de revisión"
        verbose_name_plural = "Rondas de revisión"
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["implementacion", "numero"], name="ronda_numero_unico_por_implementacion"),
        ]

    def __str__(self):
        return f"{self.implementacion} - ronda {self.numero}"

    @property
    def abierta(self):
        return self.respondida_en is None


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
    # Roles que Napsis elige de la nómina ya importada: tienen que ser empleados cargados.
    ROLES_EN_NOMINA = (ROL_APODERADO, ROL_LIQUIDADOR)

    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    apellido_nombre = models.CharField("Apellido y Nombre", max_length=255)
    cuil = models.CharField("CUIL", max_length=20, blank=True)
    mail = models.EmailField("Mail", blank=True)
    # El empleado de la nómina al que corresponde (por CUIL). Si se borra el empleado, queda vacío.
    empleado = models.ForeignKey(
        "employees.Empleado", null=True, blank=True, on_delete=models.SET_NULL, related_name="roles",
    )

    @property
    def alcance_descripcion(self):
        """Qué recibos ve esta persona, en una frase (solo tiene sentido para el Liquidador)."""
        from .alcance import alcance_de, describir

        return describir(alcance_de(self))

    class Meta:
        verbose_name = "Persona / Rol"
        verbose_name_plural = "Personas / Roles"

    def __str__(self):
        return f"{self.apellido_nombre} ({self.get_rol_display()})"


class AlcanceRegla(models.Model):
    """Un grupo de la nómina al que llega el liquidador (ej.: puesto = OPERARIO). Ver clients/alcance.py."""

    persona = models.ForeignKey(PersonaRol, on_delete=models.CASCADE, related_name="reglas_de_alcance")
    campo = models.CharField(max_length=20)
    valor = models.CharField(max_length=150)

    class Meta:
        verbose_name = "Regla de alcance"
        verbose_name_plural = "Reglas de alcance"
        constraints = [models.UniqueConstraint(fields=["persona", "campo", "valor"], name="alcance_regla_unica")]


class AlcancePersona(models.Model):
    """Una persona suelta a la que llega el liquidador. Va por CUIL (y no por el empleado) para que
    siga valiendo si la nómina se vuelve a importar."""

    persona = models.ForeignKey(PersonaRol, on_delete=models.CASCADE, related_name="personas_de_alcance")
    cuil = models.CharField(max_length=11)

    class Meta:
        verbose_name = "Persona del alcance"
        verbose_name_plural = "Personas del alcance"
        constraints = [models.UniqueConstraint(fields=["persona", "cuil"], name="alcance_persona_unica")]


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


class ImplementacionLiquidacion(models.Model):
    """Qué tipos de liquidación usa la empresa (Recibo Digital)."""

    implementacion = models.ForeignKey(
        Implementacion, on_delete=models.CASCADE, related_name="liquidaciones"
    )
    tipo_liquidacion = models.ForeignKey("catalog.TipoLiquidacion", on_delete=models.PROTECT)
    activo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Tipo de liquidación de la implementación"
        verbose_name_plural = "Tipos de liquidación de la implementación"
        unique_together = ("implementacion", "tipo_liquidacion")

    def __str__(self):
        return f"{self.implementacion} - {self.tipo_liquidacion}"


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
        ("liquidaciones", "Tipos de liquidación"),
        ("firma", "Firma del recibo"),
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
