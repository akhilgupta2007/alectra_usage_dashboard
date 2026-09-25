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
    version="1.1.0",
    instructions="MCP Server for Alectra Green Button electricity usage, billing analysis, and plan comparisons across Standard TOU, Tiered, and Ultra-Low Overnight (ULO) plans."
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

def compute_ulo_interval_summary(conn, where_clause: str, params: list) -> Dict[str, Any]:
    """
    Classifies 15-minute interval readings into official Ontario ULO slots using exact timestamps
    and statutory holidays (11 PM - 7 AM overnight, 7 AM - 11 PM weekend off-peak, 4 PM - 9 PM weekday on-peak, rest mid-peak).
    """
    import ontario_holidays
    ulo_query = f"SELECT timestamp, value FROM readings {where_clause} ORDER BY timestamp ASC"
    rows = conn.execute(ulo_query, params).fetchall()

    kwh_overnight = 0.0
    kwh_off_peak = 0.0
    kwh_mid_peak = 0.0
    kwh_on_peak = 0.0
    sample_ts = None

    for r in rows:
        ts = r['timestamp']
        if sample_ts is None:
            sample_ts = ts
        v = r['value'] or 0.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        slot = ontario_holidays.classify_ulo_slot(dt)
        if slot == 'overnight':
            kwh_overnight += v
        elif slot == 'off_peak':
            kwh_off_peak += v
        elif slot == 'on_peak':
            kwh_on_peak += v
        else:
            kwh_mid_peak += v

    return {
        "ultra_low_overnight_kwh": round(kwh_overnight, 4),
        "off_peak_kwh": round(kwh_off_peak, 4),
        "mid_peak_kwh": round(kwh_mid_peak, 4),
        "on_peak_kwh": round(kwh_on_peak, 4),
        "sample_ts": sample_ts
    }

@mcp.tool()
def get_system_status() -> Dict[str, Any]:
    """
    Returns database statistics, available date ranges, active rate plan, and system status.
    """
    conn = get_db_connection()
    try:
        total_rows = conn.execute("SELECT COUNT(*) FROM readings WHERE category = 'consumption'").fetchone()[0]
        date_bounds = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM readings WHERE category = 'consumption'").fetchone()
        files_count = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
        
        earliest = datetime.fromtimestamp(date_bounds[0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if (date_bounds and date_bounds[0]) else "None"
        latest = datetime.fromtimestamp(date_bounds[1], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if (date_bounds and date_bounds[1]) else "None"
        
        last_sync = conn.execute("SELECT value FROM settings WHERE key = 'last_sync_time'").fetchone()
        last_sync_str = last_sync[0] if last_sync else "Never"
        
        active_plan_row = conn.execute("SELECT value FROM settings WHERE key = 'active_rate_plan'").fetchone()
        active_plan = active_plan_row[0] if active_plan_row else "tou"
        
        return {
            "status": "online",
            "database_path": os.environ.get("DATABASE_PATH", DATABASE_PATH),
            "active_rate_plan": active_plan,
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
def get_billing_parameters() -> Dict[str, Any]:
    """
    Returns active Alectra billing parameters including monthly fixed delivery, volumetric delivery rate,
    distribution line loss factor, regulatory charge, HST percentage, and Ontario Electricity Rebate (OER) percentage.
    """
    import main
    params = main.get_billing_parameters()
    rates = main.get_oeb_rates()
    return {
        "active_rate_plan": params.get("active_rate_plan", "tou"),
        "delivery": {
            "monthly_fixed_delivery_dollars": params.get("monthly_fixed_delivery", 30.80),
            "volumetric_delivery_rate_dollars_per_kwh": params.get("volumetric_delivery_kwh", 0.0252),
            "line_loss_factor": params.get("line_loss_factor", 1.0341)
        },
        "regulatory": {
            "regulatory_charge_dollars_per_kwh": params.get("regulatory_kwh", 0.005983)
        },
        "taxes_and_rebates": {
            "hst_percent": params.get("hst_percent", 13.0),
            "apply_hst": params.get("apply_hst", True),
            "oer_rebate_percent": params.get("oer_percent", 23.5),
            "apply_oer": params.get("apply_oer", True)
        },
        "current_oeb_commodity_rates": {
            "tou": {
                "on_peak": rates.get("tou_on_peak", 0.203),
                "mid_peak": rates.get("tou_mid_peak", 0.157),
                "off_peak": rates.get("tou_off_peak", 0.098)
            },
            "ulo": {
                "ultra_low_overnight": rates.get("ulo_ultra_low_overnight", 0.039),
                "weekend_off_peak": rates.get("ulo_off_peak", 0.098),
                "mid_peak": rates.get("ulo_mid_peak", 0.157),
                "on_peak": rates.get("ulo_on_peak", 0.391)
            },
            "tiered": {
                "tier1": rates.get("tiered_tier1", 0.120),
                "tier2": rates.get("tiered_tier2", 0.142),
                "summer_slab_kwh": rates.get("summer_slab_kwh", 600.0),
                "winter_slab_kwh": rates.get("winter_slab_kwh", 1000.0)
            }
        }
    }

@mcp.tool()
def get_energy_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns electricity consumption (kWh), monetary commodity cost ($), solar export, peak demand (kW),
    and comprehensive breakdowns for Standard TOU, Tiered Pricing, and Ultra-Low Overnight (ULO).
    Dates should be formatted as YYYY-MM-DD.
    """
    import main
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
        tot_row = conn.execute(f"SELECT SUM(value) as total_kwh, SUM(cost) as total_cost, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM readings {where_clause}", params).fetchone()
        total_kwh = round(tot_row['total_kwh'] or 0.0, 4)
        total_cost = round(tot_row['total_cost'] or 0.0, 4)
        min_ts = tot_row['min_ts']
        max_ts = tot_row['max_ts']
        
        # Days count
        days_count = 30.0
        if min_ts and max_ts and max_ts > min_ts:
            days_count = max(1.0, round((max_ts - min_ts) / 86400.0, 1))
        
        # Solar production totals
        prod_filters = [f.replace("category = 'consumption'", "category = 'production'") for f in filters]
        prod_row = conn.execute(f"SELECT SUM(value) as total_kwh, SUM(cost) as total_cost FROM readings WHERE {' AND '.join(prod_filters)}", params).fetchone()
        export_kwh = round(prod_row['total_kwh'] or 0.0, 4)
        export_credit = round(prod_row['total_cost'] or 0.0, 4)
        
        # Standard TOU breakdown
        tou_rows = conn.execute(f"SELECT tou, SUM(value) as kwh, SUM(cost) as cost FROM readings {where_clause} GROUP BY tou", params).fetchall()
        tou_map = {1: "on_peak", 2: "mid_peak", 3: "off_peak"}
        tou_breakdown = {"on_peak": {"kwh": 0.0, "cost": 0.0}, "mid_peak": {"kwh": 0.0, "cost": 0.0}, "off_peak": {"kwh": 0.0, "cost": 0.0}}
        for r in tou_rows:
            code = r['tou']
            name = tou_map.get(code)
            if name:
                tou_breakdown[name]["kwh"] = round(r['kwh'] or 0.0, 4)
                tou_breakdown[name]["cost"] = round(r['cost'] or 0.0, 4)

        # High-precision ULO breakdown from actual 15-minute interval timestamps
        ulo_summary = compute_ulo_interval_summary(conn, where_clause, params)
        rates = main.get_oeb_rates()
        billing_params = main.get_billing_parameters()
        active_plan = billing_params.get('active_rate_plan', 'tou')

        c_ovn = ulo_summary["ultra_low_overnight_kwh"] * rates['ulo_ultra_low_overnight']
        c_off = ulo_summary["off_peak_kwh"] * rates['ulo_off_peak']
        c_mid = ulo_summary["mid_peak_kwh"] * rates['ulo_mid_peak']
        c_on = ulo_summary["on_peak_kwh"] * rates['ulo_on_peak']
        ulo_breakdown = {
            "ultra_low_overnight": {"kwh": ulo_summary["ultra_low_overnight_kwh"], "cost": round(c_ovn, 2), "rate": f"{rates['ulo_ultra_low_overnight']*100:.1f}¢"},
            "weekend_off_peak": {"kwh": ulo_summary["off_peak_kwh"], "cost": round(c_off, 2), "rate": f"{rates['ulo_off_peak']*100:.1f}¢"},
            "mid_peak": {"kwh": ulo_summary["mid_peak_kwh"], "cost": round(c_mid, 2), "rate": f"{rates['ulo_mid_peak']*100:.1f}¢"},
            "on_peak": {"kwh": ulo_summary["on_peak_kwh"], "cost": round(c_on, 2), "rate": f"{rates['ulo_on_peak']*100:.1f}¢"}
        }

        # Season-aware & prorated Tiered breakdown
        sample_ts = ulo_summary.get("sample_ts") or min_ts
        month = datetime.fromtimestamp(sample_ts, tz=timezone.utc).month if sample_ts else datetime.now().month
        is_summer = 5 <= month <= 10
        season_name = "Summer" if is_summer else "Winter"
        monthly_slab = rates['summer_slab_kwh'] if is_summer else rates['winter_slab_kwh']
        effective_slab = max(1.0, round((days_count / 30.0) * monthly_slab, 1))

        t1_kwh = min(total_kwh, effective_slab)
        t2_kwh = max(0.0, total_kwh - effective_slab)
        t1_cost = t1_kwh * rates['tiered_tier1']
        t2_cost = t2_kwh * rates['tiered_tier2']
        tiered_breakdown = {
            "season": season_name,
            "effective_threshold_kwh": effective_slab,
            "tier1": {"kwh": round(t1_kwh, 4), "cost": round(t1_cost, 2), "rate": f"{rates['tiered_tier1']*100:.1f}¢"},
            "tier2": {"kwh": round(t2_kwh, 4), "cost": round(t2_cost, 2), "rate": f"{rates['tiered_tier2']*100:.1f}¢"}
        }

        # Peak demand (max 15m reading * 4 kW)
        peak_row = conn.execute(f"SELECT MAX(value) as max_15m FROM readings {where_clause}", params).fetchone()
        peak_demand_kw = round((peak_row['max_15m'] or 0.0) * 4.0, 3)
        
        return {
            "period": {
                "start": start_date or (datetime.fromtimestamp(min_ts, tz=timezone.utc).strftime("%Y-%m-%d") if min_ts else "All time"),
                "end": end_date or (datetime.fromtimestamp(max_ts, tz=timezone.utc).strftime("%Y-%m-%d") if max_ts else "All time"),
                "evaluated_days": days_count
            },
            "active_rate_plan": active_plan,
            "total_consumption_kwh": total_kwh,
            "total_consumption_cost_dollars": total_cost,
            "total_export_kwh": export_kwh,
            "total_export_credit_dollars": export_credit,
            "net_kwh": round(total_kwh - export_kwh, 4),
            "peak_demand_kw": peak_demand_kw,
            "average_cost_per_kwh": round(total_cost / total_kwh, 4) if total_kwh > 0 else 0.0,
            "tou_breakdown": tou_breakdown,
            "ulo_breakdown": ulo_breakdown,
            "tiered_breakdown": tiered_breakdown
        }
    finally:
        conn.close()

@mcp.tool()
def get_rate_breakdown(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns the percentage distribution and effective cost per kWh for each rate tier
    across Time-of-Use (TOU), Ultra-Low Overnight (ULO), and Tiered Pricing.
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
        "active_rate_plan": summary["active_rate_plan"],
        "total_kwh": total_kwh,
        "total_cost": summary["total_consumption_cost_dollars"],
        "tou_distribution": distribution,
        "ulo_distribution": {
            slot: {
                "kwh": data["kwh"],
                "cost_dollars": data["cost"],
                "percentage_of_total_usage": f"{round((data['kwh'] / total_kwh * 100), 2) if total_kwh > 0 else 0.0}%",
                "rate": data["rate"]
            } for slot, data in summary["ulo_breakdown"].items()
        },
        "tiered_distribution": {
            "season": summary["tiered_breakdown"]["season"],
            "effective_threshold_kwh": summary["tiered_breakdown"]["effective_threshold_kwh"],
            "tier1": {
                "kwh": summary["tiered_breakdown"]["tier1"]["kwh"],
                "cost_dollars": summary["tiered_breakdown"]["tier1"]["cost"],
                "percentage_of_total_usage": f"{round((summary['tiered_breakdown']['tier1']['kwh'] / total_kwh * 100), 2) if total_kwh > 0 else 0.0}%"
            },
            "tier2": {
                "kwh": summary["tiered_breakdown"]["tier2"]["kwh"],
                "cost_dollars": summary["tiered_breakdown"]["tier2"]["cost"],
                "percentage_of_total_usage": f"{round((summary['tiered_breakdown']['tier2']['kwh'] / total_kwh * 100), 2) if total_kwh > 0 else 0.0}%"
            }
        }
    }

@mcp.tool()
def get_interval_readings(start_date: Optional[str] = None, end_date: Optional[str] = None, resolution: str = "1h", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Returns time-series intervals with timestamps, kWh consumed, dollar cost, and complete rate tier details.
    resolution can be '15min', '1h', or '1d'. limit controls maximum records returned (default 100).
    For '1d', returns complete on_peak, mid_peak, and off_peak kWh so all daily usage is 100% accounted for.
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
                    "timestamp": dt.strftime("%Y-%m-%d %H:%M"),
                    "kwh": round(r['value'], 4),
                    "cost": round(r['cost'], 4),
                    "tier": tou_map.get(r['tou'], "Other")
                })
        elif resolution == "1h":
            query = f"""
                SELECT ((timestamp / 3600) * 3600) as hr_ts, SUM(value) as val, SUM(cost) as total_cost 
                FROM readings {where_clause} 
                GROUP BY hr_ts 
                ORDER BY hr_ts ASC 
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r['hr_ts'], tz=timezone.utc)
                results.append({
                    "timestamp": dt.strftime("%Y-%m-%d %H:00"),
                    "kwh": round(r['val'], 4),
                    "cost": round(r['total_cost'], 4)
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
                    day_map[day_key] = {"kwh": 0.0, "cost": 0.0, "on_peak_kwh": 0.0, "mid_peak_kwh": 0.0, "off_peak_kwh": 0.0}
                val = r['value'] or 0.0
                day_map[day_key]["kwh"] += val
                day_map[day_key]["cost"] += (r['cost'] or 0.0)
                if r['tou'] == 1:
                    day_map[day_key]["on_peak_kwh"] += val
                elif r['tou'] == 2:
                    day_map[day_key]["mid_peak_kwh"] += val
                elif r['tou'] == 3:
                    day_map[day_key]["off_peak_kwh"] += val

            for day_key, d in list(day_map.items())[:limit]:
                results.append({
                    "date": day_key,
                    "total_kwh": round(d["kwh"], 4),
                    "total_cost": round(d["cost"], 4),
                    "breakdown": {
                        "on_peak_kwh": round(d["on_peak_kwh"], 4),
                        "mid_peak_kwh": round(d["mid_peak_kwh"], 4),
                        "off_peak_kwh": round(d["off_peak_kwh"], 4)
                    }
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
    Calculates the true all-inclusive out-of-pocket final bill (Commodity + Delivery + Line Loss + Regulatory + HST - OER Rebate).
    Provides an analytical recommendation and true net savings based on actual Green Button interval usage.
    """
    import main
    summary = get_energy_summary(start_date, end_date)
    total_kwh = summary["total_consumption_kwh"]
    if total_kwh == 0:
        return {"error": "No consumption data available for the requested period."}

    days_count = summary["period"]["evaluated_days"]
    rates = main.get_oeb_rates()
    billing_params = main.get_billing_parameters()
    active_rate_plan = billing_params.get("active_rate_plan", "tou")

    tou_summary = {
        "on_peak_kwh": summary["tou_breakdown"]["on_peak"]["kwh"],
        "mid_peak_kwh": summary["tou_breakdown"]["mid_peak"]["kwh"],
        "off_peak_kwh": summary["tou_breakdown"]["off_peak"]["kwh"],
        "ulo_kwh": 0.0
    }

    ulo_summary = {
        "ultra_low_overnight_kwh": summary["ulo_breakdown"]["ultra_low_overnight"]["kwh"],
        "off_peak_kwh": summary["ulo_breakdown"]["weekend_off_peak"]["kwh"],
        "mid_peak_kwh": summary["ulo_breakdown"]["mid_peak"]["kwh"],
        "on_peak_kwh": summary["ulo_breakdown"]["on_peak"]["kwh"]
    }

    advisor_result = main.calculate_plan_advisor(
        total_kwh=total_kwh,
        tou_summary=tou_summary,
        ulo_summary=ulo_summary,
        days_count=days_count,
        rates=rates,
        active_rate_plan=active_rate_plan,
        billing_params=billing_params
    )

    if not advisor_result:
        return {"error": "Could not calculate rate advisor for this period."}

    plans_formatted = {}
    for p in advisor_result["plan_costs"]:
        plans_formatted[p["name"]] = {
            "total_bill_dollars": p["cost"],
            "commodity_supply_dollars": p["commodity_cost"],
            "rate_schedule": p["rate_desc"],
            "subtitle": p["subtitle"]
        }

    return {
        "evaluated_period": summary["period"],
        "total_kwh": total_kwh,
        "active_rate_plan": advisor_result["active_rate_plan"],
        "is_active_plan_best": advisor_result["is_active_best"],
        "recommended_plan": advisor_result["recommended_plan"],
        "estimated_savings_vs_active_plan": f"${advisor_result['savings_vs_active']:.2f} CAD",
        "plan_comparisons": plans_formatted,
        "insights": advisor_result["insight_text"],
        "ulo_exact_consumption": advisor_result.get("ulo_breakdown")
    }

@mcp.tool()
def get_bill_estimate(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculates the complete itemized Alectra electricity bill for the period matching the official billing statement:
    Customer/Commodity Supply, Fixed & Volumetric Delivery (with line losses), Wholesale Regulatory Charges, HST, and Ontario Electricity Rebate (OER).
    """
    import main
    summary = get_energy_summary(start_date, end_date)
    total_kwh = summary["total_consumption_kwh"]
    commodity_cost = summary["total_consumption_cost_dollars"]
    days_count = summary["period"]["evaluated_days"]

    billing_params = main.get_billing_parameters()
    rates = main.get_oeb_rates()
    active_plan = billing_params.get("active_rate_plan", "tou")

    tou_summary = {
        "on_peak_kwh": summary["tou_breakdown"]["on_peak"]["kwh"],
        "mid_peak_kwh": summary["tou_breakdown"]["mid_peak"]["kwh"],
        "off_peak_kwh": summary["tou_breakdown"]["off_peak"]["kwh"],
        "ulo_kwh": 0.0
    }
    ulo_summary = {
        "ultra_low_overnight_kwh": summary["ulo_breakdown"]["ultra_low_overnight"]["kwh"],
        "off_peak_kwh": summary["ulo_breakdown"]["weekend_off_peak"]["kwh"],
        "mid_peak_kwh": summary["ulo_breakdown"]["mid_peak"]["kwh"],
        "on_peak_kwh": summary["ulo_breakdown"]["on_peak"]["kwh"]
    }

    itemized = main.calculate_bill_breakdown(
        total_kwh=total_kwh,
        commodity_cost=commodity_cost,
        days_count=days_count,
        params=billing_params,
        active_rate_plan=active_plan,
        tou_summary=tou_summary,
        ulo_summary=ulo_summary,
        rates=rates
    )

    return {
        "period": summary["period"],
        "total_kwh": total_kwh,
        "active_rate_plan": itemized.get("active_rate_plan", active_plan),
        "itemized_statement": itemized
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
