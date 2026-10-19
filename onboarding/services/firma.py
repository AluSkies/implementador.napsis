"""La firma del recibo: guardado de la intención del cliente y contexto del editor."""

import hashlib

from django.utils import timezone

from automatizacion import actores, eventos
from clients.models import UbicacionFirma
from clients.services import cambio_de_seccion
from onboarding.forms import FirmaForm


def guardar_firma(implementacion, actor, *, pagina, geometria, imagen=None):
    """Guarda la intención del cliente sobre su firma: página, recuadros y (si se sube una) la imagen.

    - La imagen anterior no se borra: queda en el disco y el evento `archivo.reemplazado` apunta a las dos.
    - Si guarda el cliente, la firma queda «propuesta» cuando algo cambió (o si estaba observada: es
      su respuesta). Si guarda el equipo, es una corrección posterior al envío y queda validada.
    """
    del_cliente = actor.tipo == actores.CLIENTE
    accion = "firma.propuesta" if del_cliente else "firma.corregida_por_implementador"
    with cambio_de_seccion(implementacion, "firma", actor, accion=accion):
        firma = implementacion.firmas.filter(tipo_liquidacion__isnull=True).first() or UbicacionFirma(
            implementacion=implementacion,
        )
        anterior = {"ruta": firma.imagen.name, "sha256": firma.imagen_sha256} if firma.imagen else None
        cambio = firma.pk is None or firma.pagina != pagina or firma.geometria != geometria or imagen is not None
        firma.pagina = pagina
        firma.geometria = geometria
        if imagen is not None:
            hash_imagen = hashlib.sha256()
            for trozo in imagen.chunks():
                hash_imagen.update(trozo)
            imagen.seek(0)
            firma.imagen.save(imagen.name, imagen, save=False)
            firma.imagen_sha256 = hash_imagen.hexdigest()
        if del_cliente:
            if cambio or firma.estado == UbicacionFirma.ESTADO_OBSERVADA:
                firma.estado = UbicacionFirma.ESTADO_PROPUESTA
                firma.motivos, firma.comentario = [], ""
                firma.validada_por, firma.validada_en = "", None
            firma.propuesta_por = firma.propuesta_por or actor.etiqueta
        else:
            firma.estado = UbicacionFirma.ESTADO_VALIDADA
            firma.motivos, firma.comentario = [], ""
            firma.validada_por, firma.validada_en = actor.etiqueta, timezone.now()
        firma.save()
        if imagen is not None and anterior:
            eventos.registrar(actor, "archivo.reemplazado", implementacion, seccion="firma", datos={
                "campo": "imagen_firma", "anterior": anterior,
                "nuevo": {"ruta": firma.imagen.name, "sha256": firma.imagen_sha256},
            })
    return firma


def contexto_del_editor_de_firma(implementacion, firma, form=None):
    """Lo que necesita el editor de firma (el del cliente, el de la ficha del panel y el de solo lectura)."""
    return {
        "form": form or FirmaForm(firma=firma),
        "form_lectura": FirmaForm(firma=firma, auto_id="lectura_%s"),
        "firma": firma,
        "modelo_url": implementacion.modelo_recibo.url if implementacion.modelo_recibo else "",
        "imagen_url": firma.imagen.url if firma and firma.imagen else "",
    }
