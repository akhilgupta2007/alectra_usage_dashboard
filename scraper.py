import os
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright

def scrape_and_save(from_date: datetime, to_date: datetime, data_dir: str = "/app/data") -> str:
    # 1. Pull credentials from env
    account_name = os.environ.get("ACCOUNT_NAME")
    account_number = os.environ.get("ACCOUNT_NUMBER")
    phone_number = os.environ.get("PHONE_NUMBER")
    meter_number = os.environ.get("METER_NUMBER")
    portal_url = os.environ.get("LOGIN_PORTAL_URL", "https://alectrautilitiesgbportal.savagedata.com/Connect/Authorize")
    
    # 2. Basic Validation (METER_NUMBER is optional)
    if not all([account_name, account_number, phone_number]):
        missing = [k for k, v in {
            "ACCOUNT_NAME": account_name,
            "ACCOUNT_NUMBER": account_number,
            "PHONE_NUMBER": phone_number
        }.items() if not v]
        raise ValueError(f"Missing required environment variables for scraper: {', '.join(missing)}")
        
    print(f"Scraper triggered for Date Range: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')} | Account: {account_name}")
    
    # Format strings for the Alectra input fields (e.g. MM/DD/YYYY)
    from_str = from_date.strftime("%m/%d/%Y")
    to_str = to_date.strftime("%m/%d/%Y")
    
    # Target path
    file_date = from_date.strftime('%Y-%m-%d')
    filename = f"alectra_{file_date}.xml"
    save_path = os.path.join(data_dir, filename)
    
    # Create directory if needed
    os.makedirs(data_dir, exist_ok=True)
    
    with sync_playwright() as p:
        # Launch Chromium with optimized flags to be lighter on resources inside container
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--no-first-run",
                "--no-zygote",
                "--single-process"
            ]
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Block images and fonts to save memory and speed up scraping
        def block_resources(route):
            try:
                if route.request.resource_type in ["image", "font"]:
                    route.abort()
                else:
                    route.continue_()
            except Exception:
                pass
        
        page.route("**/*", block_resources)

        try:
            print(f"Navigating to login portal: {portal_url}...")
            page.goto(portal_url)
            page.wait_for_load_state("networkidle")
            
            # 1. Login
            print("Entering account details...")
            page.get_by_role("textbox", name="Account Name").fill(account_name)
            page.get_by_role("textbox", name="Account Number").fill(account_number)
            page.get_by_role("textbox", name="(000) 000-").fill(phone_number)
            
            print("Clicking Sign In...")
            page.get_by_text("Sign In", exact=True).click()
            page.wait_for_load_state("networkidle")
            
            # 2. Handle optional Green Button redirection/link page
            print("Checking for optional Green Button link...")
            try:
                page.get_by_role("link").click(timeout=4000)
                page.wait_for_load_state("networkidle")
                print("Optional link found and clicked.")
            except Exception:
                print("Optional link not present. Already on dashboard. Proceeding...")
                
            # 3. Set Date Range
            print(f"Setting date range in portal: {from_str} to {to_str}")
            page.get_by_role("textbox", name="From Date:").click()
            page.get_by_role("textbox", name="From Date:").fill("") 
            page.get_by_role("textbox", name="From Date:").fill(from_str)
            
            page.get_by_role("textbox", name="To Date:").click()
            page.get_by_role("textbox", name="To Date:").fill("") 
            page.get_by_role("textbox", name="To Date:").fill(to_str)

            # 4. Check the checkboxes (Select all data types)
            print("Selecting data type checkboxes...")
            page.locator(".rz-chkbox-box").first.click()
            page.locator(".rz-chkbox-box").nth(1).click()

            # 5. Trigger the Download
            with page.expect_download(timeout=120000) as download_info:
                if meter_number:
                    print(f"Triggering download for specified meter row: {meter_number}...")
                    page.get_by_role("row", name=meter_number).get_by_role("button").click()
                else:
                    print("METER_NUMBER not provided. Triggering download for first row with a button...")
                    page.get_by_role("row").filter(has=page.get_by_role("button")).first.get_by_role("button").click()
                
            download = download_info.value
            download.save_as(save_path)
            
            print(f"Success! Downloaded XML data file to: {save_path}")
            return save_path
            
        except Exception as e:
            print(f"Scraping workflow failed: {e}")
            traceback.print_exc()
            raise e
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
