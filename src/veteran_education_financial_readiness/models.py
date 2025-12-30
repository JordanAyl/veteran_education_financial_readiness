from dataclasses import dataclass
from enum import Enum


class SchoolType(str, Enum):
    PUBLIC_IN_STATE = "public_in_state"
    PRIVATE_OR_FOREIGN = "private_or_foreign"


class RateOfPursuit(str, Enum):
    FULL_TIME = "full_time"
    THREE_QUARTER = "three_quarter"
    HALF_TIME = "half_time"
    LESS_THAN_HALF = "less_than_half"


@dataclass
class BenefitProfile:
    """
    Describes one education-benefit scenario for a veteran.

    This combines GI Bill / VR&E-style inputs that affect payment amounts
    for a single academic term.
    """
    gi_percentage: int           # e.g., 40, 50, 60, 70, 80, 90, 100
    school_zip: str              # school location ZIP (used for MHA lookup or manual input) Hard Coded
    school_type: SchoolType      # hard coded
    rate_of_pursuit: RateOfPursuit
    credits_this_term: int       # credit hours for the term
    tuition_this_term: float     # total billed tuition & fees this term (USD)


@dataclass
class AnnualRatesConfig:
    """
    Background configuration for a single academic year.

    These values come from VA / DoD reference tables and are not specific
    to any one veteran.
    """
    year_label: str                      # e.g. "2025-2026"
    private_foreign_tuition_cap_year: float
    books_cap_year: float                # typically around $1000 at 100% benefit
    per_credit_books_full: float         # per-credit book rate at 100% (approx.)
    terms_per_year: int                  # 2 for semester, 3 for quarter, etc.