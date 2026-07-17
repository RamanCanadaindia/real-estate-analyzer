import os
import sys
import json
import imaplib
import email
from email.header import decode_header
import re
from datetime import datetime

# Set up project path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_dir)

from utils.real_estate.models import PropertyListing, FinancialInputs
from utils.real_estate.calculator import (
    calculate_mortgage_details, calculate_cash_flow_details,
    calculate_appreciation_forecast, calculate_roi_details
)
from utils.real_estate.scoring import (
    evaluate_comparable_sales, evaluate_transit_score,
    evaluate_development_potential, evaluate_schools,
    evaluate_rental_demand, evaluate_property_condition,
    evaluate_risk_profile, calculate_norm_score
)
from tasks.real_estate_scraper import RealEstateScraperTask
import sheets_helper

def clean_numeric_price(price_str) -> float:
    try:
        cleaned = re.sub(r'[^\d.]', '', str(price_str))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

def run_scanner():
    print(f"[{datetime.now()}] Starting scheduled real estate email scanner...")
    
    # Load credentials
    config_path = os.path.join(project_dir, "gmail_config.json")
    if not os.path.exists(config_path):
        print(f"Error: Credentials config file '{config_path}' not found. Please save credentials in the Streamlit app first.")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    email_user = config.get("gmail_user")
    email_password = config.get("gmail_password")
    sheet_url = config.get("sheet_url")
    
    if not email_user or not email_password or not sheet_url:
        print("Error: Missing credentials or sheet URL in gmail_config.json.")
        return
        
    # Determine correct IMAP server based on email domain
    email_domain = email_user.strip().lower().split('@')[-1]
    outlook_domains = ["outlook.com", "hotmail.com", "live.com", "msn.com", "office365.com"]
    
    if any(domain in email_domain for domain in outlook_domains):
        imap_server = "outlook.office365.com"
        service_name = "Outlook"
    else:
        imap_server = "imap.gmail.com"
        service_name = "Gmail"
        
    print(f"Connecting to {service_name} IMAP server ({imap_server})...")
    try:
        mail = imaplib.IMAP4_SSL(imap_server, 993)
        mail.login(email_user, email_password)
        mail.select("inbox")
    except Exception as e:
        print(f"Error connecting to mail server: {e}")
        return

    alert_emails = []
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
        
    status_4, data_4 = mail.search(None, 'SUBJECT "MLS"')
    if status_4 == "OK" and data_4[0]:
        alert_emails.extend([(msg_id, "MLS Alert") for msg_id in data_4[0].split()])

    if not alert_emails:
        print("No recent real estate alert emails found in inbox.")
        mail.logout()
        return

    # De-duplicate email IDs and sort (process most recent 10 emails)
    seen_ids = set()
    unique_alerts = []
    for item in sorted(alert_emails, key=lambda x: int(x[0]), reverse=True):
        if item[0] not in seen_ids:
            seen_ids.add(item[0])
            unique_alerts.append(item)
            
    unique_alerts = unique_alerts[:10]
    print(f"Found {len(unique_alerts)} property alert emails to scan.")
    
    all_listings_found = []
    for msg_id, source in unique_alerts:
        res, msg_data = mail.fetch(msg_id, "(RFC822)")
        if res != "OK":
            continue
        
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        
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
                        body += re.sub("<[^<]+?>", "", html_content)
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
            for link in paragon_links[:3]:
                decoded_link = html.unescape(link).strip()
                decoded_link = re.sub(r'[\.\,\)\>\s\\]+$', '', decoded_link)
                all_listings_found.append({
                    "Link": decoded_link,
                    "Source": "Scraper"
                })
                
    mail.logout()

    # De-duplicate listings
    unique_listings = []
    seen_links = set()
    for p in all_listings_found:
        link = p.get("Link", "").strip()
        if link and link not in seen_links:
            unique_listings.append(p)
            seen_links.add(link)
    all_listings_found = unique_listings

    if not all_listings_found:
        print("No property links found inside the scanned emails.")
        return

    print(f"Scraping and underwriting {len(all_listings_found)} unique properties...")
    evaluated_rows = []
    
    for p in all_listings_found:
        listing_url = p.get("Link")
        try:
            # Run playwright headlessly
            with RealEstateScraperTask({"url": listing_url}, headless=True) as scraper_task:
                scraper_res = scraper_task.execute()
            if not scraper_res:
                continue
            p_data = scraper_res[0]
            
            price_val = clean_numeric_price(p_data.get("Price", 0.0))
            if price_val == 0.0:
                continue
                
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
                mls_number=p_data.get("MLS Number", "N/A"),
                link=p_data.get("Link", ""),
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Default Financial Assumptions
            financials_model = FinancialInputs(
                down_payment_pct=20.0,
                interest_rate=4.8,
                amortization_years=25,
                mortgage_type="Fixed",
                payment_frequency="Monthly",
                insurance_monthly=80.0,
                vacancy_rate_pct=3.0,
                maintenance_pct=5.0,
                property_management_pct=6.0,
                utilities_landlord_paid=0.0,
                misc_expenses_monthly=0.0,
                est_rent=default_rent
            )
            
            principal_mortgage = price_val * 0.8
            mort_res = calculate_mortgage_details(principal_mortgage, 4.8, 25, "Monthly", False)
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
            
            # Scoring (Default Weights: App 25%, CF 20%, Disc 15%, Dev 10%, Trans 10%, Dem 5%, Sch 5%, Safe 5%, Cond 3%, Risk 2%)
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
                (25 * score_app) +
                (20 * score_cf) +
                (15 * score_disc) +
                (10 * score_dev) +
                (10 * score_trans) +
                (5 * score_dem) +
                (5 * score_sch) +
                (5 * score_safe) +
                (3 * score_cond) +
                (2 * score_risk)
            ) / 100.0
            composite_score = round(weighted_val * 10.0, 1)
            
            # Custom Metrics
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
            print(f"Evaluated listing successfully: {listing_model.address}")
        except Exception as ex:
            print(f"Skipped listing evaluation due to error: {ex}")

    if evaluated_rows:
        print("Posting evaluations to Google Sheets...")
        try:
            client = sheets_helper.get_gspread_client()
            if client:
                spreadsheet = sheets_helper.get_spreadsheet(client, sheet_url)
                if spreadsheet:
                    import pandas as pd
                    sync_df = pd.DataFrame(evaluated_rows)
                    sheets_helper.sync_property_listings(spreadsheet, sync_df)
                    print("Google Sheets synchronization completed successfully.")
        except Exception as ex:
            print(f"Error syncing to Google Sheets: {ex}")
    else:
        print("No listings were successfully evaluated during this run.")

if __name__ == '__main__':
    run_scanner()
