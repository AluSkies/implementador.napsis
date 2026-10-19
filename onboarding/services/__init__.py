"""Servicios de guardado y control de las implementaciones.

Es un paquete de módulos chicos, cada uno con una responsabilidad:

- `pasos`: los pasos del wizard y cuáles aplican a cada implementación.
- `fechas`: fecha de implementación y días hábiles.
- `faltantes`: el control único de qué falta para enviar y para validar.
- `secciones`: guardado de las secciones simples (datos, módulos, sucursales, licencias, …).
- `roles`: roles y su vínculo con la nómina.
- `firma`: la ubicación de la firma del recibo.
- `nomina`: importación y alta, edición y baja de empleados.

Los módulos se importan entre sí directamente (nunca a través de este `__init__`), así no hay ciclos.
Acá se re-exportan los nombres públicos para que el resto del código (vistas, acciones, panel) use
`from onboarding import services` y llame `services.guardar_roles(...)`: esta es la puerta de entrada
documentada del paquete."""

from onboarding.services.faltantes import (
    pendientes_de_envio,
    pendientes_de_validacion,
)
from onboarding.services.fechas import (
    DIAS_HABILES_MINIMOS_CLIENTE,
    fecha_minima_para_cliente,
    sumar_dias_habiles,
)
from onboarding.services.firma import (
    contexto_del_editor_de_firma,
    guardar_firma,
)
from onboarding.services.nomina import (
    CAMPOS_EMPLEADO_IMPORTADOS,
    LOTE_ACTUALIZACION,
    MAX_CORRECCIONES_EN_EVENTO,
    MAX_ERRORES_EN_EVENTO,
    agregar_empleado,
    editar_empleado,
    eliminar_empleado,
    importar_archivo_empleados,
    resumen_importacion,
)
from onboarding.services.pasos import (
    CODIGO_DE_PASO,
    PASO_CONFIGURACION,
    PASO_DATOS,
    PASO_DOCUMENTOS,
    PASO_FIRMA,
    PASO_LICENCIAS,
    PASO_MODULOS,
    PASO_NOMINA,
    PASO_REQUIERE_MODULO,
    PASO_REVISION,
    PASO_ROLES,
    PASO_SUCURSALES,
    TITULOS_PASO,
    TOTAL_PASOS,
    pasos_activos,
)
from onboarding.services.roles import (
    guardar_roles,
    vincular_roles_con_nomina,
)
from onboarding.services.secciones import (
    estado_actual_documentos,
    estado_actual_licencias,
    estado_actual_novedades,
    guardar_condiciones,
    guardar_datos_contacto,
    guardar_documentos,
    guardar_fecha_implementacion,
    guardar_licencias_y_novedades,
    guardar_liquidaciones,
    guardar_modulos,
    guardar_sucursales,
    tipos_documento_disponibles,
)

__all__ = [
    "CAMPOS_EMPLEADO_IMPORTADOS",
    "CODIGO_DE_PASO",
    "DIAS_HABILES_MINIMOS_CLIENTE",
    "LOTE_ACTUALIZACION",
    "MAX_CORRECCIONES_EN_EVENTO",
    "MAX_ERRORES_EN_EVENTO",
    "PASO_CONFIGURACION",
    "PASO_DATOS",
    "PASO_DOCUMENTOS",
    "PASO_FIRMA",
    "PASO_LICENCIAS",
    "PASO_MODULOS",
    "PASO_NOMINA",
    "PASO_REQUIERE_MODULO",
    "PASO_REVISION",
    "PASO_ROLES",
    "PASO_SUCURSALES",
    "TITULOS_PASO",
    "TOTAL_PASOS",
    "agregar_empleado",
    "contexto_del_editor_de_firma",
    "editar_empleado",
    "eliminar_empleado",
    "estado_actual_documentos",
    "estado_actual_licencias",
    "estado_actual_novedades",
    "fecha_minima_para_cliente",
    "guardar_condiciones",
    "guardar_datos_contacto",
    "guardar_documentos",
    "guardar_fecha_implementacion",
    "guardar_firma",
    "guardar_licencias_y_novedades",
    "guardar_liquidaciones",
    "guardar_modulos",
    "guardar_roles",
    "guardar_sucursales",
    "importar_archivo_empleados",
    "pasos_activos",
    "pendientes_de_envio",
    "pendientes_de_validacion",
    "resumen_importacion",
    "sumar_dias_habiles",
    "tipos_documento_disponibles",
    "vincular_roles_con_nomina",
]
