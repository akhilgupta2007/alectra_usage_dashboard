import os
import sqlite3
import time
import shutil
import threading
import subprocess
import sys
import gc
import ctypes
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import contextmanager
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import parser
import ontario_holidays

def release_memory():
    """Forces Python garbage collection and instructs glibc to release free memory back to the OS."""
    gc.collect()
    try:
        # Calls glibc malloc_trim(0) on Linux to release arena memory to OS
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

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

        # Alectra Statement Billing Parameters
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_fixed_delivery_monthly', '35.38')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_volumetric_delivery_kwh', '0.0175')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_line_loss_factor', '1.034100')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_regulatory_kwh', '0.005983')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_oer_percent', '23.5')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_hst_percent', '13.0')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_apply_hst', 'true')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('billing_apply_oer', 'true')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('active_rate_plan', 'tou')")

        # Ontario Energy Board (OEB) Rate Schedule — effective Nov 1, 2024
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tou_on_peak', '0.203')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tou_mid_peak', '0.157')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tou_off_peak', '0.098')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_ulo_ultra_low_overnight', '0.039')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_ulo_off_peak', '0.098')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_ulo_mid_peak', '0.157')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_ulo_on_peak', '0.391')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tiered_tier1', '0.120')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tiered_tier2', '0.142')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tiered_threshold_summer', '600.0')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_tiered_threshold_winter', '1000.0')")

# Get settings helpers
def get_setting(key, default=""):
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row['value'] if row else default
    except Exception:
        return default

def auto_detect_rate_plan(conn=None) -> str:
    """
    Auto-detects the enrolled Alectra rate plan from meter data in the DB:
      - ULO:    tou=4 (ultra-low overnight) intervals exist in readings
      - Tiered: consumptionTier > 0 intervals exist in readings
      - TOU:    default (on/mid/off-peak codes 1/2/3 only)
    Returns 'ulo', 'tiered', or 'tou'.
    """
    try:
        def _detect(c):
            # Check for ULO: tou code 4 = ultra-low overnight (ULO customers only)
            row = c.execute(
                "SELECT COUNT(*) as cnt FROM readings WHERE tou = 4 AND category = 'consumption'"
            ).fetchone()
            if row and row[0] > 0:
                return 'ulo'
            # Check for Tiered: consumptionTier > 0 populated by Alectra for tiered customers
            row = c.execute(
                "SELECT COUNT(*) as cnt FROM readings WHERE tier > 0 AND category = 'consumption'"
            ).fetchone()
            if row and row[0] > 0:
                return 'tiered'
            return 'tou'

        if conn is not None:
            return _detect(conn)
        with get_db() as c:
            return _detect(c)
    except Exception:
        return 'tou'

def set_setting(key, value):
    try:
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    except Exception as e:
        print(f"Failed to set setting {key}={value}: {e}")

def get_billing_parameters() -> Dict[str, Any]:
    return {
        "monthly_fixed_delivery": float(get_setting('billing_fixed_delivery_monthly', '35.38')),
        "volumetric_delivery_kwh": float(get_setting('billing_volumetric_delivery_kwh', '0.0175')),
        "line_loss_factor": float(get_setting('billing_line_loss_factor', '1.034100')),
        "regulatory_kwh": float(get_setting('billing_regulatory_kwh', '0.005983')),
        "oer_percent": float(get_setting('billing_oer_percent', '23.5')),
        "hst_percent": float(get_setting('billing_hst_percent', '13.0')),
        "apply_hst": get_setting('billing_apply_hst', 'true').lower() in ('true', '1'),
        "apply_oer": get_setting('billing_apply_oer', 'true').lower() in ('true', '1'),
        # Auto-detected from meter data (tou/tier codes in XML) — no manual setting needed
        "active_rate_plan": auto_detect_rate_plan()
    }

def save_billing_parameters(params: Dict[str, Any]):
    for k, v in params.items():
        if k == 'monthly_fixed_delivery': set_setting('billing_fixed_delivery_monthly', v)
        elif k == 'volumetric_delivery_kwh': set_setting('billing_volumetric_delivery_kwh', v)
        elif k == 'line_loss_factor': set_setting('billing_line_loss_factor', v)
        elif k == 'regulatory_kwh': set_setting('billing_regulatory_kwh', v)
        elif k == 'oer_percent': set_setting('billing_oer_percent', v)
        elif k == 'hst_percent': set_setting('billing_hst_percent', v)
        elif k == 'apply_hst': set_setting('billing_apply_hst', 'true' if v else 'false')
        elif k == 'apply_oer': set_setting('billing_apply_oer', 'true' if v else 'false')
        elif k == 'active_rate_plan': set_setting('active_rate_plan', v)

def reset_billing_parameters() -> Dict[str, Any]:
    defaults = {
        "monthly_fixed_delivery": 35.38,
        "volumetric_delivery_kwh": 0.0175,
        "line_loss_factor": 1.034100,
        "regulatory_kwh": 0.005983,
        "oer_percent": 23.5,
        "hst_percent": 13.0,
        "apply_hst": True,
        "apply_oer": True,
        "active_rate_plan": "tou"
    }
    save_billing_parameters(defaults)
    return defaults

def get_oeb_rates() -> Dict[str, Any]:
    return {
        "tou_on_peak": float(get_setting('rate_tou_on_peak', '0.203')),
        "tou_mid_peak": float(get_setting('rate_tou_mid_peak', '0.157')),
        "tou_off_peak": float(get_setting('rate_tou_off_peak', '0.098')),
        "ulo_ultra_low_overnight": float(get_setting('rate_ulo_ultra_low_overnight', '0.039')),
        "ulo_off_peak": float(get_setting('rate_ulo_off_peak', '0.098')),
        "ulo_mid_peak": float(get_setting('rate_ulo_mid_peak', '0.157')),
        "ulo_on_peak": float(get_setting('rate_ulo_on_peak', '0.391')),
        "tiered_tier1": float(get_setting('rate_tiered_tier1', '0.120')),
        "tiered_tier2": float(get_setting('rate_tiered_tier2', '0.142')),
        "summer_slab_kwh": float(get_setting('rate_tiered_threshold_summer', '600.0')),
        "winter_slab_kwh": float(get_setting('rate_tiered_threshold_winter', '1000.0'))
    }

def save_oeb_rates(rates: Dict[str, Any]):
    for k, v in rates.items():
        if k == 'tou_on_peak': set_setting('rate_tou_on_peak', v)
        elif k == 'tou_mid_peak': set_setting('rate_tou_mid_peak', v)
        elif k == 'tou_off_peak': set_setting('rate_tou_off_peak', v)
        elif k == 'ulo_ultra_low_overnight': set_setting('rate_ulo_ultra_low_overnight', v)
        elif k == 'ulo_off_peak': set_setting('rate_ulo_off_peak', v)
        elif k == 'ulo_mid_peak': set_setting('rate_ulo_mid_peak', v)
        elif k == 'ulo_on_peak': set_setting('rate_ulo_on_peak', v)
        elif k == 'tiered_tier1': set_setting('rate_tiered_tier1', v)
        elif k == 'tiered_tier2': set_setting('rate_tiered_tier2', v)
        elif k == 'summer_slab_kwh': set_setting('rate_tiered_threshold_summer', v)
        elif k == 'winter_slab_kwh': set_setting('rate_tiered_threshold_winter', v)

def reset_oeb_rates() -> Dict[str, Any]:
    # OEB rate schedule effective Nov 1, 2024
    defaults = {
        "tou_on_peak": 0.203,
        "tou_mid_peak": 0.157,
        "tou_off_peak": 0.098,
        "ulo_ultra_low_overnight": 0.039,
        "ulo_off_peak": 0.098,
        "ulo_mid_peak": 0.157,
        "ulo_on_peak": 0.391,
        "tiered_tier1": 0.120,
        "tiered_tier2": 0.142,
        "summer_slab_kwh": 600.0,
        "winter_slab_kwh": 1000.0
    }
    save_oeb_rates(defaults)
    return defaults

def calculate_bill_breakdown(
    total_kwh: float,
    commodity_cost: float,
    days_count: float,
    params: Dict[str, Any] = None,
    active_rate_plan: str = None,
    tou_summary: Dict[str, Any] = None,
    ulo_summary: Dict[str, Any] = None,
    rates: Dict[str, Any] = None,
    sample_ts: int = None
) -> Dict[str, Any]:
    if params is None:
        params = get_billing_parameters()
    if rates is None:
        rates = get_oeb_rates()
    if active_rate_plan is None:
        active_rate_plan = params.get('active_rate_plan', 'tou')

    effective_days = 30.0 if days_count <= 0.0 else days_count

    # Determine Season
    if sample_ts:
        dt = datetime.fromtimestamp(sample_ts, tz=timezone.utc)
        month = dt.month
    else:
        month = datetime.now().month
    is_summer = 5 <= month <= 10
    season_name = "Summer" if is_summer else "Winter"
    monthly_slab = rates['summer_slab_kwh'] if is_summer else rates['winter_slab_kwh']
    effective_slab = max(1.0, (effective_days / 30.0) * monthly_slab)

    # Dynamic Commodity Cost and Splitup based on active_rate_plan
    actual_commodity_cost = commodity_cost
    commodity_split = {}

    if active_rate_plan == 'tiered':
        t1 = min(total_kwh, effective_slab)
        t2 = max(0.0, total_kwh - effective_slab)
        t1_cost = t1 * rates['tiered_tier1']
        t2_cost = t2 * rates['tiered_tier2']
        actual_commodity_cost = t1_cost + t2_cost
        
        text_desc = f"Tier 1: {t1:.1f} kWh (${t1_cost:.2f}) @ {rates['tiered_tier1']*100:.1f}¢"
        if t2 > 0:
            text_desc += f" • Tier 2: {t2:.1f} kWh (${t2_cost:.2f}) @ {rates['tiered_tier2']*100:.1f}¢"
        else:
            text_desc += f" (within {effective_slab:.0f} kWh slab)"

        commodity_split = {
            "plan_id": "tiered",
            "plan_name": "Tiered Pricing",
            "tier1_kwh": round(t1, 2),
            "tier1_cost": round(t1_cost, 2),
            "tier2_kwh": round(t2, 2),
            "tier2_cost": round(t2_cost, 2),
            "effective_slab_kwh": round(effective_slab, 1),
            "season_name": season_name,
            "text": text_desc
        }
    elif active_rate_plan == 'ulo' and ulo_summary:
        kwh_ulo_overnight = ulo_summary.get('ultra_low_overnight_kwh', 0.0)
        kwh_ulo_off_peak = ulo_summary.get('off_peak_kwh', 0.0)
        kwh_ulo_mid_peak = ulo_summary.get('mid_peak_kwh', 0.0)
        kwh_ulo_on_peak = ulo_summary.get('on_peak_kwh', 0.0)

        c_ovn = kwh_ulo_overnight * rates['ulo_ultra_low_overnight']
        c_off = kwh_ulo_off_peak * rates['ulo_off_peak']
        c_mid = kwh_ulo_mid_peak * rates['ulo_mid_peak']
        c_on = kwh_ulo_on_peak * rates['ulo_on_peak']
        actual_commodity_cost = c_ovn + c_off + c_mid + c_on

        commodity_split = {
            "plan_id": "ulo",
            "plan_name": "Ultra-Low Overnight (ULO)",
            "overnight_kwh": round(kwh_ulo_overnight, 2),
            "overnight_cost": round(c_ovn, 2),
            "off_peak_kwh": round(kwh_ulo_off_peak, 2),
            "off_peak_cost": round(c_off, 2),
            "mid_peak_kwh": round(kwh_ulo_mid_peak, 2),
            "mid_peak_cost": round(c_mid, 2),
            "on_peak_kwh": round(kwh_ulo_on_peak, 2),
            "on_peak_cost": round(c_on, 2),
            "text": f"O/N: {kwh_ulo_overnight:.1f}k (${c_ovn:.2f}) • Off: {kwh_ulo_off_peak:.1f}k (${c_off:.2f}) • Mid: {kwh_ulo_mid_peak:.1f}k (${c_mid:.2f}) • Peak: {kwh_ulo_on_peak:.1f}k (${c_on:.2f})"
        }
    elif tou_summary:
        on_peak = tou_summary.get('on_peak_kwh', 0.0)
        mid_peak = tou_summary.get('mid_peak_kwh', 0.0)
        off_peak = tou_summary.get('off_peak_kwh', 0.0) + tou_summary.get('ulo_kwh', 0.0)
        c_on = on_peak * rates['tou_on_peak']
        c_mid = mid_peak * rates['tou_mid_peak']
        c_off = off_peak * rates['tou_off_peak']
        actual_commodity_cost = c_on + c_mid + c_off

        commodity_split = {
            "plan_id": "tou",
            "plan_name": "Standard Time-of-Use (TOU)",
            "on_peak_kwh": round(on_peak, 2),
            "on_peak_cost": round(c_on, 2),
            "mid_peak_kwh": round(mid_peak, 2),
            "mid_peak_cost": round(c_mid, 2),
            "off_peak_kwh": round(off_peak, 2),
            "off_peak_cost": round(c_off, 2),
            "text": f"On: {on_peak:.1f}k (${c_on:.2f}) • Mid: {mid_peak:.1f}k (${c_mid:.2f}) • Off: {off_peak:.1f}k (${c_off:.2f})"
        }

    adjusted_kwh = total_kwh * params['line_loss_factor']
    fixed_delivery = params['monthly_fixed_delivery'] * (effective_days / 30.0)
    variable_delivery = adjusted_kwh * params['volumetric_delivery_kwh']
    total_delivery = fixed_delivery + variable_delivery
    regulatory = total_kwh * params['regulatory_kwh']
    total_electricity_charges = actual_commodity_cost + total_delivery + regulatory
    hst_amount = total_electricity_charges * (params['hst_percent'] / 100.0) if params['apply_hst'] else 0.0
    oer_rebate = total_electricity_charges * (params['oer_percent'] / 100.0) if params['apply_oer'] else 0.0
    total_amount_due = total_electricity_charges + hst_amount - oer_rebate

    return {
        "active_rate_plan": active_rate_plan,
        "commodity_cost": round(actual_commodity_cost, 2),
        "commodity_split": commodity_split,
        "total_kwh": round(total_kwh, 4),
        "adjusted_kwh": round(adjusted_kwh, 4),
        "fixed_delivery_cost": round(fixed_delivery, 2),
        "variable_delivery_cost": round(variable_delivery, 2),
        "total_delivery_cost": round(total_delivery, 2),
        "regulatory_cost": round(regulatory, 2),
        "total_electricity_charges": round(total_electricity_charges, 2),
        "hst_amount": round(hst_amount, 2),
        "oer_rebate_amount": round(oer_rebate, 2),
        "total_amount_due": round(total_amount_due, 2),
        "days_count": round(effective_days, 1),
        "apply_hst": params['apply_hst'],
        "apply_oer": params['apply_oer'],
        "hst_percent": params['hst_percent'],
        "oer_percent": params['oer_percent'],
        "line_loss_factor": params['line_loss_factor'],
        "volumetric_delivery_kwh": params['volumetric_delivery_kwh'],
        "monthly_fixed_delivery": params['monthly_fixed_delivery'],
        "regulatory_kwh": params['regulatory_kwh']
    }

def calculate_plan_advisor(
    total_kwh: float,
    tou_summary: Dict[str, Any],
    ulo_summary: Dict[str, Any],
    days_count: float,
    rates: Dict[str, Any] = None,
    sample_ts: int = None,
    active_rate_plan: str = 'tou',
    billing_params: Dict[str, Any] = None
) -> Optional[Dict[str, Any]]:
    if total_kwh <= 0.0:
        return None
    if rates is None:
        rates = get_oeb_rates()
    if billing_params is None:
        billing_params = get_billing_parameters()

    effective_days = max(1.0, days_count if days_count > 0 else 30.0)

    # Determine Season from sample_ts or system clock
    if sample_ts:
        dt = datetime.fromtimestamp(sample_ts, tz=timezone.utc)
        month = dt.month
    else:
        month = datetime.now().month

    is_summer = 5 <= month <= 10
    season_name = "Summer" if is_summer else "Winter"
    monthly_slab = rates['summer_slab_kwh'] if is_summer else rates['winter_slab_kwh']
    effective_slab = max(1.0, (effective_days / 30.0) * monthly_slab)

    # 1. Standard TOU Commodity
    on_peak = tou_summary.get('on_peak_kwh', 0.0)
    mid_peak = tou_summary.get('mid_peak_kwh', 0.0)
    off_peak = tou_summary.get('off_peak_kwh', 0.0)
    ulo_base = tou_summary.get('ulo_kwh', 0.0)
    cost_tou = (on_peak * rates['tou_on_peak']) + (mid_peak * rates['tou_mid_peak']) + ((off_peak + ulo_base) * rates['tou_off_peak'])

    # 2. Ultra-Low Overnight (ULO) Commodity
    kwh_ulo_overnight = ulo_summary.get('ultra_low_overnight_kwh', 0.0)
    kwh_ulo_off_peak = ulo_summary.get('off_peak_kwh', 0.0)
    kwh_ulo_mid_peak = ulo_summary.get('mid_peak_kwh', 0.0)
    kwh_ulo_on_peak = ulo_summary.get('on_peak_kwh', 0.0)

    cost_ulo = (kwh_ulo_overnight * rates['ulo_ultra_low_overnight']) + \
               (kwh_ulo_off_peak * rates['ulo_off_peak']) + \
               (kwh_ulo_mid_peak * rates['ulo_mid_peak']) + \
               (kwh_ulo_on_peak * rates['ulo_on_peak'])

    # 3. Tiered Pricing Commodity
    t1 = min(total_kwh, effective_slab)
    t2 = max(0.0, total_kwh - effective_slab)
    cost_tiered = (t1 * rates['tiered_tier1']) + (t2 * rates['tiered_tier2'])

    # Full Bill Components (Delivery, Regulatory, Taxes, Rebate)
    adj_kwh = total_kwh * billing_params.get('line_loss_factor', 1.0341)
    fixed_delivery = billing_params.get('monthly_fixed_delivery', 30.80) * (effective_days / 30.0)
    variable_delivery = adj_kwh * billing_params.get('volumetric_delivery_kwh', 0.0252)
    total_delivery = fixed_delivery + variable_delivery
    regulatory = total_kwh * billing_params.get('regulatory_kwh', 0.005983)
    apply_hst = billing_params.get('apply_hst', True)
    hst_pct = (billing_params.get('hst_percent', 13.0) / 100.0) if apply_hst else 0.0
    apply_oer = billing_params.get('apply_oer', True)
    oer_pct = (billing_params.get('oer_percent', 23.5) / 100.0) if apply_oer else 0.0

    def calc_plan_full_bill(commodity_val: float) -> float:
        sub = commodity_val + total_delivery + regulatory
        tax = sub * hst_pct
        rebate = sub * oer_pct
        return sub + tax - rebate

    bill_tou = calc_plan_full_bill(cost_tou)
    bill_ulo = calc_plan_full_bill(cost_ulo)
    bill_tiered = calc_plan_full_bill(cost_tiered)

    plan_costs = [
        {
            "id": "tou",
            "name": "Standard TOU",
            "cost": round(bill_tou, 2),
            "commodity_cost": round(cost_tou, 2),
            "rate_desc": f"{rates['tou_on_peak']*100:.1f}¢ / {rates['tou_mid_peak']*100:.1f}¢ / {rates['tou_off_peak']*100:.1f}¢",
            "subtitle": f"Supply: ${cost_tou:.2f}"
        },
        {
            "id": "ulo",
            "name": "Ultra-Low Overnight (ULO)",
            "cost": round(bill_ulo, 2),
            "commodity_cost": round(cost_ulo, 2),
            "rate_desc": f"{rates['ulo_ultra_low_overnight']*100:.1f}¢ / {rates['ulo_off_peak']*100:.1f}¢ / {rates['ulo_mid_peak']*100:.1f}¢ / {rates['ulo_on_peak']*100:.1f}¢",
            "subtitle": f"Supply: ${cost_ulo:.2f}"
        },
        {
            "id": "tiered",
            "name": "Tiered Pricing",
            "cost": round(bill_tiered, 2),
            "commodity_cost": round(cost_tiered, 2),
            "rate_desc": f"{rates['tiered_tier1']*100:.1f}¢ (<={effective_slab:.0f} kWh) / {rates['tiered_tier2']*100:.1f}¢",
            "subtitle": f"Supply: ${cost_tiered:.2f}"
        }
    ]

    active_plan_obj = next((p for p in plan_costs if p["id"] == active_rate_plan), plan_costs[0])
    best_plan = min(plan_costs, key=lambda p: p["cost"])
    savings_vs_active = max(0.0, round(active_plan_obj["cost"] - best_plan["cost"], 2))
    is_active_best = (active_rate_plan == best_plan["id"])

    # Build context-aware advice comparing to active plan
    if is_active_best:
        if best_plan["id"] == "tiered":
            insight_text = f"You are currently on Tiered Pricing, which is already your most cost-effective option (${best_plan['cost']:.2f} total bill). With {effective_slab:.0f} kWh {season_name} slab for {effective_days:.0f} days, your habits maximize savings without peak penalties."
        elif best_plan["id"] == "ulo":
            overnight_pct = (kwh_ulo_overnight / total_kwh * 100.0) if total_kwh > 0 else 0.0
            insight_text = f"You are currently on Ultra-Low Overnight, which is already your most cost-effective option (${best_plan['cost']:.2f} total bill, {overnight_pct:.0f}% overnight consumption)."
        else:
            insight_text = f"You are currently on Standard Time-of-Use, which is your most optimal plan (${best_plan['cost']:.2f} total bill). Continue shifting heavy appliance loads away from On-Peak windows."
    else:
        insight_text = f"You are on {active_plan_obj['name']} (${active_plan_obj['cost']:.2f} total bill). Switching to {best_plan['name']} (${best_plan['cost']:.2f} total bill) would save approximately ${savings_vs_active:.2f} CAD on your final bill for this {effective_days:.0f}-day evaluated period."

    return {
        "active_rate_plan": active_rate_plan,
        "is_active_best": is_active_best,
        "recommended_plan": best_plan["name"],
        "recommended_id": best_plan["id"],
        "savings_vs_active": savings_vs_active,
        "season_name": season_name,
        "effective_slab_kwh": round(effective_slab, 0),
        "days_count": round(effective_days, 1),
        "plan_costs": plan_costs,
        "insight_text": insight_text,
        "ulo_breakdown": {
            "overnight_kwh": round(kwh_ulo_overnight, 4),
            "off_peak_kwh": round(kwh_ulo_off_peak, 4),
            "mid_peak_kwh": round(kwh_ulo_mid_peak, 4),
            "on_peak_kwh": round(kwh_ulo_on_peak, 4)
        }
    }

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
    finally:
        try:
            with get_db() as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass
        release_memory()

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
        release_memory()

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
    release_memory()

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

@app.post("/api/status/clear-error")
def clear_status_error():
    set_setting('last_scraper_error', '')
    set_setting('last_sync_error', '')
    set_setting('last_error', '')
    return {"status": "success", "message": "All error states cleared successfully"}

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

# Billing Parameters & OEB Rates Models and Endpoints
class BillingParametersModel(BaseModel):
    monthly_fixed_delivery: Optional[float] = None
    volumetric_delivery_kwh: Optional[float] = None
    line_loss_factor: Optional[float] = None
    regulatory_kwh: Optional[float] = None
    oer_percent: Optional[float] = None
    hst_percent: Optional[float] = None
    apply_hst: Optional[bool] = None
    apply_oer: Optional[bool] = None
    active_rate_plan: Optional[str] = None

class OebRatesModel(BaseModel):
    tou_on_peak: Optional[float] = None
    tou_mid_peak: Optional[float] = None
    tou_off_peak: Optional[float] = None
    ulo_ultra_low_overnight: Optional[float] = None
    ulo_off_peak: Optional[float] = None
    ulo_mid_peak: Optional[float] = None
    ulo_on_peak: Optional[float] = None
    tiered_tier1: Optional[float] = None
    tiered_tier2: Optional[float] = None
    summer_slab_kwh: Optional[float] = None
    winter_slab_kwh: Optional[float] = None

@app.get("/api/billing/parameters")
def api_get_billing_parameters():
    return get_billing_parameters()

@app.post("/api/billing/parameters")
def api_update_billing_parameters(params: BillingParametersModel):
    data = {k: v for k, v in params.model_dump().items() if v is not None}
    save_billing_parameters(data)
    return {"status": "success", "message": "Alectra billing parameters updated", "parameters": get_billing_parameters()}

@app.post("/api/billing/parameters/reset")
def api_reset_billing_parameters():
    defaults = reset_billing_parameters()
    return {"status": "success", "message": "Alectra billing parameters reset to defaults", "parameters": defaults}

@app.get("/api/billing/rates")
def api_get_billing_rates():
    return get_oeb_rates()

@app.post("/api/billing/rates")
def api_update_billing_rates(rates: OebRatesModel):
    data = {k: v for k, v in rates.model_dump().items() if v is not None}
    save_oeb_rates(data)
    return {"status": "success", "message": "OEB rate schedule updated", "rates": get_oeb_rates()}

@app.post("/api/billing/rates/reset")
def api_reset_billing_rates():
    defaults = reset_oeb_rates()
    return {"status": "success", "message": "OEB rate schedule reset to defaults", "rates": defaults}


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
        release_memory()

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
        
        # Resolve all preset date ranges anchored to the latest available data in DB
        # This ensures "Last 30 Days" = latest 30 days of data, not 30 days from today
        if date_range in ("latest_day", "last_7_days", "last_30_days", "month_to_date", "year_to_date", "all_time"):
            max_row = conn.execute("SELECT MAX(timestamp), MIN(timestamp) FROM readings").fetchone()
            if max_row and max_row[0]:
                max_ts = max_row[0]
                min_ts = max_row[1]
                dt_max = datetime.fromtimestamp(max_ts + drift_sec, tz=timezone.utc)

                if date_range == "latest_day":
                    day_start = int(datetime(dt_max.year, dt_max.month, dt_max.day, tzinfo=timezone.utc).timestamp())
                    start = day_start
                    end = day_start + 86399

                elif date_range == "last_7_days":
                    end = int(datetime(dt_max.year, dt_max.month, dt_max.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
                    start = end - (7 * 86400)

                elif date_range == "last_30_days":
                    end = int(datetime(dt_max.year, dt_max.month, dt_max.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
                    start = end - (30 * 86400)

                elif date_range == "month_to_date":
                    # Start of the month containing the latest data point
                    start = int(datetime(dt_max.year, dt_max.month, 1, tzinfo=timezone.utc).timestamp())
                    end = int(datetime(dt_max.year, dt_max.month, dt_max.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

                elif date_range == "year_to_date":
                    start = int(datetime(dt_max.year, 1, 1, tzinfo=timezone.utc).timestamp())
                    end = int(datetime(dt_max.year, dt_max.month, dt_max.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

                elif date_range == "all_time":
                    start = min_ts
                    end = max_ts

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

        # High-precision calculation of ULO 4-slot breakdown across all raw intervals
        ulo_query = f"""
            SELECT timestamp, value 
            FROM readings 
            {filter_str_consumption}
            ORDER BY timestamp ASC
        """
        try:
            ulo_rows = conn.execute(ulo_query, params).fetchall()
        except Exception as e:
            ulo_rows = []
            print(f"Error fetching ULO summary: {e}")

        ulo_overnight_kwh = 0.0
        ulo_off_peak_kwh = 0.0
        ulo_mid_peak_kwh = 0.0
        ulo_on_peak_kwh = 0.0
        sample_ts = None

        for ur in ulo_rows:
            ts_sec = ur['timestamp'] + drift_sec
            if sample_ts is None:
                sample_ts = ts_sec
            v = ur['value'] or 0.0
            dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
            slot = ontario_holidays.classify_ulo_slot(dt)
            if slot == 'overnight':
                ulo_overnight_kwh += v
            elif slot == 'off_peak':
                ulo_off_peak_kwh += v
            elif slot == 'on_peak':
                ulo_on_peak_kwh += v
            else:
                ulo_mid_peak_kwh += v

        ulo_summary = {
            "ultra_low_overnight_kwh": round(ulo_overnight_kwh, 4),
            "off_peak_kwh": round(ulo_off_peak_kwh, 4),
            "mid_peak_kwh": round(ulo_mid_peak_kwh, 4),
            "on_peak_kwh": round(ulo_on_peak_kwh, 4)
        }
            
        # Capture actual date range of the queried data for frontend display
        actual_range_row = conn.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM readings {filter_str}",
            params
        ).fetchone()
        date_from_ts = None
        date_to_ts = None
        if actual_range_row and actual_range_row[0]:
            date_from_ts = (actual_range_row[0] + drift_sec) * 1000  # ms for JS
            date_to_ts = (actual_range_row[1] + drift_sec) * 1000

        # Initialize structured result
        result = {
            "resolution": resolution,
            "date_from_ts": date_from_ts,
            "date_to_ts": date_to_ts,
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
            "tier_summary": tier_summary,
            "ulo_summary": ulo_summary,
            "bill_breakdown": {},
            "plan_advisor": None
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

        # Calculate days count for effective billing calculation
        total_import = sum(p[1] for p in result["consumption"])
        total_import_cost = sum(p[1] for p in result["consumption_cost"])

        days_count = 30.0
        if start is not None and end is not None and end > start:
            days_count = max(1.0, (end - start) / 86400.0)
        elif result["consumption"]:
            min_ts = result["consumption"][0][0] / 1000.0
            max_ts = result["consumption"][-1][0] / 1000.0
            if max_ts > min_ts:
                days_count = max(1.0, (max_ts - min_ts) / 86400.0)
            else:
                days_count = 1.0

        billing_params = get_billing_parameters()
        oeb_rates = get_oeb_rates()
        active_plan = billing_params.get('active_rate_plan', 'tou')
        result["bill_breakdown"] = calculate_bill_breakdown(
            total_import, total_import_cost, days_count, billing_params, active_plan, tou_summary, ulo_summary, oeb_rates, sample_ts
        )
        result["plan_advisor"] = calculate_plan_advisor(
            total_import, tou_summary, ulo_summary, days_count, oeb_rates, sample_ts, active_plan, billing_params
        )

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

