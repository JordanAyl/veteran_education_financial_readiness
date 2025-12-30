from models import BenefitProfile, AnnualRatesConfig, RateOfPursuit, SchoolType


def rate_of_pursuit_multiplier(rop: RateOfPursuit) -> float:
    """
    Approximate multipliers for housing based on rate of pursuit.

    These are simplified and intended for planning/estimation only,
    not as an exact replication of VA payment rules.
    """
    if rop == RateOfPursuit.FULL_TIME:
        return 1.0
    if rop == RateOfPursuit.THREE_QUARTER:
        return 0.75
    if rop == RateOfPursuit.HALF_TIME:
        return 0.5
    # Under half time: in practice there's often no housing.
    return 0.0

def estimate_monthly_housing(
    full_mha_for_zip: float,
    profile: BenefitProfile
) -> float:
    """
    Estimate monthly housing allowance (MHA) for a given profile.

    full_mha_for_zip:
        Full MHA for the school ZIP at 100% GI Bill equivalent
        (e.g., E-5 w/ dependents BAH for that ZIP).

    Returns:
        Estimated monthly housing amount in USD.
    """
    gi_mult = profile.gi_percentage / 100.0
    rop_mult = rate_of_pursuit_multiplier(profile.rate_of_pursuit)
    return full_mha_for_zip * gi_mult * rop_mult

def estimate_books_for_term(
    profile: BenefitProfile,
    cfg: AnnualRatesConfig
) -> float:
    """
    Estimate the book & supplies stipend for the given term.

    Steps:
      1. Per-credit amount * credits * GI percent
      2. Cap by the per-term share of the annual books cap
    """
    gi_mult = profile.gi_percentage / 100.0

    raw_for_term = cfg.per_credit_books_full * profile.credits_this_term * gi_mult
    per_term_cap = cfg.books_cap_year / cfg.terms_per_year

    return min(raw_for_term, per_term_cap)

def estimate_tuition_coverage_for_term(
    profile: BenefitProfile,
    cfg: AnnualRatesConfig
) -> dict:
    """
    Estimate how much tuition is covered vs out-of-pocket.

    Returns a dict:
        {
            "covered": float,
            "out_of_pocket": float,
        }
    """
    gi_mult = profile.gi_percentage / 100.0
    billed = profile.tuition_this_term

    if profile.school_type == SchoolType.PUBLIC_IN_STATE:
        # Simplified: GI % of billed amount.
        covered = billed * gi_mult
    else:
        # Private / foreign: apply national annual cap, split by terms.
        annual_cap_at_percent = cfg.private_foreign_tuition_cap_year * gi_mult
        per_term_cap_at_percent = annual_cap_at_percent / cfg.terms_per_year
        covered = min(billed, per_term_cap_at_percent)

    out_of_pocket = max(0.0, billed - covered)

    return {
        "covered": round(covered, 2),
        "out_of_pocket": round(out_of_pocket, 2),
    }

def estimate_all_benefits_for_term(
    profile: BenefitProfile,
    cfg: AnnualRatesConfig,
    full_mha_for_zip: float,
) -> dict:
    """
    High-level helper that returns all major benefit estimates for a term.

    Returns:
        {
            "monthly_housing": float,
            "books_for_term": float,
            "tuition_covered": float,
            "tuition_out_of_pocket": float,
        }
    """
    housing = estimate_monthly_housing(full_mha_for_zip, profile)
    books = estimate_books_for_term(profile, cfg)
    tuition_info = estimate_tuition_coverage_for_term(profile, cfg)

    return {
        "monthly_housing": round(housing, 2),
        "books_for_term": round(books, 2),
        "tuition_covered": tuition_info["covered"],
        "tuition_out_of_pocket": tuition_info["out_of_pocket"],
    }