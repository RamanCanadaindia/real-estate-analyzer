import streamlit as st
import pandas as pd
import time
import os
import re
import json
from datetime import datetime
from typing import List, Dict, Tuple, Optional

# Auto-install Playwright browsers on startup if running on Streamlit Cloud
try:
    import subprocess
    playwright_cache = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.exists(playwright_cache) or len(os.listdir(playwright_cache)) == 0:
        with st.spinner("🔧 Installing Playwright Chromium browser for first-time use..."):
            subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception:
    pass

# Import modular investment engine components
from utils.real_estate.models import PropertyListing, FinancialInputs, PropertyEvaluation
from utils.real_estate.calculator import (
    calculate_mortgage_details, calculate_cash_flow_details, 
    calculate_appreciation_forecast, calculate_roi_details, calculate_scenarios
)
from utils.real_estate.scoring import (
    evaluate_comparable_sales, evaluate_transit_score, 
    evaluate_development_potential, evaluate_schools, 
    evaluate_rental_demand, evaluate_property_condition, 
    evaluate_risk_profile, calculate_norm_score
)
from utils.real_estate.recommender import generate_recommendation
from utils.real_estate.maps import build_property_map
from utils.real_estate.excel_export import export_evaluations_to_excel
from utils.real_estate.pdf_report import generate_property_pdf
from utils.property_text_parser import parse_property_description

# Streamlit-Folium integration
from streamlit_folium import st_folium

from tasks.real_estate_scraper import RealEstateScraperTask
import sheets_helper
import auth

# Force Page Configurations
st.set_page_config(
    page_title="Professional Real Estate Investment Engine",
    page_icon="🏠",
    layout="wide"
)

# Password Protection Check
if not auth.check_password():
    st.stop()

# 🔑 Gemini API Key Input in Sidebar
st.sidebar.markdown("### 🔑 Gemini Configuration")
gemini_key_input = st.sidebar.text_input(
    "Enter Google AI Studio API Key:",
    type="password",
    value=st.session_state.get("GEMINI_API_KEY", st.secrets.get("GEMINI_API_KEY", "")),
    help="Input your Gemini API key here to enable parsing with AI."
)
if gemini_key_input:
    st.session_state["GEMINI_API_KEY"] = gemini_key_input

# Initialize session state for properties
if "scraped_properties" not in st.session_state:
    st.session_state.scraped_properties = []

def clean_numeric_price(price_str) -> float:
    try:
        cleaned = re.sub(r'[^\d.]', '', str(price_str))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

st.title("💼 Real Estate Investment Decision Engine")
st.write("Professional residential asset valuation dashboard for Metro Vancouver development and cash flow analysis.")

# Tabs
tab_analyzer, tab_gmail = st.tabs(["📊 Investment Analyzer", "✉️ Gmail Listing Scanner"])

with tab_analyzer:
    col_left, col_right = st.columns([4, 8])

with col_left:
    st.subheader("⚙️ Analysis Parameters")
    
    # Paragon Link Input
    listing_url = st.text_input(
        "Paragon MLS Link / GUID URL:",
        placeholder="https://bcres.paragonrels.com/paragonls/publink/view.mvc/?GUID=...",
        help="Paste the Paragon public listing link from your realtor."
    )
    
    # Scraper Action Buttons
    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        analyze_btn = st.button("⚡ Scrape Property", use_container_width=True, type="primary")
    with col_sc2:
        clear_btn = st.button("🧹 Clear All Data", use_container_width=True)
        
    if clear_btn:
        st.session_state.scraped_properties = []
        st.rerun()
        
    if analyze_btn:
        if not listing_url:
            st.error("Please enter a valid Paragon listing link.")
        else:
            settings = {"url": listing_url}
            with st.spinner("Scraping listing and reconstructing coordinates..."):
                try:
                    import sys
                    is_headless_env = (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
                    with RealEstateScraperTask(settings, headless=is_headless_env) as task:
                        res = task.execute()
                    if res:
                        item = res[0]
                        # De-duplicate check
                        exists = False
                        for p in st.session_state.scraped_properties:
                            if p["Link"] == item["Link"] or p["Address"] == item["Address"]:
                                exists = True
                                break
                        if not exists:
                            st.session_state.scraped_properties.append(item)
                            st.success(f"Added listing: {item['Address']}")
                        else:
                            st.info("Listing already analyzed in this session.")
                    else:
                        st.error("Failed to parse listing details.")
                except Exception as e:
                    st.error(f"Scraper Error: {e}")

    # Paste Property Description Option
    st.write("---")
    st.write("📋 **Or Paste Property Description**")
    prop_description = st.text_area(
        "Paste listing text / description here:",
        placeholder="MLS: R2891321\nPrice: $750,000\nAddress: 123 Main St, Surrey...\nDescription: Beautiful 3 bed 2 bath house...",
        height=150,
        help="Paste any property listing text. Gemini will extract relevant details."
    )
    parse_text_btn = st.button("🧠 Parse Description with AI", use_container_width=True)
    
    if parse_text_btn:
        if not prop_description.strip():
            st.error("Please paste some property description text first.")
        else:
            with st.spinner("Analyzing text with Gemini..."):
                try:
                    from utils.gemini_helper import query_gemini, get_gemini_client
                    from datetime import datetime
                    
                    prompt = f"""
                    You are a real estate research assistant. Parse the property listing details from the user-pasted text below.
                    Text:
                    {prop_description[:10000]}
                    
                    Extract the following parameters:
                    - address: The full property address (including unit number, street, city, province/postal code if available. If incomplete, guess the city if context is provided, otherwise leave as detailed as possible)
                    - price: The list price as a number or string (e.g. 750000 or "$750,000")
                    - beds: Number of bedrooms (integer or float, e.g. 2. Default to 1 if not found)
                    - baths: Number of bathrooms (integer or float, e.g. 2. Default to 1 if not found)
                    - sqft: Total square footage (integer, e.g. 850. Default to 800 if not found)
                    - strata_fee: Monthly maintenance/strata fee as a number (e.g. 350.00. Set 0 if no strata/maintenance fee is present)
                    - property_tax: Annual property tax as a number (e.g. 2100.00. Set 0 if not listed)
                    - year_built: Year the property was built (integer, e.g. 2018. Default to 2000 if not found)
                    - property_type: The property type (e.g. "Townhouse                    - mls_number: The MLS number if listed (e.g. R2891321. Default to "N/A" if not found)
                    - lot_area: Total lot area size in square feet as a number (integer or float, e.g. 4032. Set 0 if no lot area is listed or if it is a standard condo with no individual lot size)
                    - assessed_value: The government assessed value for tax purposes as a number (integer or float, e.g. 980000. Set 0 if not found)
                    
                    Also, estimate these parameters based on Metro Vancouver geography (if the address is in British Columbia):
                    - skytrain_walk_minutes: Estimated walking time to the nearest Skytrain station in minutes (integer, e.g. 8. Default to 15 if unknown).
                    - skytrain_station: Name of the nearest Skytrain station (e.g. Surrey Central, Metrotown, Lougheed. Default to "Unknown Transit" if unknown).
                    - est_rent: Estimated monthly market rent for this property type, beds/baths, and city (integer, e.g. 2500. Default to 2200 if unknown)
                    - growth_score: Estimated long-term capital growth potential score from 1 to 10 (integer, e.g. 8)
                    
                    Format your response strictly as a JSON object:
                    {{
                        "address": "...",
                        "price": "...",
                        "beds": 2,
                        "baths": 2,
                        "sqft": 850,
                        "strata_fee": 350.00,
                        "property_tax": 2100.00,
                        "year_built": 2018,
                        "property_type": "Townhouse",
                        "mls_number": "...",
                        "lot_area": 0.0,
                        "assessed_value": 0.0,
                        "skytrain_walk_minutes": 15,
                        "skytrain_station": "...",
                        "est_rent": 2200,
                        "growth_score": 6
                    }}
                    Do not include markdown code blocks or any other explanation. Only return valid JSON.
                    """
                    
                    fallback_data = parse_property_description(prop_description)
                    gemini_response = query_gemini(prompt, response_json=True) if get_gemini_client() else None
                    if not gemini_response and fallback_data.get("address") and fallback_data.get("price"):
                        gemini_response = json.dumps(fallback_data)
                    if gemini_response:
                        cleaned_response = gemini_response.strip()
                        if cleaned_response.startswith("```json"):
                            cleaned_response = cleaned_response[7:]
                        if cleaned_response.endswith("```"):
                            cleaned_response = cleaned_response[:-3]
                            
                        try:
                            data = json.loads(cleaned_response.strip())
                        except (json.JSONDecodeError, TypeError):
                            data = fallback_data
 
                        for key in ("address", "price", "beds", "baths", "sqft", "property_tax", "year_built", "property_type", "mls_number", "lot_area", "assessed_value"):
                            if data.get(key) in (None, "", 0, "Unknown", "N/A"):
                                if fallback_data.get(key) not in (None, "", 0):
                                    data[key] = fallback_data[key]
                        
                        item = {
                            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Address": data.get("address", "Pasted Property Listing"),
                            "Price": data.get("price", "0"),
                            "Bedrooms": data.get("beds", 1),
                            "Bathrooms": data.get("baths", 1),
                            "Sqft": data.get("sqft", 800),
                            "Strata Fee": data.get("strata_fee", 0.0),
                            "Property Tax": data.get("property_tax", 0.0),
                            "Year Built": data.get("year_built", 2000),
                            "Property Type": data.get("property_type", "Condo"),
                            "MLS Number": data.get("mls_number", "N/A"),
                            "Lot Area": float(data.get("lot_area", 0.0)),
                            "Assessed Value": float(data.get("assessed_value", 0.0)),
                            "Transit Walk Min": data.get("skytrain_walk_minutes", 15),
                            "Nearest Station": data.get("skytrain_station", "Unknown Transit"),
                            "Est Rent": data.get("est_rent", 2200),
                            "Growth Score": data.get("growth_score", 6),
                            "Link": ""
                        }
                        
                        # De-duplicate check
                        exists = False
                        for p in st.session_state.scraped_properties:
                            if p["Address"] == item["Address"] or (p["MLS Number"] != "N/A" and p["MLS Number"] == item["MLS Number"]):
                                exists = True
                                break
                                
                        if not exists:
                            st.session_state.scraped_properties.append(item)
                            st.success(f"Added listing from text: {item['Address']}")
                            st.rerun()
                        else:
                            st.info("Listing with this address or MLS already analyzed in this session.")
                    else:
                        st.error("Failed to parse details. Please make sure the description contains a price/address.")
                except Exception as e:
                    st.error(f"Error parsing text with AI: {e}")

    # Granular Financial Assumptions
    with st.expander("💸 Detailed Financial Assumptions", expanded=True):
        down_payment_pct = st.number_input("Down Payment %", min_value=5.0, max_value=100.0, value=20.0, step=5.0)
        interest_rate = st.number_input("Interest Rate %", min_value=1.0, max_value=15.0, value=4.8, step=0.1)
        amortization_years = st.number_input("Amortization (Years)", min_value=5, max_value=30, value=25, step=5)
        
        col_ass1, col_ass2 = st.columns(2)
        with col_ass1:
            mortgage_type = st.selectbox("Mortgage Type", ["Fixed", "Variable"])
            frequency = st.selectbox("Payment Frequency", ["Monthly", "Semi-Monthly", "Bi-Weekly", "Weekly"])
        with col_ass2:
            vacancy_rate_pct = st.number_input("Vacancy Allowance %", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
            maintenance_pct = st.number_input("Maintenance Reserve %", min_value=0.0, max_value=20.0, value=5.0, step=0.5)
            
        insurance_monthly = st.number_input("Monthly Insurance ($)", min_value=0.0, value=80.0, step=10.0)
        prop_management_pct = st.number_input("Property Management %", min_value=0.0, max_value=25.0, value=6.0, step=0.5)
        utilities_monthly = st.number_input("Utilities (Landlord Paid $)", min_value=0.0, value=0.0, step=50.0)
        misc_monthly = st.number_input("Misc / Contingency ($/mo)", min_value=0.0, value=0.0, step=25.0)

    # 10-Factor Scoring Weights
    with st.expander("📊 10-Factor MCDA Weights", expanded=False):
        st.write("Adjust weights (relative percentages dynamically normalize to 100%):")
        w_app = st.slider("📈 Expected Appreciation", 0, 100, 25)
        w_cf = st.slider("💵 Cash Flow", 0, 100, 20)
        w_disc = st.slider("🏷️ Comparable Price Discount", 0, 100, 15)
        w_dev = st.slider("🏗️ Development Potential", 0, 100, 10)
        w_trans = st.slider("🚉 Transit Accessibility", 0, 100, 10)
        w_dem = st.slider("👥 Rental Demand", 0, 100, 5)
        w_sch = st.slider("🏫 School Quality", 0, 100, 5)
        w_safe = st.slider("🛡️ Neighbourhood Safety", 0, 100, 5)
        w_cond = st.slider("🛠️ Property Condition", 0, 100, 3)
        w_risk = st.slider("⚠️ Investment Risk Safety", 0, 100, 2)
        
        # Calculate dynamic normalized weights
        w_sum = w_app + w_cf + w_disc + w_dev + w_trans + w_dem + w_sch + w_safe + w_cond + w_risk
        if w_sum == 0:
            w_sum = 10
            w_app = w_cf = w_disc = w_dev = w_trans = w_dem = w_sch = w_safe = w_cond = w_risk = 1

# Process evaluations if listings exist
evaluations: List[PropertyEvaluation] = []
if st.session_state.scraped_properties:
    for idx, p in enumerate(st.session_state.scraped_properties):
        price_val = clean_numeric_price(p.get("Price", 0.0))
        
        # Allow rent override via numeric input
        default_rent = float(p.get("Est Rent", 2200))
        est_rent = st.sidebar.number_input(
            f"Rent Override: {p.get('Address', 'Listing')[:18]}...",
            min_value=500.0, max_value=25000.0, value=default_rent, step=100.0,
            key=f"rent_override_val_{idx}"
        )
        
        # Setup dataclass structures
        listing_model = PropertyListing(
            address=p.get("Address", "Unknown Address"),
            price=price_val,
            beds=int(p.get("Bedrooms", 1)),
            baths=int(p.get("Bathrooms", 1)),
            sqft=int(p.get("Sqft", 800)),
            strata_fee=float(p.get("Strata Fee", 0.0)),
            property_tax=float(p.get("Property Tax", 0.0)),
            year_built=int(p.get("Year Built", 2000)),
            property_type=p.get("Property Type", "Condo"),
            lot_area=float(p.get("Lot Area", 0.0)),
            assessed_value=float(p.get("Assessed Value", 0.0)),
            mls_number=p.get("MLS Number", "N/A"),
            link=p.get("Link", ""),
            timestamp=p.get("Timestamp", "")
        )
        
        financials_model = FinancialInputs(
            down_payment_pct=down_payment_pct,
            interest_rate=interest_rate,
            amortization_years=amortization_years,
            mortgage_type=mortgage_type,
            payment_frequency=frequency,
            insurance_monthly=insurance_monthly,
            vacancy_rate_pct=vacancy_rate_pct,
            maintenance_pct=maintenance_pct,
            property_management_pct=prop_management_pct,
            utilities_landlord_paid=utilities_monthly,
            misc_expenses_monthly=misc_monthly,
            est_rent=est_rent
        )
        
        # 1. Mortgage Payment Calcs
        principal_mortgage = price_val * (1 - (down_payment_pct / 100))
        mort_res = calculate_mortgage_details(
            principal_mortgage, interest_rate, amortization_years, 
            frequency, mortgage_type == "Variable"
        )
        
        # 2. Yield & Cash Flow Calcs
        cf_res = calculate_cash_flow_details(listing_model, financials_model, mort_res.monthly_payment)
        
        # 3. Appreciation Forecast
        app_res = calculate_appreciation_forecast(listing_model)
        
        # 4. ROI Metrics
        roi_res = calculate_roi_details(listing_model, financials_model, mort_res, cf_res, app_res)
        
        # 5. Comparable Sales
        comp_res = evaluate_comparable_sales(listing_model)
        
        # 6. Transit Accessibility
        transit_res = evaluate_transit_score(listing_model)
        
        # 7. Development Potential
        dev_res = evaluate_development_potential(listing_model, transit_res)
        
        # 8. Schools Catchment
        school_res = evaluate_schools(listing_model)
        
        # 9. Rental Demand
        demand_res = evaluate_rental_demand(listing_model)
        
        # 10. Property Condition
        cond_res = evaluate_property_condition(listing_model)
        
        # 11. Risk Profile
        risk_res = evaluate_risk_profile(listing_model, financials_model, cond_res)
        
        # 12. Scenarios compares (Optimistic / Base / Pessimistic)
        scenario_res = calculate_scenarios(listing_model, financials_model)
        
        # 13. Sub-scores Normalization (1 to 10 scale)
        # expected annual appreciation: range 3.0 to 8.0%
        score_app = calculate_norm_score(app_res.expected_annual_appreciation_pct, 3.0, 8.0)
        # cash on cash: range -2% to 6%
        score_cf = calculate_norm_score(cf_res.cash_on_cash_pct, -2.0, 6.0)
        # comparable discount: range -10% to 15%
        score_disc = calculate_norm_score(comp_res.price_discount_pct, -10.0, 15.0)
        
        score_dev = dev_res.development_score
        score_trans = transit_res.transit_score
        score_dem = demand_res.rental_demand_score
        score_sch = school_res.average_school_rating
        
        # safety (higher safety = better = lower crime)
        from utils.real_estate.data_source import detect_municipality, MUNICIPALITIES_DATA
        m_name = detect_municipality(listing_model.address)
        score_safe = MUNICIPALITIES_DATA.get(m_name, {}).get("safety_score", 7.0)
        
        score_cond = cond_res.condition_score
        score_risk = 10.0 - risk_res.risk_score # low risk = high score
        
        # Dynamic weighted score (normalizes to 100%)
        weighted_val = (
            (w_app * score_app) +
            (w_cf * score_cf) +
            (w_disc * score_disc) +
            (w_dev * score_dev) +
            (w_trans * score_trans) +
            (w_dem * score_dem) +
            (w_sch * score_sch) +
            (w_safe * score_safe) +
            (w_cond * score_cond) +
            (w_risk * score_risk)
        ) / w_sum
        
        composite_score = round(weighted_val * 10.0, 1) # Normalize to 100 scale
        
        eval_obj = PropertyEvaluation(
            listing=listing_model,
            financials=financials_model,
            mortgage=mort_res,
            cash_flow=cf_res,
            appreciation=app_res,
            comparables=comp_res,
            development=dev_res,
            transit=transit_res,
            schools=school_res,
            demand=demand_res,
            condition=cond_res,
            risk=risk_res,
            roi=roi_res,
            scenarios=scenario_res,
            composite_score=composite_score
        )
        # Generate written brochure recommendations
        eval_obj.ai_recommendation = generate_recommendation(eval_obj)
        evaluations.append(eval_obj)

    # Sort evaluations by score descending
    evaluations.sort(key=lambda x: x.composite_score, reverse=True)
    # Assign ranks
    for r_idx, ev in enumerate(evaluations):
        ev.overall_rank = r_idx + 1

# Render Dashboard Right Column
with col_right:
    if not evaluations:
        st.info("⚡ Real Estate Investment Decision Engine ready. Enter a listing URL in the parameters panel and click Scrape to analyze.")
    else:
        # Multi-tab layout for modular analysis
        tab_dashboard, tab_cashflow, tab_comps, tab_compare = st.tabs([
            "🏆 Investment Rankings",
            "💵 Cash Flow & Scenarios",
            "🗺️ Maps & Comparable Sales",
            "👥 Side-by-Side Comparison"
        ])
        
        # ------------------ TAB 1: RANKINGS DASHBOARD ------------------
        with tab_dashboard:
            st.subheader("📊 Property Performance Rankings")
            
            for ev in evaluations:
                listing = ev.listing
                cf = ev.cash_flow
                roi = ev.roi
                risk = ev.risk
                
                with st.container(border=True):
                    col_det1, col_det2 = st.columns([9, 3])
                    
                    with col_det1:
                        st.markdown(f"### #{ev.overall_rank}: **{listing.address}**")
                        st.markdown(
                            f"**MLS®**: `{listing.mls_number}` | **Type**: `{listing.property_type}` | "
                            f"**Built**: `{listing.year_built}` (Age: {ev.condition.age_years} yrs) | **Price**: `${listing.price:,.0f}`"
                        )
                        st.markdown(f"📐 **Size**: {listing.sqft} sqft (${listing.price/listing.sqft:,.2f}/sqft) | **Layout**: {listing.beds} Bed, {listing.baths} Bath")
                        
                        # Yield Metrics Row
                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        col_m1.metric("Cap Rate", f"{cf.cap_rate}%")
                        col_m2.metric("Cash-on-Cash Return", f"{cf.cash_on_cash_pct}%")
                        col_m3.metric("5y IRR Projection", f"{roi.irr_5y:.1f}%")
                        
                        cf_color = "green" if cf.net_cash_flow_monthly >= 0 else "red"
                        col_m4.markdown(
                            f"Monthly Cash Flow:<br><span style='color:{cf_color}; font-size:18px; font-weight:bold;'>"
                            f"${cf.net_cash_flow_monthly:,.2f}</span>", 
                            unsafe_allow_html=True
                        )
                        
                        # AI summary brochure card
                        st.markdown(f"📝 **Investment Assessment:**")
                        st.info(ev.ai_recommendation)
                        
                    with col_det2:
                        st.write("")
                        st.metric("Overall Investment Score", f"{ev.composite_score} / 100")
                        st.progress(ev.composite_score / 100.0)
                        
                        st.write(f"⚠️ Risk Profile: **{risk.risk_level}**")
                        st.write(f"🏗️ Development Score: **{ev.development.development_score}/10**")
                        
                        # Exporters Buttons
                        pdf_data = generate_property_pdf(ev)
                        st.download_button(
                            label="📥 Download PDF Report",
                            data=pdf_data,
                            file_name=f"investment_report_{listing.mls_number}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key=f"dl_pdf_btn_{listing.mls_number}"
                        )
                        st.markdown(f"[🔗 Open Listing Link]({listing.link})")
                        
        # ------------------ TAB 2: CASH FLOW & SCENARIOS ------------------
        with tab_cashflow:
            st.subheader("💵 Cash Flow Statements & Scenario Models")
            
            for ev in evaluations:
                listing = ev.listing
                cf = ev.cash_flow
                m = ev.mortgage
                sc = ev.scenarios
                
                with st.expander(f"📊 Financials & Scenario Analysis: {listing.address}", expanded=True):
                    # Side-by-side scenarios comparison table
                    st.markdown("**Side-by-Side Stress-Test Projections (Base vs Optimistic vs Pessimistic)**")
                    
                    scenario_tbl = pd.DataFrame({
                        "Metric": [
                            "Monthly Rent", "Mortgage Payment", "Vacancy Allowance", 
                            "Maintenance Reserve", "Strata Fees", "Property Taxes", 
                            "Net Cash Flow (Monthly)", "Net Cash Flow (Annual)", 
                            "Cap Rate (%)", "Cash-on-Cash Return (%)", "5-Year IRR (%)"
                        ],
                        "Pessimistic Scenario": [
                            f"${sc.pessimistic.gross_rent:,.2f}", f"${sc.pessimistic.mortgage_payment:,.2f}", f"${sc.pessimistic.vacancy_allowance_monthly:,.2f}",
                            f"${sc.pessimistic.maintenance_reserve_monthly:,.2f}", f"${sc.pessimistic.strata_fee_monthly:,.2f}", f"${sc.pessimistic.property_tax_monthly:,.2f}",
                            f"${sc.pessimistic.net_cash_flow_monthly:,.2f}", f"${sc.pessimistic.net_cash_flow_annual:,.2f}",
                            f"{sc.pessimistic.cap_rate}%", f"{sc.pessimistic.cash_on_cash_pct}%", f"{sc.pessimistic_roi.irr_5y:.1f}%"
                        ],
                        "Base Scenario": [
                            f"${sc.base.gross_rent:,.2f}", f"${sc.base.mortgage_payment:,.2f}", f"${sc.base.vacancy_allowance_monthly:,.2f}",
                            f"${sc.base.maintenance_reserve_monthly:,.2f}", f"${sc.base.strata_fee_monthly:,.2f}", f"${sc.base.property_tax_monthly:,.2f}",
                            f"${sc.base.net_cash_flow_monthly:,.2f}", f"${sc.base.net_cash_flow_annual:,.2f}",
                            f"{sc.base.cap_rate}%", f"{sc.base.cash_on_cash_pct}%", f"{sc.base_roi.irr_5y:.1f}%"
                        ],
                        "Optimistic Scenario": [
                            f"${sc.optimistic.gross_rent:,.2f}", f"${sc.optimistic.mortgage_payment:,.2f}", f"${sc.optimistic.vacancy_allowance_monthly:,.2f}",
                            f"${sc.optimistic.maintenance_reserve_monthly:,.2f}", f"${sc.optimistic.strata_fee_monthly:,.2f}", f"${sc.optimistic.property_tax_monthly:,.2f}",
                            f"${sc.optimistic.net_cash_flow_monthly:,.2f}", f"${sc.optimistic.net_cash_flow_annual:,.2f}",
                            f"{sc.optimistic.cap_rate}%", f"{sc.optimistic.cash_on_cash_pct}%", f"{sc.optimistic_roi.irr_5y:.1f}%"
                        ]
                    })
                    st.table(scenario_tbl)
                    
                    # Mortgage specifics card
                    st.markdown("**Mortgage Schedule Breakdown**")
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Monthly Payment", f"${m.monthly_payment:,.2f}")
                    col_m2.metric("Year 1 Interest Paid", f"${m.interest_paid_y1:,.2f}")
                    col_m3.metric("5-Year Balance Forecast", f"${m.remaining_balance_y5:,.2f}")
                    col_m4.metric("10-Year Balance Forecast", f"${m.remaining_balance_y10:,.2f}")

        # ------------------ TAB 3: LOCATION MAPS & COMPS ------------------
        with tab_comps:
            st.subheader("🗺️ Geographic Proximity & Market Valuation")
            
            for ev in evaluations:
                listing = ev.listing
                comps = ev.comparables
                transit = ev.transit
                
                with st.expander(f"📍 Map & Comps Analysis: {listing.address}", expanded=True):
                    # Map section
                    st.markdown("**Interactive Location Map (Subject, Transit Hubs, Schools, & Comps)**")
                    property_map = build_property_map(ev)
                    st_folium(property_map, height=350, width=700, key=f"map_{listing.mls_number}")
                    
                    # Comparable properties table
                    st.markdown("**Comparable Sales Dashboard**")
                    comp_list = []
                    for c_listing in comps.comparable_listings:
                        comp_list.append({
                            "Comparable Address": c_listing["address"],
                            "Sold Price": f"${c_listing['price']:,.0f}",
                            "Size (Sqft)": c_listing["sqft"],
                            "Price/Sqft": f"${c_listing['price_per_sqft']:.2f}",
                            "Distance (km)": f"{c_listing['distance_km']:.2f} km"
                        })
                    st.table(pd.DataFrame(comp_list))
                    
                    # Comps stats
                    st.write(
                        f"📊 Comparable Average: **${comps.average_comp_price:,.2f}** "
                        f"(${comps.comp_price_per_sqft:.2f}/sqft). Discount: **{comps.price_discount_pct}%**."
                    )
                    
                    # School catches card
                    st.markdown("**School Catchment Quality Indicators**")
                    st.write(
                        f"🏫 **Elementary**: `{ev.schools.elementary_school}` (Fraser Score: **{ev.schools.elementary_rating}/10**). "
                        f"🏫 **Secondary**: `{ev.schools.secondary_school}` (Fraser Score: **{ev.schools.secondary_rating}/10**)."
                    )

        # ------------------ TAB 4: PROPERTY COMPARISON GRID ------------------
        with tab_compare:
            st.subheader("👥 Comparative Property Matrix")
            
            # Select properties to compare
            addresses = [ev.listing.address for ev in evaluations]
            selected_addresses = st.multiselect("Select properties to compare:", addresses, default=addresses[:2])
            
            if len(selected_addresses) < 1:
                st.info("Select at least one property to view the comparative matrix.")
            else:
                compare_data = []
                for ev in evaluations:
                    if ev.listing.address in selected_addresses:
                        compare_data.append({
                            "Rank": ev.overall_rank,
                            "Address": ev.listing.address,
                            "Score": f"{ev.composite_score}/100",
                            "Price": f"${ev.listing.price:,.0f}",
                            "Beds/Baths": f"{ev.listing.beds}B / {ev.listing.baths}B",
                            "Monthly Cash Flow": f"${ev.cash_flow.net_cash_flow_monthly:,.2f}",
                            "Cap Rate": f"{ev.cash_flow.cap_rate}%",
                            "Cash-on-Cash": f"{ev.cash_flow.cash_on_cash_pct}%",
                            "IRR (5y)": f"{ev.roi.irr_5y:.1f}%",
                            "Risk Level": ev.risk.risk_level,
                            "Transit Score": f"{ev.transit.transit_score}/10",
                            "School Rating": f"{ev.schools.average_school_rating}/10",
                            "Dev Score": f"{ev.development.development_score}/10"
                        })
                st.table(pd.DataFrame(compare_data))

        # ------------------ SHEET SYNC & EXPORTS SECTION ------------------
        st.write("---")
        st.subheader("📊 Document Exporters & Synchronizations")
        
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            # Excel Multi-sheet download
            excel_bytes = export_evaluations_to_excel(evaluations)
            st.download_button(
                label="📥 Download Multi-Tab Excel Workbook",
                data=excel_bytes,
                file_name="metro_vancouver_investment_matrix.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_excel_btn"
            )
            
        with col_exp2:
            default_sheet_id = ""
            try:
                # 1. Check exact key matches
                default_sheet_id = st.secrets.get("google_spreadsheet_id", "")
                if not default_sheet_id:
                    default_sheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
                
                # 2. Smart key auto-search (handles alternative naming like google_sheet_url, sheet_id, etc.)
                if not default_sheet_id:
                    for key in st.secrets.keys():
                        if "sheet" in key.lower() or "spreadsheet" in key.lower():
                            val = st.secrets[key]
                            if isinstance(val, str) and (len(val) > 15 or "docs.google.com" in val):
                                default_sheet_id = val
                                break
                            elif isinstance(val, dict):
                                for subkey in ["id", "url", "spreadsheet_id"]:
                                    if subkey in val:
                                        default_sheet_id = val[subkey]
                                        break
                                if default_sheet_id:
                                    break
            except Exception:
                pass
                
            # Fallback to local configuration file
            if not default_sheet_id:
                try:
                    import json
                    gmail_config_path = "gmail_config.json"
                    if os.path.exists(gmail_config_path):
                        with open(gmail_config_path, "r", encoding="utf-8") as f:
                            saved_config = json.load(f)
                            default_sheet_id = saved_config.get("sheet_url", "")
                except Exception:
                    pass
                    
            spreadsheet_input = st.text_input(
                "Google Sheet Link / URL:",
                value=default_sheet_id,
                placeholder="Paste your shared Google Spreadsheet URL here...",
                key="sheets_url_input"
            )
            
        sync_btn = st.button("📤 Sync Evaluated Listings to Google Sheets", use_container_width=True, type="primary")
        
        if sync_btn:
            if not spreadsheet_input:
                st.error("Please enter a Google Spreadsheet ID/URL.")
            else:
                with st.spinner("Authorizing connection and appending rows..."):
                    client = sheets_helper.get_gspread_client()
                    if client:
                        spreadsheet = sheets_helper.get_spreadsheet(client, spreadsheet_input)
                        if spreadsheet:
                            # Save this spreadsheet URL permanently to local configuration
                            try:
                                import json
                                gmail_config_path = "gmail_config.json"
                                config_data = {"gmail_user": "", "gmail_password": "", "sheet_url": ""}
                                if os.path.exists(gmail_config_path):
                                    with open(gmail_config_path, "r", encoding="utf-8") as f:
                                        config_data = json.load(f)
                                config_data["sheet_url"] = spreadsheet_input
                                with open(gmail_config_path, "w", encoding="utf-8") as f:
                                    json.dump(config_data, f, indent=4)
                            except Exception:
                                pass
                            rows_data = []
                            for ev in evaluations:
                                listing = ev.listing
                                cf = ev.cash_flow
                                roi = ev.roi
                                transit = ev.transit
                                risk = ev.risk
                                
                                # Calculate the new custom metrics requested by the user
                                house_age = datetime.now().year - listing.year_built
                                price_per_lot = listing.price / listing.lot_area if listing.lot_area > 0 else 0.0
                                price_per_total_sqft = listing.price / listing.sqft if listing.sqft > 0 else 0.0
                                price_per_bed = listing.price / listing.beds if listing.beds > 0 else 0.0

                                rows_data.append({
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Address": listing.address,
                                    "Property Type": listing.property_type,
                                    "Year Built": listing.year_built,
                                    "House Age": house_age,
                                    "Lot Area": listing.lot_area,
                                    "Price per Lot Area": f"${price_per_lot:,.2f}" if price_per_lot > 0 else "N/A",
                                    "Price per Sq Size": f"${price_per_total_sqft:,.2f}" if price_per_total_sqft > 0 else "N/A",
                                    "Price per Bedroom": f"${price_per_bed:,.2f}" if price_per_bed > 0 else "N/A",
                                    "Assessed Value": f"${listing.assessed_value:,.2f}" if listing.assessed_value > 0 else "N/A",
                                    "Price": f"${listing.price:,.2f}",
                                    "Bedrooms": listing.beds,
                                    "Bathrooms": listing.baths,
                                    "Sqft": listing.sqft,
                                    "Strata Fee": f"${listing.strata_fee:.2f}",
                                    "Property Tax": f"${listing.property_tax:.2f}",
                                    "Est Rent": f"${cf.gross_rent:.2f}",
                                    "Mortgage": f"${cf.mortgage_payment:.2f}",
                                    "Net Cash Flow": f"${cf.net_cash_flow_monthly:.2f}",
                                    "Cap Rate": f"{cf.cap_rate}%",
                                    "Cash-on-Cash Return": f"{cf.cash_on_cash_pct}%",
                                    "5y IRR": f"{roi.irr_5y:.1f}%",
                                    "Transit Score": f"{transit.transit_score:.1f}/10",
                                    "Schools Catchment": f"{ev.schools.average_school_rating:.1f}/10",
                                    "Risk Score": f"{risk.risk_level}",
                                    "Composite Rank Score": f"{ev.composite_score}/100",
                                    "MLS Number": listing.mls_number,
                                    "Link": listing.link
                                })
                            
                            sync_df = pd.DataFrame(rows_data)
                            sheets_helper.sync_property_listings(spreadsheet, sync_df)


with tab_gmail:
    st.subheader("✉️ Scan Email (Gmail / Outlook) for Realtor.ca & Paragon MLS Alerts")
    st.markdown("This scanner logs into your Email inbox, extracts property listings from recent realtor emails, runs investment and cash flow analyses, and posts them directly to Google Sheets!")

    import imaplib
    import email
    from email.header import decode_header
    import json
    from utils.gemini_helper import query_gemini

    # Credentials Persistence
    gmail_config_path = "gmail_config.json"
    def load_gmail_config():
        if os.path.exists(gmail_config_path):
            try:
                with open(gmail_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"gmail_user": "", "gmail_password": "", "sheet_url": ""}

    def save_gmail_config(data):
        try:
            with open(gmail_config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            st.error(f"Failed to save credentials: {e}")

    gmail_saved = load_gmail_config()
    
    # Smart discovery for default configuration values in Secrets
    default_secret_sheet = ""
    default_secret_email = ""
    default_secret_email_pass = ""
    
    try:
        # 1. Search Google Sheet ID/URL
        default_secret_sheet = st.secrets.get("google_spreadsheet_id", "")
        if not default_secret_sheet:
            default_secret_sheet = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
        if not default_secret_sheet:
            for key in st.secrets.keys():
                if "sheet" in key.lower() or "spreadsheet" in key.lower():
                    val = st.secrets[key]
                    if isinstance(val, str) and (len(val) > 15 or "docs.google.com" in val):
                        default_secret_sheet = val
                        break
                    elif isinstance(val, dict):
                        for subkey in ["id", "url", "spreadsheet_id"]:
                            if subkey in val:
                                default_secret_sheet = val[subkey]
                                break
                        if default_secret_sheet:
                            break
                            
        # 2. Search Email Address
        default_secret_email = st.secrets.get("gmail_user", "")
        if not default_secret_email:
            default_secret_email = st.secrets.get("email_user", "")
        if not default_secret_email:
            for key in st.secrets.keys():
                kl = key.lower()
                if ("email" in kl or "gmail" in kl or "outlook" in kl) and "pass" not in kl:
                    val = st.secrets[key]
                    if isinstance(val, str) and "@" in val:
                        default_secret_email = val
                        break
                        
        # 3. Search Email App Password
        default_secret_email_pass = st.secrets.get("gmail_password", "")
        if not default_secret_email_pass:
            default_secret_email_pass = st.secrets.get("email_password", "")
        if not default_secret_email_pass:
            for key in st.secrets.keys():
                kl = key.lower()
                if ("gmail" in kl or "email" in kl or "outlook" in kl) and ("pass" in kl or "key" in kl):
                    val = st.secrets[key]
                    if isinstance(val, str) and val != "" and kl != "app_password":
                        default_secret_email_pass = val
                        break
    except:
        pass

    def get_email_secret(*keys):
        """Read email settings from flat secrets or a nested [gmail] table."""
        for key in keys:
            value = st.secrets.get(key, "")
            if value:
                return str(value)
        gmail_section = st.secrets.get("gmail", {})
        if hasattr(gmail_section, "get"):
            for key in keys:
                value = gmail_section.get(key, "") or gmail_section.get(key.lower(), "")
                if value:
                    return str(value)
        return ""

    # Streamlit Cloud does not preserve gmail_config.json reliably. Use Secrets
    # as the cloud default, while allowing values entered in this session to win.
    gmail_user_default = (
        st.session_state.get("GMAIL_USER")
        or get_email_secret("GMAIL_USER", "gmail_user", "EMAIL_USER", "email_address")
        or default_secret_email
        or gmail_saved.get("gmail_user", "")
    )
    gmail_password_default = (
        st.session_state.get("GMAIL_PASSWORD")
        or get_email_secret("GMAIL_PASSWORD", "gmail_password", "EMAIL_PASSWORD", "email_app_password")
        or default_secret_email_pass
        or gmail_saved.get("gmail_password", "")
    )
    sheet_url_default = (
        st.session_state.get("google_spreadsheet_id")
        or st.secrets.get("google_spreadsheet_id", "")
        or default_secret_sheet
        or gmail_saved.get("sheet_url", "")
    )

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        gmail_user = st.text_input("Email Address", value=gmail_user_default, placeholder="username@gmail.com or username@outlook.com")
        gmail_password = st.text_input("Email App Password", type="password", value=gmail_password_default, help="Create an App Password in your Google Account or Microsoft Account Security settings.")
    with col_g2:
        sheet_url = st.text_input("Google Spreadsheet URL or ID", value=sheet_url_default, placeholder="Paste sheet link here")
        scan_limit = st.slider("Scan Limit (Recent Emails)", min_value=5, max_value=50, value=15)

    if gmail_user:
        st.session_state["GMAIL_USER"] = gmail_user
    if gmail_password:
        st.session_state["GMAIL_PASSWORD"] = gmail_password
    if sheet_url:
        st.session_state["google_spreadsheet_id"] = sheet_url

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        gmail_btn = st.button("🚀 Scan Email & Sync Listings", type="primary", use_container_width=True)
    with col_btn2:
        save_gmail_btn = st.button("💾 Save Credentials locally", use_container_width=True)

    if save_gmail_btn:
        gmail_data = {
            "gmail_user": gmail_user,
            "gmail_password": gmail_password,
            "sheet_url": sheet_url
        }
        save_gmail_config(gmail_data)
        st.success("Credentials saved successfully!")

    if gmail_btn:
        if not gmail_user or not gmail_password:
            st.error("🔑 Please enter your Email Address and App Password!")
        elif not sheet_url:
            st.error("📊 Please specify your Google Sheet URL or ID!")
        else:
            # Determine correct IMAP server based on email domain
            email_domain = gmail_user.strip().lower().split('@')[-1]
            outlook_domains = ["outlook.com", "hotmail.com", "live.com", "msn.com", "office365.com"]
            
            if any(domain in email_domain for domain in outlook_domains):
                imap_server = "outlook.office365.com"
                service_name = "Outlook"
            else:
                imap_server = "imap.gmail.com"
                service_name = "Gmail"
                
            with st.spinner(f"📧 Connecting to {service_name} IMAP server ({imap_server})..."):
                try:
                    mail = imaplib.IMAP4_SSL(imap_server, 993)
                    mail.login(gmail_user, gmail_password)
                    mail.select("inbox")
                except Exception as e:
                    st.error(f"❌ Failed to connect to {service_name}: {e}. Check if IMAP is enabled and your App Password is correct.")
                    mail = None

            if mail:
                alert_emails = []
                with st.spinner("🔍 Searching for listing alert emails..."):
                    # Search Realtor.ca and Paragon
                    status_1, data_1 = mail.search(None, 'FROM "realtor.ca"')
                    if status_1 == "OK" and data_1[0]:
                        alert_emails.extend([(msg_id, "Realtor.ca") for msg_id in data_1[0].split()])
                    
                    status_2, data_2 = mail.search(None, 'FROM "paragonrels.com"')
                    if status_2 == "OK" and data_2[0]:
                        alert_emails.extend([(msg_id, "Paragon") for msg_id in data_2[0].split()])

                    status_3, data_3 = mail.search(None, 'FROM "paragonmessaging.com"')
                    if status_3 == "OK" and data_3[0]:
                        alert_emails.extend([(msg_id, "Paragon Mail") for msg_id in data_3[0].split()])
                        
                    # Backup check for subjects
                    status_4, data_4 = mail.search(None, 'SUBJECT "MLS"')
                    if status_4 == "OK" and data_4[0]:
                        alert_emails.extend([(msg_id, "MLS Alert") for msg_id in data_4[0].split()])

                    status_5, data_5 = mail.search(None, 'SUBJECT "Real Estate Listing"')
                    if status_5 == "OK" and data_5[0]:
                        alert_emails.extend([(msg_id, "Listing Notification") for msg_id in data_5[0].split()])

                if not alert_emails:
                    st.warning("No recent real estate alert emails found.")
                    mail.logout()
                else:
                    # Sort by message ID descending (most recent first) and unique values
                    seen_ids = set()
                    unique_alerts = []
                    for item in sorted(alert_emails, key=lambda x: int(x[0]), reverse=True):
                        if item[0] not in seen_ids:
                            seen_ids.add(item[0])
                            unique_alerts.append(item)
                            
                    unique_alerts = unique_alerts[:scan_limit]
                    st.info(f"Found {len(unique_alerts)} recent property alert emails to check!")
                    
                    progress_gmail = st.progress(0)
                    all_listings_found = []
                    
                    for idx, (msg_id, source) in enumerate(unique_alerts):
                        res, msg_data = mail.fetch(msg_id, "(RFC822)")
                        if res != "OK":
                            continue
                        
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        
                        # Extract subject
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8", errors="ignore")
                            
                        # Extract body
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if content_type == "text/plain" and "attachment" not in content_disposition:
                                    try:
                                        body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    except:
                                        pass
                                elif content_type == "text/html" and "attachment" not in content_disposition:
                                    try:
                                        html_content = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                        clean_text = re.sub("<[^<]+?>", "", html_content)
                                        body += clean_text
                                    except:
                                        pass
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                            except:
                                pass
                                
                        # Extract Paragon links
                        import html
                        paragon_links = re.findall(r'https?://[^\s"\'<>]*paragon[^\s"\'<>]+', body)
                        
                        if paragon_links:
                            for link in paragon_links[:3]: # Limit to max 3 links per email
                                decoded_link = html.unescape(link).strip()
                                decoded_link = re.sub(r'[\.\,\)\>\s\\]+$', '', decoded_link)
                                all_listings_found.append({
                                    "Link": decoded_link,
                                    "Source": "Scraper"
                                })
                        else:
                            # Use Gemini to parse text listing from email content
                            body_cleaned = " ".join(body.split())[:10000]
                            prompt = f"""
                            Extract any real estate properties mentioned for sale in the following text.
                            
                            Email Content:
                            {body_cleaned}
                            
                            Output details strictly in JSON format (list of listings):
                            [
                              {{
                                "Address": "Address string",
                                "Price": "$1,200,000",
                                "Bedrooms": 3,
                                "Bathrooms": 2,
                                "Sqft": 1500,
                                "Strata Fee": 400.0,
                                "Property Tax": 3200.0,
                                "Year Built": 2015,
                                "Property Type": "Townhouse",
                                "MLS Number": "MLS# string",
                                "Link": "URL link if any"
                              }}
                            ]
                            Only output valid JSON. If no properties found, output [].
                            """
                            try:
                                gemini_res = query_gemini(prompt, response_json=True)
                                parsed_list = json.loads(gemini_res.strip())
                                if isinstance(parsed_list, list) and parsed_list:
                                    for item in parsed_list:
                                        item["Source"] = "Gemini"
                                        all_listings_found.append(item)
                            except Exception:
                                pass
                                
                        progress_gmail.progress(int((idx + 1) / len(unique_alerts) * 100))
                    
                    mail.logout()
                    
                    # De-duplicate the discovered listings based on Link, Address, or MLS Number
                    unique_listings = []
                    seen_links = set()
                    seen_addresses = set()
                    seen_mls = set()
                    
                    for p in all_listings_found:
                        link = p.get("Link", "").strip()
                        addr = p.get("Address", "").strip().lower()
                        mls = p.get("MLS Number", "").strip().lower()
                        
                        is_duplicate = False
                        if link and link in seen_links:
                            is_duplicate = True
                        if addr and addr in seen_addresses:
                            is_duplicate = True
                        if mls and mls in seen_mls:
                            is_duplicate = True
                            
                        if not is_duplicate:
                            unique_listings.append(p)
                            if link:
                                seen_links.add(link)
                            if addr:
                                seen_addresses.add(addr)
                            if mls:
                                seen_mls.add(mls)
                                
                    all_listings_found = unique_listings
                    
                    if not all_listings_found:
                        st.warning("No listings found inside the scanned emails.")
                    else:
                        st.success(f"Discovered {len(all_listings_found)} unique property links/listings! Scraping & evaluating investments...")
                        
                        progress_eval = st.progress(0)
                        evaluated_rows = []
                        
                        for idx, p in enumerate(all_listings_found):
                            # If it needs scraping via playwright
                            if p.get("Source") == "Scraper":
                                listing_url = p.get("Link")
                                try:
                                    import sys
                                    is_headless_env = (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
                                    with RealEstateScraperTask({"url": listing_url}, headless=is_headless_env) as scraper_task:
                                        scraper_res = scraper_task.execute()
                                    if scraper_res:
                                        p_data = scraper_res[0]
                                    else:
                                        continue
                                except Exception as e:
                                    continue
                            else:
                                p_data = p
                                
                            price_val = clean_numeric_price(p_data.get("Price", 0.0))
                            if price_val == 0.0:
                                continue
                                
                            # Execute calculations
                            try:
                                default_rent = float(p_data.get("Est Rent", 2200))
                                listing_model = PropertyListing(
                                    address=p_data.get("Address", "Unknown Address"),
                                    price=price_val,
                                    beds=int(p_data.get("Bedrooms", 1)),
                                    baths=int(p_data.get("Bathrooms", 1)),
                                    sqft=int(p_data.get("Sqft", 800)),
                                    strata_fee=float(p_data.get("Strata Fee", 0.0)),
                                    property_tax=float(p_data.get("Property Tax", 0.0)),
                                    year_built=int(p_data.get("Year Built", 2000)),
                                    property_type=p_data.get("Property Type", "Condo"),
                                    lot_area=float(p_data.get("Lot Area", 0.0)),
                                    assessed_value=float(p_data.get("Assessed Value", 0.0)),
                                    mls_number=p_data.get("MLS Number", "N/A"),
                                    link=p_data.get("Link", ""),
                                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                )
                                
                                financials_model = FinancialInputs(
                                    down_payment_pct=down_payment_pct,
                                    interest_rate=interest_rate,
                                    amortization_years=amortization_years,
                                    mortgage_type=mortgage_type,
                                    payment_frequency=frequency,
                                    insurance_monthly=insurance_monthly,
                                    vacancy_rate_pct=vacancy_rate_pct,
                                    maintenance_pct=maintenance_pct,
                                    property_management_pct=prop_management_pct,
                                    utilities_landlord_paid=utilities_monthly,
                                    misc_expenses_monthly=misc_monthly,
                                    est_rent=default_rent
                                )
                                
                                principal_mortgage = price_val * (1 - (down_payment_pct / 100))
                                mort_res = calculate_mortgage_details(principal_mortgage, interest_rate, amortization_years, frequency, mortgage_type == "Variable")
                                cf_res = calculate_cash_flow_details(listing_model, financials_model, mort_res.monthly_payment)
                                app_res = calculate_appreciation_forecast(listing_model)
                                roi_res = calculate_roi_details(listing_model, financials_model, mort_res, cf_res, app_res)
                                comp_res = evaluate_comparable_sales(listing_model)
                                transit_res = evaluate_transit_score(listing_model)
                                dev_res = evaluate_development_potential(listing_model, transit_res)
                                school_res = evaluate_schools(listing_model)
                                demand_res = evaluate_rental_demand(listing_model)
                                cond_res = evaluate_property_condition(listing_model)
                                risk_res = evaluate_risk_profile(listing_model, financials_model, cond_res)
                                
                                # Scoring
                                score_app = calculate_norm_score(app_res.expected_annual_appreciation_pct, 3.0, 8.0)
                                score_cf = calculate_norm_score(cf_res.cash_on_cash_pct, -2.0, 6.0)
                                score_disc = calculate_norm_score(comp_res.price_discount_pct, -10.0, 15.0)
                                score_dev = dev_res.development_score
                                score_trans = transit_res.transit_score
                                score_dem = demand_res.rental_demand_score
                                score_sch = school_res.average_school_rating
                                
                                from utils.real_estate.data_source import detect_municipality, MUNICIPALITIES_DATA
                                m_name = detect_municipality(listing_model.address)
                                score_safe = MUNICIPALITIES_DATA.get(m_name, {}).get("safety_score", 7.0)
                                score_cond = cond_res.condition_score
                                score_risk = 10.0 - risk_res.risk_score
                                
                                weighted_val = (
                                    (w_app * score_app) +
                                    (w_cf * score_cf) +
                                    (w_disc * score_disc) +
                                    (w_dev * score_dev) +
                                    (w_trans * score_trans) +
                                    (w_dem * score_dem) +
                                    (w_sch * score_sch) +
                                    (w_safe * score_safe) +
                                    (w_cond * score_cond) +
                                    (w_risk * score_risk)
                                ) / w_sum
                                composite_score = round(weighted_val * 10.0, 1)
                                
                                # Calculate the new custom metrics requested by the user
                                house_age = datetime.now().year - listing_model.year_built
                                price_per_lot = listing_model.price / listing_model.lot_area if listing_model.lot_area > 0 else 0.0
                                price_per_total_sqft = listing_model.price / listing_model.sqft if listing_model.sqft > 0 else 0.0
                                price_per_bed = listing_model.price / listing_model.beds if listing_model.beds > 0 else 0.0

                                evaluated_rows.append({
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Address": listing_model.address,
                                    "Property Type": listing_model.property_type,
                                    "Year Built": listing_model.year_built,
                                    "House Age": house_age,
                                    "Lot Area": listing_model.lot_area,
                                    "Price per Lot Area": f"${price_per_lot:,.2f}" if price_per_lot > 0 else "N/A",
                                    "Price per Sq Size": f"${price_per_total_sqft:,.2f}" if price_per_total_sqft > 0 else "N/A",
                                    "Price per Bedroom": f"${price_per_bed:,.2f}" if price_per_bed > 0 else "N/A",
                                    "Assessed Value": f"${listing_model.assessed_value:,.2f}" if listing_model.assessed_value > 0 else "N/A",
                                    "Price": f"${listing_model.price:,.2f}",
                                    "Bedrooms": listing_model.beds,
                                    "Bathrooms": listing_model.baths,
                                    "Sqft": listing_model.sqft,
                                    "Strata Fee": f"${listing_model.strata_fee:.2f}",
                                    "Property Tax": f"${listing_model.property_tax:.2f}",
                                    "Est Rent": f"${cf_res.gross_rent:.2f}",
                                    "Mortgage": f"${mort_res.monthly_payment:.2f}",
                                    "Net Cash Flow": f"${cf_res.net_cash_flow_monthly:.2f}",
                                    "Cap Rate": f"{cf_res.cap_rate}%",
                                    "Cash-on-Cash Return": f"{cf_res.cash_on_cash_pct}%",
                                    "5y IRR": f"{roi_res.irr_5y:.1f}%",
                                    "Transit Score": f"{transit_res.transit_score:.1f}/10",
                                    "Schools Catchment": f"{school_res.average_school_rating:.1f}/10",
                                    "Risk Score": f"{risk_res.risk_level}",
                                    "Composite Rank Score": f"{composite_score}/100",
                                    "MLS Number": listing_model.mls_number,
                                    "Link": listing_model.link
                                })
                            except Exception as eval_e:
                                st.warning(f"Failed to evaluate {p_data.get('Address')}: {eval_e}")
                                
                            progress_eval.progress(int((idx + 1) / len(all_listings_found) * 100))
                            
                        # Post to Google Sheet
                        if evaluated_rows:
                            with st.spinner("📊 Posting evaluated listings to Google Sheets..."):
                                client = sheets_helper.get_gspread_client()
                                if client:
                                    spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                                    if spreadsheet:
                                        sync_df = pd.DataFrame(evaluated_rows)
                                        sheets_helper.sync_property_listings(spreadsheet, sync_df)
                                        
                            st.subheader("📋 Parsed Listing Results")
                            for idx, r in enumerate(evaluated_rows):
                                st.write(f"**{idx+1}. {r['Address']}** ({r['Property Type']})")
                                st.write(f"*Price:* {r['Price']} | *Score:* {r['Composite Rank Score']}")
                                st.write(f"*Cash Flow:* {r['Net Cash Flow']}/mo | *MLS:* {r['MLS Number']}")
                                if r["Link"]:
                                    st.write(f"[Open Listing Link]({r['Link']})")
                                st.write("---")
                        else:
                            st.warning("No listings were successfully evaluated.")
