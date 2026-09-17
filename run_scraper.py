import sys
import argparse
from datetime import datetime
import scraper

def main():
    parser = argparse.ArgumentParser(description="Alectra Web Scraper CLI Subprocess")
    parser.add_argument("from_date", type=str, help="Start Date (YYYY-MM-DD)")
    parser.add_argument("to_date", type=str, help="End Date (YYYY-MM-DD)")
    parser.add_argument("scan_dir", type=str, help="Output directory path")
    args = parser.parse_args()

    try:
        from_dt = datetime.strptime(args.from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(args.to_date, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        sys.exit(1)

    print(f"Scraper Subprocess: scraping {args.from_date} to {args.to_date} into {args.scan_dir}")
    try:
        scraper.scrape_and_save(from_dt, to_dt, data_dir=args.scan_dir)
        print("Scraper Subprocess: Success!")
        sys.exit(0)
    except Exception as e:
        print(f"Scraper Subprocess: Failed! {e}")
        try:
            import sqlite3
            import os
            db_path = os.environ.get("DATABASE_PATH", "green_button.db")
            conn = sqlite3.connect(db_path)
            # Ensure settings table exists (just in case)
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_scraper_error', ?)", (str(e),))
            conn.commit()
            conn.close()
        except Exception as db_err:
            print(f"Failed to write error to DB setting: {db_err}")
        sys.exit(1)

if __name__ == "__main__":
    main()
