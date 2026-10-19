"""El control de faltantes: la única fuente de «qué falta para enviar» y «qué falta para validar».

Lo usan el wizard (paso de revisión), la ficha del panel y la acción de validar."""

from clients.models import (
    Modulo,
    PersonaRol,
    UbicacionFirma,
)
from employees.services import normalizar_cuil
from onboarding.services.pasos import (
    PASO_CONFIGURACION,
    PASO_DATOS,
    PASO_FIRMA,
    PASO_MODULOS,
    PASO_NOMINA,
    PASO_ROLES,
    PASO_SUCURSALES,
    pasos_activos,
)


def pendientes_de_envio(implementacion):
    """Lo que todavía falta para poder enviar el relevamiento, como lista de
    {"paso": N, "mensaje": ...} (vacía = listo). Los pasos no son secuenciales (el cliente
    puede saltar de uno a otro por la URL), así que esta es la validación que de verdad
    protege el envío; cada paso valida además lo suyo para avisar a tiempo."""
    activos = pasos_activos(implementacion)
    pendientes = []

    cliente = implementacion.cliente
    if not (cliente.razon_social and cliente.cuits):
        pendientes.append({"paso": PASO_DATOS, "mensaje": "Completar la razón social y el CUIT de la empresa."})

    if not implementacion.usa_modulo(Modulo.RECIBO_DIGITAL):
        pendientes.append({"paso": PASO_MODULOS, "mensaje": "Recibo Digital es obligatorio en toda implementación."})

    if PASO_SUCURSALES in activos and not implementacion.sucursales.exclude(nombre="").exists():
        pendientes.append({"paso": PASO_SUCURSALES, "mensaje": "Cargar al menos una sucursal (el módulo Fichada la necesita)."})

    if PASO_ROLES in activos:
        roles = list(implementacion.roles.exclude(apellido_nombre=""))
        faltan = [nombre for rol, nombre in PersonaRol.ROL_CHOICES if rol not in {r.rol for r in roles}]
        if faltan:
            pendientes.append({
                "paso": PASO_ROLES,
                "mensaje": "Cargar al menos una persona para cada rol. Falta: " + ", ".join(faltan) + ".",
            })
        cuils_nomina = set(implementacion.empleados.values_list("cuil", flat=True))
        for rol in roles:
            if rol.rol in PersonaRol.ROLES_EN_NOMINA and normalizar_cuil(rol.cuil) not in cuils_nomina:
                pendientes.append({
                    "paso": PASO_ROLES,
                    "mensaje": f"{rol.apellido_nombre} ({rol.get_rol_display()}) no figura en la nómina: "
                               "cargalo como empleado o corregí su CUIL.",
                })

    if PASO_CONFIGURACION in activos and not implementacion.modelo_recibo:
        pendientes.append({"paso": PASO_CONFIGURACION, "mensaje": "Subir el modelo de recibo (PDF)."})

    if PASO_CONFIGURACION in activos and not implementacion.liquidaciones.filter(activo=True).exists():
        pendientes.append({
            "paso": PASO_CONFIGURACION, "mensaje": "Elegir al menos un tipo de liquidación.",
        })

    if PASO_FIRMA in activos:
        firma = implementacion.firma
        if firma is None or not firma.imagen:
            pendientes.append({
                "paso": PASO_FIRMA, "mensaje": "Subir la imagen de la firma y ubicarla sobre el recibo.",
            })
        elif firma.estado == UbicacionFirma.ESTADO_OBSERVADA:
            pendientes.append({
                "paso": PASO_FIRMA, "mensaje": "Ajustar la firma según lo que pidió el equipo de Napsis.",
            })

    if not implementacion.empleados.exists():
        pendientes.append({"paso": PASO_NOMINA, "mensaje": "Cargar la nómina de empleados (al menos una persona)."})
    elif implementacion.usa_modulo(Modulo.RECIBO_DIGITAL):
        sin_ingreso = implementacion.empleados.filter(fecha_ingreso__isnull=True).count()
        if sin_ingreso:
            pendientes.append({
                "paso": PASO_NOMINA,
                "mensaje": f"Completar la fecha de ingreso de {sin_ingreso} empleado{'s' if sin_ingreso != 1 else ''} "
                           "(es obligatoria para Recibo Digital).",
            })

    return sorted(pendientes, key=lambda p: p["paso"])


def pendientes_de_validacion(implementacion):
    """Los textos de lo que le impide al equipo validar la documentación: lo mismo que impide el envío
    más que la firma tiene que estar validada. Es lo que se le muestra en la ficha antes de validar."""
    mensajes = [p["mensaje"] for p in pendientes_de_envio(implementacion)]
    firma = implementacion.firma
    if (
        implementacion.usa_modulo(Modulo.RECIBO_DIGITAL) and firma is not None and firma.imagen
        and firma.estado == UbicacionFirma.ESTADO_PROPUESTA
    ):
        mensajes.append("Falta validar la firma del recibo.")
    return mensajes
