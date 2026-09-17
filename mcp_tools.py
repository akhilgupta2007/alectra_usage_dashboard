import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import TransportSecuritySettings

# Get paths dynamically from environment variables (Zero hardcoding)
DATABASE_PATH = os.environ.get("DATABASE_PATH", "green_button.db")
SCAN_DIR = os.environ.get("SCAN_FOLDER_PATH", "/app/data")

mcp = MCPServer(
    name="alectra-energy-dashboard",
    version="1.0.0",
    instructions="MCP Server for Alectra Green Button electricity usage, billing analysis, and plan comparisons."
)

def get_db_connection():
    db_path = os.environ.get("DATABASE_PATH", DATABASE_PATH)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def parse_date_range(start_date: Optional[str], end_date: Optional[str]):
    start_ts = None
    end_ts = None
    if start_date:
        dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ts = int(dt.timestamp())
    if end_date:
        dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        end_ts = int(dt.timestamp())
    return start_ts, end_ts

@mcp.tool()
def get_system_status() -> Dict[str, Any]:
    """
    Returns database statistics, date ranges available, and system status.
    """
    conn = get_db_connection()
    try:
        total_rows = conn.execute("SELECT COUNT(*) FROM readings WHERE category = 'consumption'").fetchone()[0]
        date_bounds = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM readings WHERE category = 'consumption'").fetchone()
        files_count = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
        
        earliest = datetime.fromtimestamp(date_bounds[0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if date_bounds[0] else "None"
        latest = datetime.fromtimestamp(date_bounds[1], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if date_bounds[1] else "None"
        
        last_sync = conn.execute("SELECT value FROM settings WHERE key = 'last_sync_time'").fetchone()
        last_sync_str = last_sync[0] if last_sync else "Never"
        
        return {
            "status": "online",
            "database_path": os.environ.get("DATABASE_PATH", DATABASE_PATH),
            "total_consumption_intervals": total_rows,
            "processed_files_count": files_count,
            "date_range": {
                "earliest_data": earliest,
                "latest_data": latest
            },
            "last_sync": last_sync_str
        }
    finally:
        conn.close()

@mcp.tool()
def get_energy_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns total electricity consumption (kWh), monetary cost ($), solar export, and Time-of-Use breakdown.
    Dates should be formatted as YYYY-MM-DD.
    """
    start_ts, end_ts = parse_date_range(start_date, end_date)
    conn = get_db_connection()
    try:
        filters = ["category = 'consumption'"]
        params = []
        if start_ts is not None:
            filters.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            filters.append("timestamp <= ?")
            params.append(end_ts)
            
        where_clause = " WHERE " + " AND ".join(filters)
        
        # Consumption totals
        tot_row = conn.execute(f"SELECT SUM(value) as total_kwh, SUM(cost) as total_cost FROM readings {where_clause}", params).fetchone()
        total_kwh = round(tot_row['total_kwh'] or 0.0, 4)
        total_cost = round(tot_row['total_cost'] or 0.0, 4)
        
        # Solar production totals
        prod_filters = [f.replace("category = 'consumption'", "category = 'production'") for f in filters]
        prod_row = conn.execute(f"SELECT SUM(value) as total_kwh, SUM(cost) as total_cost FROM readings WHERE {' AND '.join(prod_filters)}", params).fetchone()
        export_kwh = round(prod_row['total_kwh'] or 0.0, 4)
        export_credit = round(prod_row['total_cost'] or 0.0, 4)
        
        # TOU breakdown
        tou_rows = conn.execute(f"SELECT tou, SUM(value) as kwh, SUM(cost) as cost FROM readings {where_clause} GROUP BY tou", params).fetchall()
        tou_map = {1: "on_peak", 2: "mid_peak", 3: "off_peak", 4: "ultra_low_overnight", 0: "other"}
        tou_breakdown = {name: {"kwh": 0.0, "cost": 0.0} for name in tou_map.values()}
        
        for r in tou_rows:
            code = r['tou']
            name = tou_map.get(code, "other")
            tou_breakdown[name]["kwh"] = round(r['kwh'] or 0.0, 4)
            tou_breakdown[name]["cost"] = round(r['cost'] or 0.0, 4)
            
        # Peak demand (max 15m reading * 4 kW)
        peak_row = conn.execute(f"SELECT MAX(value) as max_15m FROM readings {where_clause}", params).fetchone()
        peak_demand_kw = round((peak_row['max_15m'] or 0.0) * 4.0, 3)
        
        return {
            "period": {
                "start": start_date or "All time",
                "end": end_date or "All time"
            },
            "total_consumption_kwh": total_kwh,
            "total_consumption_cost_dollars": total_cost,
            "total_export_kwh": export_kwh,
            "total_export_credit_dollars": export_credit,
            "net_kwh": round(total_kwh - export_kwh, 4),
            "peak_demand_kw": peak_demand_kw,
            "average_cost_per_kwh": round(total_cost / total_kwh, 4) if total_kwh > 0 else 0.0,
            "tou_breakdown": tou_breakdown
        }
    finally:
        conn.close()

@mcp.tool()
def get_rate_breakdown(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns the percentage distribution and effective cost per kWh for each Time-of-Use rate tier.
    """
    summary = get_energy_summary(start_date, end_date)
    total_kwh = summary["total_consumption_kwh"]
    tou = summary["tou_breakdown"]
    
    distribution = {}
    for tier, data in tou.items():
        kwh = data["kwh"]
        cost = data["cost"]
        pct = round((kwh / total_kwh * 100), 2) if total_kwh > 0 else 0.0
        eff_rate = round(cost / kwh, 4) if kwh > 0 else 0.0
        distribution[tier] = {
            "kwh": kwh,
            "cost_dollars": cost,
            "percentage_of_total_usage": f"{pct}%",
            "effective_rate_dollars_per_kwh": eff_rate
        }
        
    return {
        "period": summary["period"],
        "total_kwh": total_kwh,
        "total_cost": summary["total_consumption_cost_dollars"],
        "tier_distribution": distribution
    }

@mcp.tool()
def get_interval_readings(start_date: Optional[str] = None, end_date: Optional[str] = None, resolution: str = "1h", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Returns time-series intervals with timestamps, kWh consumed, dollar cost, and rate tier name.
    resolution can be '15min', '1h', or '1d'. limit controls maximum records returned (default 100).
    """
    start_ts, end_ts = parse_date_range(start_date, end_date)
    conn = get_db_connection()
    try:
        filters = ["category = 'consumption'"]
        params = []
        if start_ts is not None:
            filters.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            filters.append("timestamp <= ?")
            params.append(end_ts)
        where_clause = " WHERE " + " AND ".join(filters)
        
        tou_map = {1: "On-Peak", 2: "Mid-Peak", 3: "Off-Peak", 4: "Ultra-Low Overnight", 0: "Other"}
        results = []
        
        if resolution == "15min":
            query = f"SELECT timestamp, value, cost, tou FROM readings {where_clause} ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
                results.append({
                    "timestamp": dt.strftime("%Y-%m-%d %H:%M UTC"),
                    "kwh": round(r['value'], 4),
                    "cost": round(r['cost'], 4),
                    "tier": tou_map.get(r['tou'], "Other")
                })
        elif resolution == "1h":
            query = f"""
                SELECT ((timestamp / 3600) * 3600) as hr_ts, tou, SUM(value) as val, SUM(cost) as total_cost 
                FROM readings {where_clause} 
                GROUP BY hr_ts, tou 
                ORDER BY hr_ts ASC 
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r['hr_ts'], tz=timezone.utc)
                results.append({
                    "timestamp": dt.strftime("%Y-%m-%d %H:00 UTC"),
                    "kwh": round(r['val'], 4),
                    "cost": round(r['total_cost'], 4),
                    "tier": tou_map.get(r['tou'], "Other")
                })
        else: # 1d
            query = f"""
                SELECT timestamp, value, cost, tou FROM readings {where_clause} ORDER BY timestamp ASC
            """
            rows = conn.execute(query, params).fetchall()
            day_map = {}
            for r in rows:
                dt = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
                day_key = dt.strftime("%Y-%m-%d")
                if day_key not in day_map:
                    day_map[day_key] = {"kwh": 0.0, "cost": 0.0, "on_peak_kwh": 0.0, "off_peak_kwh": 0.0}
                day_map[day_key]["kwh"] += r['value']
                day_map[day_key]["cost"] += r['cost']
                if r['tou'] == 1:
                    day_map[day_key]["on_peak_kwh"] += r['value']
                elif r['tou'] == 3:
                    day_map[day_key]["off_peak_kwh"] += r['value']
            for day_key, d in list(day_map.items())[:limit]:
                results.append({
                    "date": day_key,
                    "total_kwh": round(d["kwh"], 4),
                    "total_cost": round(d["cost"], 4),
                    "on_peak_kwh": round(d["on_peak_kwh"], 4),
                    "off_peak_kwh": round(d["off_peak_kwh"], 4)
                })
                
        return results
    finally:
        conn.close()

@mcp.tool()
def compare_rate_plans(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Simulates electricity costs across all three Ontario Alectra rate plans:
    1. Standard Time-of-Use (TOU)
    2. Ultra-Low Overnight (ULO)
    3. Tiered Pricing
    Provides an analytical recommendation on which plan saves the most money based on actual usage.
    """
    summary = get_energy_summary(start_date, end_date)
    total_kwh = summary["total_consumption_kwh"]
    if total_kwh == 0:
        return {"error": "No consumption data available for the requested period."}
        
    tou = summary["tou_breakdown"]
    on_peak_kwh = tou["on_peak"]["kwh"]
    mid_peak_kwh = tou["mid_peak"]["kwh"]
    off_peak_kwh = tou["off_peak"]["kwh"]
    ulo_kwh = tou["ultra_low_overnight"]["kwh"]
    
    # 1. Standard TOU Calculation (OEB rates: On-Peak 18.2¢, Mid-Peak 12.2¢, Off-Peak 8.7¢)
    tou_cost = (on_peak_kwh * 0.182) + (mid_peak_kwh * 0.122) + ((off_peak_kwh + ulo_kwh) * 0.087)
    
    # 2. Ultra-Low Overnight (ULO) Calculation (ULO: 2.8¢, Weekend Off-Peak: 8.7¢, Mid-Peak: 12.2¢, On-Peak: 28.6¢)
    est_ulo_kwh = ulo_kwh if ulo_kwh > 0 else (off_peak_kwh * 0.40)
    est_other_off = (off_peak_kwh + ulo_kwh) - est_ulo_kwh
    ulo_cost = (est_ulo_kwh * 0.028) + (est_other_off * 0.087) + (mid_peak_kwh * 0.122) + (on_peak_kwh * 0.286)
    
    # 3. Tiered Pricing Calculation (Tier 1 <= 600 kWh @ 10.3¢, Tier 2 > 600 kWh @ 12.5¢)
    t1_limit = 600.0
    t1_kwh = min(total_kwh, t1_limit)
    t2_kwh = max(0.0, total_kwh - t1_limit)
    tiered_cost = (t1_kwh * 0.103) + (t2_kwh * 0.125)
    
    costs = {
        "Standard Time-of-Use (TOU)": round(tou_cost, 2),
        "Ultra-Low Overnight (ULO)": round(ulo_cost, 2),
        "Tiered Pricing": round(tiered_cost, 2)
    }
    
    cheapest_plan = min(costs, key=costs.get)
    savings_vs_tou = round(tou_cost - costs[cheapest_plan], 2)
    
    return {
        "total_kwh_evaluated": total_kwh,
        "actual_billed_cost": summary["total_consumption_cost_dollars"],
        "plan_cost_estimates": costs,
        "recommended_plan": cheapest_plan,
        "estimated_savings_vs_standard_tou": f"${savings_vs_tou}",
        "insights": (
            f"Your usage is best suited for {cheapest_plan}. "
            f"Overnight proportion: {round((est_ulo_kwh / total_kwh)*100, 1)}%, "
            f"On-peak proportion: {round((on_peak_kwh / total_kwh)*100, 1)}%."
        )
    }

@mcp.tool()
def trigger_folder_sync() -> Dict[str, Any]:
    """
    Triggers an immediate scan and ingestion of any new Green Button XML files from the shared folder.
    """
    try:
        import main
        main.scan_and_import_directory()
        return {"status": "success", "message": "Folder scan and import completed successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_sse_starlette_app():
    """Returns the Starlette ASGI app for mounting under FastAPI at /sse"""
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return mcp.sse_app(transport_security=security)

if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run_stdio_async())
