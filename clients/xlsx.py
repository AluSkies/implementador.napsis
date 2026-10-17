"""Utilidades para generar planillas .xlsx."""


def escribir_celda(hoja, fila, columna, valor):
    """Escribe una celda tratando SIEMPRE los textos como texto.

    openpyxl interpreta como fórmula cualquier texto que empiece con "=". Como en las planillas
    que genera el portal hay datos que cargó un cliente (nómina, razón social...), un valor como
    =HYPERLINK(...) se ejecutaría al abrir el archivo en Excel. Forzando el tipo "texto" se ve
    tal cual y no se ejecuta.
    """
    celda = hoja.cell(row=fila, column=columna, value=valor)
    if isinstance(valor, str) and celda.data_type == "f":
        celda.data_type = "s"
    return celda
