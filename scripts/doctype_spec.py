"""The decisions that turn the Access schema into Frappe DocTypes.

Data only -- generate_doctypes.py applies it. Everything here is a deliberate
choice about the legacy database, so it lives apart from the mechanical
conversion code.
"""

from rail_fms.index_config import COMPOSITE_INDEXES  # noqa: F401  (re-exported)

# Access table -> DocType name, grouped by the Frappe module that will own it.
# Access names carry no spaces-and-capitals convention and five of them contain
# "$" or quote characters, which cannot appear in a `tab<DocType>` table name.
MODULES = {
	"Rail Masters": {
		"Stations": "Railway Station",
		"Trains": "Train",
		"Commodities": "Commodity",
		"LeaseRates": "Lease Rate",
		"SplTrains": "Special Train",
		"SplClass": "Special Train Class",
		"STN_MAP": "Station Code Map",
		"PRS_MAP": "PRS Code Map",
		"TrainChange": "Train Renumbering",
		"TrainNew": "Train Renumbering New",
		"GenInfo": "Rail FMS Settings",
		"Suggestions": "Suggestion",
		"Errors": "Application Error",
	},
	"Passenger Earnings": {
		"EarnStn": "Station Earning",
		"EarnStn_2011": "Station Earning 2011",
		"EarnStn_2013": "Station Earning 2013",
		"EarnStn_MAR2006": "Station Earning Mar 2006",
		"EarnStn1": "Station Earning Snapshot",
		"EarnCopy": "Station Earning Copy",
		"stn_t": "Station Earning Staging",
		"EarnPRS": "PRS Earning",
		"EarnPRS_2011": "PRS Earning 2011",
		"EarnPRS_2013": "PRS Earning 2013",
		"EarnPRS_2015": "PRS Earning 2015",
		"EarnPRS_Cur": "PRS Earning Current",
		"EarnPRS_MAR2006": "PRS Earning Mar 2006",
		"EarnPRS 2018": "PRS Earning 2018",
		"Copy Of EarnPRS 30june2021": "PRS Earning Copy 30 Jun 2021",
		"prs_t": "PRS Earning Staging",
		"EarnDiv": "Division Earning",
		"CompSum": "Comparative Summary",
		"PRS_Sum_C": "PRS Summary Current",
		"PRS_Sum_P": "PRS Summary Previous",
		"Stn_Sum_C": "Station Summary Current",
		"Stn_Sum_P": "Station Summary Previous",
		"UtsOnMobile": "UTS On Mobile",
	},
	"Reservation And Occupancy": {
		"Waitlist": "Waitlist Position",
		"WL Oct 04": "Waitlist Position Oct 2004",
		"SplOcc": "Special Train Occupancy",
		"ExtraCoaches": "Extra Coach Attachment",
		"Unman": "Unmanned Coach Check",
		"Unm": "Unmanned Coach Check Staging",
	},
	"Parcel And Goods": {
		"Parcels": "Parcel Daily Position",
		"ParcelSpl": "Parcel Special Train",
		"ParcelEarn": "Parcel Earning",
		"ParcelCum": "Parcel Earning Cumulative",
		"LeftOvers": "Parcel Left Over",
		"CommLdg": "Commodity Loading",
		"Demands": "Wagon Demand",
		"Releases": "Wagon Release",
		"OnHandVPH": "On Hand VPH",
		"VPU": "VPU Loading",
		"Lease": "Lease Loading",
		"New_Lease": "Lease Loading New",
		"SLRUtil": "SLR Utilisation",
		"SLR": "SLR Monthly Utilisation",
	},
	"Operations And Performance": {
		"Failures": "Equipment Failure",
		"Actuals": "Division Actual",
		"Targets": "Division Target",
	},
	"Legacy Staging": {
		"Sheet1": "Legacy Sheet1",
		"Sheet2": "Legacy Sheet2",
		"Jan05": "Legacy Jan 2005",
		"Feb05": "Legacy Feb 2005",
		"Mar05": "Legacy Mar 2005",
		"Jun05": "Legacy Jun 2005",
		"Paste Errors": "Legacy Paste Error",
		"'02 AUG 2021$'_ImportErrors": "Legacy Import Error 02 Aug 2021",
		"'Summ (2)$'_ImportErrors": "Legacy Import Error Summ 2",
		"IMP$_ImportErrors1": "Legacy Import Error IMP",
		"Sheet1$_ImportErrors": "Legacy Import Error Sheet1",
		"Sheet4$_ImportErrors": "Legacy Import Error Sheet4",
		"Summ$_ImportErrors": "Legacy Import Error Summ",
		"Unman_ExportErrors": "Legacy Export Error Unman",
		"Unman_ExportErrors1": "Legacy Export Error Unman 1",
		"Waitlist_ExportErrors": "Legacy Export Error Waitlist",
	},
}

# Two Access tables are a matrix of entity x report-category, so the bare code
# repeats and cannot name a record. Splitting the category rows into a child
# table gives the parent a unique key, which is what the Link fields need.
#   Stations:    519 rows, 411 distinct codes, (Category, Station) unique
#   Commodities:  88 rows,  68 distinct names, (Category, Commodity) unique
SPLIT_TABLES = {
	"Stations": {
		"child_doctype": "Railway Station Category",
		"parent_fields": ["Station"],
		"table_fieldname": "categories",
		"table_label": "Categories",
	},
	"Commodities": {
		"child_doctype": "Commodity Category",
		"parent_fields": ["Commodity"],
		"table_fieldname": "categories",
		"table_label": "Categories",
	},
}

# Access column -> Frappe fieldname, where the mechanical snake_case is invalid
# or ambiguous. Keyed by (table, column); a bare column name applies everywhere.
FIELD_RENAMES = {
	("Stations", "Station"): "station_code",
	("Trains", "Train"): "train_no",
	("Commodities", "Commodity"): "commodity_name",
	("Trains", "Dir"): "dir_code",  # coexists with Direction
	("UtsOnMobile", "Date"): "uts_date",
	("UtsOnMobile", "RTOP AMT"): "rtop_amt",  # contains a space
	("ExtraCoaches", "Number"): "coach_count",
	("SplClass", "Class"): "travel_class",  # `class` breaks client-side JS
	("Releases", "Group"): "group_no",
	("LeaseRates", "Field1"): "field_1",
	("Paste Errors", "Field0"): "field_0",
}

# Applies to every table that has the column.
GLOBAL_FIELD_RENAMES = {
	"Type": "wagon_type",
	"Error": "error_message",
	"Field": "field_name",
	"Row": "row_no",
}

# Numeric columns that hold money rather than a count or a weight.
CURRENCY_COLUMNS = {
	"Amount", "Amount1", "Amount2", "Amount3", "Amt", "AmtP", "AmtL", "AmtTotal",
	"GrossEarn", "NetEarn", "Refund", "Earn", "Fare", "Rate", "PF", "CC",
	"Sundries", "PF_AVM", "SAMT", "JAMT", "PLAT_AMT", "BONUS_AMT", "CLERKAGE",
	"RTOP AMT", "total_amount", "MST", "QST", "HST", "YST",
	"PasEarnMon", "GdsEarnMon", "PlsEarnMon", "SunEarnMon",
	"PasEarnCum", "GdsEarnCum", "PlsEarnCum", "SunEarnCum",
	"P_PRS", "A_PRS", "P_Oth", "A_Oth", "Prior",
}

# Fieldname -> Link target. Applied after renaming.
LINK_TARGETS = {
	"station": "Railway Station",
	"station_code": "Railway Station",
	"from_stn": "Railway Station",
	"to_stn": "Railway Station",
	"destn": "Railway Station",
	"locn": "Railway Station",
	"stn_f": "Railway Station",
	"stn_t": "Railway Station",
	"load_from": "Railway Station",
	"load_to": "Railway Station",
	"train": "Train",
	"old_tr": "Train",
	"new_tr": "Train",
	"commodity": "Commodity",
	"def_comm": "Commodity",
}

# Link fields on the master itself would be self-referential.
NO_LINK = {("Railway Station", "station_code"), ("Train", "train_no")}

# Both key on SplTrains.Rec_ID, which the Access app joins on by hand.
REC_ID_LINKS = {"Special Train Class": "rec_id", "Special Train Occupancy": "rec_id"}

# Tables above ~10k rows. These get hash naming, no change tracking and indexes
# tuned for the daywise reports the Access app ran.
HIGH_VOLUME = {
	"EarnStn", "EarnStn_2011", "EarnStn_2013", "EarnStn_MAR2006", "EarnCopy", "stn_t",
	"EarnPRS", "EarnPRS_2011", "EarnPRS_2013", "EarnPRS_2015", "EarnPRS_Cur",
	"EarnPRS_MAR2006", "EarnPRS 2018", "Copy Of EarnPRS 30june2021",
	"Waitlist", "WL Oct 04", "Lease", "New_Lease", "SLRUtil", "Unman", "VPU",
	"Releases", "LeftOvers", "ExtraCoaches", "Failures", "CommLdg", "UtsOnMobile",
	"SplOcc", "SplClass", "OnHandVPH", "Unman_ExportErrors", "Unman_ExportErrors1",
}

# Masters named by a natural key instead of a hash. Special Train is absent on
# purpose: 147 of its 1562 rows carry Rec_ID 0 as a "no id" sentinel.
AUTONAME = {
	"Railway Station": "field:station_code",
	"Train": "field:train_no",
	"Commodity": "field:commodity_name",
}

TITLE_FIELDS = {
	"Railway Station": "station_code",
	"Train": "train_name",
	"Commodity": "commodity_name",
	"Special Train": "train",
	"Lease Rate": "party",
	"Station Code Map": "ccrb",
	"PRS Code Map": "ccrb",
}

SEARCH_FIELDS = {
	"Railway Station": "station_code",
	"Train": "train_no,train_name,from_stn,destn",
	"Commodity": "commodity_name",
	"Special Train": "train,from_stn,to_stn",
	"Lease Rate": "train,party,destn",
}

SINGLE_DOCTYPES = {"Rail FMS Settings"}

# Fields with no Access column behind them, appended after the ported ones.
# The importers invent records to satisfy links -- 84 off-division station codes
# appear in Trains.FromStn/Destn but not in Stations -- so those stay marked.
AUTO_CREATED_FIELD = {
	"fieldname": "auto_created",
	"fieldtype": "Check",
	"label": "Auto Created",
	"read_only": 1,
	"description": "Created to satisfy a link from imported data. Not present in the Access master.",
}

EXTRA_FIELDS = {
	"Railway Station": [AUTO_CREATED_FIELD],
	"Train": [AUTO_CREATED_FIELD],
	"Commodity": [AUTO_CREATED_FIELD],
}

# Columns that always deserve their own index. A column that leads a composite
# index is skipped, since the composite already covers it.
INDEXED_FIELDS = {"tr_date", "station", "train", "last_date", "rec_id", "uts_date", "st_date", "locn"}


# Frappe adds these itself; a DocType field of the same name breaks the ORM.
RESERVED_FIELDNAMES = {
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "parent",
	"parentfield", "parenttype", "idx", "doctype", "_user_tags", "_comments",
	"_assign", "_liked_by", "_seen",
}


def module_of(access_table):
	for module, tables in MODULES.items():
		if access_table in tables:
			return module
	raise KeyError(f"no module assigned to Access table {access_table!r}")


def doctype_of(access_table):
	return MODULES[module_of(access_table)][access_table]
