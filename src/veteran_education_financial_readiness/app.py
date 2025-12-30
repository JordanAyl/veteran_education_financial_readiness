import streamlit as st
import pandas as pd
import altair as alt
import streamlit_analytics2

from typing import List, Tuple
from datetime import date

from models import BenefitProfile, AnnualRatesConfig, RateOfPursuit, SchoolType
from calculations import estimate_all_benefits_for_term
from config import DEFAULT_ANNUAL_RATES, get_full_mha_for_zip


# -----------------------------
# Helper: generate monthly dates
# -----------------------------
from datetime import date, timedelta
from typing import List, Dict, Any


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

        total_expenses = fixed_expenses_monthly + variable_expenses_monthly
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
                "Total expenses": total_expenses,
                "Net cash": net,
                "Projected balance": balance,
            }
        )

    df = pd.DataFrame(data)
    return df


# -----------------------------
# Streamlit UI
# -----------------------------
def main():
    st.set_page_config(
        page_title="VE&FR",
        layout="wide"
    )
    with streamlit_analytics2.track():
        st.title("🎖️ Veterans Education & Financial Readiness")
        st.header("(For Mobile Users Open the Arrows on the Top Left to Input Data)")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown(
                """
        **Current features**
        - Input MHA, disability, and other monthly income  
        - Input fixed + variable monthly expenses  
        - Month-by-month projection of your balance  
        - Visual **runway** for how long your savings lasts  
        """
            )

        with col2:
            st.markdown(
                """
        **New GI/VR&E Bill helpers**
        - Estimate monthly housing (MHA) from GI % and rate of pursuit  
        - Estimate books stipend per term  
        - Estimate tuition covered vs out-of-pocket  
        """
            )


        # ----- Sidebar inputs -----
        st.sidebar.header("Inputs")

        st.sidebar.header("Forecast period")

        # Forecast start date
        forecast_start = st.sidebar.date_input(
            "Forecast start date",
            value=date.today(),
        )

        # Force the end date to be within 1 year of the start
        max_end = forecast_start + timedelta(days=365)

        forecast_end = st.sidebar.date_input(
            "Forecast end date (≤ 1 year)",
            value=min(forecast_start + timedelta(days=365), max_end),
            min_value=forecast_start,
            max_value=max_end,
            help="You can forecast up to one year from the start date.",
        )

        st.sidebar.header("Term schedule (BAH by semester)")

        # Map from label to multiplier
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
            enabled = st.sidebar.checkbox(f"{term_name} term", value=default_enabled, key=f"{key_prefix}_enabled")
            if not enabled:
                return

            start_default = min(forecast_start + timedelta(days=default_start_offset_days), max_end)
            end_default = min(start_default + timedelta(days=default_length_days), max_end)

            start = st.sidebar.date_input(
                f"{term_name} start",
                value=start_default,
                min_value=forecast_start,
                max_value=max_end,
                key=f"{key_prefix}_start",
            )

            end = st.sidebar.date_input(
                f"{term_name} end",
                value=end_default,
                min_value=start,
                max_value=max_end,
                key=f"{key_prefix}_end",
            )

            rate_label = st.sidebar.selectbox(
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

        # Exactly four terms: Winter, Spring, Summer, Fall
        add_term_block("Winter", default_enabled=False, default_start_offset_days=0,   default_length_days=60,  key_prefix="winter")
        add_term_block("Spring", default_enabled=False,  default_start_offset_days=60,  default_length_days=90,  key_prefix="spring")
        add_term_block("Summer", default_enabled=False, default_start_offset_days=150, default_length_days=60,  key_prefix="summer")
        add_term_block("Fall",   default_enabled=False,  default_start_offset_days=240, default_length_days=90,  key_prefix="fall")

        # Derive an "effective" Rate of Pursuit for the GI Bill helper
        # based on the term schedule and forecast_start.
        def get_effective_rate_of_pursuit(forecast_start, term_configs):
            # Map your intensity multipliers to the enum the GI helper expects
            multiplier_to_enum = {
                1.0: RateOfPursuit.FULL_TIME,
                0.75: RateOfPursuit.THREE_QUARTER,
                0.5: RateOfPursuit.HALF_TIME,
                0.25: RateOfPursuit.LESS_THAN_HALF,
            }

            if not term_configs:
                # No terms configured: default to full-time
                return RateOfPursuit.FULL_TIME

            # Prefer a term that is active at the forecast start date
            active_terms = [
                cfg for cfg in term_configs
                if cfg["start"] is not None
                and cfg["end"] is not None
                and cfg["start"] <= forecast_start <= cfg["end"]
            ]

            if not active_terms:
                # If none are active on forecast_start, just pick the
                # highest-intensity term as a representative
                active_terms = term_configs

            best_cfg = max(active_terms, key=lambda c: c["multiplier"])
            return multiplier_to_enum.get(best_cfg["multiplier"], RateOfPursuit.FULL_TIME)

        rate_of_pursuit = get_effective_rate_of_pursuit(forecast_start, term_configs)


        # Starting position
        st.sidebar.subheader("Starting position")
        starting_savings = st.sidebar.number_input(
            "Current savings ($)",
            min_value=0.0,
            step=500.0,
            value=0.0,
        )

        # -----------------------------
        # GI Bill / Education Benefits
        # -----------------------------
        st.sidebar.subheader("GI Bill / Education benefits (optional)")

        gi_percentage = st.sidebar.selectbox(
            "GI Bill percentage",
            options=[40, 50, 60, 70, 80, 90, 100],
            index=6,  # default 100%
        )

        # Default school configuration (no UI)
        school_zip = "92110"  # or whatever your default should be
        school_type = SchoolType.PUBLIC_IN_STATE

        credits_this_term = st.sidebar.number_input(
            "Credits this term",
            min_value=0,
            max_value=30,
            value=12,
            step=1,
        )

        tuition_this_term = st.sidebar.number_input(
            "Tuition & fees this term ($) (Optional)",
            min_value=0.0,
            step=500.0,
            value=0.0,
        )

        # For now we let the user override the full MHA for ZIP directly.
        full_mha_for_zip = st.sidebar.number_input(
            "Full MHA for this ZIP at 100% ($/month)",
            min_value=0.0,
            step=500.0,
            value=get_full_mha_for_zip(school_zip),
            help="This is the full monthly housing allowance for your school's ZIP at 100% GI Bill. You can edit it.",
        )

        # Build benefit profile + estimates if they provided at least some tuition
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

        # Income
        st.sidebar.subheader("Monthly income (for cashflow)")

        # Use the computed GI Bill monthly housing automatically
        bah_monthly = benefits["monthly_housing"]

        disability_monthly = st.sidebar.number_input(
            "VA disability ($)",
            min_value=0.0,
            step=50.0,
            value=0.0,
        )
        other_income_monthly = st.sidebar.number_input(
            "Other income (job, spouse, etc.) ($)",
            min_value=0.0,
            step=100.0,
            value=0.0,
        )

        # Expenses
        st.sidebar.subheader("Monthly expenses")
        fixed_expenses_monthly = st.sidebar.number_input(
            "Fixed expenses (rent, utilities, insurance, etc.) ($)",
            min_value=0.0,
            step=100.0,
            value=0.0,
        )
        variable_expenses_monthly = st.sidebar.number_input(
            "Variable expenses (food, gas, misc.) ($)",
            min_value=0.0,
            step=100.0,
            value=0.0,
        )

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
            term_configs=term_configs,
        )

        # ----- High-level metrics we’ll reuse -----
        final_balance = df["Projected balance"].iloc[-1]
        min_balance = df["Projected balance"].min()
        runway_months = len(df)

        negative_mask = df["Projected balance"] < 0
        if negative_mask.any():
            first_negative_idx = negative_mask.idxmax()
            month_negative = df.loc[first_negative_idx, "Month"]
        else:
            month_negative = None

        # ----- Tabs for a cleaner layout -----
        tab_overview, tab_table, tab_assumptions, tab_feedback = st.tabs(
            ["📊 Overview", "📅 Monthly breakdown", "⚙️ Assumptions", "💬 Feedback"]
        )

        # ===== OVERVIEW TAB =====
        with tab_overview:
            # Top metrics + GI Bill summary side by side
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Cashflow summary")

                st.metric("Runway (months)", f"{runway_months}")
                st.metric("Balance at end of period", f"${final_balance:,.0f}")
                st.metric("Lowest balance", f"${min_balance:,.0f}")

                if month_negative is not None:
                    st.warning(
                        f"⚠️ Your balance is projected to go negative around **{month_negative:%b %Y}**."
                    )
                else:
                    st.success(
                        "✅ Your balance stays positive for the entire projection period."
                    )

            with col2:
                st.subheader("GI Bill / Education benefit estimates")

                st.markdown(
                    f"""
        **Monthly housing (MHA estimate):** `${benefits['monthly_housing']:,.0f}`  
        **Books for this term:** `${benefits['books_for_term']:,.0f}`  
        **Tuition covered this term:** `${benefits['tuition_covered']:,.0f}`  
        **Tuition out-of-pocket this term:** `${benefits['tuition_out_of_pocket']:,.0f}`
        """
                )

            # Chart under the metrics
            st.subheader(
                "Projected balance over time  \n"
                "(Hover over each point to see projected balance at the start of each month.)"
            )

            chart_data = df[["Month", "Projected balance", "Enrollment status"]]

            base = (
                alt.Chart(chart_data)
                .encode(
                    x=alt.X("Month:T", title="Month"),
                    y=alt.Y("Projected balance:Q", title="Projected balance ($)"),
                    tooltip=[
                        alt.Tooltip("Month:T", title="Month"),
                        alt.Tooltip("Projected balance:Q", title="Balance", format="$.0f"),
                        alt.Tooltip("Enrollment status:N", title="Enrollment"),
                    ],
                )
            )

            line = base.mark_line()
            points = base.mark_circle(size=40)

            st.altair_chart(line + points, use_container_width=True)

        # ===== MONTHLY TABLE TAB =====
        with tab_table:
            st.subheader("Monthly breakdown")

            view_mode = st.radio(
                "View style",
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

                        st.write(f"**Net cashflow:** ${row['Net cash']:,.0f}")

        # ===== ASSUMPTIONS TAB =====
        with tab_assumptions:
            st.subheader("Key assumptions")

            st.markdown(f"- **Forecast start:** {forecast_start:%b %Y}")
            st.markdown(f"- **Forecast end:** {forecast_end:%b %Y}")
            st.markdown(f"- **Starting savings:** `${starting_savings:,.0f}`")
            st.markdown(f"- **GI Bill percentage:** `{gi_percentage}%`")
            st.markdown(f"- **School ZIP:** `{school_zip}`")
            st.markdown(f"- **Rate of pursuit (effective):** `{rate_of_pursuit.name}`")

            st.markdown("### Term schedule")
            if term_configs:
                for cfg in term_configs:
                    st.markdown(
                        f"- **{cfg['name']}**: {cfg['rate_label']}  "
                        f"({cfg['start']} → {cfg['end']})"
                    )
            else:
                st.info("No terms enabled in the sidebar.")

        # ===== FEEDBACK TAB =====
        with tab_feedback:
            st.subheader("Feedback & suggestions")

            st.write(
                "Have ideas or found a bug? Please use the feedback form so I can track and fix things."
            )

            st.link_button(
                "Open feedback form",
                "https://docs.google.com/forms/d/e/1FAIpQLSc2lNwiDnZK9Eu81ezFtUHyc3DCVzojloFwufl4lX-gIwd-7g/viewform?usp=header",
            )


if __name__ == "__main__":
    main()
