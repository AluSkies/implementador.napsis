"""Gestión de las cuentas del equipo y de sus grupos de trabajo (el rol Admin las administra desde el panel).

Cada cambio deja un `EventoDeCuenta` (quién, a quién, qué): dar el rol Admin o mover a alguien de grupo cambia quién
ve qué, y eso tiene que poder reconstruirse.
"""

from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count, Q

from automatizacion.actores import GRUPO_SUPERVISOR, es_supervisor
from clients.models import Implementacion
from clients.services import generar_password

from .models import EventoDeCuenta, GrupoDeTrabajo, Membresia

ROL_IMPLEMENTADOR = "implementador"
ROL_SUPERVISOR = "supervisor"
ROL_ADMIN = "admin"
ROLES = ((ROL_IMPLEMENTADOR, "Implementador"), (ROL_SUPERVISOR, "Supervisor"), (ROL_ADMIN, "Admin"))


class CambioNoPermitido(Exception):
    """El cambio dejaría al portal sin admin o sin que alguien pueda deshacerlo: se explica el motivo."""


def _quien(por):
    return por.get_username() if por is not None else "sistema"


def _registrar(por, accion, sujeto, **datos):
    return EventoDeCuenta.objects.create(actor=_quien(por), sujeto=sujeto, accion=accion, datos=datos)


def rol_de(usuario):
    if usuario.is_superuser:
        return ROL_ADMIN
    return ROL_SUPERVISOR if es_supervisor(usuario) else ROL_IMPLEMENTADOR


# --- cuentas -----------------------------------------------------------------------------------------------------


def cuentas_del_equipo():
    """Las cuentas del equipo: staff, con cualquier rol (Implementador, Supervisor o Admin). `es_supervisor` dice
    si pertenece al grupo Supervisor; el rol Admin es `is_superuser`. Los clientes no aparecen acá."""
    return (
        User.objects.filter(is_staff=True)
        .annotate(creadas=Count("implementaciones_generadas", distinct=True))
        .annotate(es_supervisor=Count("groups", filter=Q(groups__name=GRUPO_SUPERVISOR), distinct=True))
        .select_related("membresia__grupo")
        .prefetch_related("grupos_a_cargo")
        .order_by("-is_active", "username")
    )


def asignables(para=None):
    """Cuentas a las que `para` puede asignar una implementación. El admin (o nadie en particular), a todo el equipo
    activo; el supervisor, a sí mismo y a los integrantes de sus grupos; cualquier otro, solo a sí mismo."""
    equipo = User.objects.filter(is_staff=True, is_active=True)
    if para is not None and not para.is_superuser:
        equipo = equipo.filter(Q(pk=para.pk) | Q(membresia__grupo__supervisor=para))
    return equipo.order_by("first_name", "username")


def admins_activos(excluyendo=None):
    admins = User.objects.filter(is_superuser=True, is_staff=True, is_active=True)
    return admins.exclude(pk=excluyendo.pk) if excluyendo is not None else admins


def error_de_cambio_de_rol(usuario, rol, por=None):
    """Por qué no se puede dejar a `usuario` con ese rol (o None si se puede)."""
    actual = rol_de(usuario)
    if rol == actual:
        return None
    if por is not None and usuario.pk == por.pk:
        return "No podés cambiar tu propio rol: pedile a otro admin que lo haga."
    if actual == ROL_ADMIN and usuario.is_active and not admins_activos(excluyendo=usuario).exists():
        return "Tiene que quedar al menos un admin activo."
    if usuario.pk and usuario.grupos_a_cargo.exists():
        return "Tiene grupos a cargo: asignales otro supervisor (o borralos) antes de cambiarle el rol."
    return None


def error_de_baja(usuario, por=None):
    """Por qué no se puede dar de baja a `usuario` (o None si se puede)."""
    if por is not None and usuario.pk == por.pk:
        return "No podés darte de baja a vos mismo."
    if usuario.is_superuser and usuario.is_active and not admins_activos(excluyendo=usuario).exists():
        return "Tiene que quedar al menos un admin activo."
    return None


def _aplicar_rol(usuario, rol):
    """Deja a la cuenta con ese rol (banderas y grupo de Django). Un supervisor o un admin no es integrante de
    ningún grupo de trabajo: si lo era, sale. Devuelve el nombre del grupo del que salió, o None."""
    grupo, _ = Group.objects.get_or_create(name=GRUPO_SUPERVISOR)
    usuario.is_staff = True
    usuario.is_superuser = rol == ROL_ADMIN
    usuario.save(update_fields=["is_staff", "is_superuser"])
    if rol == ROL_SUPERVISOR:
        usuario.groups.add(grupo)
    else:
        usuario.groups.remove(grupo)
    if rol == ROL_IMPLEMENTADOR:
        return None
    membresia = Membresia.objects.filter(usuario=usuario).select_related("grupo").first()
    if membresia is None:
        return None
    sale_de = membresia.grupo.nombre
    membresia.delete()
    return sale_de


def asignar_rol(usuario, rol, por=None):
    """Cambia el rol de la cuenta (Implementador, Supervisor o Admin) y deja el evento. Si el cambio no se puede
    (propia cuenta, último admin, grupos a cargo) levanta `CambioNoPermitido`."""
    error = error_de_cambio_de_rol(usuario, rol, por)
    if error:
        raise CambioNoPermitido(error)
    antes = rol_de(usuario)
    with transaction.atomic():
        sale_de = _aplicar_rol(usuario, rol)
        if antes != rol:
            _registrar(por, "cuenta.rol_cambiado", usuario.get_username(), de=antes, a=rol, sale_del_grupo=sale_de)
    return sale_de


def crear_implementador(username, first_name, last_name, email, rol=ROL_IMPLEMENTADOR, por=None):
    """Crea la cuenta (Implementador, Supervisor o Admin) con una contraseña generada. Devuelve
    (usuario, password_en_claro): la contraseña solo se puede ver esta vez."""
    password = generar_password()
    with transaction.atomic():
        usuario = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name,
            is_staff=True, is_superuser=False,
        )
        _aplicar_rol(usuario, rol)
        _registrar(por, "cuenta.creada", usuario.get_username(), rol=rol)
    return usuario, password


def resetear_password(usuario, por=None):
    """Nueva contraseña generada; la anterior (y las sesiones abiertas) dejan de valer."""
    password = generar_password()
    usuario.set_password(password)
    usuario.save(update_fields=["password"])
    _registrar(por, "cuenta.password_reiniciada", usuario.get_username())
    return password


def dar_de_baja(usuario, por=None):
    """Baja lógica: no puede ingresar, pero la cuenta se conserva (y su grupo, para que su supervisor siga viendo lo
    que tenía asignado). Se mantiene en vez de borrarla para no perder a quién se atribuyen las implementaciones que
    creó. No se puede dar de baja a uno mismo ni al último admin activo."""
    error = error_de_baja(usuario, por)
    if error:
        raise CambioNoPermitido(error)
    usuario.is_active = False
    usuario.save(update_fields=["is_active"])
    _registrar(por, "cuenta.baja", usuario.get_username())


def reactivar(usuario, por=None):
    usuario.is_active = True
    usuario.save(update_fields=["is_active"])
    _registrar(por, "cuenta.reactivada", usuario.get_username())


# --- grupos de trabajo -----------------------------------------------------------------------------------------


def grupos():
    """Los grupos con su supervisor, la cantidad de integrantes y de implementaciones que reúnen."""
    return (
        GrupoDeTrabajo.objects.select_related("supervisor")
        .annotate(
            integrantes=Count("membresias", distinct=True),
            implementaciones=Count("membresias__usuario__implementaciones_asignadas", distinct=True),
        )
        .order_by("nombre")
    )


def supervisores_posibles():
    """Quienes pueden estar a cargo de un grupo: las cuentas activas con rol Supervisor."""
    return (
        User.objects.filter(is_staff=True, is_superuser=False, is_active=True, groups__name=GRUPO_SUPERVISOR)
        .order_by("first_name", "username")
    )


def integrantes_posibles():
    """Quienes pueden ser integrantes de un grupo: las cuentas con rol Implementador (un supervisor o un admin no
    pertenece a un grupo de trabajo)."""
    return (
        User.objects.filter(is_staff=True, is_superuser=False)
        .exclude(groups__name=GRUPO_SUPERVISOR)
        .select_related("membresia__grupo")
        .order_by("-is_active", "first_name", "username")
    )


def cantidad_asignada_a(usuarios):
    """Cuántas implementaciones tienen asignadas esas cuentas."""
    return Implementacion.objects.filter(implementador_asignado__in=usuarios).count()


def _fijar_integrantes(grupo, usuarios):
    """Deja al grupo con exactamente esos integrantes. Quien ya estaba en otro grupo se mueve (un implementador
    pertenece a uno solo). Devuelve (los que salieron del grupo, los que entraron, de qué grupo venían)."""
    quedan = {u.pk for u in usuarios}
    actuales = {m.usuario_id: m for m in grupo.membresias.select_related("usuario")}
    salen = [m.usuario for pk, m in actuales.items() if pk not in quedan]
    Membresia.objects.filter(grupo=grupo, usuario__in=salen).delete()
    entran, vienen_de = [], {}
    for usuario in usuarios:
        if usuario.pk in actuales:
            continue
        previa = Membresia.objects.filter(usuario=usuario).select_related("grupo").first()
        if previa:
            vienen_de[usuario.get_username()] = previa.grupo.nombre
        Membresia.objects.update_or_create(usuario=usuario, defaults={"grupo": grupo})
        entran.append(usuario)
    return salen, entran, vienen_de


def crear_grupo(nombre, supervisor, integrantes, por=None):
    with transaction.atomic():
        grupo = GrupoDeTrabajo.objects.create(nombre=nombre, supervisor=supervisor)
        _, entran, vienen_de = _fijar_integrantes(grupo, integrantes)
        _registrar(
            por, "grupo.creado", grupo.nombre, supervisor=supervisor.get_username(),
            integrantes=sorted(u.get_username() for u in entran), vienen_de=vienen_de,
        )
    return grupo


def actualizar_grupo(grupo, nombre, supervisor, integrantes, por=None):
    """Cambia el nombre, el supervisor y los integrantes del grupo. Devuelve las cuentas que salieron del grupo: lo
    que tengan asignado deja de verlo el supervisor del grupo (el admin siempre lo ve y puede reasignarlo)."""
    with transaction.atomic():
        nombre_anterior, supervisor_anterior = grupo.nombre, grupo.supervisor
        grupo.nombre, grupo.supervisor = nombre, supervisor
        grupo.save(update_fields=["nombre", "supervisor"])
        salen, entran, vienen_de = _fijar_integrantes(grupo, integrantes)
        cambios = {}
        if nombre != nombre_anterior:
            cambios["nombre"] = {"antes": nombre_anterior, "despues": nombre}
        if supervisor != supervisor_anterior:
            cambios["supervisor"] = {"antes": supervisor_anterior.get_username(), "despues": supervisor.get_username()}
        if salen:
            cambios["salen"] = sorted(u.get_username() for u in salen)
        if entran:
            cambios["entran"] = sorted(u.get_username() for u in entran)
            if vienen_de:
                cambios["vienen_de"] = vienen_de
        if cambios:
            _registrar(por, "grupo.modificado", nombre, **cambios)
    return salen


def borrar_grupo(grupo, por=None):
    """Borra el grupo (no las cuentas). Devuelve cuántas implementaciones dejan de verse por su supervisor."""
    afectadas = Implementacion.objects.filter(implementador_asignado__membresia__grupo=grupo).count()
    with transaction.atomic():
        _registrar(
            por, "grupo.borrado", grupo.nombre, supervisor=grupo.supervisor.get_username(),
            integrantes=sorted(grupo.membresias.values_list("usuario__username", flat=True)),
            implementaciones_afectadas=afectadas,
        )
        grupo.delete()
    return afectadas
