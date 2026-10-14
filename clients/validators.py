from django.conf import settings
from django.core.exceptions import ValidationError


def validar_tamanio_archivo(archivo):
    if archivo.size > settings.MAX_UPLOAD_SIZE_BYTES:
        limite_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f"El archivo no puede pesar más de {limite_mb}MB.")


def _digito_verificador(base):
    """Verificador (módulo 11) de los primeros 10 dígitos; 10 significa 'no representable'."""
    suma = sum(int(d) * p for d, p in zip(base, [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]))
    verificador = 11 - suma % 11
    return 0 if verificador == 11 else verificador


def _cuit_valido(digitos):
    """11 dígitos con el verificador correcto, igual que AFIP.

    Caso especial: cuando el verificador da 10 no se puede escribir en un dígito, así que el
    CUIT se emite con prefijo 23 y verificador 9 (si habría sido 20) o 4 (si habría sido 27).
    """
    if len(digitos) != 11 or not digitos.isdigit():
        return False
    if digitos[:2] == "23":
        return any(
            digitos[10] == final and _digito_verificador(prefijo + digitos[2:10]) == 10
            for prefijo, final in (("20", "9"), ("27", "4"))
        )
    return _digito_verificador(digitos[:10]) == int(digitos[10])


def normalizar_cuits(valor):
    """Valida uno o varios CUIT separados por coma (con o sin guiones) y los devuelve
    formateados como NN-NNNNNNNN-N, separados por coma. Lanza ValidationError si alguno
    es inválido, indicando cuál (un CUIT mal tipeado es justo lo que hay que atajar)."""
    resultado = []
    for crudo in valor.replace(";", ",").split(","):
        crudo = crudo.strip()
        if not crudo:
            continue
        digitos = "".join(c for c in crudo if c.isdigit())
        if not _cuit_valido(digitos):
            raise ValidationError(f"El CUIT {crudo!r} no es válido: revisá los 11 dígitos.")
        resultado.append(f"{digitos[:2]}-{digitos[2:10]}-{digitos[10]}")
    return ", ".join(resultado)
