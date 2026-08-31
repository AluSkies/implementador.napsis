from django.conf import settings
from django.core.exceptions import ValidationError


def validar_tamanio_archivo(archivo):
    if archivo.size > settings.MAX_UPLOAD_SIZE_BYTES:
        limite_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f"El archivo no puede pesar más de {limite_mb}MB.")
