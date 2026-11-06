"""El panel lateral de filtros del listado de implementaciones.

Arma lo que la pantalla necesita para dibujarlo: qué opciones ofrece cada filtro (con cuántas implementaciones tiene),
cuáles están marcadas y los «chips» de lo aplicado, cada uno con el enlace que lo quita. Solo cuenta y ofrece lo que
el usuario ve: las opciones salen del queryset de implementaciones visibles que se le pasa.

El filtrado en sí está en `clients.services.filtrar_y_ordenar_implementaciones`; los filtros viajan por la URL
(`?estado=a&estado=b&empresa=3&implementador=sin`), así que se pueden compartir.
"""

from django.contrib.auth.models import User
from django.db.models import Count
from django.utils.dateparse import parse_date

from automatizacion.actores import es_supervisor
from clients.models import Implementacion
from clients.services import SIN_ASIGNAR, con_ultimo_movimiento, ids_del_filtro, valores_del_filtro

from .models import GrupoDeTrabajo

# (desde, hasta, nombre del rango) de los dos filtros por fecha.
RANGOS_DE_FECHA = (
    ("creado_desde", "creado_hasta", "Carga"),
    ("fecha_impl_desde", "fecha_impl_hasta", "Implementación"),
)


def _nombre(usuario):
    return usuario.get_full_name() or usuario.get_username()


def _cuenta_por_implementador(visibles):
    """{id de la cuenta (o None si no tiene asignada): cuántas implementaciones}."""
    filas = visibles.order_by().values("implementador_asignado_id").annotate(n=Count("pk"))
    return {fila["implementador_asignado_id"]: fila["n"] for fila in filas}


def _estados(visibles, marcados):
    claves = list(Implementacion.VISUAL_LABELS)
    cuentas = visibles.order_by().aggregate(
        **{clave: Count("pk", filter=Implementacion.filtro_visual(clave)) for clave in claves}
    )
    cuentas[Implementacion.SIN_MOVIMIENTO] = (
        con_ultimo_movimiento(visibles)
        .filter(estado=Implementacion.ESTADO_PENDIENTE, movimiento_en__lte=Implementacion.limite_sin_movimiento())
        .count()
    )
    return [
        {"clave": clave, "label": label, "n": cuentas[clave], "marcado": clave in marcados}
        for clave, label in Implementacion.opciones_de_filtro_de_estado()
    ]


def _empresas(visibles, marcadas):
    filas = visibles.order_by().values("cliente_id", "cliente__nombre").annotate(n=Count("pk")).order_by("cliente__nombre")
    return [
        {"id": fila["cliente_id"], "nombre": fila["cliente__nombre"], "n": fila["n"], "marcado": fila["cliente_id"] in marcadas}
        for fila in filas
    ]


def _implementadores(usuario, cuentas, marcados):
    """Las opciones del filtro de implementador, o None si el usuario no lo necesita (un implementador solo ve lo suyo).

    Primero «Mías»; después una sección por grupo (el supervisor ve los suyos; el admin, todos) con el supervisor y los
    integrantes, y, para el admin, «Sin grupo» con las demás cuentas que tienen algo asignado y «Sin asignar»."""
    if not (usuario.is_superuser or es_supervisor(usuario)):
        return None

    def opcion(cuenta, nombre=None, rol=""):
        return {
            "valor": str(cuenta.pk), "nombre": nombre or _nombre(cuenta), "rol": rol, "n": cuentas.get(cuenta.pk, 0),
            "marcado": str(cuenta.pk) in marcados, "de_baja": not cuenta.is_active,
        }

    grupos = GrupoDeTrabajo.objects.select_related("supervisor").prefetch_related("membresias__usuario")
    if not usuario.is_superuser:
        grupos = grupos.filter(supervisor=usuario)

    mostradas = {usuario.pk}
    secciones = []
    for grupo in grupos:
        integrantes = sorted((m.usuario for m in grupo.membresias.all()), key=lambda c: _nombre(c).lower())
        gente = [(grupo.supervisor, "supervisor")] + [(c, "") for c in integrantes]
        opciones = [opcion(cuenta, rol=rol) for cuenta, rol in gente if cuenta.pk != usuario.pk]
        if not opciones:
            continue
        mostradas.update(int(o["valor"]) for o in opciones)
        secciones.append({"nombre": grupo.nombre, "personas": opciones, "todos": all(o["marcado"] for o in opciones)})

    otras = [pk for pk in cuentas if pk is not None and pk not in mostradas]
    if otras:
        opciones = [opcion(c) for c in sorted(User.objects.filter(pk__in=otras), key=lambda c: _nombre(c).lower())]
        secciones.append({"nombre": "Sin grupo", "personas": opciones, "todos": all(o["marcado"] for o in opciones)})

    return {
        "mias": opcion(usuario, nombre="Mías"),
        "secciones": secciones,
        "sin_asignar": (
            {"valor": SIN_ASIGNAR, "nombre": "Sin asignar", "rol": "", "n": cuentas.get(None, 0), "marcado": SIN_ASIGNAR in marcados}
            if usuario.is_superuser else None
        ),
    }


def _sin(params, ruta, *claves, valor=None):
    """La URL del listado sin esos filtros (o, con `valor`, sin ese solo valor de un filtro repetido); el resto se
    conserva, el orden incluido."""
    q = params.copy()
    for clave in claves:
        if valor is None:
            q.pop(clave, None)
        else:
            q.setlist(clave, [v for v in q.getlist(clave) if v.strip() != valor])
    consulta = q.urlencode()
    return ruta + (f"?{consulta}" if consulta else "")


def _fecha(valor):
    fecha = parse_date(valor) if valor else None
    return fecha.strftime("%d/%m/%Y") if fecha else ""


def panel_de_filtros(usuario, visibles, params, ruta):
    """Todo lo que necesita el panel lateral. `visibles` son las implementaciones que el usuario puede ver (sin filtrar),
    `params` el querystring (`request.GET`) y `ruta` la URL del listado (para armar los enlaces de los chips)."""
    estados_marcados = set(valores_del_filtro(params, "estado"))
    empresas_marcadas = set(ids_del_filtro(params, "empresa"))
    implementadores_marcados = set(valores_del_filtro(params, "implementador"))

    estados = _estados(visibles, estados_marcados)
    empresas = _empresas(visibles, empresas_marcadas)
    cuentas = _cuenta_por_implementador(visibles)
    implementadores = _implementadores(usuario, cuentas, implementadores_marcados)

    nombre_de_empresa = {e["id"]: e["nombre"] for e in empresas}
    nombre_de_cuenta = {}
    if implementadores:
        opciones = [implementadores["mias"], implementadores["sin_asignar"]]
        opciones += [p for seccion in implementadores["secciones"] for p in seccion["personas"]]
        nombre_de_cuenta = {o["valor"]: o["nombre"] for o in opciones if o}

    chips = []
    texto = (params.get("cliente") or "").strip()
    if texto:
        chips.append({"texto": f"Empresa que contiene «{texto}»", "quitar": _sin(params, ruta, "cliente")})
    for id_empresa in ids_del_filtro(params, "empresa"):
        chips.append({
            "texto": f"Empresa: {nombre_de_empresa.get(id_empresa, f'#{id_empresa}')}",
            "quitar": _sin(params, ruta, "empresa", valor=str(id_empresa)),
        })
    for valor in valores_del_filtro(params, "implementador"):
        if valor.isdigit() or valor == SIN_ASIGNAR:
            chips.append({
                "texto": f"Implementador: {nombre_de_cuenta.get(valor, 'Sin asignar' if valor == SIN_ASIGNAR else f'#{valor}')}",
                "quitar": _sin(params, ruta, "implementador", valor=valor),
            })
    etiquetas_de_estado = dict(Implementacion.opciones_de_filtro_de_estado())
    for clave in valores_del_filtro(params, "estado"):
        if clave in etiquetas_de_estado:
            chips.append({"texto": f"Estado: {etiquetas_de_estado[clave]}", "quitar": _sin(params, ruta, "estado", valor=clave)})
    for desde, hasta, nombre in RANGOS_DE_FECHA:
        d, h = _fecha(params.get(desde)), _fecha(params.get(hasta))
        if d or h:
            chips.append({"texto": f"{nombre}: {d or '…'} a {h or '…'}", "quitar": _sin(params, ruta, desde, hasta)})

    return {
        "estados": estados, "empresas": empresas, "implementadores": implementadores,
        "chips": chips, "hay_filtros": bool(chips),
    }
