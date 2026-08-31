"""Parser/validador de la plantilla masiva de empleados y generador de la plantilla vacía."""

import io
import re
import unicodedata

import openpyxl
import pandas as pd
from django.utils.dateparse import parse_date

# (header visible en la plantilla, campo del modelo Empleado, obligatorio, tipo)
COLUMNAS = [
    ("CUIL", "cuil", True, "texto"),
    ("DNI", "dni", False, "texto"),
    ("Nombre", "nombre", True, "texto"),
    ("Apellido", "apellido", True, "texto"),
    ("Legajo", "legajo", False, "texto"),
    ("Fecha Ingreso (DD/MM/AAAA)", "fecha_ingreso", False, "fecha"),
    ("Mail", "mail", False, "texto"),
    ("Sexo (F/M)", "sexo", False, "sexo"),
    ("Fecha Nacimiento (DD/MM/AAAA)", "fecha_nacimiento", False, "fecha"),
    ("Lugar de Nacimiento", "lugar_nacimiento", False, "texto"),
    ("Nacionalidad", "nacionalidad", False, "texto"),
    ("Estado Civil", "estado_civil", False, "texto"),
    ("Domicilio", "domicilio", False, "texto"),
    ("Planta/Vivienda", "planta_vivienda", False, "texto"),
    ("Codigo Postal", "codigo_postal", False, "texto"),
    ("Localidad", "localidad", False, "texto"),
    ("Telefono", "telefono", False, "texto"),
    ("Obra Social", "obra_social", False, "texto"),
    ("Centro de Costo", "centro_costo", False, "texto"),
    ("Puesto", "puesto", False, "texto"),
    ("Gerencia", "gerencia", False, "texto"),
    ("Sector", "sector", False, "texto"),
    ("Funcion", "funcion", False, "texto"),
    ("Es Supervisor (SI/NO)", "es_supervisor", False, "booleano"),
    ("Home Office (SI/NO)", "home_office", False, "booleano"),
    ("Reporta A (CUIL)", "reporta_a", False, "texto"),
    ("Aprobador (CUIL)", "aprobador", False, "texto"),
]

CUIL_RE = re.compile(r"^\d{11}$")


def normalizar_texto(valor):
    """Mayúsculas, sin espacios de más, sin tildes — mismo criterio usado en la plantilla Mondezza."""
    if valor is None:
        return ""
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", texto)


def normalizar_cuil(valor):
    if valor is None:
        return ""
    return re.sub(r"\D", "", str(valor))


def _armar_hoja_con_headers():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Empleados"
    for col_idx, (header, *_rest) in enumerate(COLUMNAS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = openpyxl.styles.Font(bold=True)
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(18, len(header) + 2)
    return wb, ws


def generar_plantilla_xlsx():
    """Genera un .xlsx vacío con las columnas esperadas, para que el cliente lo descargue y complete."""
    wb, _ws = _armar_hoja_con_headers()
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def generar_nomina_xlsx(empleados):
    """Genera un .xlsx con la nómina ya cargada de una implementación, para que el
    equipo de Napsis la descargue (mismas columnas que la plantilla vacía)."""
    wb, ws = _armar_hoja_con_headers()
    for fila_idx, empleado in enumerate(empleados, start=2):
        for col_idx, (_header, campo, _obligatorio, tipo) in enumerate(COLUMNAS, start=1):
            if campo in ("reporta_a", "aprobador"):
                relacionado = getattr(empleado, campo)
                valor = relacionado.cuil if relacionado else ""
            else:
                valor = getattr(empleado, campo)
                if tipo == "booleano":
                    valor = "SI" if valor else "NO"
                elif tipo == "fecha" and valor:
                    valor = valor.strftime("%d/%m/%Y")
                elif valor is None:
                    valor = ""
            ws.cell(row=fila_idx, column=col_idx, value=valor)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _parse_fecha(valor):
    if valor in (None, ""):
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date()
    texto = str(valor).strip()
    for fmt_sep in ("/", "-"):
        partes = texto.split(fmt_sep)
        if len(partes) == 3 and len(partes[2]) == 4:
            dd, mm, yyyy = partes
            texto = f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
            break
    return parse_date(texto)


def _parse_booleano(valor):
    return normalizar_texto(valor) in ("SI", "SÍ", "TRUE", "1", "X")


def parse_archivo_empleados(django_file):
    """
    Lee un .xlsx/.csv subido por el cliente y devuelve (filas_validas, errores).

    filas_validas: lista de dicts listos para instanciar/actualizar Empleado.
    errores: lista de dicts {fila, mensaje} para las filas rechazadas.
    """
    nombre = django_file.name.lower()
    if nombre.endswith(".csv"):
        df = pd.read_csv(django_file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(django_file, dtype=str, keep_default_na=False)

    columnas_por_header = {header: campo for header, campo, *_ in COLUMNAS}
    tipos_por_campo = {campo: tipo for _header, campo, _req, tipo in COLUMNAS}
    obligatorios = {campo for _header, campo, req, _tipo in COLUMNAS if req}

    # tolerante a variaciones menores de header (mayúsculas/espacios)
    columnas_normalizadas = {normalizar_texto(h): campo for h, campo in columnas_por_header.items()}
    mapeo_reales = {}
    for col in df.columns:
        campo = columnas_normalizadas.get(normalizar_texto(col))
        if campo:
            mapeo_reales[col] = campo
    df = df.rename(columns=mapeo_reales)

    filas_validas = []
    errores = []
    cuils_vistos = set()

    for idx, row in df.iterrows():
        fila_num = idx + 2  # +1 por header, +1 porque idx es 0-based
        datos = {}
        fila_errores = []

        for campo, tipo in tipos_por_campo.items():
            valor_crudo = row.get(campo, "")
            if tipo == "texto":
                datos[campo] = normalizar_texto(valor_crudo) if campo in ("nombre", "apellido") else str(valor_crudo).strip()
            elif tipo == "fecha":
                try:
                    datos[campo] = _parse_fecha(valor_crudo)
                except Exception:
                    datos[campo] = None
                    fila_errores.append(f"Fecha inválida en '{campo}'")
            elif tipo == "booleano":
                datos[campo] = _parse_booleano(valor_crudo)
            elif tipo == "sexo":
                sexo = normalizar_texto(valor_crudo)
                datos[campo] = sexo[:1] if sexo in ("F", "M") else ""

        datos["cuil"] = normalizar_cuil(row.get("cuil", ""))

        for campo in obligatorios:
            if not datos.get(campo):
                fila_errores.append(f"Falta el campo obligatorio '{campo}'")

        if datos.get("cuil") and not CUIL_RE.match(datos["cuil"]):
            fila_errores.append("CUIL inválido: debe tener 11 dígitos")
        elif datos.get("cuil") in cuils_vistos:
            fila_errores.append(f"CUIL duplicado dentro del archivo: {datos['cuil']}")
        elif datos.get("cuil"):
            cuils_vistos.add(datos["cuil"])

        if fila_errores:
            errores.append({"fila": fila_num, "mensaje": "; ".join(fila_errores)})
        else:
            filas_validas.append(datos)

    return filas_validas, errores
