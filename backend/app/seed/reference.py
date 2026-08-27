"""Static reference data for the seeded pilot (Section 14 step 1).

Everything here is synthetic. Section 12 and Section 14 both forbid real
children's data before consent and legal sign-off, so no row in this file
corresponds to a real person.

What is *not* synthetic: the districts, blocks and coordinates. Banswara and
Dungarpur are the actual pilot belt named in Section 1, and the coordinates are
real block centroids -- a district map built on invented geography is the kind
of detail a reviewer from DoIT&C notices immediately.
"""

from __future__ import annotations

# --- Centres --------------------------------------------------------------
# `child_count` and `age_band_months` drive generation. The Anandpuri entry is
# the one that exercises the WHO 2007 reference (deviation D1) -- without an
# Ashram school in the seed, half the growth code would never run in a demo.
AWCS: list[dict] = [
    {
        "awc_code": "RJ-BSW-GTL-001",
        "name_en": "Anganwadi Centre, Ghatol-1",
        "name_hi": "आंगनवाड़ी केंद्र, घाटोल-1",
        "centre_type": "anganwadi",
        "district": "Banswara",
        "district_hi": "बांसवाड़ा",
        "block": "Ghatol",
        "block_hi": "घाटोल",
        "latitude": 23.5556,
        "longitude": 74.2469,
        "child_count": 45,
        "age_band_months": (6, 71),
    },
    {
        "awc_code": "RJ-BSW-ANP-002",
        "name_en": "Government Ashram School, Anandpuri",
        "name_hi": "राजकीय आश्रम विद्यालय, आनंदपुरी",
        "centre_type": "ashram_school",
        "district": "Banswara",
        "district_hi": "बांसवाड़ा",
        "block": "Anandpuri",
        "block_hi": "आनंदपुरी",
        "latitude": 23.3167,
        "longitude": 74.1833,
        "child_count": 45,
        "age_band_months": (74, 168),  # ~6y to 14y: the WHO 2007 band
    },
    {
        "awc_code": "RJ-DGP-SGW-003",
        "name_en": "Anganwadi Centre, Sagwara-4",
        "name_hi": "आंगनवाड़ी केंद्र, सागवाड़ा-4",
        "centre_type": "anganwadi",
        "district": "Dungarpur",
        "district_hi": "डूंगरपुर",
        "block": "Sagwara",
        "block_hi": "सागवाड़ा",
        "latitude": 23.6667,
        "longitude": 74.0167,
        "child_count": 30,
        "age_band_months": (6, 71),
    },
]

# --- Staff ----------------------------------------------------------------
# Phone numbers are in the reserved 99999xxxxx test range, never real numbers.
FIELD_WORKERS: list[dict] = [
    {
        "phone": "9999900001",
        "name": "सुनीता देवी",
        "role": "field_worker",
        "awc_code": "RJ-BSW-GTL-001",
        "district": "Banswara",
    },
    {
        "phone": "9999900002",
        "name": "कविता मीणा",
        "role": "field_worker",
        "awc_code": "RJ-BSW-ANP-002",
        "district": "Banswara",
    },
    {
        "phone": "9999900003",
        "name": "रेखा डामोर",
        "role": "field_worker",
        "awc_code": "RJ-DGP-SGW-003",
        "district": "Dungarpur",
    },
    {
        "phone": "9999900010",
        "name": "महेश कुमार",
        "role": "district_official",
        "awc_code": None,
        "district": "Banswara",
    },
    {
        "phone": "9999900011",
        "name": "अनिता शर्मा",
        "role": "district_official",
        "awc_code": None,
        "district": "Dungarpur",
    },
    {
        "phone": "9999900020",
        "name": "डॉ. प्रिया जैन",
        "role": "state_admin",
        "awc_code": None,
        "district": None,
    },
]

# --- PM POSHAN menu vocabulary (deviation D4) -----------------------------
# `ifct_code` stays NULL until Phase 2 wires up IFCT 2017 (Section 4).
MENU_ITEMS: list[dict] = [
    {"code": "dal", "name_en": "Dal (lentils)", "name_hi": "दाल", "category": "pulse"},
    {"code": "roti", "name_en": "Roti", "name_hi": "रोटी", "category": "cereal"},
    {"code": "rice", "name_en": "Rice", "name_hi": "चावल", "category": "cereal"},
    {"code": "khichdi", "name_en": "Khichdi", "name_hi": "खिचड़ी", "category": "mixed"},
    {
        "code": "sabzi",
        "name_en": "Seasonal vegetable",
        "name_hi": "मौसमी सब्ज़ी",
        "category": "vegetable",
    },
    {"code": "banana", "name_en": "Banana", "name_hi": "केला", "category": "fruit"},
    {"code": "egg", "name_en": "Egg", "name_hi": "अंडा", "category": "protein"},
    {"code": "milk", "name_en": "Milk", "name_hi": "दूध", "category": "dairy"},
    {"code": "sprouts", "name_en": "Sprouted pulses", "name_hi": "अंकुरित दाल", "category": "pulse"},
    {"code": "halwa", "name_en": "Sweet halwa", "name_hi": "हलवा", "category": "mixed"},
]

#: PM POSHAN menu cycle by weekday (0 = Monday). Sunday is not a serving day.
MENU_CYCLE: dict[int, list[str]] = {
    0: ["dal", "roti", "sabzi", "banana"],
    1: ["khichdi", "sabzi", "milk"],
    2: ["dal", "rice", "sabzi", "egg"],
    3: ["roti", "sabzi", "sprouts", "banana"],
    4: ["dal", "rice", "sabzi", "milk"],
    5: ["khichdi", "halwa", "banana"],
}

#: Reasons a day gets flagged, mirroring the Gadchiroli precedent in Section 1:
#: menu non-compliance and food-quality issues invisible to a paper register.
FLAG_REASONS: list[tuple[str, str]] = [
    ("Prescribed {n} items, {m} detected", "निर्धारित {n} में से {m} वस्तुएँ मिलीं"),
    ("Dal appears watery across multiple plates", "कई थालियों में दाल पतली दिखी"),
    ("Fruit missing from served plates", "परोसी गई थाली में फल नहीं मिला"),
    ("Portion size below prescribed quantity", "मात्रा निर्धारित से कम पाई गई"),
    ("Egg not served on a prescribed egg day", "अंडा दिवस पर अंडा नहीं परोसा गया"),
]

# --- Synthetic names -------------------------------------------------------
GIRL_NAMES = [
    "कमला",
    "सीता",
    "गीता",
    "राधा",
    "लक्ष्मी",
    "सुशीला",
    "मंजू",
    "पूजा",
    "अनिता",
    "रीना",
    "ममता",
    "संगीता",
    "शारदा",
    "उर्मिला",
    "किरण",
    "बबीता",
    "निर्मला",
    "सरिता",
    "आशा",
    "मीरा",
]
BOY_NAMES = [
    "रमेश",
    "सुरेश",
    "महेश",
    "दिनेश",
    "राजू",
    "मुकेश",
    "कैलाश",
    "प्रकाश",
    "विनोद",
    "अशोक",
    "मनोज",
    "संजय",
    "अनिल",
    "सुनील",
    "दीपक",
    "अर्जुन",
    "भरत",
    "गोपाल",
    "हरीश",
    "जगदीश",
]
SURNAMES = ["डामोर", "मीणा", "कटारा", "निनामा", "खराड़ी", "पारगी", "बरंडा", "अहारी", "रोत", "मईड़ा"]
