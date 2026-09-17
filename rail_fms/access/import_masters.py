"""Load the core master data from the legacy Access database.

Covers the four things every later transaction import links to: Commodity,
Railway Station, Train and the Rail FMS Settings single. The remaining Rail
Masters tables (SplTrains, SplClass, LeaseRates, TrainChange, the code maps) are
a later pass.

Run with:
    bench --site <site> execute rail_fms.access.import_masters.execute \\
        --kwargs "{'mdb_path': '/path/to/Daily - Copy.mdb'}"
"""

from __future__ import annotations

import frappe

from rail_fms.access.convert import to_frappe_value
from rail_fms.access.reader import MdbFile

# Access column -> child row fieldname, for the two tables that were split into a
# parent keyed on the code plus a per-category child.
STATION_CATEGORY_FIELDS = {
	"Category": "category",
	"TrDate": "tr_date",
	"Counters": "counters",
	"Priority": "priority",
	"DisplayOrder": "display_order",
	"Disp12Stn": "disp_12_stn",
	"DefComm": "def_comm",
	"Options": "options",
	"StnCateg": "stn_categ",
}

COMMODITY_CATEGORY_FIELDS = {
	"Category": "category",
	"Item": "item",
	"Priority": "priority",
}

TRAIN_FIELDS = {
	"Train": "train_no",
	"TrainName": "train_name",
	"Classes": "classes",
	"Tatkal": "tatkal",
	"Days": "days",
	"DOS": "dos",
	"CC": "cc",
	"Departure": "departure",
	"FromStn": "from_stn",
	"Destn": "destn",
	"Direction": "direction",
	"Dir": "dir_code",
	"NextDayPosition": "next_day_position",
	"Daily": "daily",
	"Priority": "priority",
	"Resvn": "resvn",
	"Categ": "categ",
}

# Deleted before loading, children first.
TARGET_DOCTYPES = [
	"Train",
	"Railway Station Category",
	"Railway Station",
	"Commodity Category",
	"Commodity",
]


def execute(mdb_path, reset=True):
	importer = MasterImporter(mdb_path, reset=reset)
	importer.run()
	print(importer.report())


class MasterImporter:
	def __init__(self, mdb_path, reset=True):
		self.mdb = MdbFile(mdb_path)
		self.reset_first = reset
		self.counts = {}
		self.notes = []
		self.commodities = LinkIndex()
		self.stations = LinkIndex()

	def run(self):
		stations = self.read("Stations")
		commodities = self.read("Commodities")
		trains = self.read("Trains")
		settings = self.read("GenInfo")

		if self.reset_first:
			self.reset()

		self.import_commodities(commodities, stations)
		self.import_stations(stations)
		self.create_station_stubs(trains)
		self.import_trains(trains)
		self.import_settings(settings)
		frappe.db.commit()

	def read(self, table):
		"""Read a table, refusing the result if the page scan looks unreliable."""
		rows = self.mdb.rows(table)
		self.mdb.assert_row_count(table, rows)
		self.counts[f"{table} (rows read)"] = len(rows)
		return rows

	def reset(self):
		for doctype in TARGET_DOCTYPES:
			frappe.db.delete(doctype)

	# -- Commodity ---------------------------------------------------------

	def import_commodities(self, rows, station_rows):
		grouped = group_by(rows, "Commodity")
		for name, group in grouped.items():
			frappe.get_doc(
				{
					"doctype": "Commodity",
					"commodity_name": name,
					"categories": [
						map_row(row, COMMODITY_CATEGORY_FIELDS, "Commodity Category") for row in group
					],
				}
			).insert()
		self.counts["Commodity"] = len(grouped)
		self.counts["Commodity Category"] = sum(len(group) for group in grouped.values())
		self.commodities = LinkIndex(grouped)

		# Stations.DefComm names commodities the Commodities table never listed.
		referenced = {row["DefComm"] for row in station_rows if row.get("DefComm")}
		self.stub("Commodity", "commodity_name", self.commodities, referenced)

	# -- Railway Station ---------------------------------------------------

	def import_stations(self, rows):
		grouped = group_by(rows, "Station")
		for code, group in grouped.items():
			categories = []
			for row in group:
				child = map_row(row, STATION_CATEGORY_FIELDS, "Railway Station Category")
				child["def_comm"] = self.commodities.resolve(child["def_comm"])
				categories.append(child)
			frappe.get_doc(
				{"doctype": "Railway Station", "station_code": code, "categories": categories}
			).insert()
		self.counts["Railway Station"] = len(grouped)
		self.counts["Railway Station Category"] = sum(len(group) for group in grouped.values())
		self.stations = LinkIndex(grouped)

	def create_station_stubs(self, train_rows):
		referenced = set()
		for row in train_rows:
			referenced.update(row[key] for key in ("FromStn", "Destn") if row.get(key))
		self.stub("Railway Station", "station_code", self.stations, referenced)

	# -- Train -------------------------------------------------------------

	def import_trains(self, rows):
		seen = {}
		for row in rows:
			number = row.get("Train")
			if not number:
				self.notes.append("Train row skipped: blank train number")
				continue
			if number in seen:
				self.notes.append(
					f"Train {number!r} ({row.get('TrainName')!r}) skipped: duplicate of {seen[number]!r}"
				)
				continue
			seen[number] = row.get("TrainName")

			values = map_row(row, TRAIN_FIELDS, "Train")
			values["from_stn"] = self.stations.resolve(values["from_stn"])
			values["destn"] = self.stations.resolve(values["destn"])
			frappe.get_doc(dict(values, doctype="Train")).insert()
		self.counts["Train"] = len(seen)

	# -- Settings ----------------------------------------------------------

	def import_settings(self, rows):
		if not rows:
			return
		row = rows[0]
		settings = frappe.get_single("Rail FMS Settings")
		settings.zone = row.get("Zone")
		settings.division = row.get("Division")
		settings.background = row.get("Background")
		settings.save()
		self.counts["Rail FMS Settings"] = 1

	# -- Helpers -----------------------------------------------------------

	def stub(self, doctype, key_field, index, referenced):
		"""Create the records a Link points at but the Access master never held."""
		codes = sorted(index.missing(referenced))
		for code in codes:
			frappe.get_doc({"doctype": doctype, key_field: code, "auto_created": 1}).insert()
			index.add(code)
		self.counts[f"{doctype} (auto created)"] = len(codes)
		self.counts[doctype] = self.counts.get(doctype, 0) + len(codes)
		for kept, dropped in index.merged.items():
			self.notes.append(f"{doctype} {kept!r} also covers {dropped} (names differ only in case)")

	def report(self):
		width = max(len(key) for key in self.counts)
		lines = [f"{key:<{width}}  {value:>6}" for key, value in self.counts.items()]
		return "\n".join(lines + self.notes)


class LinkIndex:
	"""Maps a code to the record that actually exists for it.

	MariaDB compares names case-insensitively, so 'NDLS' and 'ndls' cannot both
	name a record even though Access treats them as two codes. Link values are
	resolved through this index so they point at the record that was created.
	"""

	def __init__(self, names=()):
		self.canonical = {}
		self.merged = {}
		for name in names:
			self.add(name)

	def add(self, name):
		return self.canonical.setdefault(name.casefold(), name)

	def resolve(self, code):
		if not code:
			return None
		return self.canonical.get(code.casefold(), code)

	def missing(self, codes):
		"""Codes with no record yet, one per case-insensitive group."""
		groups = {}
		for code in codes:
			if code and code.casefold() not in self.canonical:
				groups.setdefault(code.casefold(), []).append(code)
		# Uppercase sorts first, which matches the railway convention for codes.
		self.merged = {sorted(g)[0]: sorted(g)[1:] for g in groups.values() if len(g) > 1}
		return [sorted(group)[0] for group in groups.values()]


def group_by(rows, column):
	"""Group rows by a column, preserving first-seen order and skipping blanks."""
	grouped = {}
	for row in rows:
		key = row.get(column)
		if key:
			grouped.setdefault(key, []).append(row)
	return grouped


def map_row(row, mapping, doctype):
	"""Convert one Access row into Frappe values, using the DocType's fieldtypes."""
	meta = frappe.get_meta(doctype)
	return {
		fieldname: to_frappe_value(row.get(column), meta.get_field(fieldname).fieldtype)
		for column, fieldname in mapping.items()
	}
