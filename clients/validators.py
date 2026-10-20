from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions


def validar_tamanio_archivo(archivo):
    if archivo.size > settings.MAX_UPLOAD_SIZE_BYTES:
        limite_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f"El archivo no puede pesar más de {limite_mb}MB.")


# Medidas que acepta el wizard de Napsis: fuera de rango rechaza la imagen y el paso se traba.
LOGO_MAX = (200, 200)
BANNER_MIN = (1500, 200)
BANNER_MAX = (1600, 400)


def _medidas(imagen):
    ancho, alto = get_image_dimensions(imagen)
    if hasattr(imagen, "seek"):
        imagen.seek(0)
    return ancho, alto


def validar_medidas_logo(imagen):
    """El logo puede medir hasta 200 × 200 px."""
    ancho, alto = _medidas(imagen)
    if ancho is None:
        return  # no se pudo leer: ya lo rechaza el campo de imagen
    if ancho > LOGO_MAX[0] or alto > LOGO_MAX[1]:
        raise ValidationError(
            f"El logo puede medir como máximo {LOGO_MAX[0]} × {LOGO_MAX[1]} px y el tuyo mide {ancho} × {alto} px. "
            "Achicalo y volvé a subirlo."
        )


def validar_medidas_banner(imagen):
    """El banner tiene que medir entre 1500 × 200 px y 1600 × 400 px."""
    ancho, alto = _medidas(imagen)
    if ancho is None:
        return
    if not (BANNER_MIN[0] <= ancho <= BANNER_MAX[0] and BANNER_MIN[1] <= alto <= BANNER_MAX[1]):
        raise ValidationError(
            f"El banner tiene que medir entre {BANNER_MIN[0]} × {BANNER_MIN[1]} y {BANNER_MAX[0]} × {BANNER_MAX[1]} px "
            f"y el tuyo mide {ancho} × {alto} px. Ajustalo y volvé a subirlo."
        )


def _digito_verificador(base):
    """Verificador (módulo 11) de los primeros 10 dígitos; 10 significa 'no representable'."""
    suma = sum(int(d) * p for d, p in zip(base, [5, 4, 3, 2, 7, 6, 5, 4, 3, 2], strict=True))
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
        if len(digitos) != 11:
            raise ValidationError(
                f"El CUIT {crudo!r} no es válido: tiene {len(digitos)} dígitos y tiene que tener 11."
            )
        if not _cuit_valido(digitos):
            raise ValidationError(
                f"El CUIT {crudo!r} no es válido: tiene 11 dígitos pero el último no corresponde a los anteriores "
                "(dígito verificador). Revisá que no haya un número mal tipeado."
            )
        resultado.append(f"{digitos[:2]}-{digitos[2:10]}-{digitos[10]}")
    return ", ".join(resultado)
