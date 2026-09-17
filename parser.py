import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import os

namespaces = {
    'atom': 'http://www.w3.org/2005/Atom',
    'espi': 'http://naesb.org/espi'
}

def parse_green_button_xml(file_path, time_shift_hours=0):
    """
    Parses Green Button ESPI XML file and returns a list of dictionaries with keys:
    - timestamp: adjusted unix timestamp (seconds)
    - category: 'consumption', 'production', 'net'
    - value: kwh consumption/production
    - cost: estimated cost in local currency (CAD/USD)
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing XML file {file_path}: {e}")
        return []

    # Step 1: Parse ReadingTypes
    reading_types = {}
    for entry in root.findall('atom:entry', namespaces):
        rt_elem = entry.find('.//espi:ReadingType', namespaces)
        if rt_elem is not None:
            self_href = None
            for link in entry.findall('atom:link', namespaces):
                if link.get('rel') == 'self':
                    self_href = link.get('href')
                    break
            
            uom = rt_elem.find('espi:uom', namespaces)
            mult = rt_elem.find('espi:powerOfTenMultiplier', namespaces)
            flow = rt_elem.find('espi:flowDirection', namespaces)
            int_len = rt_elem.find('espi:intervalLength', namespaces)
            
            uom_val = int(uom.text) if uom is not None else 72
            mult_val = int(mult.text) if mult is not None else 0
            flow_val = int(flow.text) if flow is not None else 1
            int_len_val = int(int_len.text) if int_len is not None else 900
            
            # Filter: only parse interval data for energy (uom == 72, Wh).
            # Skip demand readings (uom == 38, kW) and daily/monthly summaries (> 3600s)
            # so they never overwrite energy consumption.
            if uom_val != 72 or int_len_val > 3600:
                continue
                
            if self_href:
                reading_types[self_href] = {
                    'uom': uom_val,
                    'multiplier': mult_val,
                    'flow_direction': flow_val,
                    'interval_length': int_len_val
                }

    # Step 2: Parse MeterReadings and link them to ReadingTypes
    meter_readings = {}
    for entry in root.findall('atom:entry', namespaces):
        mr_elem = entry.find('.//espi:MeterReading', namespaces)
        if mr_elem is not None:
            self_href = None
            rt_href = None
            for link in entry.findall('atom:link', namespaces):
                if link.get('rel') == 'self':
                    self_href = link.get('href')
                elif link.get('rel') == 'related' and 'ReadingType' in link.get('href', ''):
                    rt_href = link.get('href')
            
            if self_href and rt_href:
                matched_rt = None
                for key in reading_types.keys():
                    if key == rt_href or key.endswith(rt_href) or rt_href.endswith(key):
                        matched_rt = reading_types[key]
                        break
                
                if matched_rt:
                    meter_readings[self_href] = matched_rt

    # Step 3: Parse IntervalBlocks
    readings_by_key = {}
    
    from zoneinfo import ZoneInfo
    tz_name = 'America/Toronto'
    
    # Auto-detect timezone from LocalTimeParameters in XML
    ltp_elem = root.find('.//espi:LocalTimeParameters', namespaces)
    if ltp_elem is not None:
        tz_offset_elem = ltp_elem.find('espi:tzOffset', namespaces)
        if tz_offset_elem is not None:
            try:
                offset_val = int(tz_offset_elem.text)
                if offset_val == -18000:
                    tz_name = 'America/Toronto'
                elif offset_val == -21600:
                    tz_name = 'America/Chicago'
                elif offset_val == -25200:
                    tz_name = 'America/Denver'
                elif offset_val == -28800:
                    tz_name = 'America/Los_Angeles'
                elif offset_val == -14400:
                    tz_name = 'America/Halifax'
                elif offset_val == 0:
                    tz_name = 'UTC'
            except Exception as e:
                print(f"Error parsing tzOffset: {e}")
                
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Toronto")
        
    for entry in root.findall('atom:entry', namespaces):
        ib_elem = entry.find('.//espi:IntervalBlock', namespaces)
        if ib_elem is not None:
            self_href = None
            up_href = None
            related_href = None
            for link in entry.findall('atom:link', namespaces):
                if link.get('rel') == 'self':
                    self_href = link.get('href')
                elif link.get('rel') == 'up':
                    up_href = link.get('href')
                elif link.get('rel') == 'related':
                    related_href = link.get('href')

            matched_rt = None
            parent_link = up_href or related_href or self_href
            if parent_link:
                if '/IntervalBlock/' in parent_link:
                    parent_link = parent_link.split('/IntervalBlock/')[0]
                elif parent_link.endswith('/IntervalBlock'):
                    parent_link = parent_link[:-14]
                
                for key, rt_info in meter_readings.items():
                    if key == parent_link or key.endswith(parent_link) or parent_link.endswith(key):
                        matched_rt = rt_info
                        break
            
            if not matched_rt:
                continue

            uom_val = matched_rt['uom']
            mult_val = matched_rt['multiplier']
            flow_val = matched_rt['flow_direction']
            
            # Map ESPI FlowDirection:
            # 1: Forward (Delivered from grid to premises -> Consumption / Import)
            # 19: Reverse (Received by grid from premises -> Production / Solar Export)
            # 4: Net (Net Energy Delivered = Delivered minus Received)
            if flow_val == 1:
                category = 'consumption'
            elif flow_val == 19:
                category = 'production'
            elif flow_val == 4:
                category = 'net'
            else:
                continue
            
            for reading in ib_elem.findall('espi:IntervalReading', namespaces):
                start_elem = reading.find('espi:timePeriod/espi:start', namespaces)
                val_elem = reading.find('espi:value', namespaces)
                cost_elem = reading.find('espi:cost', namespaces)
                
                if start_elem is not None and val_elem is not None:
                    raw_start = int(start_elem.text)
                    raw_val = int(val_elem.text)
                    tou_elem = reading.find('espi:tou', namespaces)
                    tou_val = int(tou_elem.text) if tou_elem is not None else 0
                    tier_elem = reading.find('espi:consumptionTier', namespaces)
                    tier_val = int(tier_elem.text) if tier_elem is not None else 0
                    
                    # Convert UTC epoch to local clock face epoch
                    dt_utc = datetime.fromtimestamp(raw_start, tz=timezone.utc)
                    dt_local = dt_utc.astimezone(tz)
                    local_naive = dt_local.replace(tzinfo=None)
                    adjusted_ts = int(local_naive.replace(tzinfo=timezone.utc).timestamp())
                    
                    if time_shift_hours:
                        adjusted_ts += int(time_shift_hours * 3600)
                        
                    actual_val = raw_val * (10 ** mult_val)
                    
                    if uom_val == 72:
                        actual_val = actual_val / 1000.0
                        
                    # Calculate cost (Alectra / SavageData Green Button raw cost is in tenths of a cent; divide by 1000.0 for dollars)
                    actual_cost = 0.0
                    if cost_elem is not None and cost_elem.text is not None:
                        actual_cost = float(cost_elem.text) / 1000.0
                    
                    # DST Fall-Back handling: In November when clock rolls back (25-hour day),
                    # the 1:00 AM clock hour repeats (fold 0 then fold 1).
                    # Accumulate value and cost for identical (adjusted_ts, category) to prevent
                    # the repeated hour from overwriting and losing data in SQLite.
                    key = (adjusted_ts, category)
                    if key in readings_by_key:
                        prev = readings_by_key[key]
                        prev['value'] += actual_val
                        prev['cost'] += actual_cost
                        if tou_val > 0 and prev.get('tou', 0) == 0:
                            prev['tou'] = tou_val
                        if tier_val > 0 and prev.get('tier', 0) == 0:
                            prev['tier'] = tier_val
                    else:
                        readings_by_key[key] = {
                            'timestamp': adjusted_ts,
                            'value': actual_val,
                            'cost': actual_cost,
                            'category': category,
                            'tou': tou_val,
                            'tier': tier_val
                        }
                    
    result = list(readings_by_key.values())
    try:
        root.clear()
    except Exception:
        pass
    return result
