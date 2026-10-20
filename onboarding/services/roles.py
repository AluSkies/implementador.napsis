"""Roles de la implementación (Apoderado, Liquidador, Admin. de RRHH) y su vínculo con la nómina."""

from clients.alcance import alcance_de, guardar_alcance
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
    """Deja los roles como vienen en el formulario. Una persona que sigue (mismo rol y CUIL) se
    actualiza en el lugar, sin recrearse: conserva su identidad y su alcance si no se tocó."""
    with cambio_de_seccion(implementacion, "roles", actor):
        sin_usar = list(implementacion.roles.all())
        for form in formset:
            datos = form.cleaned_data
            if datos.get("DELETE") or not datos.get("apellido_nombre"):
                continue
            cuil = datos.get("cuil", "")
            existente = next((r for r in sin_usar if cuil and r.rol == datos["rol"] and r.cuil == cuil), None)
            if existente:
                sin_usar.remove(existente)
            persona = existente or PersonaRol(implementacion=implementacion)
            persona.rol, persona.apellido_nombre, persona.cuil = datos["rol"], datos["apellido_nombre"], cuil
            persona.mail = datos.get("mail", "")
            persona.save()
            # El alcance es solo del liquidador, y solo se arma si el equipo no lo dejó en «ve todo».
            alcance = datos.get("alcance") or {}
            if persona.rol != PersonaRol.ROL_LIQUIDADOR or not implementacion.segmentacion_editable:
                alcance = {}
            # Si el formulario no trajo el campo (un cliente viejo, un script), no se toca lo guardado.
            if form.add_prefix("alcance") in form.data and alcance_de(persona) != alcance:
                guardar_alcance(persona, alcance)
        for r in sin_usar:
            r.delete()
        vincular_roles_con_nomina(implementacion)
