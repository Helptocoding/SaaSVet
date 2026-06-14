"""
imports/parsers.py — Lectura de CSV y XLSX a (columns, rows).

Interfaz única: parse_file(uploaded_file) -> (columns: list[str], rows: list[list[str]]).
Selección por extensión/content-type. Toda celda se devuelve como str ya
recortado ('' si vacía). Filas completamente vacías se descartan.

Caps duros (sin workers — un archivo grande NO debe bloquear el worker gunicorn):
    MAX_FILE_BYTES = 5 MB · MAX_ROWS = 2000 · MAX_COLUMNS = 50.
Excederlos ⇒ ImportParseError con mensaje accionable (no truncado silencioso).
"""
import csv
import datetime
import io

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
MAX_COLUMNS = 50


class ImportParseError(Exception):
    """Error de parseo legible para el usuario (se mapea a 400)."""


def _cell_to_str(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'sí' if value else 'no'
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.date().isoformat() if isinstance(value, datetime.datetime) else value.isoformat()
    if isinstance(value, float):
        # Excel guarda enteros como float (8112345678.0). Evitar el ".0" que
        # rompería teléfonos / nº de expediente.
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value).strip()


def _finalize(columns, raw_rows):
    """Normaliza ancho, descarta filas vacías, aplica caps."""
    columns = [c.strip() for c in columns]
    if not columns or all(c == '' for c in columns):
        raise ImportParseError("El archivo no tiene encabezados de columna.")
    if len(columns) > MAX_COLUMNS:
        raise ImportParseError(
            f"El archivo tiene demasiadas columnas ({len(columns)}). "
            f"Máximo {MAX_COLUMNS}."
        )

    width = len(columns)
    rows = []
    for raw in raw_rows:
        cells = [_cell_to_str(v) for v in raw]
        # Alinear ancho a las columnas (pad/truncate).
        if len(cells) < width:
            cells += [''] * (width - len(cells))
        elif len(cells) > width:
            cells = cells[:width]
        if any(c != '' for c in cells):  # descartar filas 100% vacías
            rows.append(cells)
        if len(rows) > MAX_ROWS:
            raise ImportParseError(
                f"El archivo supera el máximo de {MAX_ROWS} filas. "
                "Divídelo en partes más pequeñas."
            )
    if not rows:
        raise ImportParseError("El archivo no tiene filas de datos.")
    return columns, rows


def _parse_csv(data: bytes):
    # Encoding: utf-8 con BOM primero (Excel exporta así), fallback latin-1
    # (común en sistemas viejos mexicanos). latin-1 nunca falla → último recurso.
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportParseError("No se pudo leer la codificación del archivo CSV.")

    # Separador: Excel es-MX exporta con ';'. Detectar con Sniffer, fallback por
    # conteo en la primera línea.
    sample = text[:4096]
    delimiter = ','
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter
    except csv.Error:
        if sample.count(';') > sample.count(','):
            delimiter = ';'

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = [row for row in reader]
    if not all_rows:
        raise ImportParseError("El archivo CSV está vacío.")
    return _finalize(all_rows[0], all_rows[1:])


def _parse_xlsx(data: bytes):
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover
        raise ImportParseError("Soporte de Excel no disponible (falta openpyxl).")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportParseError("No se pudo abrir el archivo de Excel (¿corrupto?).")
    ws = wb.active
    if ws is None:
        raise ImportParseError("El archivo de Excel no tiene hojas.")

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        raise ImportParseError("El archivo de Excel está vacío.")
    columns = [_cell_to_str(c) for c in header]
    raw_rows = list(rows_iter)
    wb.close()
    return _finalize(columns, raw_rows)


def parse_file(uploaded_file):
    """Punto de entrada. uploaded_file = DRF/Django UploadedFile.

    Devuelve (columns, rows). Lanza ImportParseError en cualquier fallo legible.
    """
    size = getattr(uploaded_file, 'size', None)
    if size is not None and size > MAX_FILE_BYTES:
        raise ImportParseError(
            f"El archivo pesa demasiado ({size // 1024} KB). "
            f"Máximo {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    name = (getattr(uploaded_file, 'name', '') or '').lower()
    data = uploaded_file.read()
    if not data:
        raise ImportParseError("El archivo está vacío.")
    # Doble cinturón: algunos backends de upload no reportan .size.
    if len(data) > MAX_FILE_BYTES:
        raise ImportParseError(
            f"El archivo pesa demasiado. Máximo {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    if name.endswith('.csv') or name.endswith('.txt'):
        return _parse_csv(data)
    if name.endswith('.xlsx'):
        return _parse_xlsx(data)
    # Sin extensión reconocible: intentar XLSX (firma ZIP) y caer a CSV.
    if data[:2] == b'PK':
        return _parse_xlsx(data)
    return _parse_csv(data)
