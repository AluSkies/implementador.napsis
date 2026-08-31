from django import template

register = template.Library()


@register.filter
def formato_snapshot(datos):
    """Convierte un snapshot de ImplementacionVersion.datos (dict o list, con formas
    distintas según la sección) en un texto legible para el historial de cambios."""
    if isinstance(datos, list):
        if not datos:
            return "(vacío)"
        filas = [
            ", ".join(f"{k}: {v}" for k, v in item.items() if v not in (None, "", False))
            for item in datos
        ]
        return " | ".join(filas)

    if isinstance(datos, dict):
        partes = []
        for clave, valor in datos.items():
            if isinstance(valor, dict):
                activos = [nombre for nombre, activo in valor.items() if activo]
                partes.append(f"{clave}: {', '.join(activos) if activos else '(ninguna)'}")
            elif isinstance(valor, bool):
                if valor:
                    partes.append(clave)
            elif valor not in (None, ""):
                partes.append(f"{clave}: {valor}")
        return ", ".join(partes) if partes else "(vacío)"

    return str(datos)
