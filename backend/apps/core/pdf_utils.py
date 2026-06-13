"""
PDF rendering helpers compartidos.
"""
import re

# C0 control characters except whitespace (\t \n \r). ReportLab puede romper si
# llegan bytes NUL u otros controles heredados de imports / shell rewrites.
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def safe_pdf_text(value, default=""):
    """
    Strip caracteres de control C0 (excepto \\t \\n \\r) y bytes NUL.
    Defensa adicional sobre sanitize_text — para datos legacy / importados que
    podrían no haber pasado por el saneador del serializer.
    """
    if value is None:
        return default
    s = str(value)
    return _CONTROL_CHARS_RE.sub('', s)


def safe_filename_segment(value, max_length=50):
    """
    Reduce un string a caracteres seguros para Content-Disposition filename.
    Permite alfanuméricos, espacios y guiones. Trunca a max_length.
    """
    if not value:
        return ""
    return re.sub(r'[^\w\s\-]', '', str(value))[:max_length]


def pdf_filename(prefix, pk, name_segment, local_date=None):
    """
    Nombre de descarga identificable: ``prefijo_id_segmento[_YYYY-MM-DD].pdf``.

    ``name_segment`` (nombre de mascota, etc.) se sanea con
    ``safe_filename_segment``; si queda vacío se usa 'documento'.
    ``local_date`` debe venir ya convertida a la zona horaria de la org.
    """
    seg = safe_filename_segment(name_segment) or "documento"
    parts = [str(prefix), str(pk), seg]
    if local_date:
        parts.append(local_date.strftime('%Y-%m-%d'))
    return "_".join(parts) + ".pdf"
