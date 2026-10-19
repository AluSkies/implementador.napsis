"""Los pasos del wizard: cuáles son, cómo se llaman y cuáles le corresponden a cada implementación.

Los números de paso se definen una sola vez, acá. Las observaciones de una devolución se guardan con
el código estable de cada paso (no con su número), así no se pierden si el orden cambia."""

from clients.models import Modulo

TOTAL_PASOS = 10

# Orden del wizard. La nómina va antes que los roles (para poder elegir de ahí a las personas
# con rol) y las sucursales antes que la nómina (para poder asignar a cada empleado la suya).
(
    PASO_DATOS, PASO_MODULOS, PASO_SUCURSALES, PASO_NOMINA, PASO_ROLES,
    PASO_CONFIGURACION, PASO_FIRMA, PASO_LICENCIAS, PASO_DOCUMENTOS, PASO_REVISION,
) = range(1, TOTAL_PASOS + 1)

TITULOS_PASO = {
    PASO_DATOS: "Datos de contacto",
    PASO_MODULOS: "Módulos contratados",
    PASO_SUCURSALES: "Sucursales",
    PASO_NOMINA: "Carga de empleados",
    PASO_ROLES: "Apoderado/s, Liquidador y Admin. de RRHH",
    PASO_CONFIGURACION: "Configuración y adjuntos",
    PASO_FIRMA: "Firma del recibo",
    PASO_LICENCIAS: "Licencias y Novedades",
    PASO_DOCUMENTOS: "Documentos de Legajo Digital",
    PASO_REVISION: "Revisión y envío",
}

# Código estable de cada paso: las observaciones de una devolución se guardan con él, así que no se
# pierden aunque cambie el número de orden de los pasos.
CODIGO_DE_PASO = {
    PASO_DATOS: "datos", PASO_MODULOS: "modulos", PASO_SUCURSALES: "sucursales", PASO_NOMINA: "nomina",
    PASO_ROLES: "roles", PASO_CONFIGURACION: "configuracion", PASO_FIRMA: "firma", PASO_LICENCIAS: "licencias",
    PASO_DOCUMENTOS: "documentos", PASO_REVISION: "revision",
}

# Pasos que solo aplican si el cliente contrató alguno de estos módulos.
# Los pasos que no aparecen acá (datos, módulos, nómina y revisión) son universales.
PASO_REQUIERE_MODULO = {
    PASO_SUCURSALES: {Modulo.FICHADA},                          # Sucursales (fichada por ubicación)
    PASO_ROLES: {Modulo.RECIBO_DIGITAL, Modulo.LEGAJOS},        # Apoderado/Liquidador (recibos) o Admin RRHH (legajo)
    PASO_CONFIGURACION: {Modulo.RECIBO_DIGITAL},                # Configuración y adjuntos del recibo
    PASO_FIRMA: {Modulo.RECIBO_DIGITAL},                        # Dónde va la firma sobre el recibo
    PASO_LICENCIAS: {Modulo.NOVEDADES},                         # Licencias y Novedades
    PASO_DOCUMENTOS: {Modulo.LEGAJOS},                          # Documentos de Legajo Digital
}


def pasos_activos(implementacion):
    """Devuelve la lista ordenada de pasos que le corresponde completar a esta
    implementación puntual, según los módulos que contrató."""
    modulos_activos = set(
        implementacion.modulos.filter(activo=True).values_list("modulo__codigo", flat=True)
    )
    activos = []
    for paso in range(1, TOTAL_PASOS + 1):
        requeridos = PASO_REQUIERE_MODULO.get(paso)
        if requeridos is None or requeridos & modulos_activos:
            activos.append(paso)
    return activos
