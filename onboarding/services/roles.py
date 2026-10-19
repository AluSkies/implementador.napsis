"""Roles de la implementación (Apoderado, Liquidador, Admin. de RRHH) y su vínculo con la nómina."""

from clients.models import PersonaRol
from clients.services import cambio_de_seccion
from employees.services import normalizar_cuil


def vincular_roles_con_nomina(implementacion):
    """Liga cada persona con rol a su empleado de la nómina (por CUIL). Se llama cuando cambian los
    roles o la nómina. Si el empleado se borra, el vínculo queda vacío solo."""
    por_cuil = {e.cuil: e for e in implementacion.empleados.all()}
    for rol in implementacion.roles.all():
        empleado = por_cuil.get(normalizar_cuil(rol.cuil)) if rol.cuil else None
        if (empleado.pk if empleado else None) != rol.empleado_id:
            rol.empleado = empleado
            rol.save(update_fields=["empleado"])


def guardar_roles(implementacion, formset, actor):
    with cambio_de_seccion(implementacion, "roles", actor):
        implementacion.roles.all().delete()
        nuevos = []
        for form in formset:
            if form.cleaned_data.get("DELETE"):
                continue
            nombre = form.cleaned_data.get("apellido_nombre")
            if not nombre:
                continue
            nuevos.append(
                PersonaRol(
                    implementacion=implementacion,
                    rol=form.cleaned_data["rol"],
                    apellido_nombre=nombre,
                    cuil=form.cleaned_data.get("cuil", ""),
                    mail=form.cleaned_data.get("mail", ""),
                )
            )
        PersonaRol.objects.bulk_create(nuevos)
        vincular_roles_con_nomina(implementacion)
