"""Extract the table schema of a Jet4 (Access 2000+) .mdb file as JSON.

Reads the Access system catalog directly, so mdbtools is not required. The output
feeds generate_doctypes.py.

Usage:
    python scripts/extract_access_schema.py "Daily - Copy.mdb" schema/access_schema.json
"""

from __future__ import annotations

import json
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rail_fms.access.reader import (  # noqa: E402
	ACCESS_TYPES,
	COL_FLAG_AUTONUMBER,
	COL_FLAG_FIXED,
	COL_FLAG_NULLABLE,
	DATA_NUM_ROWS,
	DATA_OWNING_TDEF,
	DATA_ROW_OFFSETS,
	PAGE_SIZE,
	PAGE_TYPE_DATA,
	ROW_OFFSET_MASK,
	ROW_OFFSET_UNUSABLE,
	MdbFile,
)

# Sampling every page of a million-row table to classify its date columns is not
# worth the time; the first few hundred settle the question.
DATE_SAMPLE_PAGE_LIMIT = 400


def build_schema(mdb_path):
	mdb = MdbFile(mdb_path)
	tables = mdb.catalog
	date_kinds = classify_date_columns(mdb, tables)

	schema = {}
	for name, tdef_page in sorted(tables.items()):
		columns = []
		for column in mdb.columns(tdef_page):
			access_type = ACCESS_TYPES.get(column["type"], str(column["type"]))
			entry = {
				"name": column["name"],
				"access_type": access_type,
				# Access stores text sizes in bytes; UTF-16 means two per character.
				"length": column["size"] // 2 if access_type == "Text" else column["size"],
				"nullable": bool(column["flags"] & COL_FLAG_NULLABLE),
				"autonumber": bool(column["flags"] & COL_FLAG_AUTONUMBER),
			}
			if access_type == "DateTime":
				entry["date_kind"] = date_kinds.get(f"{name}.{column['name']}", "Date")
			columns.append(entry)
		schema[name] = {"row_count": mdb.row_count(tdef_page), "columns": columns}
	return schema


def classify_date_columns(mdb, tables):
	"""Decide whether each DateTime column holds a date, a time, or a timestamp.

	Access stores all three in one type, so the only way to tell them apart is to
	look at the values: a whole number is a date, a value below 1 is a time of day,
	and anything else is a real timestamp.
	"""
	sampled = {}
	for name, tdef_page in tables.items():
		date_columns = [
			c for c in mdb.columns(tdef_page) if c["type"] == 8 and c["flags"] & COL_FLAG_FIXED
		]
		if date_columns:
			sampled[tdef_page] = (name, date_columns)

	tally = defaultdict(lambda: {"total": 0, "time_only": 0, "with_time": 0})
	pages_seen = defaultdict(int)
	for page in mdb.iter_pages():
		if page[0] != PAGE_TYPE_DATA:
			continue
		tdef_page = struct.unpack_from("<I", page, DATA_OWNING_TDEF)[0]
		if tdef_page not in sampled or pages_seen[tdef_page] > DATE_SAMPLE_PAGE_LIMIT:
			continue
		pages_seen[tdef_page] += 1
		tally_page(page, *sampled[tdef_page], tally)

	verdicts = {}
	for (table_name, column_name), stats in tally.items():
		total = stats["total"]
		if total and stats["time_only"] > total * 0.8:
			verdict = "Time"
		elif total and stats["with_time"] > total * 0.2:
			verdict = "Datetime"
		else:
			verdict = "Date"
		verdicts[f"{table_name}.{column_name}"] = verdict
	return verdicts


def tally_page(page, table_name, date_columns, tally):
	count = struct.unpack_from("<H", page, DATA_NUM_ROWS)[0]
	offsets = [struct.unpack_from("<H", page, DATA_ROW_OFFSETS + i * 2)[0] for i in range(count)]
	for i, offset in enumerate(offsets):
		if offset & ROW_OFFSET_UNUSABLE:
			continue
		row_start = offset & ROW_OFFSET_MASK
		row_end = (PAGE_SIZE if i == 0 else offsets[i - 1] & ROW_OFFSET_MASK) - 1
		try:
			column_count = struct.unpack_from("<H", page, row_start)[0]
			bitmap_size = (column_count + 7) // 8
			null_bitmap = page[row_end - bitmap_size + 1 : row_end + 1]
			for column in date_columns:
				index = column["number"]
				if not (null_bitmap[index // 8] >> (index % 8) & 1):
					continue
				value = struct.unpack_from("<d", page, row_start + 2 + column["fixed_offset"])[0]
				stats = tally[(table_name, column["name"])]
				stats["total"] += 1
				if abs(value) < 2:
					stats["time_only"] += 1
				if abs(value - int(value)) > 1e-9:
					stats["with_time"] += 1
		except (IndexError, struct.error):
			continue


def main():
	if len(sys.argv) != 3:
		sys.exit(__doc__)
	schema = build_schema(sys.argv[1])
	with open(sys.argv[2], "w") as out:
		json.dump(schema, out, indent="\t", sort_keys=True)
		out.write("\n")
	print(f"{len(schema)} tables -> {sys.argv[2]}")


if __name__ == "__main__":
	main()
