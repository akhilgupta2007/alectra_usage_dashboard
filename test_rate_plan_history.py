import os
import sys
import unittest
import sqlite3
import tempfile
from datetime import datetime, timezone

# Add parent directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_PATH"] = ":memory:"

import main

class TestRatePlanHistory(unittest.TestCase):
    def setUp(self):
        # Create temp sqlite db
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        main.DATABASE_PATH = self.tmp.name
        main.init_db()

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_default_baseline_seeded(self):
        history = main.get_rate_plan_history()
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]['plan'], 'tou')
        self.assertEqual(history[0]['effective_date'], '1970-01-01')

    def test_plan_resolution(self):
        # Add transition on 2026-10-21 -> tiered
        with main.get_db() as conn:
            conn.execute("INSERT INTO rate_plan_history (plan, effective_date) VALUES ('tiered', '2026-10-21')")
        
        history = main.get_rate_plan_history()
        self.assertEqual(len(history), 2)
        
        # Date before Oct 21 -> tou
        self.assertEqual(main.resolve_plan_for_date(history, '2026-10-15'), 'tou')
        self.assertEqual(main.resolve_plan_for_date(history, '2026-10-20'), 'tou')
        
        # Date on or after Oct 21 -> tiered
        self.assertEqual(main.resolve_plan_for_date(history, '2026-10-21'), 'tiered')
        self.assertEqual(main.resolve_plan_for_date(history, '2026-10-25'), 'tiered')
        self.assertEqual(main.resolve_plan_for_date(history, '2026-11-01'), 'tiered')

    def test_multi_window_bill_breakdown(self):
        # Test calculate_bill_breakdown with plan_windows
        plan_windows = [
            {
                'plan': 'tou',
                'start_date': '2026-10-01',
                'end_date': '2026-10-20',
                'days_count': 20,
                'total_kwh': 200.0,
                'commodity_cost': 25.50
            },
            {
                'plan': 'tiered',
                'start_date': '2026-10-21',
                'end_date': '2026-10-31',
                'days_count': 11,
                'total_kwh': 110.0,
                'commodity_cost': 13.20
            }
        ]
        breakdown = main.calculate_bill_breakdown(
            total_kwh=310.0,
            commodity_cost=0.0,
            days_count=31.0,
            plan_windows=plan_windows
        )
        self.assertTrue(breakdown['is_blended'])
        self.assertEqual(breakdown['commodity_cost'], 25.50 + 13.20)
        self.assertTrue('Blended' in breakdown['commodity_split']['plan_name'])
        self.assertGreater(breakdown['total_amount_due'], breakdown['commodity_cost'])

    def test_get_data_with_mixed_plans(self):
        # Insert transition on 2026-10-21 -> tiered
        with main.get_db() as conn:
            conn.execute("INSERT INTO rate_plan_history (plan, effective_date) VALUES ('tiered', '2026-10-21')")
            
            # Insert readings: 1 interval on Oct 15 (TOU), 1 interval on Oct 25 (Tiered)
            # Oct 15, 2026 12:00 UTC = 1792065600
            # Oct 25, 2026 12:00 UTC = 1792929600
            conn.execute("""
                INSERT INTO readings (timestamp, category, tou, tier, value, cost)
                VALUES (1792065600, 'consumption', 1, 0, 10.0, 2.03)
            """)
            conn.execute("""
                INSERT INTO readings (timestamp, category, tou, tier, value, cost)
                VALUES (1792929600, 'consumption', 0, 0, 15.0, 1.80)
            """)
            conn.commit()

        data = main.get_data(resolution="1d", start=1792000000, end=1793000000)
        
        # Verify tou_summary reflects Oct 15 (TOU) and tier_summary reflects Oct 25 (Tiered)
        self.assertGreater(data["tou_summary"]["on_peak_kwh"], 0.0)
        self.assertGreater(data["tier_summary"]["tier1_kwh"], 0.0)
        
        # Verify breakdowns contain non-zero points
        tou_points = [p[1] for p in data["tou_breakdown"]["on_peak"] if p[1] > 0]
        tier_points = [p[1] for p in data["tier_breakdown"]["tier1"] if p[1] > 0]
        self.assertEqual(len(tou_points), 1)
        self.assertEqual(len(tier_points), 1)
        self.assertEqual(tou_points[0], 10.0)
        self.assertEqual(tier_points[0], 15.0)

if __name__ == '__main__':
    unittest.main()

