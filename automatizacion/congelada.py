"""La configuración congelada: la foto de todo lo que el equipo aprobó para configurar.

Al ejecutar «Validar documentación» se arma, de una sola vez, lo que va a leer quien configure (hoy una
persona, más adelante un agente): los datos **estructurados y con códigos estables** (no nombres que se
puedan corregir), más una **copia inmutable de los archivos** (modelo de recibo, logo, banner y firma) con
su `sha256`. Si después el equipo cambia algo, la validación se pierde y una nueva aprobación crea la
versión siguiente: las anteriores quedan como historia.

El contenido es un esquema propio y versionado (`VERSION_ESQUEMA`), distinto del historial que se le
muestra a las personas. No incluye la nómina (son datos personales que la base ya conserva): solo cuántos
empleados hay; el archivo de la nómina para Napsis se suma cuando exista (RF-07).
"""

import hashlib
import json
import os

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .models import ConfiguracionCongelada

VERSION_ESQUEMA = 1


class ArchivoNoDisponible(Exception):
    """Un archivo que forma parte de la configuración no se pudo leer del almacenamiento."""

    def __init__(self, campo):
        super().__init__(campo)
        self.campo = campo


def _codigo(item):
    """Identificador estable de un ítem de catálogo (si todavía no tuviera código, su nombre)."""
    return item.codigo or f"nombre:{item.nombre}"


def _cuits(texto):
    return [cuit.strip() for cuit in (texto or "").split(",") if cuit.strip()]


def _documentos(implementacion):
    documentos = []
    for activo in implementacion.documentos_legajo.filter(activo=True).select_related("tipo_documento"):
        tipo = activo.tipo_documento
        if tipo.es_custom:
            # Los tipos «Otros» no son del catálogo: no hay código global, así que van con su definición.
            documentos.append({
                "codigo": None, "personalizado": True, "nombre": tipo.nombre,
                "campos": [
                    {"nombre": campo.nombre, "obligatorio": campo.obligatorio}
                    for campo in tipo.campos.order_by("orden", "nombre")
                ],
            })
        else:
            documentos.append({"codigo": _codigo(tipo), "personalizado": False})
    return sorted(documentos, key=lambda d: (d["codigo"] or "~", d.get("nombre", "")))


def contenido_de(implementacion):
    """Lo que se aprobó, como estructura JSON con códigos estables. Todo va ordenado para que el mismo
    contenido dé siempre el mismo hash."""
    cliente = implementacion.cliente
    firma = implementacion.firma
    empleados = implementacion.empleados
    return {
        "esquema": VERSION_ESQUEMA,
        "implementacion": {
            "uuid": str(implementacion.uuid), "origen": implementacion.origen, "id_externo": implementacion.id_externo,
        },
        "empresa": {
            "razon_social": cliente.razon_social, "cuits": _cuits(cliente.cuits),
            "telefono": implementacion.telefono, "mail_contacto": implementacion.mail_contacto,
        },
        "fecha_salida_productivo": (
            implementacion.fecha_salida_productivo.isoformat() if implementacion.fecha_salida_productivo else None
        ),
        "condiciones": {
            "tipo_firma": implementacion.tipo_firma, "nomenclatura_pdf": implementacion.nomenclatura_pdf,
            "segmentacion_liquidador": implementacion.segmentacion_liquidador,
            "liquidador_utilizado": implementacion.liquidador_utilizado,
            "cantidad_capitas": implementacion.cantidad_capitas, "max_roles": implementacion.max_roles,
        },
        "modulos": sorted(
            _codigo(m.modulo) for m in implementacion.modulos.filter(activo=True).select_related("modulo")
        ),
        "liquidaciones": sorted(
            _codigo(l.tipo_liquidacion)
            for l in implementacion.liquidaciones.filter(activo=True).select_related("tipo_liquidacion")
        ),
        "firma": None if firma is None else {
            "pagina": firma.pagina, "geometria": firma.geometria, "estado": firma.estado,
        },
        "roles": sorted(
            ({"rol": r.rol, "apellido_nombre": r.apellido_nombre, "cuil": r.cuil, "mail": r.mail}
             for r in implementacion.roles.all()),
            key=lambda r: (r["rol"], r["cuil"], r["apellido_nombre"]),
        ),
        "sucursales": sorted(
            ({"nombre": s.nombre, "calle": s.calle, "altura": s.altura, "piso_depto": s.piso_depto,
              "codigo_postal": s.codigo_postal, "localidad": s.localidad, "entre_calles": s.entre_calles,
              "observaciones": s.observaciones}
             for s in implementacion.sucursales.all()),
            key=lambda s: (s["nombre"], s["calle"], s["altura"]),
        ),
        "licencias": sorted(
            _codigo(l.tipo_licencia) for l in implementacion.licencias.filter(activo=True).select_related("tipo_licencia")
        ),
        "novedades": sorted(
            _codigo(n.tipo_novedad) for n in implementacion.novedades.filter(activo=True).select_related("tipo_novedad")
        ),
        "documentos": _documentos(implementacion),
        "nomina": {
            "empleados": empleados.count(),
            "con_fecha_ingreso": empleados.filter(fecha_ingreso__isnull=False).count(),
        },
    }


def _archivos_de(implementacion):
    """Los archivos que forman parte de la configuración: [(campo, FieldFile)]."""
    firma = implementacion.firma
    candidatos = [
        ("modelo_recibo", implementacion.modelo_recibo), ("logo", implementacion.logo),
        ("banner", implementacion.banner), ("firma_imagen", firma.imagen if firma else None),
    ]
    return [(campo, archivo) for campo, archivo in candidatos if archivo]


def _copiar_archivos(implementacion, version):
    copias = []
    for campo, archivo in _archivos_de(implementacion):
        try:
            with archivo.storage.open(archivo.name, "rb") as origen:
                datos = origen.read()
        except (FileNotFoundError, OSError):
            raise ArchivoNoDisponible(campo) from None
        extension = os.path.splitext(archivo.name)[1].lower()
        ruta = default_storage.save(
            f"congeladas/{implementacion.uuid}/v{version}/{campo}{extension}", ContentFile(datos),
        )
        copias.append({
            "campo": campo, "ruta": ruta, "sha256": hashlib.sha256(datos).hexdigest(), "bytes": len(datos),
            "nombre_original": os.path.basename(archivo.name),
        })
    return copias


def hash_de(contenido, archivos):
    """Huella de la configuración: el contenido y el `sha256` de cada archivo (no sus rutas)."""
    base = {"contenido": contenido, "archivos": sorted((a["campo"], a["sha256"]) for a in archivos)}
    texto = json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def congelar(implementacion, actor):
    """Crea la versión siguiente de la configuración congelada (llamar dentro de la transacción de la
    aprobación). Levanta `ArchivoNoDisponible` si un archivo no se puede leer."""
    ultima = implementacion.congeladas.order_by("-version").first()
    version = (ultima.version if ultima else 0) + 1
    contenido = contenido_de(implementacion)
    archivos = _copiar_archivos(implementacion, version)
    return ConfiguracionCongelada.objects.create(
        implementacion=implementacion, implementacion_uuid=implementacion.uuid, version=version,
        version_esquema=VERSION_ESQUEMA, contenido=contenido, archivos=archivos,
        hash=hash_de(contenido, archivos), creada_por=actor.etiqueta,
    )


def como_documento(congelada):
    """La configuración como un único JSON descargable (con sus metadatos)."""
    return {
        "version": congelada.version, "version_esquema": congelada.version_esquema, "hash": congelada.hash,
        "creada_por": congelada.creada_por, "creada_en": congelada.creada_en.isoformat(),
        "contenido": congelada.contenido, "archivos": congelada.archivos,
    }
