import os
import re
import time
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def format_phone_number(raw_phone: str) -> str:
    """Normalizes any phone string (digits-only, spaces, parentheses, dots, +1) into XXX-XXX-XXXX format."""
    if not raw_phone:
        return ""
    digits = re.sub(r"\D", "", str(raw_phone).strip())
    # If 11 digits and starts with country code 1, strip leading 1
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return str(raw_phone).strip()

def _scrape_single_attempt(
    account_name: str,
    account_number: str,
    phone_number: str,
    meter_number: str | None,
    portal_url: str,
    from_str: str,
    to_str: str,
    save_path: str,
    timeout_ms: int
) -> str:
    """Executes a single login, navigation, and download attempt with Playwright."""
    with sync_playwright() as p:
        # Launch Chromium with flags required for stable Docker container operation.
        # Key flags that prevent "page crashed" errors:
        #   --disable-dev-shm-usage  : use /tmp instead of /dev/shm (avoids 64MB shm limit)
        #   --no-sandbox             : required when running as root in Docker
        #   --single-process         : prevents multi-process renderer crashes in low-memory envs
        #   --no-zygote              : avoids zygote subprocess issues in Docker
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--single-process",
                "--no-zygote",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--no-first-run",
                "--mute-audio",
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

            # 5. Trigger the Download with specified timeout
            print(f"Waiting for download event (timeout: {timeout_ms / 1000:.0f}s)...")
            with page.expect_download(timeout=timeout_ms) as download_info:
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

def scrape_and_save(from_date: datetime, to_date: datetime, data_dir: str = "/app/data") -> str:
    # 1. Pull credentials and settings from env
    account_name = (os.environ.get("ACCOUNT_NAME") or "").strip()
    account_number = (os.environ.get("ACCOUNT_NUMBER") or "").strip()
    raw_phone = os.environ.get("PHONE_NUMBER") or ""
    phone_number = format_phone_number(raw_phone)
    meter_number = (os.environ.get("METER_NUMBER") or "").strip() or None
    portal_url = os.environ.get("LOGIN_PORTAL_URL", "https://alectrautilitiesgbportal.savagedata.com/Connect/Authorize").strip()
    
    # Base download timeout in seconds (default: 120s)
    base_timeout_sec = int(os.environ.get("SCRAPER_DOWNLOAD_TIMEOUT_SECONDS", "120"))
    
    # 2. Basic Validation (METER_NUMBER is optional)
    if not all([account_name, account_number, phone_number]):
        missing = [k for k, v in {
            "ACCOUNT_NAME": account_name,
            "ACCOUNT_NUMBER": account_number,
            "PHONE_NUMBER": phone_number
        }.items() if not v]
        raise ValueError(f"Missing required environment variables for scraper: {', '.join(missing)}")
        
    print(f"Scraper triggered for Date Range: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')} | Account: {account_name} | Formatted Phone: {phone_number}")
    
    # Format strings for the Alectra input fields (e.g. MM/DD/YYYY)
    from_str = from_date.strftime("%m/%d/%Y")
    to_str = to_date.strftime("%m/%d/%Y")
    
    # Target path
    file_date = from_date.strftime('%Y-%m-%d')
    filename = f"alectra_{file_date}.xml"
    save_path = os.path.join(data_dir, filename)
    
    # Create directory if needed
    os.makedirs(data_dir, exist_ok=True)
    
    # Smart retry policy:
    # - Up to 3 attempts total
    # - Attempt 1: base_timeout_sec (e.g. 120s)
    # - Attempt 2: base_timeout_sec (e.g. 120s)
    # - Attempt 3: bumped to 5 minutes (300s)
    max_attempts = 3
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        if attempt == 3:
            current_timeout_sec = max(base_timeout_sec, 300) # 5 minutes for 3rd attempt
            print(f"\n[Scraper Attempt {attempt}/{max_attempts}] Bumping download timeout to {current_timeout_sec}s (5 minutes) for final attempt...")
        else:
            current_timeout_sec = base_timeout_sec
            print(f"\n[Scraper Attempt {attempt}/{max_attempts}] Download timeout: {current_timeout_sec}s...")

        try:
            return _scrape_single_attempt(
                account_name=account_name,
                account_number=account_number,
                phone_number=phone_number,
                meter_number=meter_number,
                portal_url=portal_url,
                from_str=from_str,
                to_str=to_str,
                save_path=save_path,
                timeout_ms=current_timeout_sec * 1000
            )
        except PlaywrightTimeoutError as e:
            last_exception = e
            print(f"[Scraper Attempt {attempt}/{max_attempts}] Download timed out after {current_timeout_sec}s.")
            if attempt < max_attempts:
                retry_wait = 5
                print(f"Portal is slow to generate XML. Retrying in {retry_wait}s (Attempt {attempt + 1} of {max_attempts})...")
                time.sleep(retry_wait)
            else:
                print(f"All {max_attempts} attempts failed. Aborting scrape.")
                raise TimeoutError(
                    f"Alectra export timed out after {max_attempts} attempts (final wait: {current_timeout_sec}s). "
                    "The SavageData portal took too long to generate the XML file for this date range."
                ) from e
        except Exception as e:
            last_exception = e
            err_str = str(e).lower()
            print(f"[Scraper Attempt {attempt}/{max_attempts}] Workflow failed: {e}")
            traceback.print_exc()
            # Retry on recoverable errors: timeouts, crashes, navigation failures
            recoverable = any(kw in err_str for kw in ["timeout", "crashed", "navigation failed", "net::", "connection"])
            if attempt < max_attempts and recoverable:
                retry_wait = 10
                print(f"Recoverable error detected. Retrying in {retry_wait}s (Attempt {attempt + 1} of {max_attempts})...")
                time.sleep(retry_wait)
            else:
                raise e

    if last_exception:
        raise last_exception
