import frappe

from rail_fms.index_config import COMPOSITE_INDEXES


def execute():
	"""Add the (date, code) indexes that DocType JSON cannot declare."""
	for doctype, columns in COMPOSITE_INDEXES.items():
		if frappe.db.table_exists(doctype):
			frappe.db.add_index(doctype, columns)
