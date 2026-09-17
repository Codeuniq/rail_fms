"""Convert a value read from Access into what a Frappe fieldtype expects.

Access has one DateTime type for dates, times and timestamps alike, so the
target fieldtype decides which of the three a value becomes.
"""

from __future__ import annotations

import datetime

# Access counts days from this epoch; the fractional part is the time of day.
ACCESS_EPOCH = datetime.datetime(1899, 12, 30)


def to_frappe_value(value, fieldtype):
	if value is None:
		return None

	if fieldtype == "Date":
		return access_datetime(value).date()
	if fieldtype == "Time":
		return access_datetime(value).time()
	if fieldtype == "Datetime":
		return access_datetime(value)
	if fieldtype in ("Currency", "Float", "Percent"):
		return float(value)
	if fieldtype in ("Int", "Check"):
		return int(value)

	text = str(value).strip()
	return text or None


def access_datetime(days):
	return ACCESS_EPOCH + datetime.timedelta(days=float(days))
