"""
Flowables reutilizables para los documentos del SaaS.

Cada función devuelve una lista de flowables lista para anexar al story.
Ninguna toca la base de datos: los views deciden el contenido, el tema decide
la apariencia. Las celdas/valores que vienen de datos de usuario deben llegar
ya saneados con ``safe_pdf_text`` (responsabilidad del caller).
"""
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, KeepTogether, LongTable, Paragraph, Spacer, Table, TableStyle,
)

from .document import CONTENT_WIDTH


def title_block(st, title, meta_lines=()):
    """Título del documento + líneas de metadata (estado, fechas…)."""
    flows = [Paragraph(title, st['doc_title'])]
    for line in meta_lines:
        flows.append(Paragraph(line, st['doc_meta']))
    flows.append(Spacer(1, 0.35 * cm))
    return flows


def section(st, theme, text):
    """Encabezado de sección: título en color de marca + hairline."""
    hr = HRFlowable(width='100%', thickness=0.7, color=theme.line,
                    spaceBefore=0, spaceAfter=6)
    # Sin esto el título+hairline pueden quedar huérfanos al pie de página
    # con su contenido en la siguiente ('section' ya trae keepWithNext).
    hr.keepWithNext = 1
    return [
        Spacer(1, 0.42 * cm),
        Paragraph(text.upper(), st['section']),
        hr,
    ]


def info_card(st, theme, pairs, columns=3):
    """
    Tarjeta de datos label/valor sobre fondo cream.

    ``pairs`` = [(label, value), ...]. Se acomodan ``columns`` por fila;
    valores vacíos se muestran como '—'.
    """
    pairs = [p for p in pairs if p is not None]
    if not pairs:
        return []
    cells = []
    for label, value in pairs:
        cells.append([
            Paragraph(str(label).upper(), st['label']),
            Paragraph(value if value not in (None, '') else '—', st['value']),
        ])
    rows = []
    for i in range(0, len(cells), columns):
        row = cells[i:i + columns]
        while len(row) < columns:
            row.append('')
        rows.append(row)
    col_w = CONTENT_WIDTH / columns
    t = Table(rows, colWidths=[col_w] * columns)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), theme.card_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, theme.line),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return [t]


def data_table(st, theme, header, rows, col_widths, align_right=()):
    """
    Tabla de datos con encabezado tintado, hairlines horizontales y zebra
    sutil (sin grid completo). ``repeatRows=1`` repite el header al paginar.

    Las celdas pueden ser strings o Paragraphs (para texto largo usar
    ``Paragraph(..., st['cell'])`` en el caller).
    """
    table_rows = [list(header)] + [list(r) for r in rows]
    t = LongTable(table_rows, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), theme.table_header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), theme.brand_dark),
        ('FONTNAME', (0, 0), (-1, 0), theme.font_bold),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('LEADING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.9, theme.brand),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    if rows:
        style += [
            ('FONTNAME', (0, 1), (-1, -1), theme.font),
            ('TEXTCOLOR', (0, 1), (-1, -1), theme.ink),
            ('LINEBELOW', (0, 1), (-1, -1), 0.4, theme.line),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, theme.zebra_bg]),
        ]
    for col in align_right:
        style.append(('ALIGN', (col, 0), (col, -1), 'RIGHT'))
    t.setStyle(TableStyle(style))
    return [t]


def totals_table(st, theme, rows):
    """Bloque de totales alineado a la derecha; la última fila se enfatiza."""
    if not rows:
        return []
    t = Table(rows, colWidths=[4.8 * cm, 3.4 * cm], hAlign='RIGHT')
    style = [
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('FONTNAME', (0, -1), (-1, -1), theme.font_bold),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('TEXTCOLOR', (0, -1), (-1, -1), theme.brand_dark),
        ('LINEABOVE', (0, -1), (-1, -1), 1.0, theme.brand),
        ('TOPPADDING', (0, -1), (-1, -1), 7),
    ]
    if len(rows) > 1:
        style += [
            ('FONTNAME', (0, 0), (-1, -2), theme.font),
            ('FONTSIZE', (0, 0), (-1, -2), 10),
            ('TEXTCOLOR', (0, 0), (-1, -2), theme.ink),
        ]
    t.setStyle(TableStyle(style))
    return [Spacer(1, 0.3 * cm), t]


def numbered_item(st, index, title_markup, detail_parts=()):
    """Ítem numerado (medicamentos de receta): título bold + detalle indentado."""
    flows = [Paragraph(f"{index}. {title_markup}", st['item_title'])]
    detail_parts = [d for d in detail_parts if d]
    if detail_parts:
        flows.append(Paragraph(' &nbsp;·&nbsp; '.join(detail_parts), st['item_detail']))
    return [KeepTogether(flows)]


def signature_block(st, theme, name, sub_lines=()):
    """Línea de firma + nombre + líneas secundarias (especialidad, cédula…)."""
    rows = [[Paragraph(name, st['sig_name'])]]
    for sub in sub_lines:
        if sub:
            rows.append([Paragraph(sub, st['sig_sub'])])
    style = [
        ('LINEABOVE', (0, 0), (-1, 0), 0.8, theme.ink),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]
    if len(rows) > 1:
        style.append(('TOPPADDING', (0, 1), (-1, -1), 1))
    t = Table(rows, colWidths=[6.8 * cm], hAlign='RIGHT')
    t.setStyle(TableStyle(style))
    return [KeepTogether([Spacer(1, 1.5 * cm), t])]
