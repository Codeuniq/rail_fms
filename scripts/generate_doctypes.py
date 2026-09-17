"""Generate rail_fms DocTypes from the extracted Access schema.

Reads schema/access_schema.json plus the decisions in doctype_spec.py and writes
one DocType per Access table. Re-running it is idempotent: the output depends
only on those two inputs, so a second run leaves a clean `git diff`.

Usage (from the app root):
    python scripts/generate_doctypes.py
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import doctype_spec as spec

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(APP_ROOT, "schema", "access_schema.json")
PACKAGE_ROOT = os.path.join(APP_ROOT, "rail_fms")

# Frozen so regenerating does not churn every file. Frappe re-imports on content
# change, not on this timestamp.
STAMP = "2026-09-04 00:00:00.000000"

CONTROLLER_TEMPLATE = '''# Copyright (c) 2026, sherinkr and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class {class_name}(Document):
	pass
'''

DATA_MAX_LENGTH = 140


def scrub(name):
	"""Frappe's module/doctype folder naming."""
	return name.lower().replace(" ", "_").replace("-", "_")


def class_name(doctype):
	return re.sub(r"[^A-Za-z0-9]", "", doctype)


def fieldname_for(access_table, column):
	renamed = spec.FIELD_RENAMES.get((access_table, column))
	if renamed:
		return renamed
	renamed = spec.GLOBAL_FIELD_RENAMES.get(column)
	if renamed:
		return renamed

	name = re.sub(r"[^0-9a-zA-Z]+", "_", column)
	# Access columns are PascalCase with no separators ("DisplayOrder",
	# "Disp12Stn"), so split on case and digit boundaries before lowercasing.
	name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
	name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
	name = re.sub(r"(?<=[A-Za-z])(?=[0-9])", "_", name)
	name = re.sub(r"(?<=[0-9])(?=[A-Za-z])", "_", name)
	name = re.sub(r"_+", "_", name).strip("_").lower()
	# MariaDB and Frappe both reject a leading digit (the Jan05..Jun05 sheets
	# have columns literally named "1".."6").
	if not name or name[0].isdigit():
		name = f"col_{name}"
	return name


class FieldBuilder:
	"""Maps one Access column to one Frappe docfield."""

	def __init__(self, access_table, doctype):
		self.access_table = access_table
		self.doctype = doctype

	def build(self, column):
		if column["autonumber"]:
			return self.legacy_id_field(column)

		fieldname = fieldname_for(self.access_table, column["name"])
		if fieldname in spec.RESERVED_FIELDNAMES:
			raise ValueError(f"{self.doctype}.{fieldname} collides with a Frappe built-in field")

		field = {
			"fieldname": fieldname,
			"fieldtype": self.fieldtype(column, fieldname),
			"label": column["name"],
		}
		if field["fieldtype"] == "Data" and column["access_type"] == "Text":
			field["length"] = column["length"]
		if field["fieldtype"] == "Link":
			field["options"] = spec.LINK_TARGETS[fieldname]
		if self.wants_index(fieldname):
			field["search_index"] = 1
		return field

	def wants_index(self, fieldname):
		if fieldname not in spec.INDEXED_FIELDS:
			return False
		# Frappe does not index Link columns on its own, and a composite index
		# already covers its own leading column.
		composite = spec.COMPOSITE_INDEXES.get(self.doctype)
		return not (composite and composite[0] == fieldname)

	def legacy_id_field(self, column):
		# The Access autonumber has no meaning outside the old application; Frappe
		# names the record instead. Keep the value so rows stay traceable.
		return {
			"fieldname": "legacy_id",
			"fieldtype": "Int",
			"label": f"Legacy {column['name']}",
			"read_only": 1,
		}

	def fieldtype(self, column, fieldname):
		access_type = column["access_type"]
		is_link = fieldname in spec.LINK_TARGETS and (self.doctype, fieldname) not in spec.NO_LINK
		# Legacy Sheet1 stores its train number as a Double; only a text column
		# can hold another record's name.
		if is_link and access_type == "Text":
			return "Link"

		if access_type == "Text":
			return "Data" if column["length"] <= DATA_MAX_LENGTH else "Small Text"
		if access_type == "Memo":
			return "Text"
		if access_type == "Bool":
			return "Check"
		# Access has no money type here; several rupee columns are stored as
		# whole-number Longs, so the column name decides, not the storage type.
		if column["name"] in spec.CURRENCY_COLUMNS:
			return "Currency"
		if access_type in ("Byte", "Int", "Long"):
			return "Int"
		if access_type in ("Single", "Double", "Money"):
			return "Float"
		if access_type == "DateTime":
			return column.get("date_kind", "Date")
		return "Data"


class DocTypeBuilder:
	"""Assembles the DocType JSON for one Access table."""

	def __init__(self, access_table, table_schema):
		self.access_table = access_table
		self.schema = table_schema
		self.module = spec.module_of(access_table)
		self.doctype = spec.doctype_of(access_table)
		self.split = spec.SPLIT_TABLES.get(access_table)

	def build(self):
		"""Return [(doctype, module, definition), ...] -- two when the table splits."""
		fields = [FieldBuilder(self.access_table, self.doctype).build(c) for c in self.schema["columns"]]
		fields = self.add_rec_id_link(fields)

		if not self.split:
			return [(self.doctype, self.module, self.definition(self.doctype, fields))]

		parent_names = set(self.split["parent_fields"])
		parent_fields = [f for f, c in zip(fields, self.schema["columns"]) if c["name"] in parent_names]
		child_fields = [f for f, c in zip(fields, self.schema["columns"]) if c["name"] not in parent_names]
		parent_fields.append(
			{
				"fieldname": self.split["table_fieldname"],
				"fieldtype": "Table",
				"label": self.split["table_label"],
				"options": self.split["child_doctype"],
			}
		)
		return [
			(self.doctype, self.module, self.definition(self.doctype, parent_fields)),
			(
				self.split["child_doctype"],
				self.module,
				self.definition(self.split["child_doctype"], child_fields, is_child=True),
			),
		]

	def add_rec_id_link(self, fields):
		"""SplClass and SplOcc join to SplTrains on Rec_ID; make that a real link."""
		link_source = spec.REC_ID_LINKS.get(self.doctype)
		if not link_source:
			return fields

		position = next(i for i, f in enumerate(fields) if f["fieldname"] == link_source)
		link = {
			"fieldname": "special_train",
			"fieldtype": "Link",
			"label": "Special Train",
			"options": "Special Train",
		}
		return fields[: position + 1] + [link] + fields[position + 1 :]

	def definition(self, doctype, fields, is_child=False):
		fields = fields + [dict(f) for f in spec.EXTRA_FIELDS.get(doctype, [])]
		for field in fields[:4]:
			if field["fieldtype"] not in ("Table", "Small Text", "Text"):
				field["in_list_view"] = 1

		definition = {
			"actions": [],
			"allow_rename": 0 if self.access_table in spec.HIGH_VOLUME else 1,
			"creation": STAMP,
			"doctype": "DocType",
			"editable_grid": 1,
			"engine": "InnoDB",
			"field_order": [f["fieldname"] for f in fields],
			"fields": fields,
			"index_web_pages_for_search": 0,
			"links": [],
			"modified": STAMP,
			"modified_by": "Administrator",
			"module": self.module,
			"name": doctype,
			"owner": "Administrator",
			"sort_order": "DESC",
			"states": [],
			"track_changes": 0 if self.access_table in spec.HIGH_VOLUME else 1,
		}

		if is_child:
			definition["istable"] = 1
			definition["permissions"] = []
			definition.pop("allow_rename")
			definition.pop("track_changes")
			definition["sort_field"] = "idx"
			definition["sort_order"] = "ASC"
			return definition

		definition["permissions"] = [
			{
				"create": 1,
				"delete": 1,
				"email": 1,
				"export": 1,
				"print": 1,
				"read": 1,
				"report": 1,
				"role": "System Manager",
				"share": 1,
				"write": 1,
			}
		]
		definition["sort_field"] = self.sort_field(fields)
		self.apply_naming(definition, doctype)

		if doctype in spec.SINGLE_DOCTYPES:
			definition["issingle"] = 1
			definition.pop("sort_field", None)
			definition.pop("sort_order", None)
		if doctype in spec.TITLE_FIELDS:
			definition["title_field"] = spec.TITLE_FIELDS[doctype]
		if doctype in spec.SEARCH_FIELDS:
			definition["search_fields"] = spec.SEARCH_FIELDS[doctype]
		return definition

	def apply_naming(self, definition, doctype):
		autoname = spec.AUTONAME.get(doctype)
		if autoname:
			definition["autoname"] = autoname
			definition["naming_rule"] = "By fieldname"
			definition["allow_rename"] = 1
		elif doctype not in spec.SINGLE_DOCTYPES:
			# Hash naming avoids the tabSeries row lock that would serialise the
			# bulk load of the larger tables.
			definition["autoname"] = "hash"
			definition["naming_rule"] = "Random"

	def sort_field(self, fields):
		names = {f["fieldname"] for f in fields}
		for candidate in ("tr_date", "uts_date", "last_date", "arr_date", "wef"):
			if candidate in names:
				return candidate
		return "modified"


def write_doctype(doctype, module, definition):
	folder = os.path.join(PACKAGE_ROOT, scrub(module), "doctype", scrub(doctype))
	os.makedirs(folder, exist_ok=True)
	slug = scrub(doctype)

	write_if_changed(os.path.join(folder, "__init__.py"), "")
	write_if_changed(
		os.path.join(folder, f"{slug}.json"),
		json.dumps(definition, indent=1, sort_keys=True) + "\n",
	)
	write_if_changed(
		os.path.join(folder, f"{slug}.py"),
		CONTROLLER_TEMPLATE.format(class_name=class_name(doctype)),
	)


def write_if_changed(path, content):
	if os.path.exists(path):
		with open(path) as existing:
			if existing.read() == content:
				return
	with open(path, "w") as out:
		out.write(content)


def prepare_module(module):
	module_root = os.path.join(PACKAGE_ROOT, scrub(module))
	os.makedirs(os.path.join(module_root, "doctype"), exist_ok=True)
	write_if_changed(os.path.join(module_root, "__init__.py"), "")
	write_if_changed(os.path.join(module_root, "doctype", "__init__.py"), "")


def write_modules_txt():
	path = os.path.join(PACKAGE_ROOT, "modules.txt")
	write_if_changed(path, "\n".join(["Rail FMS"] + list(spec.MODULES)) + "\n")


def main():
	with open(SCHEMA_PATH) as handle:
		schema = json.load(handle)

	missing = [t for t in schema if t not in {k for m in spec.MODULES.values() for k in m}]
	if missing:
		sys.exit(f"Access tables with no module assigned: {missing}")

	for module in spec.MODULES:
		prepare_module(module)

	count = 0
	for access_table in sorted(schema):
		for doctype, module, definition in DocTypeBuilder(access_table, schema[access_table]).build():
			write_doctype(doctype, module, definition)
			count += 1

	write_modules_txt()
	print(f"{count} DocTypes across {len(spec.MODULES)} modules")


if __name__ == "__main__":
	main()
