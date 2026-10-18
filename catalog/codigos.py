"""Códigos estables de los catálogos.

El **nombre** de un módulo, una licencia, una novedad o un tipo de documento se puede corregir en el
admin; el **código** no cambia nunca. Todo lo que dependa de "cuál es" (los pasos del wizard según el
módulo, el mapeo a un sistema externo) se identifica por código, no por un texto editable.
"""

import re
import unicodedata

from django.db import models


def codigo_desde_nombre(nombre):
    """"Recibo Digital" -> "recibo_digital" (sin tildes, minúsculas, guiones bajos)."""
    texto = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")[:80] or "item"


class ConCodigo(models.Model):
    """Mezcla para los modelos de catálogo: agrega `codigo` (único e inmutable una vez creado)."""

    codigo = models.SlugField(
        "Código", max_length=80, unique=True, null=True, blank=True,
        help_text="Identificador estable. Se genera solo a partir del nombre y no se puede cambiar después.",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.codigo and self.nombre and self._codigo_aplica():
            self.codigo = self._codigo_libre(codigo_desde_nombre(self.nombre))
        super().save(*args, **kwargs)

    def _codigo_aplica(self):
        """Los tipos 'Otros' que agrega un cliente no llevan código (no son parte del catálogo)."""
        return True

    def _codigo_libre(self, base):
        candidato, n = base, 1
        existentes = type(self)._default_manager.exclude(pk=self.pk)
        while existentes.filter(codigo=candidato).exists():
            n += 1
            candidato = f"{base}_{n}"
        return candidato


class AdminConCodigo:
    """Para los ModelAdmin: el código se ve, pero no se edita una vez creado el registro."""

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        return base + ["codigo"] if obj else base
