"""El tope de filas corta la lectura; no se aplica después de materializarla.

Origen (auditoría run-1, hallazgo
`imports/parsers/row-cap-applied-after-full-materialization`):

El módulo declaraba sus topes como defensa del worker de gunicorn, pero los
aplicaba DESPUÉS de convertir el archivo entero en objetos de Python:
`_parse_xlsx` hacía `list(rows_iter)` —anulando el `read_only=True` que había
abierto dos líneas antes— y `_parse_csv` materializaba el fichero completo. El
único control efectivo era MAX_FILE_BYTES.

Medido contra openpyxl real antes del arreglo: 28x de amplificación en el peor
caso (cadenas repetidas), ~140 MB proyectados por petición con el tope de 5 MB.
No llegaba a vulnerabilidad de disponibilidad —y así se registró— pero el
código no hacía lo que su docstring prometía.

El arreglo pasa un iterable perezoso a `_finalize`. La prueba que importa no es
que un archivo grande falle (ya fallaba), sino que falle SIN LEERLO TODO: eso
es lo que distingue el tope real del decorativo.

El módulo no tenía ninguna prueba, así que aquí se fija también el
comportamiento preservado por el refactor.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from apps.imports import parsers
from apps.imports.parsers import (
    MAX_COLUMNS,
    MAX_FILE_BYTES,
    MAX_ROWS,
    ImportParseError,
    _finalize,
    parse_file,
)


def _upload(name, data):
    return SimpleUploadedFile(name, data)


def _csv_bytes(rows, header='a,b,c'):
    return ('\n'.join([header] + rows)).encode('utf-8')


class RowCapStopsTheReadTests(SimpleTestCase):
    """La propiedad de seguridad: el tope corta, no recorta al final."""

    def test_finalize_stops_consuming_once_the_cap_is_exceeded(self):
        consumed = {'n': 0}

        def endless():
            # Si el tope se aplicara después de materializar, este generador
            # se agotaría entero (100 000 filas) antes de que nadie mire.
            for i in range(100_000):
                consumed['n'] += 1
                yield [str(i), 'x', 'y']

        with self.assertRaises(ImportParseError) as ctx:
            _finalize(['a', 'b', 'c'], endless())

        self.assertIn('supera el máximo', str(ctx.exception))
        self.assertLessEqual(
            consumed['n'], MAX_ROWS + 2,
            f"Se leyeron {consumed['n']} filas para imponer un tope de {MAX_ROWS}: "
            f"el tope se está aplicando después de materializar, que es el defecto "
            f"que esta prueba existe para impedir.",
        )

    def test_exactly_the_cap_is_accepted(self):
        """Frontera: MAX_ROWS pasa, MAX_ROWS + 1 no. Comportamiento previo."""
        rows = (['v', 'v', 'v'] for _ in range(MAX_ROWS))
        columns, out = _finalize(['a', 'b', 'c'], rows)
        self.assertEqual(len(out), MAX_ROWS)

    def test_empty_rows_do_not_consume_the_cap(self):
        """Una fila 100 % vacía se descarta y no cuenta. Comportamiento previo."""
        def mixed():
            for _ in range(MAX_ROWS):
                yield ['', '', '']      # descartadas
            yield ['x', '', '']         # la única que cuenta

        columns, out = _finalize(['a', 'b', 'c'], mixed())
        self.assertEqual(out, [['x', '', '']])

    def test_neither_parser_materialises_the_row_iterator(self):
        """Gate estático: el defecto era materializar, fácil de reponer.

        Una prueba de comportamiento sobre `_finalize` no impide que alguien
        vuelva a envolver el iterador en el parser, porque el tope seguiría
        disparando y solo cambiaría cuánta memoria se gasta antes de hacerlo.

        Se analiza el AST y no el texto: un grep de `list(` encuentra también
        los comentarios que explican el arreglo, lo que convertiría al gate en
        un falso positivo sobre su propia documentación. Se cubre además la
        forma por comprensión, porque el defecto del CSV era exactamente
        `[row for row in reader]`.
        """
        import ast
        import inspect
        import textwrap

        eager_calls = {'list', 'tuple', 'sorted', 'frozenset', 'set'}

        for fn in (parsers._parse_csv, parsers._parse_xlsx):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            offenders = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id in eager_calls:
                    offenders.append(f'{node.func.id}() en línea {node.lineno}')
                elif isinstance(node, (ast.ListComp, ast.SetComp)):
                    # Una comprensión sobre las COLUMNAS es legítima: son como
                    # máximo MAX_COLUMNS y se validan antes de leer filas. Lo
                    # que no puede materializarse es el iterador de filas.
                    src = ast.unparse(node)
                    if 'reader' in src or 'rows_iter' in src:
                        offenders.append(f'comprensión sobre filas en línea {node.lineno}')
            self.assertEqual(
                offenders, [],
                f"{fn.__name__} materializa su iterador de filas ({', '.join(offenders)}): "
                f"eso devuelve el tope a aplicarse después de la asignación que debe acotar.",
            )


class CsvParsingTests(SimpleTestCase):
    def test_rows_over_the_cap_are_refused(self):
        data = _csv_bytes(['x,y,z'] * (MAX_ROWS + 1))
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('big.csv', data))
        self.assertIn('supera el máximo', str(ctx.exception))

    def test_empty_file_is_refused(self):
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('e.csv', b'   '))
        # Un archivo con solo espacios tiene encabezado ilegible, no está vacío
        # en bytes: el mensaje correcto es el de encabezados.
        self.assertIn('encabezados', str(ctx.exception))

    def test_zero_bytes_is_refused(self):
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('e.csv', b''))
        self.assertIn('vacío', str(ctx.exception))

    def test_header_without_data_rows_is_refused(self):
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('h.csv', b'a,b,c'))
        self.assertIn('no tiene filas de datos', str(ctx.exception))

    def test_too_many_columns_is_refused(self):
        header = ','.join(f'c{i}' for i in range(MAX_COLUMNS + 1))
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('w.csv', _csv_bytes(['1'], header=header)))
        self.assertIn('demasiadas columnas', str(ctx.exception))

    def test_semicolon_delimiter_is_detected(self):
        data = 'a;b;c\n1;2;3'.encode('utf-8')
        columns, rows = parse_file(_upload('s.csv', data))
        self.assertEqual(columns, ['a', 'b', 'c'])
        self.assertEqual(rows, [['1', '2', '3']])

    def test_latin1_is_the_last_resort_encoding(self):
        data = 'nombre,tel\nJosé Muñoz,5551234567'.encode('latin-1')
        columns, rows = parse_file(_upload('l.csv', data))
        self.assertEqual(rows[0][0], 'José Muñoz')

    def test_width_is_normalised_in_both_directions(self):
        data = 'a,b,c\n1,2\n1,2,3,4'.encode('utf-8')
        columns, rows = parse_file(_upload('n.csv', data))
        self.assertEqual(rows, [['1', '2', ''], ['1', '2', '3']])

    def test_size_cap_is_applied_before_parsing(self):
        oversized = b'a,b,c\n' + b'x' * (MAX_FILE_BYTES + 1)
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('huge.csv', oversized))
        self.assertIn('demasiado', str(ctx.exception))


class XlsxParsingTests(SimpleTestCase):
    @staticmethod
    def _xlsx(rows, header=('a', 'b', 'c')):
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet()
        ws.append(list(header))
        for r in rows:
            ws.append(list(r))
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_rows_over_the_cap_are_refused(self):
        """Ejercita además el `finally` que cierra el libro al abortar."""
        data = self._xlsx([('x', 'y', 'z')] * (MAX_ROWS + 1))
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('big.xlsx', data))
        self.assertIn('supera el máximo', str(ctx.exception))

    def test_rows_are_read_lazily_and_the_workbook_still_closes(self):
        data = self._xlsx([('1', '2', '3'), ('4', '5', '6')])
        columns, rows = parse_file(_upload('ok.xlsx', data))
        self.assertEqual(columns, ['a', 'b', 'c'])
        self.assertEqual(rows, [['1', '2', '3'], ['4', '5', '6']])

    def test_integer_floats_do_not_gain_a_decimal_suffix(self):
        """Excel guarda enteros como float; un teléfono no puede salir '...0'."""
        data = self._xlsx([(5551234567.0, 2.5, True)])
        columns, rows = parse_file(_upload('f.xlsx', data))
        self.assertEqual(rows[0][0], '5551234567')
        self.assertEqual(rows[0][1], '2.5')
        self.assertEqual(rows[0][2], 'sí')

    def test_zip_signature_is_parsed_as_xlsx_without_an_extension(self):
        data = self._xlsx([('1', '2', '3')])
        columns, rows = parse_file(_upload('sinextension', data))
        self.assertEqual(rows, [['1', '2', '3']])

    def test_corrupt_workbook_is_refused_with_a_readable_message(self):
        with self.assertRaises(ImportParseError) as ctx:
            parse_file(_upload('bad.xlsx', b'PK\x03\x04 basura'))
        self.assertIn('Excel', str(ctx.exception))
