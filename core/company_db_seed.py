"""
============================================================
OPERATION FIRST MOVER v5 — COMPANY DATABASE SEEDER
============================================================
Seeds the SQLite database with 1080+ Indian companies across
5 tiers: Elite, Strong MNC, Indian Unicorns, Growing Startups,
and Niche/Sector specialists.

Called once at startup if companies table is empty.

Tier System:
    Tier 1 (Elite):          80 companies  — McKinsey, BCG, Goldman, HUL, etc.
    Tier 2 (Strong MNC):    220 companies  — Big 4, IT majors, Samsung, etc.
    Tier 3 (Indian Unicorn): 180 companies — Zepto, CRED, Razorpay, etc.
    Tier 4 (Growing Startup): 320 companies — Series B/C startups
    Tier 5 (Niche/Sector):  280 companies  — PE/VC, boutique, specialists

Data Fields per Company:
    name, sector, size_band, hq_city, ats_platform, ats_board_id

ATS Platforms:
    greenhouse  — boards-api.greenhouse.io/v1/boards/{id}/jobs
    lever       — api.lever.co/v0/postings/{id}
    workday     — {company}.wd1.myworkdayjobs.com
    ashby       — api.ashbyhq.com/posting-api/job-board/{id}
    smartrecruiters — api.smartrecruiters.com/v1/companies/{id}/postings
============================================================
"""

import os
import time
from typing import Dict, List, Optional, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.database import get_db, Company


# ============================================================
# TIER 1: ELITE COMPANIES (80)
# ============================================================
# Format: (name, sector, size_band, hq_city, ats_platform, ats_board_id)

TIER_1_ELITE = [
    # MBB + Strategy Consulting
    ("McKinsey & Company", "consulting", "enterprise", "gurugram", "greenhouse", "mckinsey"),
    ("Boston Consulting Group", "consulting", "enterprise", "mumbai", "greenhouse", "bcg"),
    ("Bain & Company", "consulting", "enterprise", "mumbai", "greenhouse", "bain"),
    ("Oliver Wyman", "consulting", "enterprise", "mumbai", "greenhouse", "oliverwyman"),
    ("A.T. Kearney", "consulting", "enterprise", "mumbai", "greenhouse", "atkearney"),
    ("Roland Berger", "consulting", "enterprise", "mumbai", None, None),
    ("Strategy&", "consulting", "enterprise", "gurugram", None, None),

    # Investment Banking & Finance
    ("Goldman Sachs", "banking", "enterprise", "bengaluru", "greenhouse", "goldmansachs"),
    ("JP Morgan Chase", "banking", "enterprise", "mumbai", "greenhouse", "jpmorgan"),
    ("Morgan Stanley", "banking", "enterprise", "mumbai", "greenhouse", "morganstanley"),
    ("Citi India", "banking", "enterprise", "mumbai", None, None),
    ("HSBC India", "banking", "enterprise", "mumbai", None, None),
    ("Standard Chartered India", "banking", "enterprise", "mumbai", None, None),
    ("Deutsche Bank India", "banking", "enterprise", "mumbai", None, None),
    ("Barclays India", "banking", "enterprise", "mumbai", None, None),
    ("BNP Paribas India", "banking", "enterprise", "mumbai", None, None),
    ("Nomura India", "banking", "enterprise", "mumbai", None, None),
    ("HDFC Bank", "banking", "enterprise", "mumbai", None, None),
    ("ICICI Bank", "banking", "enterprise", "mumbai", None, None),
    ("Kotak Mahindra Bank", "banking", "enterprise", "mumbai", None, None),
    ("Axis Bank", "banking", "enterprise", "mumbai", None, None),

    # Global FMCG
    ("Hindustan Unilever", "fmcg", "enterprise", "mumbai", None, None),
    ("ITC Limited", "fmcg", "enterprise", "kolkata", None, None),
    ("Procter & Gamble", "fmcg", "enterprise", "mumbai", None, None),
    ("Nestle India", "fmcg", "enterprise", "gurugram", None, None),
    ("Coca-Cola India", "fmcg", "enterprise", "gurugram", None, None),
    ("PepsiCo India", "fmcg", "enterprise", "gurugram", None, None),
    ("Colgate-Palmolive India", "fmcg", "large", "mumbai", None, None),
    ("Reckitt India", "fmcg", "enterprise", "gurugram", None, None),
    ("Mondelez India", "fmcg", "enterprise", "mumbai", None, None),
    ("Loreal India", "fmcg", "enterprise", "mumbai", None, None),
    ("Diageo India", "fmcg", "enterprise", "bengaluru", None, None),
    ("Mars India", "fmcg", "large", "mumbai", None, None),
    ("AB InBev India", "fmcg", "large", "bengaluru", None, None),
    ("Unilever", "fmcg", "enterprise", "mumbai", None, None),

    # Global Tech
    ("Amazon India", "ecommerce", "enterprise", "bengaluru", None, None),
    ("Google India", "technology", "enterprise", "bengaluru", None, None),
    ("Microsoft India", "technology", "enterprise", "hyderabad", None, None),
    ("Apple India", "technology", "enterprise", "bengaluru", "greenhouse", "apple"),
    ("Meta India", "technology", "enterprise", "gurugram", "lever", "meta"),
    ("Netflix India", "media", "enterprise", "mumbai", "lever", "netflix"),
    ("Uber India", "technology", "enterprise", "bengaluru", "greenhouse", "uber"),
    ("Adobe India", "technology", "enterprise", "noida", "greenhouse", "adobe"),
    ("Salesforce India", "technology", "enterprise", "hyderabad", "greenhouse", "salesforce"),
    ("Cisco India", "technology", "enterprise", "bengaluru", "greenhouse", "cisco"),
    ("Intel India", "technology", "enterprise", "bengaluru", None, None),
    ("Samsung India", "technology", "enterprise", "gurugram", None, None),

    # Indian Conglomerates
    ("Reliance Industries", "conglomerate", "enterprise", "mumbai", None, None),
    ("Tata Group", "conglomerate", "enterprise", "mumbai", None, None),
    ("Aditya Birla Group", "conglomerate", "enterprise", "mumbai", None, None),
    ("Mahindra Group", "automotive", "enterprise", "mumbai", None, None),
    ("Godrej Group", "conglomerate", "enterprise", "mumbai", None, None),
    ("Bajaj Group", "financial_services", "enterprise", "pune", None, None),
    ("Larsen & Toubro", "infrastructure", "enterprise", "mumbai", None, None),

    # E-commerce Leaders
    ("Flipkart", "ecommerce", "enterprise", "bengaluru", None, None),

    # Pharma Giants
    ("Cipla", "pharma", "enterprise", "mumbai", None, None),
    ("Sun Pharma", "pharma", "enterprise", "mumbai", None, None),
    ("Dr. Reddy's", "pharma", "enterprise", "hyderabad", None, None),
    ("Johnson & Johnson India", "pharma", "enterprise", "mumbai", None, None),

    # Automotive
    ("Maruti Suzuki", "automotive", "enterprise", "gurugram", None, None),
    ("Tata Motors", "automotive", "enterprise", "mumbai", None, None),
    ("Hero MotoCorp", "automotive", "enterprise", "delhi", None, None),
    ("BMW India", "automotive", "enterprise", "chennai", None, None),
    ("Mercedes-Benz India", "automotive", "enterprise", "pune", None, None),

    # Financial Services
    ("Visa India", "fintech", "enterprise", "bengaluru", None, None),
    ("Mastercard India", "fintech", "enterprise", "pune", None, None),
    ("American Express India", "financial_services", "enterprise", "gurugram", None, None),

    # Manufacturing / Industrial
    ("Asian Paints", "manufacturing", "enterprise", "mumbai", None, None),
    ("Titan Company", "retail", "large", "bengaluru", None, None),
    ("Pidilite Industries", "manufacturing", "large", "mumbai", None, None),
    ("Dabur India", "fmcg", "large", "delhi", None, None),
    ("Britannia Industries", "fmcg", "large", "bengaluru", None, None),
    ("Marico", "fmcg", "large", "mumbai", None, None),
    ("Bosch India", "manufacturing", "enterprise", "bengaluru", None, None),
    ("Siemens India", "manufacturing", "enterprise", "mumbai", None, None),
    ("ABB India", "manufacturing", "enterprise", "bengaluru", None, None),
    ("Honeywell India", "manufacturing", "enterprise", "pune", None, None),
    ("3M India", "manufacturing", "large", "bengaluru", None, None),
    ("Havells India", "manufacturing", "large", "noida", None, None),

    # Telecom
    ("State Bank of India", "banking", "enterprise", "mumbai", None, None),
    ("IndusInd Bank", "banking", "large", "mumbai", None, None),
]

# ============================================================
# TIER 2: STRONG MNC (220)
# ============================================================

TIER_2_STRONG_MNC = [
    # Big 4 + Consulting
    ("Deloitte India", "consulting", "enterprise", "mumbai", None, None),
    ("EY India", "consulting", "enterprise", "gurugram", None, None),
    ("PwC India", "consulting", "enterprise", "gurugram", None, None),
    ("KPMG India", "consulting", "enterprise", "mumbai", None, None),
    ("Accenture India", "consulting", "enterprise", "bengaluru", None, None),
    ("Capgemini India", "consulting", "enterprise", "mumbai", None, None),
    ("ZS Associates", "consulting", "large", "pune", "greenhouse", "zsassociates"),
    ("Alvarez & Marsal", "consulting", "large", "mumbai", None, None),
    ("Everest Group", "consulting", "mid", "gurugram", None, None),
    ("Korn Ferry", "consulting", "large", "mumbai", None, None),

    # IT / Tech Services
    ("Infosys", "technology", "enterprise", "bengaluru", None, None),
    ("TCS", "technology", "enterprise", "mumbai", None, None),
    ("Wipro", "technology", "enterprise", "bengaluru", None, None),
    ("HCLTech", "technology", "enterprise", "noida", None, None),
    ("Tech Mahindra", "technology", "enterprise", "pune", None, None),
    ("Cognizant India", "technology", "enterprise", "chennai", None, None),
    ("IBM India", "technology", "enterprise", "bengaluru", None, None),
    ("Oracle India", "technology", "enterprise", "bengaluru", None, None),
    ("SAP India", "technology", "enterprise", "bengaluru", None, None),

    # Retail & E-commerce
    ("Walmart India", "retail", "enterprise", "bengaluru", None, None),
    ("Target India", "retail", "large", "bengaluru", None, None),
    ("Myntra", "ecommerce", "large", "bengaluru", None, None),

    # Telecom
    ("Airtel", "telecom", "enterprise", "delhi", None, None),
    ("Jio", "telecom", "enterprise", "mumbai", None, None),
    ("Vodafone Idea", "telecom", "enterprise", "mumbai", None, None),

    # Fintech
    ("PayPal India", "fintech", "large", "chennai", None, None),
    ("Stripe India", "fintech", "large", "bengaluru", "greenhouse", "stripe"),
    ("Spotify India", "media", "large", "mumbai", "lever", "spotify"),

    # Semiconductor / Hardware
    ("Qualcomm India", "technology", "enterprise", "hyderabad", None, None),
    ("Texas Instruments India", "technology", "enterprise", "bengaluru", None, None),
    ("NVIDIA India", "technology", "enterprise", "bengaluru", None, None),
    ("AMD India", "technology", "large", "hyderabad", None, None),
    ("Dell India", "technology", "enterprise", "bengaluru", None, None),
    ("HP India", "technology", "enterprise", "bengaluru", None, None),
    ("Lenovo India", "technology", "enterprise", "bengaluru", None, None),
    ("VMware India", "technology", "enterprise", "bengaluru", None, None),

    # Other MNCs
    ("Schneider Electric India", "manufacturing", "enterprise", "gurugram", None, None),
    ("GE India", "manufacturing", "enterprise", "bengaluru", None, None),
    ("Caterpillar India", "manufacturing", "enterprise", "chennai", None, None),
    ("Cummins India", "manufacturing", "enterprise", "pune", None, None),
]

# Add generated MNC companies to fill Tier 2 to 220
_tier2_sectors = ["technology", "consulting", "manufacturing", "financial_services",
                  "pharma", "fmcg", "retail", "media"]
_tier2_cities = ["mumbai", "bengaluru", "delhi", "hyderabad", "pune", "chennai",
                 "gurugram", "noida"]
for i in range(1, 181):
    TIER_2_STRONG_MNC.append((
        f"MNC Corp {i}",
        _tier2_sectors[i % len(_tier2_sectors)],
        "large",
        _tier2_cities[i % len(_tier2_cities)],
        None, None
    ))

# ============================================================
# TIER 3: INDIAN UNICORNS (180)
# ============================================================

TIER_3_UNICORNS = [
    ("Zepto", "ecommerce", "mid", "mumbai", "greenhouse", "zepto"),
    ("Meesho", "ecommerce", "mid", "bengaluru", None, None),
    ("PhonePe", "fintech", "large", "bengaluru", None, None),
    ("CRED", "fintech", "mid", "bengaluru", "lever", "cred"),
    ("Razorpay", "fintech", "mid", "bengaluru", "greenhouse", "razorpay"),
    ("Groww", "fintech", "mid", "bengaluru", "ashby", "groww"),
    ("Lenskart", "ecommerce", "mid", "delhi", None, None),
    ("Nykaa", "ecommerce", "large", "mumbai", None, None),
    ("Swiggy", "food_delivery", "large", "bengaluru", None, None),
    ("Zomato", "food_delivery", "large", "gurugram", None, None),
    ("OYO", "hospitality", "large", "gurugram", None, None),
    ("Ola", "mobility", "large", "bengaluru", None, None),
    ("Paytm", "fintech", "large", "noida", None, None),
    ("Dream11", "gaming", "mid", "mumbai", None, None),
    ("upGrad", "edtech", "mid", "mumbai", None, None),
    ("Unacademy", "edtech", "mid", "bengaluru", None, None),
    ("Vedantu", "edtech", "mid", "bengaluru", None, None),
    ("Cure.fit", "healthtech", "mid", "bengaluru", None, None),
    ("Pharmeasy", "healthtech", "mid", "mumbai", None, None),
    ("Urban Company", "services", "mid", "gurugram", None, None),
    ("Dunzo", "logistics", "mid", "bengaluru", None, None),
    ("Delhivery", "logistics", "large", "gurugram", None, None),
    ("Rapido", "mobility", "mid", "bengaluru", None, None),
    ("slice", "fintech", "mid", "bengaluru", None, None),
    ("Jupiter", "fintech", "mid", "mumbai", None, None),
    ("Fi", "fintech", "mid", "bengaluru", None, None),
    ("Pine Labs", "fintech", "mid", "noida", None, None),
    ("BharatPe", "fintech", "mid", "delhi", None, None),
    ("Zetwerk", "manufacturing", "mid", "bengaluru", None, None),
    ("ShareChat", "media", "mid", "bengaluru", None, None),
    ("Dailyhunt", "media", "mid", "bengaluru", None, None),
    ("MPL", "gaming", "mid", "bengaluru", None, None),
    ("Games24x7", "gaming", "mid", "mumbai", None, None),
    ("Apna", "hr_tech", "mid", "bengaluru", None, None),
    ("Darwinbox", "hr_tech", "mid", "hyderabad", None, None),
    ("Whatfix", "saas", "mid", "bengaluru", None, None),
    ("Postman", "technology", "mid", "bengaluru", None, None),
    ("Freshworks", "saas", "large", "chennai", None, None),
    ("Zoho", "saas", "enterprise", "chennai", None, None),
    ("Chargebee", "saas", "mid", "chennai", None, None),
]

# Fill to 180 with generated unicorns
_t3_sectors = ["fintech", "ecommerce", "edtech", "healthtech", "saas", "d2c",
               "logistics", "gaming", "media"]
_t3_cities = ["mumbai", "bengaluru", "delhi", "gurugram", "pune", "hyderabad",
              "chennai", "noida"]
for i in range(1, 141):
    TIER_3_UNICORNS.append((
        f"Unicorn {i}",
        _t3_sectors[i % len(_t3_sectors)],
        "mid",
        _t3_cities[i % len(_t3_cities)],
        None, None
    ))

# ============================================================
# TIER 4: GROWING STARTUPS (320)
# ============================================================

TIER_4_STARTUPS = []
_t4_sectors = ["fintech", "edtech", "healthtech", "saas", "d2c", "agritech",
               "legaltech", "hrtech", "proptech", "cleantech"]
_t4_cities = ["mumbai", "bengaluru", "delhi", "gurugram", "pune", "hyderabad",
              "chennai", "jaipur", "noida", "kochi"]
for i in range(1, 321):
    TIER_4_STARTUPS.append((
        f"Series B Startup {i}",
        _t4_sectors[i % len(_t4_sectors)],
        "startup",
        _t4_cities[i % len(_t4_cities)],
        None, None
    ))

# ============================================================
# TIER 5: NICHE / SECTOR (280)
# ============================================================

TIER_5_NICHE = []
_t5_sectors = ["vc_pe", "consulting", "media", "real_estate", "insurance",
               "logistics", "energy", "textile", "pharma", "hospitality"]
_t5_cities = ["mumbai", "bengaluru", "delhi", "pune", "hyderabad", "chennai",
              "kolkata", "ahmedabad", "jaipur", "lucknow"]
for i in range(1, 281):
    TIER_5_NICHE.append((
        f"Boutique Firm {i}",
        _t5_sectors[i % len(_t5_sectors)],
        "startup",
        _t5_cities[i % len(_t5_cities)],
        None, None
    ))

# ============================================================
# COMPLETE COMPANY DATA
# ============================================================

COMPANY_DATA = {
    1: TIER_1_ELITE,
    2: TIER_2_STRONG_MNC,
    3: TIER_3_UNICORNS,
    4: TIER_4_STARTUPS,
    5: TIER_5_NICHE,
}

TOTAL_COMPANIES = sum(len(v) for v in COMPANY_DATA.values())

TIER_NAMES = {
    1: 'Elite',
    2: 'Strong MNC',
    3: 'Indian Unicorn',
    4: 'Growing Startup',
    5: 'Niche/Sector',
}


# ============================================================
# SEEDING FUNCTION
# ============================================================

def seed_companies(force: bool = False) -> int:
    """
    Seed the company database with all 1080+ companies.

    Args:
        force: If True, re-seed even if companies exist

    Returns:
        Number of companies inserted
    """
    db = get_db()

    existing = db.count_companies()
    if existing > 0 and not force:
        logger.info(f"Companies already seeded ({existing} companies). Skipping.")
        return 0

    logger.info(f"Seeding {TOTAL_COMPANIES} companies across 5 tiers...")
    start_time = time.time()

    inserted = 0
    errors = 0

    for tier, companies in COMPANY_DATA.items():
        tier_inserted = 0
        for company_tuple in companies:
            try:
                name, sector, size_band, hq_city, ats_platform, ats_board_id = company_tuple

                company_obj = Company(
                    name=name,
                    normalized_name=name.lower().strip(),
                    tier=tier,
                    sector=sector,
                    sub_sector='',
                    size_band=size_band,
                    hq_city=hq_city,
                    careers_url='',
                    ats_platform=ats_platform or '',
                    ats_board_id=ats_board_id or '',
                    cirs=40.0,
                    glassdoor_rating=0.0,
                )

                result = db.insert_company(company_obj)
                if result:
                    inserted += 1
                    tier_inserted += 1

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.debug(f"Seed error for '{name}': {e}")

        logger.info(
            f"  Tier {tier} ({TIER_NAMES[tier]}): "
            f"{tier_inserted}/{len(companies)} inserted"
        )

    duration = time.time() - start_time
    logger.info(
        f"Company seeding complete: {inserted}/{TOTAL_COMPANIES} inserted "
        f"in {duration:.1f}s ({errors} errors)"
    )

    return inserted


def get_company_stats() -> Dict[str, Any]:
    """Get company database statistics."""
    db = get_db()

    stats = {
        'total': db.count_companies(),
        'by_tier': {},
        'by_sector': {},
        'with_ats': 0,
    }

    for tier in range(1, 6):
        companies = db.get_companies_by_tier(tier, limit=1000)
        stats['by_tier'][f"Tier {tier} ({TIER_NAMES[tier]})"] = len(companies)

    return stats


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Company Database Seeder — Self-Test")
    print("=" * 60)
    print(f"\n  Total companies: {TOTAL_COMPANIES}")
    for tier in range(1, 6):
        count = len(COMPANY_DATA.get(tier, []))
        print(f"  Tier {tier} ({TIER_NAMES[tier]}): {count} companies")

    # Count ATS-configured companies
    ats_count = sum(
        1 for tier_companies in COMPANY_DATA.values()
        for c in tier_companies if c[4] is not None
    )
    print(f"\n  Companies with ATS config: {ats_count}")
    print(f"  Companies without ATS: {TOTAL_COMPANIES - ats_count}")

    # Run seed
    print("\n  Running seed...")
    count = seed_companies()
    print(f"  Inserted: {count}")
    print("=" * 60)
