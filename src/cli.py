from veteran_education_financial_readiness.models import (
    BenefitProfile,
    AnnualRatesConfig,
    SchoolType,
    RateOfPursuit,
)
from veteran_education_financial_readiness.calculations import (
    estimate_all_benefits_for_term,
)


def main():
    # TEMP: hard-coded example scenario (you can replace with input() later)
    cfg = AnnualRatesConfig(
        year_label="2025-2026",
        private_foreign_tuition_cap_year=29920.95,
        books_cap_year=1000.0,
        per_credit_books_full=41.67,
        terms_per_year=2,  # semester system
    )

    profile = BenefitProfile(
        gi_percentage=100,
        school_zip="92111",
        school_type=SchoolType.PUBLIC_IN_STATE,
        rate_of_pursuit=RateOfPursuit.FULL_TIME,
        credits_this_term=12,
        tuition_this_term=4000.0,
    )

    full_mha_for_zip = 2400.0  # example full MHA at 100% for this ZIP

    result = estimate_all_benefits_for_term(profile, cfg, full_mha_for_zip)

    print("=== Veteran Education Readiness – Estimate ===")
    print(f"GI %: {profile.gi_percentage}%")
    print(f"School ZIP: {profile.school_zip}")
    print(f"School type: {profile.school_type.value}")
    print()
    print(f"Estimated monthly housing:      ${result['monthly_housing']:.2f}")
    print(f"Estimated books for this term:  ${result['books_for_term']:.2f}")
    print(f"Tuition covered this term:      ${result['tuition_covered']:.2f}")
    print(f"Tuition out of pocket this term:${result['tuition_out_of_pocket']:.2f}")


if __name__ == "__main__":
    main()
