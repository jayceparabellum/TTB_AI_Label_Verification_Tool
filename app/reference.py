"""Pinned regulatory reference data.

The government-warning string below is the strict reference for the warning
check. It is the statement mandated by 27 CFR Sec. 16.21, verified verbatim
against Cornell LII (https://www.law.cornell.edu/cfr/text/27/16.21) on
2026-06-17. Do NOT paraphrase or "tidy" this text — the warning check compares
against it exactly (modulo whitespace).
"""

# The literal all-caps header that must be present, exactly, on a compliant label.
WARNING_HEADER = "GOVERNMENT WARNING:"

# The full official warning statement (27 CFR 16.21).
OFFICIAL_GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
