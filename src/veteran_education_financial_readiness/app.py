import streamlit as st
import pandas as pd
import altair as alt

from contextlib import nullcontext
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

from models import BenefitProfile, RateOfPursuit, SchoolType
from calculations import estimate_all_benefits_for_term
from bah_rates_2026_data import (
    e05_rate_for_code,
    label_to_code,
    list_location_labels,
)
from config import DEFAULT_ANNUAL_RATES


# -----------------------------
# Helper: generate monthly dates
# -----------------------------


def generate_months(start_date: date, end_date: date) -> List[date]:
    """
    Generate a list of date objects representing the first day
    of each month between start_date and end_date (inclusive).
    """
    months = []
    year = start_date.year
    month = start_date.month

    while True:
        current = date(year, month, 1)
        if current > end_date:
            break
        months.append(current)

        # move to next month
        month += 1
        if month > 12:
            month = 1
            year += 1

    return months


def build_forecast(
    start_date: date,
    end_date: date,
    starting_savings: float,
    bah_full_time_base: float,
    disability_monthly: float,
    other_income_monthly: float,
    fixed_expenses_monthly: float,
    variable_expenses_monthly: float,
    scheduled_one_time_expenses: List[Dict[str, Any]],
    term_configs: List[Dict[str, Any]],
):
    """
    Build a monthly cashflow forecast.

    - BAH is based on bah_full_time_base * multiplier
    - multiplier depends on which term (if any) the month falls into
      and that term's enrollment intensity (full / 3/4 / half / < half).
    - If multiple terms overlapped (rare), we use the highest multiplier.
    """
    dates = generate_months(start_date, end_date)

    data = []
    balance = starting_savings
    one_time_expense_applied = set()

    for d in dates:
        # Find which terms are active this month
        active_terms = [
            cfg for cfg in term_configs
            if cfg["start"] is not None
            and cfg["end"] is not None
            and cfg["start"] <= d <= cfg["end"]
        ]

        if active_terms:
            # Use the term with the highest multiplier for BAH
            active_cfg = max(active_terms, key=lambda c: c["multiplier"])
            enrollment_label = active_cfg["rate_label"]
            multiplier = active_cfg["multiplier"]
            in_school = True
        else:
            enrollment_label = "Not enrolled"
            multiplier = 0.0
            in_school = False

        income_bah = bah_full_time_base * multiplier
        income_disability = disability_monthly
        income_other = other_income_monthly
        total_income = income_bah + income_disability + income_other

        scheduled_one_time_total = 0.0
        for exp in scheduled_one_time_expenses:
            if not exp.get("enabled", True):
                continue

            amount = float(exp.get("amount", 0.0) or 0.0)
            if amount <= 0:
                continue

            month_due = int(exp.get("month", 1) or 1)
            frequency = exp.get("frequency", "Annual")
            unique_key = str(exp.get("id", "expense"))

            apply_now = False
            if frequency == "Annual":
                apply_now = d.month == month_due
            elif frequency == "Quarterly":
                apply_now = (d.month - month_due) % 3 == 0
            elif frequency == "Semiannual":
                apply_now = (d.month - month_due) % 6 == 0
            else:  # One-time
                once_key = f"{unique_key}:{d.year}:{month_due}"
                apply_now = d.year == start_date.year and d.month == month_due and once_key not in one_time_expense_applied
                if apply_now:
                    one_time_expense_applied.add(once_key)

            if apply_now:
                scheduled_one_time_total += amount

        total_expenses = fixed_expenses_monthly + variable_expenses_monthly + scheduled_one_time_total
        net = total_income - total_expenses
        balance += net

        data.append(
            {
                "Month": d,
                "Enrollment status":  enrollment_label,
                #"In school full-time?": "Yes" if in_school else "No",
                "MHA": income_bah,
                "Disability": income_disability,
                "Other income": income_other,
                "Total income": total_income,
                "Fixed expenses": fixed_expenses_monthly,
                "Variable expenses": variable_expenses_monthly,
                "Scheduled one-time expenses": scheduled_one_time_total,
                "Total expenses": total_expenses,
                "Net cash": net,
                "Projected balance": balance,
            }
        )

    df = pd.DataFrame(data)
    return df


def _inject_custom_css() -> None:
    """Use Streamlit theme tokens so light/dark mode (Settings → Theme) stays coherent."""
    # Streamlit does not expose its theme as CSS variables, but it does set
    # `color-scheme` on .stApp for the theme it is actually rendering. Using
    # light-dark() lets the browser resolve the tokens against that — so the
    # palette follows live theme switches without a script rerun and can never
    # disagree with Streamlit's own text colors.
    st.markdown(
        """
<style>
    .stApp {
        --st-primary-color: light-dark(#1e3a8a, #60a5fa);
        --st-background-color: light-dark(#eef1f6, #0f172a);
        --st-secondary-background-color: light-dark(#e2e8f0, #1e293b);
        --st-text-color: light-dark(#0f172a, #f8fafc);
        /* Card surface: true white on the tinted canvas (one step lighter than
           the page) so elevation comes from value contrast, not borders. */
        --vefr-surface: light-dark(#ffffff, #1e293b);
        --vefr-shadow:
            0 1px 2px color-mix(in srgb, var(--st-text-color) 5%, transparent),
            0 10px 28px color-mix(in srgb, var(--st-text-color) 6%, transparent);
    }
</style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
    /* Core: follow active Streamlit theme (injected --st-* variables on :root) */
    .stApp {
        font-family: "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, sans-serif;
        color: var(--st-text-color);
        background: var(--st-background-color);
    }
    .stApp {
        /* Canvas texture, top to bottom: film grain, blueprint dot grid (echoes
           the hero), glow accents, base gradient. Cards stay untextured white so
           content reads crisp against the textured canvas. */
        background:
            url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E"),
            radial-gradient(circle at 1px 1px, color-mix(in srgb, var(--st-primary-color) 7%, transparent) 1px, transparent 1.6px),
            radial-gradient(ellipse 120% 80% at 100% -20%, color-mix(in srgb, var(--st-primary-color) 14%, transparent), transparent 50%),
            radial-gradient(ellipse 80% 50% at 0% 100%, color-mix(in srgb, var(--st-primary-color) 8%, transparent), transparent 45%),
            linear-gradient(
                168deg,
                color-mix(in srgb, var(--st-background-color) 88%, var(--st-primary-color)) 0%,
                var(--st-background-color) 42%,
                color-mix(in srgb, var(--st-background-color) 96%, var(--st-secondary-background-color)) 100%
            );
        background-size: 180px 180px, 22px 22px, 100% 100%, 100% 100%, 100% 100%;
        background-attachment: fixed;
    }
    [data-testid="stAppViewContainer"] .block-container {
        padding-top: 0.5rem;
        padding-bottom: 2.5rem;
        max-width: min(1180px, 100%);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(
            180deg,
            color-mix(in srgb, var(--st-secondary-background-color) 70%, var(--st-background-color)) 0%,
            var(--st-secondary-background-color) 35%,
            var(--st-secondary-background-color) 100%
        );
        border-right: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
        box-shadow: inset 4px 0 0 0 var(--st-primary-color);
    }
    /* Fixed wide sidebar on desktop only; mobile keeps Streamlit's
       collapsible overlay so the 375px viewport never scrolls sideways */
    @media (min-width: 992px) {
        [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }
        [data-testid="stSidebar"] {
            min-width: 460px !important;
            max-width: 460px !important;
        }
    }
    [data-testid="stSidebar"] [data-testid="stMarkdown"] h1,
    [data-testid="stSidebar"] [data-testid="stMarkdown"] h2,
    [data-testid="stSidebar"] [data-testid="stMarkdown"] h3,
    [data-testid="stSidebar"] [data-testid="stMarkdown"] h4 {
        color: var(--st-text-color);
        letter-spacing: 0.02em;
    }
    /* Sidebar: intro + grouped panels */
    .vefr-sidebar-intro {
        padding: 0.15rem 0 0.85rem;
        margin-bottom: 0.35rem;
        border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    }
    .vefr-sidebar-kicker {
        margin: 0 0 0.2rem 0;
        font-size: 0.68rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: color-mix(in srgb, var(--st-text-color) 55%, transparent);
    }
    .vefr-sidebar-title {
        margin: 0 0 0.25rem 0;
        font-size: 1.25rem;
        font-weight: 700;
        color: var(--st-text-color);
        letter-spacing: -0.02em;
    }
    .vefr-sidebar-blurb {
        margin: 0;
        font-size: 0.85rem;
        line-height: 1.45;
        color: color-mix(in srgb, var(--st-text-color) 72%, transparent);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        border: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent);
        border-radius: 6px;
        margin-bottom: 0.55rem;
        overflow: hidden;
        background: color-mix(
            in srgb,
            var(--st-background-color) 25%,
            var(--st-secondary-background-color)
        );
        background-image: linear-gradient(
            180deg,
            color-mix(in srgb, var(--st-primary-color) 6%, transparent) 0%,
            transparent 42%
        );
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details > summary {
        font-weight: 600;
        letter-spacing: 0.02em;
        padding: 0.5rem 0.65rem;
        border-radius: 4px;
        background: color-mix(in srgb, var(--st-primary-color) 7%, transparent);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] {
        padding-top: 0.15rem;
    }
    /* Sidebar widgets: clear field frames (numbers/options not “floating”) */
    [data-testid="stSidebar"] [data-testid="stNumberInput"],
    [data-testid="stSidebar"] [data-testid="stSelectbox"],
    [data-testid="stSidebar"] [data-testid="stDateInput"] {
        border: 1px solid color-mix(in srgb, var(--st-text-color) 20%, transparent);
        border-radius: 4px;
        padding: 0.45rem 0.6rem 0.5rem;
        margin-bottom: 0.45rem;
        background-color: color-mix(
            in srgb,
            var(--st-background-color) 55%,
            var(--st-secondary-background-color)
        );
    }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] {
        border: 1px solid color-mix(in srgb, var(--st-text-color) 16%, transparent);
        border-radius: 4px;
        padding: 0.35rem 0.5rem;
        margin-bottom: 0.35rem;
        background-color: color-mix(
            in srgb,
            var(--st-background-color) 45%,
            var(--st-secondary-background-color)
        );
    }
    /* Single outline: hide inner Base Web borders so the outer frame is the only box */
    [data-testid="stSidebar"] [data-testid="stNumberInput"] div[data-baseweb="input"],
    [data-testid="stSidebar"] [data-testid="stDateInput"] div[data-baseweb="input"] {
        border: none !important;
        box-shadow: none !important;
        background-color: transparent !important;
    }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        border: none !important;
        box-shadow: none !important;
        background-color: transparent !important;
    }
    /* Fallback if a Streamlit version omits widget test ids: still frame native controls */
    [data-testid="stSidebar"] div[data-baseweb="input"] {
        border: 1px solid color-mix(in srgb, var(--st-text-color) 20%, transparent) !important;
        border-radius: 4px !important;
        background-color: color-mix(
            in srgb,
            var(--st-background-color) 55%,
            var(--st-secondary-background-color)
        ) !important;
    }
    [data-testid="stSidebar"] div[data-baseweb="select"] > div {
        border: 1px solid color-mix(in srgb, var(--st-text-color) 20%, transparent) !important;
        border-radius: 4px !important;
        background-color: color-mix(
            in srgb,
            var(--st-background-color) 55%,
            var(--st-secondary-background-color)
        ) !important;
    }
    div[data-testid="stVerticalBlock"] > div:has(> div.vefr-hero) {
        margin-bottom: 0.25rem;
    }
    /* Hero: brand band + soft highlights */
    .vefr-hero {
        position: relative;
        overflow: hidden;
        /* Layers, top to bottom: film grain, blueprint dot grid, glow accents, base gradient */
        background-image:
            url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)' opacity='0.06'/%3E%3C/svg%3E"),
            radial-gradient(circle at 1px 1px, rgba(248, 250, 252, 0.09) 1px, transparent 1.6px),
            radial-gradient(ellipse 70% 120% at 100% 0%, rgba(59, 130, 246, 0.20), transparent 55%),
            radial-gradient(ellipse 50% 80% at 0% 100%, rgba(201, 162, 39, 0.16), transparent 50%),
            linear-gradient(135deg, #0f172a 0%, #16244b 55%, #1e3a8a 100%);
        background-size: 180px 180px, 22px 22px, 100% 100%, 100% 100%, 100% 100%;
        color: #f8fafc;
        padding: 1.85rem 1.95rem 1.65rem;
        border-radius: 8px;
        margin: 0 0 1.35rem 0;
        box-shadow:
            0 4px 6px color-mix(in srgb, var(--st-text-color) 8%, transparent),
            0 20px 50px color-mix(in srgb, #1e3a8a 35%, transparent);
        border: 1px solid color-mix(in srgb, rgba(255, 255, 255, 0.2) 100%, transparent);
    }
    .vefr-hero-kicker {
        margin: 0 0 0.35rem 0;
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: #c9a227;
    }
    .vefr-hero-title {
        margin: 0 0 0.5rem 0;
        font-size: clamp(1.45rem, 3vw, 1.85rem);
        font-weight: 700;
        line-height: 1.2;
        letter-spacing: -0.02em;
    }
    .vefr-hero-sub {
        margin: 0;
        font-size: 1rem;
        line-height: 1.55;
        color: #cbd5e1;
        max-width: 42rem;
    }
    .vefr-hero-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-top: 1.05rem;
    }
    .vefr-hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 500;
        color: #e2e8f0;
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.14);
    }
    .vefr-hero-badge svg {
        color: #d9b64a;
        flex: none;
    }
    .vefr-mobile-hint {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        margin-top: 0.8rem;
        padding: 0.5rem 0.75rem;
        background: rgba(255, 255, 255, 0.08);
        border-radius: 4px;
        font-size: 0.875rem;
        color: #e2e8f0;
    }
    .vefr-mobile-hint svg {
        flex: none;
        color: #cbd5e1;
    }
    /* First-run onboarding panel (shown until the user enters any numbers) */
    .vefr-start {
        padding: 1.15rem 1.3rem 1.25rem;
        border-radius: 6px;
        border: 1px solid color-mix(in srgb, var(--st-text-color) 11%, transparent);
        border-left: 4px solid #c9a227;
        background: color-mix(in srgb, var(--st-secondary-background-color) 45%, var(--st-background-color));
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
        background-size: 180px 180px;
        box-shadow: 0 4px 20px color-mix(in srgb, var(--st-text-color) 6%, transparent);
        margin: 0 0 1.15rem 0;
    }
    .vefr-start-kicker {
        margin: 0 0 0.2rem 0;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: color-mix(in srgb, #a16207 80%, var(--st-text-color));
    }
    .vefr-start-title {
        margin: 0 0 0.85rem 0;
        font-size: 1.15rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--st-text-color);
    }
    .vefr-start-steps {
        display: flex;
        flex-wrap: wrap;
        gap: 0.9rem;
    }
    .vefr-start-step {
        flex: 1 1 210px;
        display: flex;
        gap: 0.6rem;
        align-items: flex-start;
    }
    .vefr-start-num {
        flex: none;
        width: 1.65rem;
        height: 1.65rem;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.85rem;
        font-weight: 700;
        color: var(--st-text-color);
        background: color-mix(in srgb, #c9a227 22%, transparent);
        border: 1px solid color-mix(in srgb, #c9a227 45%, transparent);
    }
    .vefr-start-step .vefr-start-h {
        display: block;
        margin: 0 0 0.15rem 0;
        font-size: 0.92rem;
        font-weight: 600;
        color: var(--st-text-color);
    }
    .vefr-start-step p {
        margin: 0;
        font-size: 0.82rem;
        line-height: 1.45;
        color: color-mix(in srgb, var(--st-text-color) 70%, transparent);
    }
    .vefr-start-note {
        margin: 0.85rem 0 0 0;
        font-size: 0.8rem;
        color: color-mix(in srgb, var(--st-text-color) 62%, transparent);
    }
    .vefr-card-title {
        font-weight: 600;
        font-size: 1.02rem;
        color: var(--st-text-color);
        margin: 0 0 0.75rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.55rem 0.85rem;
        border-radius: 4px;
        background: linear-gradient(
            90deg,
            color-mix(in srgb, var(--st-primary-color) 16%, var(--st-secondary-background-color)) 0%,
            color-mix(in srgb, var(--st-primary-color) 6%, var(--st-secondary-background-color)) 100%
        );
        border: 1px solid color-mix(in srgb, var(--st-primary-color) 22%, transparent);
        border-left: 4px solid var(--st-primary-color);
    }
    .vefr-card-title span {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
        padding: 0.35rem;
        border-radius: 4px;
        color: var(--st-primary-color);
        background: color-mix(in srgb, var(--st-primary-color) 16%, transparent);
    }
    .vefr-card-title span svg {
        display: block;
    }
    .vefr-card ul {
        margin: 0;
        padding-left: 1.15rem;
        color: color-mix(in srgb, var(--st-text-color) 78%, transparent);
        line-height: 1.65;
        font-size: 0.95rem;
    }
    /* Section header (Results, etc.): typography on the canvas — the cards are
       the boxes, so the section break stays airy */
    .vefr-section-head {
        margin: 0.5rem 0 1.1rem 0;
        padding: 0.35rem 0.15rem 0;
    }
    .vefr-section-kicker {
        display: inline-block;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--st-primary-color);
        margin-bottom: 0.25rem;
    }
    .vefr-section-title {
        margin: 0 0 0.35rem 0;
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: -0.03em;
        color: var(--st-text-color);
        line-height: 1.2;
    }
    .vefr-section-desc {
        margin: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: color-mix(in srgb, var(--st-text-color) 68%, transparent);
    }
    .vefr-chart-heading {
        margin: 1.35rem 0 0.35rem 0;
        font-size: 1.12rem;
        font-weight: 700;
        color: var(--st-text-color);
        letter-spacing: -0.02em;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .vefr-chart-heading::before {
        content: "";
        width: 4px;
        height: 1.15em;
        border-radius: 4px;
        background: linear-gradient(180deg, var(--st-primary-color), color-mix(in srgb, var(--st-primary-color) 45%, transparent));
    }
    [data-testid="stAppViewContainer"] [data-testid="stVerticalBlockBorderWrapper"] .vefr-chart-heading,
    [data-testid="stAppViewContainer"] [class*="st-key-panel_"] .vefr-chart-heading {
        margin-top: 0.4rem;
    }
    /* Bordered panels (feature cards, overview, chart): clean white surfaces.
       Elevation comes from the value step vs the tinted canvas, so no accent
       bar or texture here — those stay on the canvas and headers.
       Containers are keyed (st.container(key="panel_*")) so the selector
       survives Streamlit DOM/testid churn. */
    [data-testid="stAppViewContainer"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stAppViewContainer"] [class*="st-key-panel_"] {
        border-radius: 6px !important;
        border: 1px solid color-mix(in srgb, var(--st-text-color) 9%, transparent) !important;
        box-shadow: var(--vefr-shadow) !important;
        background-color: var(--vefr-surface) !important;
        padding: 0.9rem 1rem;
    }
    /* Side-by-side cards fill their column so paired panels match heights */
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:only-child,
    [data-testid="stColumn"] [class*="st-key-panel_"],
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
        height: 100%;
    }
    /* Metric tiles in main area: the headline numbers, so let them lead */
    [data-testid="stAppViewContainer"] [data-testid="stMetric"] {
        padding: 0.65rem 0.75rem;
        border-radius: 4px;
        background: linear-gradient(
            180deg,
            color-mix(in srgb, var(--st-primary-color) 9%, var(--vefr-surface)) 0%,
            color-mix(in srgb, var(--st-primary-color) 3%, var(--vefr-surface)) 100%
        );
        border: 1px solid color-mix(in srgb, var(--st-primary-color) 15%, transparent);
        border-top: 3px solid color-mix(in srgb, var(--st-primary-color) 55%, transparent);
    }
    /* KPI tiles fill the row so a wrapped label doesn't leave uneven heights */
    .st-key-panel_kpi [data-testid="stElementContainer"],
    .st-key-panel_kpi [data-testid="stMetric"] {
        height: 100%;
    }
    /* Runway (first tile) is the single most important number: gold accent */
    .st-key-panel_kpi [data-testid="stColumn"]:first-child [data-testid="stMetric"] {
        border-top-color: #c9a227;
        background: linear-gradient(
            180deg,
            color-mix(in srgb, #c9a227 10%, var(--vefr-surface)) 0%,
            color-mix(in srgb, #c9a227 3%, var(--vefr-surface)) 100%
        );
    }
    [data-testid="stAppViewContainer"] [data-testid="stMetricLabel"] {
        font-size: 0.7rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: color-mix(in srgb, var(--st-text-color) 62%, transparent) !important;
        width: auto;
    }
    /* Labels wrap instead of truncating ("END BALAN...") */
    [data-testid="stAppViewContainer"] [data-testid="stMetricLabel"] > div,
    [data-testid="stAppViewContainer"] [data-testid="stMetricLabel"] p {
        overflow: visible !important;
        white-space: normal !important;
        text-overflow: clip !important;
    }
    [data-testid="stAppViewContainer"] [data-testid="stMetricValue"] {
        font-size: clamp(1.15rem, 1.6vw, 1.5rem) !important;
        font-weight: 700 !important;
        font-variant-numeric: tabular-nums;
        color: var(--st-primary-color);
        letter-spacing: -0.02em;
    }
    [data-testid="stAppViewContainer"] [data-testid="stMetricValue"] > div {
        overflow: visible !important;
        white-space: normal !important;
        text-overflow: clip !important;
    }
    /* Main horizontal rule (after hero cards) */
    [data-testid="stAppViewContainer"] hr {
        margin: 1.6rem 0;
        border: none;
        height: 2px;
        border-radius: 2px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            color-mix(in srgb, var(--st-primary-color) 45%, transparent) 20%,
            color-mix(in srgb, var(--st-primary-color) 25%, transparent) 50%,
            color-mix(in srgb, var(--st-primary-color) 45%, transparent) 80%,
            transparent 100%
        );
    }
    [data-testid="stAppViewContainer"] [data-testid="stRadio"] > div {
        padding: 0.65rem 0.85rem;
        border-radius: 4px;
        border: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent);
        background: color-mix(in srgb, var(--st-secondary-background-color) 30%, var(--st-background-color));
    }
    /* Markdown tables (e.g. GI Bill summary) */
    [data-testid="stAppViewContainer"] .block-container .stMarkdown table {
        color: var(--st-text-color);
        border-collapse: separate;
        border-spacing: 0;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
    }
    [data-testid="stAppViewContainer"] .block-container .stMarkdown th {
        background: color-mix(in srgb, var(--st-primary-color) 12%, var(--st-secondary-background-color));
        font-weight: 600;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 0.5rem 0.75rem !important;
    }
    [data-testid="stAppViewContainer"] .block-container .stMarkdown td {
        padding: 0.55rem 0.75rem !important;
        background: color-mix(in srgb, var(--st-background-color) 40%, transparent);
    }
    [data-testid="stAppViewContainer"] .block-container .stMarkdown th,
    [data-testid="stAppViewContainer"] .block-container .stMarkdown td {
        border-color: color-mix(in srgb, var(--st-text-color) 12%, transparent) !important;
    }
    /* Main tabs: obvious “tab bar” + selected state keeps readable text (no forced white) */
    div[data-testid="stTabs"] {
        margin-top: 0.25rem;
        padding: 14px 16px 6px;
        border-radius: 6px;
        border: 1px solid color-mix(in srgb, var(--st-text-color) 9%, transparent);
        background: var(--vefr-surface);
        box-shadow: var(--vefr-shadow);
    }
    /* Nested panels inside the white tabs surface: tint instead of border-on-border */
    div[data-testid="stTabs"] [data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stTabs"] [class*="st-key-panel_"] {
        background-color: color-mix(
            in srgb,
            var(--st-secondary-background-color) 30%,
            var(--vefr-surface)
        ) !important;
        box-shadow: none !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        padding: 0 0 10px;
        border-radius: 0;
        border: none;
        border-bottom: 2px solid color-mix(in srgb, var(--st-text-color) 10%, transparent);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 0;
        padding: 0.5rem 0.95rem;
        font-weight: 500;
        color: color-mix(in srgb, var(--st-text-color) 82%, transparent) !important;
    }
    .stTabs [data-baseweb="tab"] p,
    .stTabs [data-baseweb="tab"] span {
        color: inherit !important;
    }
    .stTabs [aria-selected="true"] {
        background: color-mix(
            in srgb,
            var(--st-primary-color) 22%,
            var(--st-background-color)
        ) !important;
        color: var(--st-text-color) !important;
        font-weight: 700;
        box-shadow: inset 0 -3px 0 var(--st-primary-color);
    }
    .stTabs [aria-selected="false"]:hover {
        color: var(--st-text-color) !important;
        background: color-mix(
            in srgb,
            var(--st-text-color) 6%,
            var(--st-secondary-background-color)
        ) !important;
    }
    /* Accessibility: visible keyboard focus + pointer affordance */
    .stApp :focus-visible {
        outline: 3px solid color-mix(in srgb, var(--st-primary-color) 75%, transparent);
        outline-offset: 2px;
        border-radius: 6px;
    }
    .stApp button,
    .stApp [role="tab"],
    .stApp [role="button"],
    .stApp [role="combobox"],
    .stApp label,
    .stApp summary {
        cursor: pointer;
    }
    /* Calm, consistent motion on interactive elements (150-300ms) */
    .stTabs [data-baseweb="tab"],
    [data-testid="stExpander"] details > summary,
    .stApp button {
        transition: background-color 180ms ease-out, color 180ms ease-out,
            border-color 180ms ease-out, box-shadow 180ms ease-out;
    }
    @media (prefers-reduced-motion: reduce) {
        .stApp *, .stApp *::before, .stApp *::after {
            transition-duration: 0.01ms !important;
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
        }
    }
    /* Money columns align cleanly with tabular figures */
    [data-testid="stAppViewContainer"] .stMarkdown table td,
    [data-testid="stMetricValue"] {
        font-variant-numeric: tabular-nums;
    }
</style>
        """,
        unsafe_allow_html=True,
    )


def _theme_is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


# -----------------------------
# Streamlit UI
# -----------------------------
def main():
    st.set_page_config(
        page_title="Veterans Readiness Planner",
        page_icon="🎖️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_custom_css()
    with nullcontext():
        st.markdown(
            """
<div class="vefr-hero">
  <p class="vefr-hero-kicker">Education &amp; financial readiness</p>
  <h1 class="vefr-hero-title">Veterans Education &amp; Financial Readiness Planner</h1>
  <p class="vefr-hero-sub">
    Plan your pathway through school while modeling GI Bill housing, income, expenses,
    and how long your savings can carry you.
  </p>
  <div class="vefr-hero-badges">
    <span class="vefr-hero-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>2026 BAH rates built in</span>
    <span class="vefr-hero-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>Post-9/11 GI Bill housing math</span>
    <span class="vefr-hero-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>Month-by-month runway forecast</span>
  </div>
  <div class="vefr-mobile-hint"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/></svg>On mobile, open the sidebar (top-left) to enter your numbers.</div>
</div>
            """,
            unsafe_allow_html=True,
        )

        # KPI strip (or first-run onboarding) lives directly under the hero;
        # filled in after the sidebar inputs and forecast are computed.
        kpi_slot = st.container()

        fc1, fc2 = st.columns(2, gap="medium")
        with fc1:
            with st.container(border=True, key="panel_feature_cashflow"):
                st.markdown(
                    """
<div class="vefr-card-title"><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg></span> Cashflow &amp; runway</div>
<ul>
  <li>Monthly income: MHA, disability, and other sources</li>
  <li>Fixed and variable expenses</li>
  <li>Month-by-month balance projection</li>
  <li>See how long savings may last at a glance</li>
</ul>
                    """,
                    unsafe_allow_html=True,
                )
        with fc2:
            with st.container(border=True, key="panel_feature_gibill"):
                st.markdown(
                    """
<div class="vefr-card-title"><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg></span> GI Bill estimates</div>
<ul>
  <li>Monthly housing (MHA) from GI % and rate of pursuit</li>
  <li>Books stipend for the term</li>
  <li>Tuition covered vs. out-of-pocket</li>
</ul>
                    """,
                    unsafe_allow_html=True,
                )

        st.divider()


        # ----- Sidebar inputs (grouped expanders; widgets use st.* inside with st.sidebar) -----
        INTENSITY_OPTIONS = {
            "Full time (100%)": 1.0,
            "3/4 time (75%)": 0.75,
            "Half time (50%)": 0.5,
            "Less than half (25%)": 0.25,
        }

        term_configs: List[Dict[str, Any]] = []

        def add_term_block(
            term_name: str,
            default_enabled: bool,
            default_start_offset_days: int,
            default_length_days: int,
            key_prefix: str,
        ):
            enabled = st.checkbox(
                f"{term_name} term", value=default_enabled, key=f"{key_prefix}_enabled"
            )
            if not enabled:
                return

            start_default = min(
                forecast_start + timedelta(days=default_start_offset_days), max_end
            )
            end_default = min(
                start_default + timedelta(days=default_length_days), max_end
            )

            start = st.date_input(
                f"{term_name} start",
                value=start_default,
                min_value=forecast_start,
                max_value=max_end,
                key=f"{key_prefix}_start",
            )

            end = st.date_input(
                f"{term_name} end",
                value=end_default,
                min_value=start,
                max_value=max_end,
                key=f"{key_prefix}_end",
            )

            rate_label = st.selectbox(
                f"{term_name} enrollment",
                options=list(INTENSITY_OPTIONS.keys()),
                index=0,
                key=f"{key_prefix}_rate",
            )

            multiplier = INTENSITY_OPTIONS[rate_label]

            term_configs.append(
                {
                    "name": term_name,
                    "start": start,
                    "end": end,
                    "rate_label": rate_label,
                    "multiplier": multiplier,
                }
            )

        def get_effective_rate_of_pursuit(forecast_start, term_configs):
            multiplier_to_enum = {
                1.0: RateOfPursuit.FULL_TIME,
                0.75: RateOfPursuit.THREE_QUARTER,
                0.5: RateOfPursuit.HALF_TIME,
                0.25: RateOfPursuit.LESS_THAN_HALF,
            }

            if not term_configs:
                return RateOfPursuit.FULL_TIME

            active_terms = [
                cfg
                for cfg in term_configs
                if cfg["start"] is not None
                and cfg["end"] is not None
                and cfg["start"] <= forecast_start <= cfg["end"]
            ]

            if not active_terms:
                active_terms = term_configs

            best_cfg = max(active_terms, key=lambda c: c["multiplier"])
            return multiplier_to_enum.get(best_cfg["multiplier"], RateOfPursuit.FULL_TIME)

        school_type = SchoolType.PUBLIC_IN_STATE
        _bah_location_labels = list_location_labels()
        _default_bah_label = next(
            (lb for lb in _bah_location_labels if lb == "SAN DIEGO, CA"),
            _bah_location_labels[0],
        )

        with st.sidebar:
            st.markdown(
                """
<div class="vefr-sidebar-intro">
  <p class="vefr-sidebar-kicker">Your plan</p>
  <h3 class="vefr-sidebar-title">Inputs</h3>
  <p class="vefr-sidebar-blurb">Set dates, semesters, benefits, and cashflow. Open each section as needed.</p>
</div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander("Forecast period", expanded=True, icon=":material/calendar_month:"):
                forecast_start = st.date_input(
                    "Forecast start date",
                    value=date.today(),
                )
                max_end = forecast_start + timedelta(days=365)
                forecast_end = st.date_input(
                    "Forecast end date (≤ 1 year)",
                    value=min(forecast_start + timedelta(days=365), max_end),
                    min_value=forecast_start,
                    max_value=max_end,
                    help="You can forecast up to one year from the start date.",
                )
            with st.expander("Term schedule (BAH by semester)", expanded=True, icon=":material/school:"):
                st.caption(
                    "Turn on each term you attend. Enrollment intensity adjusts the housing multiplier."
                )
                add_term_block(
                    "Winter",
                    default_enabled=False,
                    default_start_offset_days=0,
                    default_length_days=60,
                    key_prefix="winter",
                )
                add_term_block(
                    "Spring",
                    default_enabled=False,
                    default_start_offset_days=60,
                    default_length_days=90,
                    key_prefix="spring",
                )
                add_term_block(
                    "Summer",
                    default_enabled=False,
                    default_start_offset_days=150,
                    default_length_days=60,
                    key_prefix="summer",
                )
                add_term_block(
                    "Fall",
                    default_enabled=False,
                    default_start_offset_days=240,
                    default_length_days=90,
                    key_prefix="fall",
                )
            with st.expander("Savings & GI Bill", expanded=True, icon=":material/savings:"):
                starting_savings = st.number_input(
                    "Current savings ($)",
                    min_value=0.0,
                    step=500.0,
                    value=0.0,
                )
                st.divider()
                st.caption("Used to estimate MHA, books, and tuition coverage.")
                bah_location_label = st.selectbox(
                    "School location",
                    options=_bah_location_labels,
                    index=_bah_location_labels.index(_default_bah_label),
                    help=(
                        "Choose the area that best matches your school. The amount shown is the "
                        "monthly housing baseline at 100% before your GI Bill percentage and "
                        "term enrollment intensity are applied."
                    ),
                    key="vefr_bah_location_v2",
                )
                mha_code = label_to_code(bah_location_label)
                school_zip = mha_code
                full_mha_for_zip = float(e05_rate_for_code(mha_code))
                st.caption(
                    f"**${full_mha_for_zip:,.0f}/mo** at 100% (before GI % & rate of pursuit)."
                )
                gi_percentage = st.selectbox(
                    "GI Bill percentage",
                    options=[40, 50, 60, 70, 80, 90, 100],
                    index=6,
                )
                credits_this_term = st.number_input(
                    "Credits this term",
                    min_value=0,
                    max_value=30,
                    value=12,
                    step=1,
                )
                tuition_this_term = st.number_input(
                    "Tuition & fees this term ($) (Optional)",
                    min_value=0.0,
                    step=500.0,
                    value=0.0,
                )

        rate_of_pursuit = get_effective_rate_of_pursuit(forecast_start, term_configs)

        profile = BenefitProfile(
            gi_percentage=gi_percentage,
            school_zip=school_zip,
            school_type=school_type,
            rate_of_pursuit=rate_of_pursuit,
            credits_this_term=credits_this_term,
            tuition_this_term=tuition_this_term,
        )

        benefits = estimate_all_benefits_for_term(
            profile=profile,
            cfg=DEFAULT_ANNUAL_RATES,
            full_mha_for_zip=full_mha_for_zip,
        )

        bah_monthly = benefits["monthly_housing"]

        with st.sidebar:
            with st.expander("Monthly income (cashflow)", expanded=True, icon=":material/payments:"):
                st.caption(
                    "MHA is taken from your GI Bill settings above. Add other income here."
                )
                disability_monthly = st.number_input(
                    "VA disability ($)",
                    min_value=0.0,
                    step=50.0,
                    value=0.0,
                )
                other_income_monthly = st.number_input(
                    "Other income (job, spouse, etc.) ($)",
                    min_value=0.0,
                    step=100.0,
                    value=0.0,
                )
            with st.expander("Monthly expenses", expanded=True, icon=":material/receipt_long:"):
                month_options = [
                    (1, "January"),
                    (2, "February"),
                    (3, "March"),
                    (4, "April"),
                    (5, "May"),
                    (6, "June"),
                    (7, "July"),
                    (8, "August"),
                    (9, "September"),
                    (10, "October"),
                    (11, "November"),
                    (12, "December"),
                ]
                month_by_label = {name: num for num, name in month_options}

                if "vefr_recurring_expenses" not in st.session_state:
                    st.session_state.vefr_recurring_expenses = []
                if "vefr_one_time_expenses" not in st.session_state:
                    st.session_state.vefr_one_time_expenses = []

                st.caption("Itemize recurring expenses and scheduled one-time payments.")

                st.markdown("**Recurring monthly expenses**")
                st.caption("Line 1: Name, Amount, Remove. Line 2: Type.")
                recurring_to_remove = []
                fixed_expenses_monthly = 0.0
                variable_expenses_monthly = 0.0

                for i, item in enumerate(st.session_state.vefr_recurring_expenses):
                    c1, c2, c3 = st.columns([2.0, 2.1, 0.6])
                    with c1:
                        name = st.text_input(
                            "Name",
                            value=item.get("name", ""),
                            key=f"re_name_{item['id']}",
                            label_visibility="collapsed",
                            placeholder="Expense name",
                        )
                    with c2:
                        amount = st.number_input(
                            "Amount",
                            min_value=0.0,
                            step=50.0,
                            value=float(item.get("amount", 0.0)),
                            key=f"re_amt_{item['id']}",
                            label_visibility="collapsed",
                        )
                    with c3:
                        if st.button(":material/delete:", key=f"re_rm_{item['id']}", help="Remove row"):
                            recurring_to_remove.append(i)

                    c4, c5 = st.columns([2.1, 2.7])
                    with c4:
                        kind = st.selectbox(
                            "Type",
                            options=["Fixed", "Variable"],
                            index=0 if item.get("kind", "Fixed") == "Fixed" else 1,
                            key=f"re_kind_{item['id']}",
                        )
                    with c5:
                        st.write("")
                    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

                    item.update({"name": name, "amount": amount, "kind": kind, "enabled": True})
                    if kind == "Fixed":
                        fixed_expenses_monthly += amount
                    else:
                        variable_expenses_monthly += amount

                if st.button("Add recurring expense", icon=":material/add:"):
                    st.session_state.vefr_recurring_expenses.append(
                        {
                            "id": f"re_{len(st.session_state.vefr_recurring_expenses) + 1}_{len(st.session_state.vefr_one_time_expenses)}",
                            "name": "",
                            "amount": 0.0,
                            "kind": "Variable",
                            "enabled": True,
                        }
                    )
                    st.rerun()

                for idx in sorted(recurring_to_remove, reverse=True):
                    st.session_state.vefr_recurring_expenses.pop(idx)
                if recurring_to_remove:
                    st.rerun()

                st.caption(
                    f"Recurring totals — Fixed: ${fixed_expenses_monthly:,.0f} | Variable: ${variable_expenses_monthly:,.0f}"
                )
                st.divider()

                st.markdown("**Scheduled one-time expenses**")
                st.caption("Line 1: Name, Amount, Remove. Line 2: Frequency and Month.")
                one_time_to_remove = []
                scheduled_one_time_expenses = []
                for i, item in enumerate(st.session_state.vefr_one_time_expenses):
                    c1, c2, c3 = st.columns([1.6, 1.8, 0.6])
                    with c1:
                        name = st.text_input(
                            "Label",
                            value=item.get("name", ""),
                            key=f"ot_name_{item['id']}",
                            label_visibility="collapsed",
                            placeholder="One-time expense",
                        )
                    with c2:
                        amount = st.number_input(
                            "Amount",
                            min_value=0.0,
                            step=50.0,
                            value=float(item.get("amount", 0.0)),
                            key=f"ot_amt_{item['id']}",
                            label_visibility="collapsed",
                        )
                    with c3:
                        if st.button(":material/delete:", key=f"ot_rm_{item['id']}", help="Remove row"):
                            one_time_to_remove.append(i)

                    c5, c6 = st.columns([1.6, 2.0])
                    with c5:
                        frequency = st.selectbox(
                            "Frequency",
                            options=["One-time", "Annual", "Semiannual", "Quarterly"],
                            index=["One-time", "Annual", "Semiannual", "Quarterly"].index(
                                item.get("frequency", "Annual")
                            ),
                            key=f"ot_freq_{item['id']}",
                        )
                    with c6:
                        month_label = st.selectbox(
                            "Month",
                            options=[m[1] for m in month_options],
                            index=max(0, min(11, int(item.get("month", forecast_start.month)) - 1)),
                            key=f"ot_month_{item['id']}",
                        )
                    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

                    month_num = month_by_label[month_label]
                    item.update(
                        {
                            "name": name,
                            "amount": amount,
                            "frequency": frequency,
                            "month": month_num,
                            "enabled": True,
                        }
                    )
                    scheduled_one_time_expenses.append(
                        {
                            "id": item["id"],
                            "name": name,
                            "amount": amount,
                            "frequency": frequency,
                            "month": month_num,
                            "enabled": True,
                        }
                    )

                if st.button("Add one-time expense", icon=":material/add:"):
                    st.session_state.vefr_one_time_expenses.append(
                        {
                            "id": f"ot_{len(st.session_state.vefr_one_time_expenses) + 1}_{len(st.session_state.vefr_recurring_expenses)}",
                            "name": "",
                            "amount": 0.0,
                            "frequency": "Annual",
                            "month": forecast_start.month,
                            "enabled": True,
                        }
                    )
                    st.rerun()

                for idx in sorted(one_time_to_remove, reverse=True):
                    st.session_state.vefr_one_time_expenses.pop(idx)
                if one_time_to_remove:
                    st.rerun()

        # Build forecast
        df = build_forecast(
            start_date=forecast_start,
            end_date=forecast_end,
            starting_savings=starting_savings,
            bah_full_time_base=bah_monthly,
            disability_monthly=disability_monthly,
            other_income_monthly=other_income_monthly,
            fixed_expenses_monthly=fixed_expenses_monthly,
            variable_expenses_monthly=variable_expenses_monthly,
            scheduled_one_time_expenses=scheduled_one_time_expenses,
            term_configs=term_configs,
        )

        # ----- High-level metrics we’ll reuse -----
        final_balance = df["Projected balance"].iloc[-1]
        min_balance = df["Projected balance"].min()

        negative_mask = df["Projected balance"] < 0
        if negative_mask.any():
            first_negative_idx = negative_mask.idxmax()
            month_negative = df.loc[first_negative_idx, "Month"]
            runway_months = int(first_negative_idx)
        else:
            month_negative = None
            runway_months = len(df)

        # ----- KPI strip / first-run onboarding under the hero -----
        is_first_run = (
            starting_savings == 0
            and disability_monthly == 0
            and other_income_monthly == 0
            and fixed_expenses_monthly == 0
            and variable_expenses_monthly == 0
            and not scheduled_one_time_expenses
            and not term_configs
        )

        with kpi_slot:
            if is_first_run:
                st.markdown(
                    """
<div class="vefr-start">
  <p class="vefr-start-kicker">Start here</p>
  <h3 class="vefr-start-title">Build your forecast in three steps</h3>
  <div class="vefr-start-steps">
    <div class="vefr-start-step"><span class="vefr-start-num">1</span><div><span class="vefr-start-h">Savings &amp; GI Bill</span><p>Enter your current savings, pick your school's location, and set your GI Bill percentage.</p></div></div>
    <div class="vefr-start-step"><span class="vefr-start-num">2</span><div><span class="vefr-start-h">Term schedule</span><p>Turn on the terms you'll attend so housing (MHA) is only counted for school months.</p></div></div>
    <div class="vefr-start-step"><span class="vefr-start-num">3</span><div><span class="vefr-start-h">Income &amp; expenses</span><p>Add VA disability, other income, and monthly costs to see how long your savings last.</p></div></div>
  </div>
  <p class="vefr-start-note">All inputs live in the sidebar on the left — on mobile, tap the arrow in the top-left corner.</p>
</div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                with st.container(border=True, key="panel_kpi"):
                    k1, k2, k3, k4 = st.columns(4)
                    with k1:
                        st.metric(
                            "Runway",
                            f"{runway_months} mo",
                            help=(
                                "Months until your balance first goes negative "
                                "(the full projection period if it never does)."
                            ),
                        )
                    with k2:
                        net_change = final_balance - starting_savings
                        st.metric(
                            "End balance",
                            f"${final_balance:,.0f}",
                            delta=f"{net_change:+,.0f}" if net_change else None,
                        )
                    with k3:
                        st.metric("Low point", f"${min_balance:,.0f}")
                    with k4:
                        st.metric(
                            "MHA",
                            f"${bah_monthly:,.0f}",
                            help="Monthly housing allowance from your GI Bill settings.",
                        )
                    if month_negative is not None:
                        st.caption(
                            f"Balance is projected to go negative around "
                            f"**{month_negative:%b %Y}** — details in the Overview tab below."
                        )

        # ----- Tabs (styled in _inject_custom_css) -----
        st.markdown(
            """
<div class="vefr-section-head">
  <span class="vefr-section-kicker">Your projections</span>
  <h3 class="vefr-section-title">Results</h3>
  <p class="vefr-section-desc">Use the tabs for the summary, month-by-month detail, or feedback.</p>
</div>
            """,
            unsafe_allow_html=True,
        )
        tab_overview, tab_table, tab_feedback = st.tabs(
            [
                ":material/monitoring: Overview",
                ":material/calendar_view_month: Monthly breakdown",
                ":material/forum: Feedback",
            ]
        )

        # ===== OVERVIEW TAB =====
        with tab_overview:
            col1, col2 = st.columns(2, gap="medium")

            with col1:
                with st.container(border=True, key="panel_status"):
                    st.markdown(
                        '<p class="vefr-chart-heading">Cashflow status</p>',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"Projection {forecast_start:%b %Y} → {forecast_end:%b %Y}. "
                        "Headline numbers are in the strip under the title."
                    )

                    if month_negative is not None:
                        st.warning(
                            f"Your balance is projected to go negative around **{month_negative:%b %Y}**."
                        )
                    else:
                        st.success(
                            "Your balance stays positive for the entire projection period."
                        )

            with col2:
                with st.container(border=True, key="panel_estimates"):
                    st.markdown(
                        '<p class="vefr-chart-heading">GI Bill / education estimates</p>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"""
| | |
| :--- | ---: |
| **Monthly housing (MHA)** | `${benefits['monthly_housing']:,.0f}` |
| **Books (this term)** | `${benefits['books_for_term']:,.0f}` |
| **Tuition covered** | `${benefits['tuition_covered']:,.0f}` |
| **Tuition out-of-pocket** | `${benefits['tuition_out_of_pocket']:,.0f}` |
                        """
                    )

            st.markdown(
                '<p class="vefr-chart-heading">Projected balance over time</p>',
                unsafe_allow_html=True,
            )
            if not is_first_run:
                st.caption(
                    "Hover a point for balance at the start of that month and enrollment status."
                )

            chart_data = df[["Month", "Projected balance", "Enrollment status"]]

            dark = _theme_is_dark()
            if dark:
                area_hi, area_lo = "#3b82f6", "#0f172a"
                line_pt = "#93c5fd"
                point_stroke = "#111418"
                grid_c, domain_c = "#3d4b5c", "#64748b"
                label_c, title_c = "#94a3b8", "#e2e8f0"
            else:
                area_hi, area_lo = "#93c5fd", "#dbeafe"
                line_pt = "#1d4ed8"
                point_stroke = "#ffffff"
                grid_c, domain_c = "#e2e8f0", "#cbd5e1"
                label_c, title_c = "#475569", "#0f172a"

            base = (
                alt.Chart(chart_data)
                .encode(
                    x=alt.X(
                        "Month:T",
                        title="Month",
                        axis=alt.Axis(format="%b %Y", labelAngle=-35),
                    ),
                    y=alt.Y(
                        "Projected balance:Q",
                        title="Projected balance ($)",
                        scale=alt.Scale(zero=False),
                    ),
                    tooltip=[
                        alt.Tooltip("Month:T", title="Month", format="%b %Y"),
                        alt.Tooltip("Projected balance:Q", title="Balance", format="$.0f"),
                        alt.Tooltip("Enrollment status:N", title="Enrollment"),
                    ],
                )
            )

            area = base.mark_area(
                line=False,
                color=alt.Gradient(
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color=area_hi, offset=0),
                        alt.GradientStop(color=area_lo, offset=1),
                    ],
                    x1=1,
                    x2=1,
                    y1=1,
                    y2=0,
                ),
                opacity=0.85 if not dark else 0.55,
            ).encode(y2=alt.Y2(shorthand="0"))

            line = base.mark_line(
                color=line_pt, strokeWidth=2.5, interpolate="monotone"
            )
            points = base.mark_circle(
                size=56,
                color=line_pt,
                stroke=point_stroke,
                strokeWidth=2,
            )

            balance_chart = (
                (area + line + points)
                .properties(height=380, padding={"left": 12, "right": 16, "top": 12})
                .configure_view(strokeWidth=0)
                .configure_axis(
                    gridColor=grid_c,
                    domainColor=domain_c,
                    labelColor=label_c,
                    titleColor=title_c,
                    tickColor=domain_c,
                )
            )

            with st.container(border=True, key="panel_chart"):
                if is_first_run:
                    st.info(
                        "Enter your savings, income, or school terms in the sidebar "
                        "and your projected balance will take shape here.",
                        icon=":material/query_stats:",
                    )
                else:
                    st.altair_chart(
                        balance_chart,
                        use_container_width=True,
                        theme="streamlit",
                    )

            with st.expander("Assumptions & Notes", icon=":material/info:"):
                st.markdown(f"- **Forecast period:** {forecast_start:%b %Y} → {forecast_end:%b %Y}")
                st.markdown(f"- **Starting savings used:** `${starting_savings:,.0f}`")
                st.markdown(f"- **GI Bill percentage:** `{gi_percentage}%`")
                st.markdown(f"- **Effective rate of pursuit:** `{rate_of_pursuit.name}`")
                st.markdown(
                    f"- **MHA / housing:** `{bah_location_label}` → **${full_mha_for_zip:,.0f}/mo** at 100%; "
                    f"then scaled by GI % and term enrollment intensity."
                )
                st.markdown(
                    f"- **Scheduled one-time expenses enabled:** `{len(scheduled_one_time_expenses)}` item(s), "
                    f"applied by each item's frequency/month."
                )
                st.markdown(f"- Projections are estimates only and may differ from actual VA payments.")

        # ===== MONTHLY TABLE TAB =====
        with tab_table:
            st.markdown(
                '<p class="vefr-chart-heading">Monthly breakdown</p>',
                unsafe_allow_html=True,
            )
            view_mode = st.radio(
                "Display as",
                ["Table (desktop)", "Mobile cards"],
                horizontal=True,
            )

            if view_mode == "Table (desktop)":
                st.dataframe(
                    df.style.format(
                        {
                            "MHA": "${:,.0f}",
                            "Disability": "${:,.0f}",
                            "Other income": "${:,.0f}",
                            "Total income": "${:,.0f}",
                            "Fixed expenses": "${:,.0f}",
                            "Variable expenses": "${:,.0f}",
                            "Scheduled one-time expenses": "${:,.0f}",
                            "Total expenses": "${:,.0f}",
                            "Net cash": "${:,.0f}",
                            "Projected balance": "${:,.0f}",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            else:
                st.caption("Mobile-friendly view. Tap a month to expand details.")

                for _, row in df.iterrows():
                    month = row["Month"]
                    bal = row["Projected balance"]

                    with st.expander(f"{month:%b %Y} — Balance: ${bal:,.0f}"):
                        st.write(f"**Enrollment:** {row['Enrollment status']}")
                        st.write(f"**Income total:** ${row['Total income']:,.0f}")
                        st.write(f"- MHA: ${row['MHA']:,.0f}")
                        st.write(f"- Disability: ${row['Disability']:,.0f}")
                        st.write(f"- Other income: ${row['Other income']:,.0f}")

                        st.write(f"**Expenses total:** ${row['Total expenses']:,.0f}")
                        st.write(f"- Fixed: ${row['Fixed expenses']:,.0f}")
                        st.write(f"- Variable: ${row['Variable expenses']:,.0f}")
                        st.write(f"- Scheduled one-time: ${row['Scheduled one-time expenses']:,.0f}")

                        st.write(f"**Net cashflow:** ${row['Net cash']:,.0f}")

        # ===== FEEDBACK TAB =====
        with tab_feedback:
            with st.container(border=True, key="panel_feedback"):
                st.markdown(
                    '<p class="vefr-chart-heading">Feedback & suggestions</p>',
                    unsafe_allow_html=True,
                )
                st.write(
                    "Have ideas or found a bug? Use the form below so issues and ideas stay organized."
                )
                st.link_button(
                    "Open feedback form",
                    "https://docs.google.com/forms/d/e/1FAIpQLSc2lNwiDnZK9Eu81ezFtUHyc3DCVzojloFwufl4lX-gIwd-7g/viewform?usp=header",
                    type="primary",
                    icon=":material/open_in_new:",
                )


if __name__ == "__main__":
    main()
