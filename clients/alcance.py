"""Alcance del Liquidador: de qué empleados ve los recibos.

Se arma con dos listas, y el alcance es la unión de las dos:
- `reglas`: grupos de la nómina («todos los del puesto OPERARIO», «todos los del sector Liquidaciones»).
- `cuils`: personas sueltas, una por una (por ejemplo, los gerentes).
Sin reglas ni personas el liquidador ve a todos (equivale a «AREA UNICA»).

Se guardan las reglas (`AlcanceRegla`) y los CUIL (`AlcancePersona`), no la lista de empleados resultante:
así, si la nómina cambia, el alcance se recalcula solo. En el código un alcance es un dict
{"reglas": [{"campo", "valor"}], "cuils": [...]}, que es también lo que viaja por el formulario.
"""

import json

from django.db.models import Q

from employees.services import normalizar_cuil

CAMPOS = {
    "gerencia": "Gerencia",
    "sector": "Sector",
    "puesto": "Puesto",
    "centro_costo": "Centro de costo",
    "es_supervisor": "Supervisor",
}
CAMPOS_DE_TEXTO = ("gerencia", "sector", "puesto", "centro_costo")
VALORES_SUPERVISOR = ("SI", "NO")
MAXIMO_DE_ITEMS = 200  # tope para que nadie mande un formulario gigante


def normalizar(crudo):
    """Valida lo que llega del formulario (texto JSON o dict) y devuelve el alcance limpio.
    Un alcance vacío es válido. Lanza ValueError con un mensaje legible si algo está mal."""
    if crudo in (None, "", {}):
        return {}
    if isinstance(crudo, str):
        try:
            crudo = json.loads(crudo)
        except ValueError:
            raise ValueError("El alcance del liquidador no es válido.") from None
    if not isinstance(crudo, dict):
        raise ValueError("El alcance del liquidador no es válido.")
    reglas, vistas = [], set()
    for regla in crudo.get("reglas") or []:
        campo = regla.get("campo") if isinstance(regla, dict) else None
        valor = str(regla.get("valor", "")).strip() if isinstance(regla, dict) else ""
        if campo not in CAMPOS or not valor:
            raise ValueError("Una de las reglas del alcance está incompleta.")
        if campo == "es_supervisor":
            valor = valor.upper()
            if valor not in VALORES_SUPERVISOR:
                raise ValueError("«Supervisor» solo admite SI o NO.")
        if (campo, valor.lower()) not in vistas:
            vistas.add((campo, valor.lower()))
            reglas.append({"campo": campo, "valor": valor})
    cuils = []
    for cuil in crudo.get("cuils") or []:
        cuil = normalizar_cuil(str(cuil))
        if len(cuil) != 11:
            raise ValueError("Una de las personas del alcance tiene un CUIL que no es válido.")
        if cuil not in cuils:
            cuils.append(cuil)
    if len(reglas) + len(cuils) > MAXIMO_DE_ITEMS:
        raise ValueError("El alcance tiene demasiados elementos.")
    return {"reglas": reglas, "cuils": cuils} if (reglas or cuils) else {}


def alcanzados(implementacion, alcance):
    """Los empleados de la nómina a los que llega el alcance (todos, si está vacío)."""
    empleados = implementacion.empleados.all()
    alcance = alcance or {}
    if not alcance.get("reglas") and not alcance.get("cuils"):
        return empleados
    condicion = Q(pk__in=[])
    for regla in alcance.get("reglas", []):
        if regla["campo"] == "es_supervisor":
            condicion |= Q(es_supervisor=(regla["valor"] == "SI"))
        else:
            condicion |= Q(**{f"{regla['campo']}__iexact": regla["valor"]})
    if alcance.get("cuils"):
        condicion |= Q(cuil__in=alcance["cuils"])
    return empleados.filter(condicion)


def describir(alcance):
    """El alcance en una frase para mostrar en pantalla."""
    alcance = alcance or {}
    partes = [f"{CAMPOS[r['campo']]}: {r['valor']}" for r in alcance.get("reglas", [])]
    sueltas = len(alcance.get("cuils", []))
    if sueltas:
        partes.append(f"{sueltas} persona{'s' if sueltas != 1 else ''} elegida{'s' if sueltas != 1 else ''} una por una")
    return "; ".join(partes) if partes else "Todos los recibos (sin segmentar)"


def opciones_de_la_nomina(implementacion):
    """Los valores que hay en la nómina para cada campo, para armar las reglas con una lista."""
    opciones = {}
    for campo in CAMPOS_DE_TEXTO:
        valores = implementacion.empleados.exclude(**{campo: ""}).values_list(campo, flat=True).distinct()
        opciones[campo] = sorted(set(valores), key=str.lower)
    opciones["es_supervisor"] = list(VALORES_SUPERVISOR)
    return opciones


def empleados_para_el_editor(implementacion):
    """La nómina resumida, para que el editor cuente en vivo a cuántas personas llega el alcance."""
    return [
        {"cuil": e.cuil, "nombre": f"{e.apellido}, {e.nombre}", "gerencia": e.gerencia, "sector": e.sector,
         "puesto": e.puesto, "centro_costo": e.centro_costo, "es_supervisor": "SI" if e.es_supervisor else "NO"}
        for e in implementacion.empleados.order_by("apellido", "nombre")
    ]


def alcance_de(persona):
    """El alcance guardado de una persona con rol, como dict ({} si no tiene)."""
    reglas = [{"campo": r.campo, "valor": r.valor} for r in persona.reglas_de_alcance.order_by("pk")]
    cuils = [p.cuil for p in persona.personas_de_alcance.order_by("pk")]
    return {"reglas": reglas, "cuils": cuils} if (reglas or cuils) else {}


def guardar_alcance(persona, alcance):
    """Reemplaza el alcance de una persona por `alcance` (ya normalizado). Es el único lugar que lo escribe."""
    from clients.models import AlcancePersona, AlcanceRegla

    persona.reglas_de_alcance.all().delete()
    persona.personas_de_alcance.all().delete()
    AlcanceRegla.objects.bulk_create(AlcanceRegla(persona=persona, **r) for r in alcance.get("reglas", []))
    AlcancePersona.objects.bulk_create(AlcancePersona(persona=persona, cuil=c) for c in alcance.get("cuils", []))


def contexto_del_editor_de_alcance(implementacion):
    """Lo que necesita la pantalla para dibujar el editor: nombres de los campos, valores de la nómina y la
    nómina resumida. Con la segmentación fija en «sin segmentar», el editor no se muestra."""
    return {
        "editable": implementacion.segmentacion_editable,
        "campos": CAMPOS,
        "opciones": opciones_de_la_nomina(implementacion),
        "empleados": empleados_para_el_editor(implementacion),
    }
