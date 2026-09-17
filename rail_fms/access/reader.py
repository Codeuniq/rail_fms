"""Read-only reader for a Jet4 (Access 2000+) .mdb file.

Standard library only, and deliberately free of any `frappe` import: the schema
extraction script runs this outside a site context, while the importers run it
inside one.

It finds a table's rows by scanning every page for one whose owner pointer
matches the table. That also picks up pages freed from that table, so a caller
that needs exact data must check `MdbFile.row_count` against the number of rows
it actually read. `assert_row_count` does this.
"""

from __future__ import annotations

import struct

PAGE_SIZE = 4096

PAGE_TYPE_DATA = 0x01
PAGE_TYPE_TDEF = 0x02

# Offsets into a table definition page (Jet4).
TDEF_NEXT_PAGE = 0x04
TDEF_NUM_ROWS = 0x10
TDEF_NUM_COLS = 0x2D
TDEF_NUM_REAL_INDEXES = 0x33
TDEF_DEFINITIONS_START = 0x3F
REAL_INDEX_ENTRY_SIZE = 12
COLUMN_ENTRY_SIZE = 25

# Offsets within one 25-byte column definition entry.
COL_TYPE = 0x00
COL_NUMBER = 0x05
COL_VARIABLE_INDEX = 0x07
COL_FLAGS = 0x0F
COL_FIXED_OFFSET = 0x15
COL_SIZE = 0x17

COL_FLAG_FIXED = 0x01
COL_FLAG_NULLABLE = 0x02
COL_FLAG_AUTONUMBER = 0x04

# Offsets into a data page (Jet4).
DATA_OWNING_TDEF = 0x04
DATA_NUM_ROWS = 0x0C
DATA_ROW_OFFSETS = 0x0E
ROW_OFFSET_MASK = 0x1FFF
ROW_OFFSET_UNUSABLE = 0xC000  # deleted (0x8000) or a pointer to another row (0x4000)

ACCESS_TYPES = {
	1: "Bool",
	2: "Byte",
	3: "Int",
	4: "Long",
	5: "Money",
	6: "Single",
	7: "Double",
	8: "DateTime",
	9: "Binary",
	10: "Text",
	11: "OLE",
	12: "Memo",
	13: "RepID",
	15: "GUID",
	16: "Numeric",
}

TEXT_TYPES = (10, 12)
CATALOG_TDEF_PAGE = 2  # MSysObjects always lives here
CATALOG_TYPE_TABLE = 1
SYSTEM_TABLE_PREFIX = "MSys"


class RowCountMismatch(Exception):
	"""The pages scanned for a table did not yield the row count Access records."""


class MdbFile:
	"""Minimal reader for the Jet4 catalog, table definitions and rows."""

	def __init__(self, path):
		self.handle = open(path, "rb")
		header = self.page(0)
		if header[0x14] != 1:
			raise ValueError("not a Jet4 database (Access 2000 or later)")
		self._catalog = None

	def page(self, number):
		self.handle.seek(number * PAGE_SIZE)
		return self.handle.read(PAGE_SIZE)

	def iter_pages(self):
		self.handle.seek(0)
		while True:
			page = self.handle.read(PAGE_SIZE)
			if len(page) < PAGE_SIZE:
				return
			yield page

	@property
	def catalog(self):
		"""{table name: tdef page} for every user table."""
		if self._catalog is None:
			self._catalog = read_catalog(self)
		return self._catalog

	def table_definition(self, tdef_page):
		"""Concatenate a table definition, which may span several linked pages."""
		buffer = b""
		visited = set()
		while tdef_page and tdef_page not in visited:
			visited.add(tdef_page)
			page = self.page(tdef_page)
			buffer = page if not buffer else buffer + page[8:]
			tdef_page = struct.unpack_from("<I", page, TDEF_NEXT_PAGE)[0]
		return buffer

	def columns(self, tdef_page):
		tdef = self.table_definition(tdef_page)
		count = struct.unpack_from("<H", tdef, TDEF_NUM_COLS)[0]
		real_indexes = struct.unpack_from("<I", tdef, TDEF_NUM_REAL_INDEXES)[0]
		start = TDEF_DEFINITIONS_START + real_indexes * REAL_INDEX_ENTRY_SIZE

		columns = []
		for i in range(count):
			entry = tdef[start + i * COLUMN_ENTRY_SIZE :][:COLUMN_ENTRY_SIZE]
			columns.append(
				{
					"type": entry[COL_TYPE],
					"number": struct.unpack_from("<H", entry, COL_NUMBER)[0],
					"variable_index": struct.unpack_from("<H", entry, COL_VARIABLE_INDEX)[0],
					"flags": entry[COL_FLAGS],
					"fixed_offset": struct.unpack_from("<H", entry, COL_FIXED_OFFSET)[0],
					"size": struct.unpack_from("<H", entry, COL_SIZE)[0],
				}
			)

		# Column names follow the definitions, each as a length-prefixed UTF-16LE string.
		cursor = start + count * COLUMN_ENTRY_SIZE
		for column in columns:
			length = struct.unpack_from("<H", tdef, cursor)[0]
			cursor += 2
			column["name"] = tdef[cursor : cursor + length].decode("utf-16le")
			cursor += length

		columns.sort(key=lambda column: column["number"])
		return columns

	def row_count(self, tdef_page):
		"""The row count Access itself records in the table definition."""
		return struct.unpack_from("<I", self.table_definition(tdef_page), TDEF_NUM_ROWS)[0]

	def rows(self, table_name):
		"""Every row of a user table, as {column name: value}."""
		tdef_page = self.catalog[table_name]
		columns = self.columns(tdef_page)
		rows = []
		for page in self.iter_pages():
			if page[0] != PAGE_TYPE_DATA:
				continue
			if struct.unpack_from("<I", page, DATA_OWNING_TDEF)[0] != tdef_page:
				continue
			rows.extend(iter_page_rows(page, columns))
		return rows

	def assert_row_count(self, table_name, rows):
		"""Guard against the page scan reading pages freed from the table."""
		expected = self.row_count(self.catalog[table_name])
		if len(rows) != expected:
			raise RowCountMismatch(
				f"{table_name}: read {len(rows)} rows but Access records {expected}. "
				"Page scanning is unreliable for this table; extract it with mdb-export."
			)
		return rows


def read_catalog(mdb):
	"""Return {table name: tdef page} for every user table."""
	columns = mdb.columns(CATALOG_TDEF_PAGE)
	tables = {}
	for page in mdb.iter_pages():
		if page[0] != PAGE_TYPE_DATA:
			continue
		if struct.unpack_from("<I", page, DATA_OWNING_TDEF)[0] != CATALOG_TDEF_PAGE:
			continue
		for row in iter_page_rows(page, columns):
			name = row.get("Name")
			if not name or row.get("Type") != CATALOG_TYPE_TABLE:
				continue
			if name.startswith(SYSTEM_TABLE_PREFIX):
				continue
			# The low bytes of Id are the table definition page number.
			tables[name] = row["Id"] & 0x00FFFFFF
	return tables


def iter_page_rows(page, columns):
	count = struct.unpack_from("<H", page, DATA_NUM_ROWS)[0]
	offsets = [struct.unpack_from("<H", page, DATA_ROW_OFFSETS + i * 2)[0] for i in range(count)]
	for i, offset in enumerate(offsets):
		if offset & ROW_OFFSET_UNUSABLE:
			continue
		row_start = offset & ROW_OFFSET_MASK
		row_end = (PAGE_SIZE if i == 0 else offsets[i - 1] & ROW_OFFSET_MASK) - 1
		try:
			yield parse_row(page, row_start, row_end, columns)
		except (IndexError, struct.error):
			continue  # a page freed from this table, or an overflow row


def parse_row(page, row_start, row_end, columns):
	"""Decode one row.

	Jet4 row layout: a 2-byte column count, then the fixed-width columns, then the
	variable-width ones. The tail of the row, read backwards from the end, holds
	the null bitmap, the variable-column count, and the variable-column offsets.
	"""
	column_count = struct.unpack_from("<H", page, row_start)[0]
	bitmap_size = (column_count + 7) // 8
	null_bitmap = page[row_end - bitmap_size + 1 : row_end + 1]

	variable_count = struct.unpack_from("<H", page, row_end - bitmap_size - 1)[0]
	variable_offsets = [
		struct.unpack_from("<H", page, row_end - bitmap_size - 3 - i * 2)[0]
		for i in range(variable_count + 1)
	]

	row = {}
	for column in columns:
		index = column["number"]
		if not (null_bitmap[index // 8] >> (index % 8) & 1):
			row[column["name"]] = None
			continue

		if column["flags"] & COL_FLAG_FIXED:
			start = row_start + 2 + column["fixed_offset"]
			row[column["name"]] = decode_value(column, page[start : start + column["size"]])
			continue

		variable_index = column["variable_index"]
		if variable_index >= variable_count:
			row[column["name"]] = None
			continue
		start = row_start + variable_offsets[variable_index]
		end = row_start + variable_offsets[variable_index + 1]
		row[column["name"]] = decode_value(column, page[start:end]) if end >= start else None

	return row


def decode_value(column, raw):
	"""Decode one column value into a Python primitive.

	Dates come back as the raw Access float (days since 1899-12-30); convert.py
	turns those into date, time or datetime once the target fieldtype is known.
	"""
	if not raw:
		return None
	access_type = column["type"]
	if access_type in TEXT_TYPES:
		# 0xFF 0xFE marks a "compressed" string: one byte per character.
		if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
			return raw[2:].decode("latin-1").strip()
		return raw.decode("utf-16le", "replace").strip()
	if access_type == 4:
		return struct.unpack("<i", raw[:4])[0]
	if access_type == 3:
		return struct.unpack("<h", raw[:2])[0]
	if access_type == 2:
		return raw[0]
	if access_type == 1:
		return bool(raw[0])
	if access_type in (7, 8):
		return struct.unpack("<d", raw[:8])[0]
	if access_type == 6:
		return struct.unpack("<f", raw[:4])[0]
	return None
