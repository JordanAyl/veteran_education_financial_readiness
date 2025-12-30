
# config.py

from models import AnnualRatesConfig

# Demo values, tweak these to match the real VA tables.
DEFAULT_ANNUAL_RATES = AnnualRatesConfig(
    year_label="2025-2026",
    private_foreign_tuition_cap_year=29000.0,  # example national cap
    books_cap_year=1000.0,                      # approx full-year books cap
    per_credit_books_full=41.67,                # ~ $1000 / 24 credits
    terms_per_year=2,                           # 2 semesters per year
)


# Super simple placeholder: in reality you'd hit a real BAH/MHA source.
# For now we let the user type it, but we keep this helper in case
# we later want logic by ZIP.
def get_full_mha_for_zip(zip_code: str) -> float:
    """
    Return the full (100% GI Bill equivalent) MHA / BAH
    for the provided ZIP code.

    For now this is just a stub. You can customize it manually or
    replace it later with a real lookup or API.
    """
    # TODO: hook this up to a real table.
    return 4000.0  # example default