"""Composite indexes for the ported Access tables.

DocType JSON cannot express a multi-column index, so
rail_fms/patches/v1_0/add_composite_indexes.py creates these. They back the
daywise reports the Access application ran (Netearn_Stn_Daywise, PRS_12Stn,
Netearn_PRS_Daywise and friends).
"""

COMPOSITE_INDEXES = {
	"Station Earning": ["tr_date", "station"],
	"Station Earning 2011": ["tr_date", "station"],
	"Station Earning 2013": ["tr_date", "station"],
	"Station Earning Mar 2006": ["tr_date", "station"],
	"Station Earning Copy": ["tr_date", "station"],
	"Station Earning Staging": ["tr_date", "station"],
	"PRS Earning": ["tr_date", "station"],
	"PRS Earning 2011": ["tr_date", "station"],
	"PRS Earning 2013": ["tr_date", "station"],
	"PRS Earning 2015": ["tr_date", "station"],
	"PRS Earning Current": ["tr_date", "station"],
	"PRS Earning Mar 2006": ["tr_date", "station"],
	"PRS Earning 2018": ["tr_date", "station"],
	"PRS Earning Copy 30 Jun 2021": ["tr_date", "station"],
	"Waitlist Position": ["tr_date", "train"],
	"Waitlist Position Oct 2004": ["tr_date", "train"],
	"Lease Loading": ["tr_date", "train"],
	"Lease Loading New": ["tr_date", "train"],
	"SLR Utilisation": ["tr_date", "train"],
	"Unmanned Coach Check": ["tr_date", "train"],
	"VPU Loading": ["tr_date", "train"],
	"Special Train Occupancy": ["tr_date", "train"],
	"Extra Coach Attachment": ["tr_date", "train"],
	"Wagon Release": ["tr_date", "station"],
	"Equipment Failure": ["tr_date", "station"],
	"Commodity Loading": ["tr_date", "station"],
	"UTS On Mobile": ["uts_date", "locn"],
}
