import os
import sqlite3
import time
import shutil
import threading
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import contextmanager
from pydantic import BaseModel
from typing import Optional
import parser

app = FastAPI(title="Green Button Energy Dashboard & Alectra Scraper")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_PATH = os.environ.get("DATABASE_PATH", "green_button.db")
SCAN_DIR = os.environ.get("SCAN_FOLDER_PATH", "/app/data")

# Ensure SQLite Connection with WAL mode and proper timeout
@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000") # 8MB cache limit
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                timestamp INTEGER,
                category TEXT,
                value REAL,
                cost REAL DEFAULT 0.0,
                tou INTEGER DEFAULT 0,
                tier INTEGER DEFAULT 0,
                PRIMARY KEY (timestamp, category)
            )
        """)
        
        # Check if Column 'tou' and 'tier' exist (migration for existing database)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(readings)")
        cols = [col[1] for col in cursor.fetchall()]
        if 'tou' not in cols:
            try:
                conn.execute("ALTER TABLE readings ADD COLUMN tou INTEGER DEFAULT 0")
                print("Database migrated: added 'tou' column to readings table.")
            except Exception as e:
                print(f"Error altering table readings to add tou: {e}")
        if 'tier' not in cols:
            try:
                conn.execute("ALTER TABLE readings ADD COLUMN tier INTEGER DEFAULT 0")
                print("Database migrated: added 'tier' column to readings table.")
            except Exception as e:
                print(f"Error altering table readings to add tier: {e}")
        
        # Ensure optimal indexes for category, rate, and timestamp queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_cat_ts ON readings (category, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_cat_tou_ts ON readings (category, tou, timestamp)")
        
        # Check if columns exist in processed_files to handle updates
        cursor = conn.execute("PRAGMA table_info(processed_files)")
        columns = [row['name'] for row in cursor.fetchall()]
        if columns and 'records_imported' not in columns:
            conn.execute("DROP TABLE processed_files")
            
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_files (
                filename TEXT PRIMARY KEY,
                processed_at INTEGER,
                file_size INTEGER,
                records_imported INTEGER DEFAULT 0,
                start_time INTEGER,
                end_time INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Insert default settings
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('time_shift_hours', '0')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('scan_folder_path', ?)", (SCAN_DIR,))
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('scan_interval_minutes', '60')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('archive_retention_days', '60')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_sync_time', '')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_sync_error', '')")
        
        # Scraper-specific settings
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('scraper_run_time', '06:00')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_scraper_run', '')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_scraper_error', '')")

# Get settings helpers
def get_setting(key, default=""):
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row['value'] if row else default
    except Exception:
        return default

def set_setting(key, value):
    try:
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    except Exception as e:
        print(f"Failed to set setting {key}={value}: {e}")

# Clean up archive older than retention days
def cleanup_archive_folder(archive_folder, retention_days):
    if not os.path.exists(archive_folder):
        return
    now = time.time()
    retention_secs = float(retention_days) * 86400.0
    for file in os.listdir(archive_folder):
        file_path = os.path.join(archive_folder, file)
        if os.path.isfile(file_path) and file.lower().endswith('.xml'):
            mtime = os.path.getmtime(file_path)
            if now - mtime > retention_secs:
                print(f"Archived file cleanup (older than {retention_days} days): {file}")
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting archived file {file}: {e}")

# Sync folder logic
def scan_and_import_directory():
    scan_folder = get_setting('scan_folder_path', SCAN_DIR)
    archive_retention = float(get_setting('archive_retention_days', '60'))
    
    print(f"Scanning directory: {scan_folder}, retention {archive_retention}d")
    
    if not os.path.exists(scan_folder):
        error_msg = f"Path {scan_folder} does not exist"
        set_setting('last_sync_error', error_msg)
        print(error_msg)
        return
        
    try:
        # Create archive folder if it doesn't exist
        archive_folder = os.path.join(scan_folder, "archive")
        os.makedirs(archive_folder, exist_ok=True)
        
        # 1. Scan the main folder (process and move to archive)
        files = [f for f in os.listdir(scan_folder) if os.path.isfile(os.path.join(scan_folder, f)) and f.lower().endswith('.xml')]
        total_files = len(files)
        files_processed = 0
        total_records_inserted = 0
        
        for file in sorted(files):
            file_path = os.path.join(scan_folder, file)
            stat = os.stat(file_path)
            file_size = stat.st_size
            
            # Check if file has changed or is new
            with get_db() as conn:
                row = conn.execute("SELECT file_size FROM processed_files WHERE filename = ?", (file,)).fetchone()
                if row and row['file_size'] == file_size:
                    # File is already processed, move it to archive directly if it wasn't moved yet
                    dest_path = os.path.join(archive_folder, file)
                    if not os.path.exists(dest_path):
                        shutil.move(file_path, dest_path)
                    continue
            
            print(f"Processing new file in scan folder: {file} ({file_size} bytes)")
            readings = parser.parse_green_button_xml(file_path, time_shift_hours=0)
            
            if readings:
                records_imported = len(readings)
                start_time = min(r['timestamp'] for r in readings)
                end_time = max(r['timestamp'] for r in readings)
                
                with get_db() as conn:
                    conn.executemany("""
                        INSERT OR REPLACE INTO readings (timestamp, category, value, cost, tou, tier)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [(r['timestamp'], r['category'], r['value'], r['cost'], r.get('tou', 0), r.get('tier', 0)) for r in readings])
                        
                    # Mark file as processed in DB log
                    conn.execute("""
                        INSERT OR REPLACE INTO processed_files (filename, processed_at, file_size, records_imported, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (file, int(time.time()), file_size, records_imported, start_time, end_time))
                    
                    total_records_inserted += records_imported
            
            # Move file to archive directory
            dest_path = os.path.join(archive_folder, file)
            # If destination already exists, overwrite it
            if os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(file_path, dest_path)
            files_processed += 1
            
        # 2. Scan the archive folder (Required to allow rebuild on "Wipe & Re-import")
        archived_files = [f for f in os.listdir(archive_folder) if os.path.isfile(os.path.join(archive_folder, f)) and f.lower().endswith('.xml')]
        for file in sorted(archived_files):
            file_path = os.path.join(archive_folder, file)
            stat = os.stat(file_path)
            file_size = stat.st_size
            
            # If not in processed_files (i.e. DB wiped or new db setup), process it!
            with get_db() as conn:
                row = conn.execute("SELECT file_size FROM processed_files WHERE filename = ?", (file,)).fetchone()
                if row and row['file_size'] == file_size:
                    continue
                    
            print(f"Processing wiped/un-indexed file in archive: {file} ({file_size} bytes)")
            readings = parser.parse_green_button_xml(file_path, time_shift_hours=0)
            
            if readings:
                records_imported = len(readings)
                start_time = min(r['timestamp'] for r in readings)
                end_time = max(r['timestamp'] for r in readings)
                
                with get_db() as conn:
                    conn.executemany("""
                        INSERT OR REPLACE INTO readings (timestamp, category, value, cost, tou, tier)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [(r['timestamp'], r['category'], r['value'], r['cost'], r.get('tou', 0), r.get('tier', 0)) for r in readings])
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO processed_files (filename, processed_at, file_size, records_imported, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (file, int(time.time()), file_size, records_imported, start_time, end_time))
                    
                    total_records_inserted += records_imported
                    files_processed += 1
                    
        # 3. Cleanup files in archive folder older than retention period
        cleanup_archive_folder(archive_folder, archive_retention)
            
        set_setting('last_sync_time', datetime.now(timezone.utc).isoformat())
        set_setting('last_sync_error', '')
        print(f"Sync complete. Processed/checked files. Inserted {total_records_inserted} intervals.")
        
    except Exception as e:
        error_msg = f"Sync Error: {str(e)}"
        set_setting('last_sync_error', error_msg)
        print(error_msg)

# Background scheduler thread for folder scanner
def start_folder_scanner():
    def loop():
        last_scan_time = 0
        while True:
            try:
                interval_mins = float(get_setting('scan_interval_minutes', '60'))
                interval_secs = interval_mins * 60.0
                now = time.time()
                
                if now - last_scan_time >= interval_secs:
                    scan_and_import_directory()
                    last_scan_time = now
            except Exception as e:
                print(f"Exception in scanner loop: {e}")
            time.sleep(10) # Wake up and check settings/elapsed time every 10 seconds
            
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

# Helper to execute web scraper inside isolated subprocess to save continuous RAM
def _run_scraper_isolated(from_dt: datetime, to_dt: datetime) -> None:
    # 1. Double-run prevention (Lock check)
    if get_setting('scraper_active', 'false') == 'true':
        raise Exception("A scraping process is already running. Please wait for it to complete.")
        
    try:
        set_setting('scraper_active', 'true')
        
        from_str = from_dt.strftime("%Y-%m-%d")
        to_str = to_dt.strftime("%Y-%m-%d")
        scan_path = get_setting('scan_folder_path', SCAN_DIR)
        
        print(f"Spawning scraper subprocess: python run_scraper.py {from_str} {to_str} {scan_path}")
        res = subprocess.run([
            sys.executable,
            "run_scraper.py",
            from_str,
            to_str,
            scan_path
        ])
        
        # Check return code
        if res.returncode != 0:
            raise Exception(f"Scraper Subprocess exited with error code {res.returncode}. See Docker container logs for details.")
                
        set_setting('last_scraper_run', datetime.now(timezone.utc).isoformat())
        set_setting('last_scraper_error', '')
        
        # Immediately run scanner to parse newly downloaded files
        scan_and_import_directory()
        
    finally:
        set_setting('scraper_active', 'false')

# Background scheduler thread for daily web scraper runs
def start_daily_scraper():
    def loop():
        last_run_date = ""
        
        # Check environment variables
        has_credentials = all([
            os.environ.get("ACCOUNT_NAME"),
            os.environ.get("ACCOUNT_NUMBER"),
            os.environ.get("PHONE_NUMBER")
        ])
        
        # 1. Handle startup scrape if configured
        scrape_on_startup = os.environ.get("SCRAPE_ON_STARTUP", "true").lower() == "true"
        if scrape_on_startup:
            if has_credentials:
                print("SCRAPE_ON_STARTUP is enabled. Running initial scrape...")
                set_setting('last_scraper_error', 'Running startup scrape...')
                try:
                    from_dt = datetime.now() - timedelta(days=2)
                    to_dt = datetime.now() - timedelta(days=1)
                    _run_scraper_isolated(from_dt, to_dt)
                    last_run_date = datetime.now().strftime("%Y-%m-%d")
                except Exception as e:
                    err_msg = f"Startup Scrape Failed: {str(e)}"
                    set_setting('last_scraper_error', err_msg)
                    print(err_msg)
            else:
                print("Startup scrape skipped: Scraper environment variables are not configured.")
                
        # 2. Check scheduled runs
        while True:
            try:
                run_time_str = get_setting('scraper_run_time', '06:00') # format: "HH:MM"
                now = datetime.now()
                current_time_str = now.strftime("%H:%M")
                current_date_str = now.strftime("%Y-%m-%d")
                
                if current_time_str == run_time_str and last_run_date != current_date_str:
                    print(f"Scheduled time reached: {run_time_str}. Triggering daily scrape...")
                    
                    # Reload env status dynamically
                    has_creds = all([
                        os.environ.get("ACCOUNT_NAME"),
                        os.environ.get("ACCOUNT_NUMBER"),
                        os.environ.get("PHONE_NUMBER")
                    ])
                    
                    if has_creds:
                        set_setting('last_scraper_error', f'Running daily scrape for {current_date_str}...')
                        from_dt = now - timedelta(days=2)
                        to_dt = now - timedelta(days=1)
                        try:
                            _run_scraper_isolated(from_dt, to_dt)
                            last_run_date = current_date_str
                        except Exception as e:
                            err_msg = f"Scheduled Scrape Failed: {str(e)}"
                            set_setting('last_scraper_error', err_msg)
                            print(err_msg)
                    else:
                        err_msg = "Daily scrape skipped: Scraper environment variables are not configured."
                        set_setting('last_scraper_error', err_msg)
                        print(err_msg)
                        last_run_date = current_date_str # Skip today so we don't poll-warn continuously
                        
            except Exception as e:
                err_msg = f"Scheduled Scrape Failed: {str(e)}"
                set_setting('last_scraper_error', err_msg)
                print(err_msg)
                
            time.sleep(30) # Poll every 30 seconds
            
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

# API Endpoints
@app.on_event("startup")
def startup_event():
    init_db()
    set_setting('scraper_active', 'false')
    start_folder_scanner()
    start_daily_scraper()

@app.get("/api/status")
def get_status():
    with get_db() as conn:
        total_readings = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        consumption_readings = conn.execute("SELECT COUNT(*) FROM readings WHERE category = 'consumption'").fetchone()[0]
        production_readings = conn.execute("SELECT COUNT(*) FROM readings WHERE category = 'production'").fetchone()[0]
        processed_files_count = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
        
        last_sync = get_setting('last_sync_time')
        last_error = get_setting('last_sync_error')
        time_shift = get_setting('time_shift_hours', '0')
        scan_folder = get_setting('scan_folder_path', SCAN_DIR)
        scan_interval = get_setting('scan_interval_minutes', '60')
        archive_retention = get_setting('archive_retention_days', '60')
        
        # Scraper integration details
        scraper_run_time = get_setting('scraper_run_time', '06:00')
        last_scraper_run = get_setting('last_scraper_run', '')
        last_scraper_error = get_setting('last_scraper_error', '')
        scraper_active = get_setting('scraper_active', 'false') == 'true'
        has_credentials = all([
            os.environ.get("ACCOUNT_NAME"),
            os.environ.get("ACCOUNT_NUMBER"),
            os.environ.get("PHONE_NUMBER")
        ])
        
        # Get list of recently processed files with detailed logs
        files_rows = conn.execute("""
            SELECT filename, processed_at, file_size, records_imported, start_time, end_time 
            FROM processed_files 
            ORDER BY processed_at DESC 
            LIMIT 50
        """).fetchall()
        files_list = [{
            "filename": r['filename'], 
            "processed_at": r['processed_at'], 
            "file_size": r['file_size'],
            "records_imported": r['records_imported'],
            "start_time": r['start_time'],
            "end_time": r['end_time']
        } for r in files_rows]

        return {
            "total_readings": total_readings,
            "consumption_readings": consumption_readings,
            "production_readings": production_readings,
            "processed_files_count": processed_files_count,
            "last_sync": last_sync,
            "last_error": last_error,
            "time_shift_hours": float(time_shift),
            "scan_folder": scan_folder,
            "scan_interval_minutes": float(scan_interval),
            "archive_retention_days": float(archive_retention),
            "recent_files": files_list,
            # Scraper Info
            "scraper_run_time": scraper_run_time,
            "last_scraper_run": last_scraper_run,
            "last_scraper_error": last_scraper_error,
            "scraper_configured": has_credentials,
            "scraper_active": scraper_active
        }

@app.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_and_import_directory)
    return {"status": "Sync task scheduled in background"}

@app.get("/api/settings")
def get_settings():
    return {
        "time_shift_hours": float(get_setting('time_shift_hours', '0')),
        "scan_folder_path": get_setting('scan_folder_path', SCAN_DIR),
        "scan_interval_minutes": float(get_setting('scan_interval_minutes', '60')),
        "archive_retention_days": float(get_setting('archive_retention_days', '60')),
        "scraper_run_time": get_setting('scraper_run_time', '06:00')
    }

@app.post("/api/settings")
def update_settings(
    time_shift_hours: float = Form(0.0),
    scan_folder_path: Optional[str] = Form(None),
    scan_interval_minutes: float = Form(60.0),
    archive_retention_days: float = Form(60.0),
    scraper_run_time: str = Form("06:00")
):
    print(f"[DEBUG] update_settings received settings update with time_shift_hours: {time_shift_hours}")
    set_setting('time_shift_hours', time_shift_hours)
    if scan_folder_path is not None:
        set_setting('scan_folder_path', scan_folder_path)
    set_setting('scan_interval_minutes', scan_interval_minutes)
    set_setting('archive_retention_days', archive_retention_days)
    set_setting('scraper_run_time', scraper_run_time)
    print(f"[DEBUG] settings committed. new time_shift_hours={get_setting('time_shift_hours')}")
    return {"status": "Settings updated successfully"}

@app.post("/api/reimport")
def trigger_reimport(background_tasks: BackgroundTasks):
    def reimport_task():
        with get_db() as conn:
            conn.execute("DELETE FROM readings")
            conn.execute("DELETE FROM processed_files")
        print("Database wiped for re-import.")
        scan_and_import_directory()
        
    background_tasks.add_task(reimport_task)
    return {"status": "Database wipe and full re-import scheduled"}

@app.post("/api/upload")
def upload_xml_file(file: UploadFile = File(...)):
    scan_folder = get_setting('scan_folder_path', SCAN_DIR)
    
    temp_path = f"temp_{file.filename}"
    try:
        with open(temp_path, "wb") as buffer:
            buffer.write(file.file.read())
            
        readings = parser.parse_green_button_xml(temp_path, time_shift_hours=0)
        
        if readings:
            inserted = len(readings)
            start_time = min(r['timestamp'] for r in readings)
            end_time = max(r['timestamp'] for r in readings)
            file_size = os.path.getsize(temp_path)
            
            with get_db() as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO readings (timestamp, category, value, cost, tou, tier)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [(r['timestamp'], r['category'], r['value'], r['cost'], r.get('tou', 0), r.get('tier', 0)) for r in readings])
                    
                # Log upload metadata
                conn.execute("""
                    INSERT OR REPLACE INTO processed_files (filename, processed_at, file_size, records_imported, start_time, end_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (file.filename, int(time.time()), file_size, inserted, start_time, end_time))
            
            # Save copy to archive
            archive_folder = os.path.join(scan_folder, "archive")
            os.makedirs(archive_folder, exist_ok=True)
            dest_path = os.path.join(archive_folder, file.filename)
            shutil.copy(temp_path, dest_path)
            
            return {"status": "success", "message": f"Processed file. Inserted/updated {inserted} intervals."}
        else:
            return {"status": "error", "message": "No valid intervals parsed from file"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.get("/api/data")
def get_data(
    resolution: str = Query("1h", pattern="^(15min|1h|1d|1m|1y)$"),
    start: int = Query(None),
    end: int = Query(None),
    date_range: Optional[str] = Query(None)
):
    with get_db() as conn:
        time_shift = float(get_setting('time_shift_hours', '0'))
        drift_sec = int(time_shift * 3600)
        
        # Handle 'latest_day': automatically find the most recent available date in database
        if date_range == "latest_day":
            max_row = conn.execute("SELECT MAX(timestamp) FROM readings").fetchone()
            if max_row and max_row[0]:
                max_ts = max_row[0]
                dt = datetime.fromtimestamp(max_ts + drift_sec, tz=timezone.utc)
                day_start = int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp())
                day_end = day_start + 86399
                start = day_start
                end = day_end
        
        # Resolution safety guards to bound memory and CPU usage
        if resolution == "15min":
            # 15-minute resolution is constrained to at most 2 days (up to 192 intervals)
            if start is None:
                max_row = conn.execute("SELECT MAX(timestamp) FROM readings").fetchone()
                latest_ts = max_row[0] if (max_row and max_row[0]) else int(time.time())
                start = latest_ts - (2 * 86400)
            elif end is not None and (end - start) > (2 * 86400):
                start = end - (2 * 86400)
        elif resolution == "1h":
            # Hourly resolution is constrained to at most 14 days (up to 336 bars); step to 1d if longer
            if start is None or (end is not None and (end - start) > (14 * 86400)):
                resolution = "1d"
        
        filters = []
        params = []
        if start is not None:
            filters.append("timestamp >= ?")
            params.append(start - drift_sec)
        if end is not None:
            filters.append("timestamp <= ?")
            params.append(end - drift_sec)
            
        filter_str = " AND ".join(filters)
        if filter_str:
            filter_str = " WHERE " + filter_str
        
        # Get TOU summary breakdown (always filter for category = 'consumption')
        filters_consumption = list(filters)
        filters_consumption.append("category = 'consumption'")
        filter_str_consumption = " WHERE " + " AND ".join(filters_consumption)
        
        tou_query = f"""
            SELECT tou, SUM(value) as val, SUM(cost) as total_cost 
            FROM readings 
            {filter_str_consumption}
            GROUP BY tou
        """
        try:
            tou_rows = conn.execute(tou_query, params).fetchall()
        except Exception as e:
            tou_rows = []
            print(f"Error fetching TOU summary: {e}")
            
        tou_summary = {
            "on_peak_kwh": 0.0, "on_peak_cost": 0.0,
            "mid_peak_kwh": 0.0, "mid_peak_cost": 0.0,
            "off_peak_kwh": 0.0, "off_peak_cost": 0.0,
            "ulo_kwh": 0.0, "ulo_cost": 0.0,
            "other_kwh": 0.0, "other_cost": 0.0
        }
        for tr in tou_rows:
            code = tr['tou']
            val = tr['val'] or 0.0
            cost = tr['total_cost'] or 0.0
            if code == 1:
                tou_summary["on_peak_kwh"] += val
                tou_summary["on_peak_cost"] += cost
            elif code == 2:
                tou_summary["mid_peak_kwh"] += val
                tou_summary["mid_peak_cost"] += cost
            elif code == 3:
                tou_summary["off_peak_kwh"] += val
                tou_summary["off_peak_cost"] += cost
            elif code == 4:
                tou_summary["ulo_kwh"] += val
                tou_summary["ulo_cost"] += cost
            else:
                tou_summary["other_kwh"] += val
                tou_summary["other_cost"] += cost
                
        # Get Tier summary breakdown
        tier_query = f"""
            SELECT tier, SUM(value) as val, SUM(cost) as total_cost 
            FROM readings 
            {filter_str_consumption}
            GROUP BY tier
        """
        try:
            tier_rows = conn.execute(tier_query, params).fetchall()
        except Exception as e:
            tier_rows = []
            print(f"Error fetching Tier summary: {e}")
            
        tier_summary = {
            "tier1_kwh": 0.0, "tier1_cost": 0.0,
            "tier2_kwh": 0.0, "tier2_cost": 0.0,
            "tier3_kwh": 0.0, "tier3_cost": 0.0,
            "other_kwh": 0.0, "other_cost": 0.0
        }
        for tr in tier_rows:
            code = tr['tier']
            val = tr['val'] or 0.0
            cost = tr['total_cost'] or 0.0
            if code == 1:
                tier_summary["tier1_kwh"] += val
                tier_summary["tier1_cost"] += cost
            elif code == 2:
                tier_summary["tier2_kwh"] += val
                tier_summary["tier2_cost"] += cost
            elif code == 3:
                tier_summary["tier3_kwh"] += val
                tier_summary["tier3_cost"] += cost
            else:
                tier_summary["other_kwh"] += val
                tier_summary["other_cost"] += cost
            
        # Initialize structured result
        result = {
            "resolution": resolution,
            "consumption": [],
            "consumption_cost": [],
            "production": [],
            "production_cost": [],
            "tou_breakdown": {
                "on_peak": [],
                "on_peak_cost": [],
                "mid_peak": [],
                "mid_peak_cost": [],
                "off_peak": [],
                "off_peak_cost": [],
                "ulo": [],
                "ulo_cost": [],
                "other": [],
                "other_cost": []
            },
            "tier_breakdown": {
                "tier1": [],
                "tier1_cost": [],
                "tier2": [],
                "tier2_cost": [],
                "tier3": [],
                "tier3_cost": [],
                "other": [],
                "other_cost": []
            },
            "tou_summary": tou_summary,
            "tier_summary": tier_summary
        }

        def make_bucket():
            return {
                'total': 0.0, 'cost': 0.0,
                'tou': {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 0: 0.0},
                'tou_cost': {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 0: 0.0},
                'tier': {1: 0.0, 2: 0.0, 3: 0.0, 0: 0.0},
                'tier_cost': {1: 0.0, 2: 0.0, 3: 0.0, 0: 0.0}
            }

        consumption_map = {}
        production_map = {}

        if resolution == "15min":
            query = f"""
                SELECT (timestamp + {drift_sec}) * 1000 AS time_ms, category, tou, tier, value, cost 
                FROM readings 
                {filter_str} 
                ORDER BY timestamp ASC
            """
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                time_ms = r['time_ms']
                cat = r['category']
                val = r['value'] or 0.0
                cost = r['cost'] or 0.0
                tou = r['tou'] or 0
                tier = r['tier'] or 0
                if cat == "consumption":
                    if time_ms not in consumption_map:
                        consumption_map[time_ms] = make_bucket()
                    b = consumption_map[time_ms]
                    b['total'] += val
                    b['cost'] += cost
                    tou_key = tou if tou in [1, 2, 3, 4] else 0
                    b['tou'][tou_key] += val
                    b['tou_cost'][tou_key] += cost
                    tier_key = tier if tier in [1, 2, 3] else 0
                    b['tier'][tier_key] += val
                    b['tier_cost'][tier_key] += cost
                elif cat == "production":
                    if time_ms not in production_map:
                        production_map[time_ms] = {'total': 0.0, 'cost': 0.0}
                    production_map[time_ms]['total'] += val
                    production_map[time_ms]['cost'] += cost

        elif resolution in ["1h", "1d", "1m", "1y"]:
            if resolution == "1h":
                time_expr = f"(((timestamp + {drift_sec}) / 3600) * 3600) * 1000"
            elif resolution == "1d":
                time_expr = f"unixepoch(date(timestamp + {drift_sec}, 'auto')) * 1000"
            elif resolution == "1m":
                time_expr = f"unixepoch(date(timestamp + {drift_sec}, 'auto', 'start of month')) * 1000"
            else: # 1y
                time_expr = f"unixepoch(date(timestamp + {drift_sec}, 'auto', 'start of year')) * 1000"

            query = f"""
                SELECT {time_expr} AS time_ms, category, tou, tier, SUM(value) as val, SUM(cost) as total_cost 
                FROM readings 
                {filter_str} 
                GROUP BY time_ms, category, tou, tier 
                ORDER BY time_ms ASC
            """
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                time_ms = r['time_ms']
                cat = r['category']
                val = r['val'] or 0.0
                cost = r['total_cost'] or 0.0
                tou = r['tou'] or 0
                tier = r['tier'] or 0
                if cat == "consumption":
                    if time_ms not in consumption_map:
                        consumption_map[time_ms] = make_bucket()
                    b = consumption_map[time_ms]
                    b['total'] += val
                    b['cost'] += cost
                    tou_key = tou if tou in [1, 2, 3, 4] else 0
                    b['tou'][tou_key] += val
                    b['tou_cost'][tou_key] += cost
                    tier_key = tier if tier in [1, 2, 3] else 0
                    b['tier'][tier_key] += val
                    b['tier_cost'][tier_key] += cost
                elif cat == "production":
                    if time_ms not in production_map:
                        production_map[time_ms] = {'total': 0.0, 'cost': 0.0}
                    production_map[time_ms]['total'] += val
                    production_map[time_ms]['cost'] += cost

        # Collect all timestamps in sorted order
        all_timestamps = sorted(set(list(consumption_map.keys()) + list(production_map.keys())))
        for ms in all_timestamps:
            c = consumption_map.get(ms, make_bucket())
            p = production_map.get(ms, {'total': 0.0, 'cost': 0.0})
            
            result["consumption"].append([ms, round(c['total'], 4)])
            result["consumption_cost"].append([ms, round(c['cost'], 4)])
            result["production"].append([ms, round(p['total'], 4)])
            result["production_cost"].append([ms, round(p['cost'], 4)])
            
            # TOU series
            result["tou_breakdown"]["on_peak"].append([ms, round(c['tou'].get(1, 0.0), 4)])
            result["tou_breakdown"]["on_peak_cost"].append([ms, round(c['tou_cost'].get(1, 0.0), 4)])
            result["tou_breakdown"]["mid_peak"].append([ms, round(c['tou'].get(2, 0.0), 4)])
            result["tou_breakdown"]["mid_peak_cost"].append([ms, round(c['tou_cost'].get(2, 0.0), 4)])
            result["tou_breakdown"]["off_peak"].append([ms, round(c['tou'].get(3, 0.0), 4)])
            result["tou_breakdown"]["off_peak_cost"].append([ms, round(c['tou_cost'].get(3, 0.0), 4)])
            result["tou_breakdown"]["ulo"].append([ms, round(c['tou'].get(4, 0.0), 4)])
            result["tou_breakdown"]["ulo_cost"].append([ms, round(c['tou_cost'].get(4, 0.0), 4)])
            result["tou_breakdown"]["other"].append([ms, round(c['tou'].get(0, 0.0), 4)])
            result["tou_breakdown"]["other_cost"].append([ms, round(c['tou_cost'].get(0, 0.0), 4)])
            
            # Tier series
            result["tier_breakdown"]["tier1"].append([ms, round(c['tier'].get(1, 0.0), 4)])
            result["tier_breakdown"]["tier1_cost"].append([ms, round(c['tier_cost'].get(1, 0.0), 4)])
            result["tier_breakdown"]["tier2"].append([ms, round(c['tier'].get(2, 0.0), 4)])
            result["tier_breakdown"]["tier2_cost"].append([ms, round(c['tier_cost'].get(2, 0.0), 4)])
            result["tier_breakdown"]["tier3"].append([ms, round(c['tier'].get(3, 0.0), 4)])
            result["tier_breakdown"]["tier3_cost"].append([ms, round(c['tier_cost'].get(3, 0.0), 4)])
            result["tier_breakdown"]["other"].append([ms, round(c['tier'].get(0, 0.0), 4)])
            result["tier_breakdown"]["other_cost"].append([ms, round(c['tier_cost'].get(0, 0.0), 4)])

        return result


# Manual Scrape Endpoints
class ManualScrapeRequest(BaseModel):
    from_date: Optional[str] = None
    to_date: Optional[str] = None

@app.post("/api/scraper/scrape")
def trigger_manual_scrape(req: ManualScrapeRequest, background_tasks: BackgroundTasks):
    has_credentials = all([
        os.environ.get("ACCOUNT_NAME"),
        os.environ.get("ACCOUNT_NUMBER"),
        os.environ.get("PHONE_NUMBER")
    ])
    if not has_credentials:
        return {
            "status": "error", 
            "message": "Scraper is not configured. Please set ACCOUNT_NAME, ACCOUNT_NUMBER, and PHONE_NUMBER in the environment variables."
        }
        
    if get_setting('scraper_active', 'false') == 'true':
        return {
            "status": "error",
            "message": "A scraping process is already running. Please wait for it to complete."
        }
        
    try:
        if req.from_date:
            from_dt = datetime.strptime(req.from_date, "%Y-%m-%d")
        else:
            from_dt = datetime.now() - timedelta(days=2)
            
        if req.to_date:
            to_dt = datetime.strptime(req.to_date, "%Y-%m-%d")
        else:
            to_dt = datetime.now() - timedelta(days=1)
    except Exception as e:
        return {
            "status": "error", 
            "message": f"Invalid date format. Expected YYYY-MM-DD. Error: {str(e)}"
        }

    def run_scraper_task():
        set_setting('last_scraper_error', 'Running manual scrape...')
        try:
            _run_scraper_isolated(from_dt, to_dt)
        except Exception as err:
            error_msg = f"Manual scrape error: {str(err)}"
            set_setting('last_scraper_error', error_msg)
            print(error_msg)

    background_tasks.add_task(run_scraper_task)
    return {"status": "success", "message": "Manual scraper run scheduled in background."}

# Mount MCP SSE Server endpoints
try:
    import mcp_tools
    mcp_app = mcp_tools.get_sse_starlette_app()
    app.routes.extend(mcp_app.routes)
    print("MCP SSE endpoint mounted at /sse and /messages")
except Exception as e:
    print(f"Warning: Could not mount MCP SSE endpoint: {e}")

# Mount Static frontend files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_files")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

