"""Acciones sobre las implementaciones: crear, dar acceso, reasignar, enviar, cumplir...

Es la capa que usan las pantallas (wizard del cliente y panel del equipo) y que mañana podrán usar una
API o un agente. Cada acción:

- recibe un **actor** (quién la hace) y **no conoce el `request`**: si hace falta la URL pública del
  portal para armar un link, llega como `base_url`;
- aplica las reglas y guarda todo en **una transacción** junto con su **evento**;
- hace los avisos por mail **después** de guardar, y un mail que falla nunca deshace lo que ya se hizo:
  queda registrado y se avisa en el resultado;
- devuelve un `Resultado` con los errores de validación (si no se pudo) y los avisos para mostrar.
"""

import logging
from dataclasses import dataclass, field

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from automatizacion import eventos
from clients.models import Cliente, Implementacion, Modulo, RondaRevision, UbicacionFirma
from clients.services import cambio_de_seccion, crear_o_resetear_acceso, foto_de_seccion
from clients.validators import normalizar_cuits
from notifications import services as notificaciones

from . import services

logger = logging.getLogger(__name__)


@dataclass
class Aviso:
    nivel: int  # un nivel de django.contrib.messages
    texto: str


@dataclass
class Resultado:
    implementacion: object = None
    errores: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    ya_existia: bool = False

    @property
    def ok(self):
        return not self.errores

    def mostrar(self, request):
        """Muestra los avisos con el sistema de mensajes de Django (para las pantallas)."""
        for aviso in self.avisos:
            messages.add_message(request, aviso.nivel, aviso.texto)


# --------------------------------------------------------------------------- mails


def _avisar_por_mail(actor, implementacion, tipo, enviar, descripcion_falla=None):
    """Ejecuta un envío de mail sin que su falla afecte a lo ya hecho. Registra el evento
    (`mail.enviado` o `mail.fallido`) y devuelve el Aviso de falla (None si salió bien o no había a quién)."""
    try:
        destinatario = enviar()
    except Exception as error:
        logger.exception("No se pudo enviar el mail «%s» (implementación %s)", tipo, getattr(implementacion, "pk", None))
        eventos.registrar(actor, "mail.fallido", implementacion, datos={"tipo": tipo, "error": type(error).__name__})
        return Aviso(messages.WARNING, descripcion_falla) if descripcion_falla else None
    if destinatario:
        destinatarios = destinatario if isinstance(destinatario, list) else [destinatario]
        eventos.registrar(actor, "mail.enviado", implementacion, datos={"tipo": tipo, "destinatarios": destinatarios})
    return None


def _invitar(actor, usuario, implementacion, base_url, avisos):
    """Manda el link para crear o cambiar la contraseña. Si el mail falla se avisa y se puede reenviar."""
    resultado = {}

    def enviar():
        resultado["para"] = notificaciones.enviar_invitacion(usuario, base_url=base_url)
        return resultado["para"]

    falla = _avisar_por_mail(
        actor, implementacion, "invitacion", enviar,
        descripcion_falla=(
            f"No se pudo enviar el mail a {usuario.email}. Usuario: {usuario.username}. "
            "Probá de nuevo desde la ficha con «Enviar mail para crear contraseña»."
        ),
    )
    if falla:
        avisos.append(falla)
    else:
        avisos.append(Aviso(
            messages.SUCCESS,
            f"Le mandamos a {usuario.email} un mail para que cree su contraseña (usuario: {usuario.username}).",
        ))


def _aviso_de_credenciales(titulo, username, password):
    """Las credenciales generadas se muestran una única vez al equipo (no se vuelven a ver)."""
    return Aviso(
        messages.SUCCESS,
        f"{titulo} — usuario: {username} / contraseña: {password} (anotala ahora, no se vuelve a mostrar).",
    )


def _validar_mail(mail):
    """Devuelve el mail limpio, "" si no vino, o None si no es válido."""
    mail = (mail or "").strip()
    if mail:
        try:
            validate_email(mail)
        except ValidationError:
            return None
    return mail


# --------------------------------------------------------------------------- crear


def crear_implementacion(
    actor, *, cliente=None, datos_cliente=None, username="", mail_cliente="", implementador=None, creado_por=None,
    modulo_ids=(), modulos_editables=True, condiciones=None,
    origen=Implementacion.ORIGEN_PORTAL, id_externo=None, base_url=None,
):
    """Crea una implementación (y la empresa y su acceso, si hacen falta).

    - `cliente`: una empresa existente; si no, `datos_cliente` = {"nombre", "razon_social", "cuits"}.
    - Con `mail_cliente`, la cuenta nueva nace sin contraseña y se le manda una invitación; sin mail,
      se genera una contraseña que el resultado muestra una única vez.
    - `implementador`: la cuenta del equipo que lleva la implementación; `creado_por`: la que la creó
      (ambas son cuentas de usuario, o None si la crea un sistema).
    - `condiciones`: un CondicionesForm ya validado (o None).
    - `origen` + `id_externo` identifican el caso en el sistema que lo originó: si ya existe uno con
      esos valores, no se crea otro y se devuelve el existente (`ya_existia`).
    Todo o nada: empresa, cuenta, implementación y módulos se guardan juntos.
    """
    if id_externo:
        existente = Implementacion.objects.filter(origen=origen, id_externo=id_externo).first()
        if existente:
            return Resultado(implementacion=existente, ya_existia=True)

    mail = _validar_mail(mail_cliente)
    if mail is None:
        return Resultado(errores=["El mail del cliente no es válido."])

    acceso = None
    with transaction.atomic():
        cliente_nuevo = cliente is None
        if cliente_nuevo:
            datos = datos_cliente or {}
            nombre = (datos.get("nombre") or "").strip()
            if not nombre:
                return Resultado(errores=["Elegí un cliente existente o completá el nombre de la empresa."])
            try:
                # Razón social y CUIT son opcionales acá: si no se cargan, el cliente los completa
                # (obligatorios) en el paso 1 del wizard.
                cuits = normalizar_cuits(datos["cuits"].strip()) if (datos.get("cuits") or "").strip() else ""
            except ValidationError as error:
                return Resultado(errores=[error.messages[0]])
            cliente = Cliente.objects.create(
                nombre=nombre, razon_social=(datos.get("razon_social") or "").strip(), cuits=cuits,
            )

        if not cliente.usuario:
            acceso = crear_o_resetear_acceso(cliente, (username or "").strip(), email=mail)

        implementacion = Implementacion(
            cliente=cliente, creado_por=creado_por, implementador_asignado=implementador,
            mail_contacto=mail,  # el paso 1 del cliente ya lo trae cargado
            modulos_editables_por_cliente=bool(modulos_editables), origen=origen, id_externo=id_externo or None,
        )
        if condiciones is not None:
            condiciones.aplicar(implementacion)
        implementacion.save()
        services.guardar_modulos(implementacion, Modulo.objects.all(), set(modulo_ids), actor)
        eventos.registrar(actor, "implementacion.creada", implementacion, datos={
            "origen": origen, "id_externo": id_externo, "cliente_id": cliente.pk, "cliente_nuevo": cliente_nuevo,
            "implementador": implementador.get_username() if implementador else None,
            "modulos": sorted(
                implementacion.modulos.filter(activo=True).values_list("modulo__codigo", flat=True)
            ),
            "condiciones": foto_de_seccion(implementacion, "condiciones"),
            "con_invitacion": bool(acceso and acceso[1] is None),
        })
        if acceso:
            eventos.registrar(actor, "acceso.creado", implementacion, datos={
                "username": acceso[0], "invitacion": acceso[1] is None,
            })

    avisos = []
    if acceso:
        username_creado, password = acceso
        if password:
            avisos.append(_aviso_de_credenciales("Acceso creado para el cliente", username_creado, password))
        else:
            _invitar(actor, cliente.usuario, implementacion, base_url, avisos)
    return Resultado(implementacion=implementacion, avisos=avisos)


# --------------------------------------------------------------------------- acceso del cliente


def entregar_acceso(actor, cliente, username="", mail="", base_url=None, implementacion=None):
    """Crea o reinicia el acceso del cliente. Con un mail (y cuenta nueva) lo invita a crear su
    propia contraseña; si no, genera una y la muestra una única vez."""
    mail_limpio = _validar_mail(mail)
    if mail_limpio is None:
        return Resultado(errores=["El mail no es válido."])
    era_nueva = not cliente.usuario
    with transaction.atomic():
        nombre, password = crear_o_resetear_acceso(cliente, (username or "").strip(), email=mail_limpio)
        eventos.registrar(
            actor, "acceso.creado" if era_nueva else "acceso.contrasena_reiniciada", implementacion,
            datos={"cliente_id": cliente.pk, "username": nombre, "invitacion": password is None},
        )
    avisos = []
    if password:
        titulo = "Acceso creado para el cliente" if era_nueva else "Nueva contraseña generada"
        avisos.append(_aviso_de_credenciales(titulo, nombre, password))
    else:
        _invitar(actor, cliente.usuario, implementacion, base_url, avisos)
    return Resultado(implementacion=implementacion, avisos=avisos)


def invitar_cliente(actor, cliente, implementacion=None, base_url=None):
    """Reenvía el link para crear o cambiar la contraseña al mail de la cuenta (o, si la cuenta no
    tiene, al de contacto de la implementación, que queda guardado en la cuenta)."""
    usuario = cliente.usuario
    if not usuario:
        return Resultado(errores=["El cliente todavía no tiene acceso creado."])
    if not usuario.email and implementacion and implementacion.mail_contacto:
        usuario.email = implementacion.mail_contacto
        usuario.save(update_fields=["email"])
    if not usuario.email:
        return Resultado(errores=["No hay un mail cargado para este cliente: completalo en los datos de contacto."])
    avisos = []
    _invitar(actor, usuario, implementacion, base_url, avisos)
    return Resultado(implementacion=implementacion, avisos=avisos)


# --------------------------------------------------------------------------- estado


def reasignar(actor, implementacion, nuevo):
    desde = implementacion.implementador_asignado
    with transaction.atomic():
        implementacion.implementador_asignado = nuevo
        implementacion.save(update_fields=["implementador_asignado"])
        eventos.registrar(actor, "implementacion.reasignada", implementacion, datos={
            "desde": desde.get_username() if desde else None, "hacia": nuevo.get_username(),
        })
    return Resultado(
        implementacion=implementacion,
        avisos=[Aviso(messages.SUCCESS, f"Implementación asignada a {nuevo.get_full_name() or nuevo.username}.")],
    )


def reabrir(actor, implementacion):
    """Vuelve la implementación al principio ("regenerar el link"): pendiente, en el paso 1 y sin envío."""
    antes = {
        "estado": implementacion.estado, "paso_actual": implementacion.paso_actual,
        "enviado": implementacion.enviado, "cancelada_en": implementacion.cancelada_en,
        "cumplida_en": implementacion.cumplida_en, "validada_en": implementacion.validada_en,
    }
    with transaction.atomic():
        implementacion.estado = Implementacion.ESTADO_PENDIENTE
        implementacion.paso_actual = 1
        implementacion.enviado = None
        implementacion.validada_en = None
        implementacion.cancelada_en = None
        implementacion.cumplida_en = None
        implementacion.save(update_fields=[
            "estado", "paso_actual", "enviado", "validada_en", "cancelada_en", "cumplida_en",
        ])
        eventos.registrar(actor, "estado.reabierta", implementacion, post_envio=antes["enviado"] is not None,
                          datos={"antes": antes})
    return Resultado(implementacion=implementacion)


def anular(actor, implementacion):
    estado_anterior = implementacion.estado
    with transaction.atomic():
        implementacion.anular()
        eventos.registrar(actor, "estado.cancelada", implementacion, datos={"estado_anterior": estado_anterior})
    return Resultado(implementacion=implementacion)


def _puede_revisarse(implementacion):
    return implementacion.estado == Implementacion.ESTADO_PENDIENTE and implementacion.enviado is not None


def aprobar_para_configurar(actor, implementacion):
    """El equipo da por buena la documentación: queda «Validada - Pendiente de configurar».

    Solo se valida lo que está completo: se vuelve a correr el control de faltantes, porque el equipo
    pudo haber cambiado datos después del envío."""
    if not _puede_revisarse(implementacion) or implementacion.validada_en:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Solo se puede validar una implementación enviada por el cliente y todavía sin validar."),
        ])
    pendientes = services.pendientes_de_validacion(implementacion)
    if pendientes:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "No se puede validar: todavía falta completar datos obligatorios. " + " ".join(pendientes)),
        ])
    with transaction.atomic():
        implementacion.validada_en = timezone.now()
        implementacion.save(update_fields=["validada_en", "actualizado"])
        eventos.registrar(actor, "estado.validada", implementacion, datos={"ronda": implementacion.rondas.count()})
    return Resultado(
        implementacion=implementacion,
        avisos=[Aviso(messages.SUCCESS, "Documentación validada: la implementación quedó lista para configurar.")],
    )


def validar_firma(actor, implementacion):
    """El equipo da por buena la ubicación de la firma que propuso el cliente."""
    firma = implementacion.firma
    if firma is None or not firma.imagen:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Todavía no hay una firma cargada para validar."),
        ])
    if firma.estado == UbicacionFirma.ESTADO_VALIDADA:
        return Resultado(implementacion=implementacion)
    with cambio_de_seccion(implementacion, "firma", actor, accion="firma.validada"):
        firma.estado = UbicacionFirma.ESTADO_VALIDADA
        firma.motivos, firma.comentario = [], ""
        firma.validada_por, firma.validada_en = actor.etiqueta, timezone.now()
        firma.save()
    return Resultado(implementacion=implementacion, avisos=[Aviso(messages.SUCCESS, "Firma validada.")])


def observar_firma(actor, implementacion, motivos, comentario="", base_url=None):
    """El equipo no acepta la firma: la marca como observada (con motivos del catálogo cerrado) y la
    devuelve al cliente para que la ubique de nuevo, con el mismo recorrido que cualquier devolución."""
    firma = implementacion.firma
    if firma is None or not firma.imagen:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Todavía no hay una firma cargada para observar."),
        ])
    nombres = dict(UbicacionFirma.MOTIVOS)
    motivos = [m for m in dict.fromkeys(motivos or []) if m in nombres]
    if not motivos:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Elegí al menos un motivo de la lista."),
        ])
    if not _puede_revisarse(implementacion):
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Solo se puede devolver una implementación que el cliente ya envió."),
        ])
    comentario = (comentario or "").strip()
    texto = "Hay que ajustar la firma del recibo: " + "; ".join(nombres[m].lower() for m in motivos) + "."
    if comentario:
        texto += f" {comentario}"
    with cambio_de_seccion(
        implementacion, "firma", actor, accion="firma.observada", datos={"motivos": motivos, "comentario": comentario},
    ):
        firma.estado = UbicacionFirma.ESTADO_OBSERVADA
        firma.motivos, firma.comentario = motivos, comentario
        firma.validada_por, firma.validada_en = "", None
        firma.save()
    return devolver_al_cliente(actor, implementacion, texto, {"firma": texto}, base_url=base_url)


def devolver_al_cliente(actor, implementacion, motivo, observaciones=None, base_url=None):
    """El equipo le devuelve el relevamiento al cliente para que corrija o complete algo.

    Abre una ronda (queda el historial de idas y vueltas), saca la implementación del envío para que el
    cliente pueda editar y le avisa por mail. Las observaciones por sección son opcionales:
    `{código de paso: texto}`; se descartan las vacías y las de pasos que no existen."""
    motivo = (motivo or "").strip()
    if not motivo:
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Contale al cliente qué tiene que corregir o completar."),
        ])
    if not _puede_revisarse(implementacion):
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Solo se puede devolver una implementación que el cliente ya envió."),
        ])
    codigos = set(services.CODIGO_DE_PASO.values())
    observaciones = {
        codigo: texto.strip() for codigo, texto in (observaciones or {}).items()
        if codigo in codigos and (texto or "").strip()
    }
    with transaction.atomic():
        numero = implementacion.rondas.count() + 1
        ronda = RondaRevision.objects.create(
            implementacion=implementacion, numero=numero, motivo=motivo, observaciones=observaciones,
            devuelta_por=actor.ref,
        )
        implementacion.enviado = None
        implementacion.validada_en = None
        implementacion.paso_actual = services.PASO_REVISION
        implementacion.save(update_fields=["enviado", "validada_en", "paso_actual", "actualizado"])
        eventos.registrar(
            actor, "ronda.devuelta", implementacion, post_envio=True,
            datos={"ronda": numero, "motivo": motivo, "observaciones": observaciones},
        )
    avisos = [Aviso(messages.SUCCESS, f"Devuelta al cliente (ronda {numero}).")]
    falla = _avisar_por_mail(
        actor, implementacion, "cliente_devuelta",
        lambda: notificaciones.notificar_cliente_devuelta(implementacion, ronda, base_url=base_url),
        descripcion_falla="Quedó devuelta, pero no se pudo avisarle al cliente por mail.",
    )
    if falla:
        avisos.append(falla)
    return Resultado(implementacion=implementacion, avisos=avisos)


def marcar_cumplida(actor, implementacion, base_url=None):
    """El equipo terminó de implementar. Se le avisa al cliente por mail (si falla, queda cumplida igual).
    Solo se puede cumplir lo que ya está validado: la configuración parte de lo que se aprobó."""
    if not (_puede_revisarse(implementacion) and implementacion.validada_en):
        return Resultado(implementacion=implementacion, avisos=[
            Aviso(messages.ERROR, "Solo se puede marcar como cumplida una implementación ya validada."),
        ])
    estado_anterior = implementacion.estado
    with transaction.atomic():
        implementacion.marcar_cumplida()
        eventos.registrar(actor, "estado.cumplida", implementacion, datos={"estado_anterior": estado_anterior})
    avisos = []
    falla = _avisar_por_mail(
        actor, implementacion, "cliente_cumplida",
        lambda: notificaciones.notificar_cliente_implementacion_cumplida(implementacion, base_url=base_url),
        descripcion_falla="Quedó cumplida, pero no se pudo avisarle al cliente por mail.",
    )
    if falla:
        avisos.append(falla)
    return Resultado(implementacion=implementacion, avisos=avisos)


def atender_revision(actor, implementacion):
    with transaction.atomic():
        implementacion.marcar_revision_atendida()
        eventos.registrar(actor, "revision.atendida", implementacion)
    return Resultado(implementacion=implementacion)


# --------------------------------------------------------------------------- el cliente envía


def registrar_validacion_fallida(actor, implementacion, paso, errores):
    """Deja constancia de lo que el cliente no pudo completar (sin los valores: solo qué falló)."""
    eventos.registrar(actor, "validacion.fallida", implementacion, datos={"paso": paso, "errores": errores})


def enviar_relevamiento(actor, implementacion, fecha, base_url=None):
    """El cliente envía el relevamiento (ya validado por quien llama: `pendientes_de_envio` vacío).

    Primero se registra el envío y recién después se avisa al equipo y al cliente: si el mail falla
    (SMTP caído, etc.) el cliente no pierde lo que ya terminó."""
    with transaction.atomic():
        if fecha != implementacion.fecha_salida_productivo:
            services.guardar_fecha_implementacion(implementacion, fecha, actor)
        implementacion.enviado = timezone.now()
        implementacion.save(update_fields=["enviado"])
        ronda = implementacion.ronda_abierta
        if ronda:
            ronda.respondida_en = implementacion.enviado
            ronda.save(update_fields=["respondida_en"])
        eventos.registrar(actor, "envio.confirmado", implementacion, datos={
            "fecha_salida_productivo": fecha, "empleados": implementacion.empleados.count(),
            **({"ronda": ronda.numero} if ronda else {}),
        })
    for tipo, enviar in (
        ("equipo_resumen", lambda: notificaciones.notificar_implementacion_completa(implementacion, base_url=base_url)),
        ("cliente_recibido", lambda: notificaciones.notificar_cliente_relevamiento_recibido(implementacion, base_url=base_url)),
    ):
        _avisar_por_mail(actor, implementacion, tipo, enviar)
    return Resultado(implementacion=implementacion)


def pedir_revision(actor, implementacion, mensaje, base_url=None):
    """El cliente pide que lo contacten. Se avisa al equipo (si el mail falla, el pedido queda igual)."""
    with transaction.atomic():
        implementacion.pedir_revision(mensaje)
        eventos.registrar(actor, "revision.solicitada", implementacion, datos={"mensaje": mensaje})
    _avisar_por_mail(
        actor, implementacion, "equipo_revision_solicitada",
        lambda: notificaciones.notificar_revision_solicitada(implementacion, base_url=base_url),
    )
    return Resultado(
        implementacion=implementacion,
        avisos=[Aviso(messages.SUCCESS, "Le avisamos al equipo de Napsis que necesitás que te contacten.")],
    )
