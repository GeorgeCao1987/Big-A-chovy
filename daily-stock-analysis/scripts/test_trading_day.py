import unittest
from datetime import datetime
from unittest.mock import patch

import realtime_dashboard as dash


def _reset_cache():
    dash._TRADING_DAY_CACHE.update(date=None, value=True)


class TradingDayTests(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        self.addCleanup(_reset_cache)

    @patch.object(dash, "_fetch_index_kline_dates", return_value=[])
    def test_weekend_is_never_trading_day(self, _mock):
        saturday = datetime(2026, 9, 26, 10, 0)
        self.assertFalse(dash.is_trading_day(saturday))

    @patch.object(dash, "_fetch_index_kline_dates")
    def test_today_kline_present_is_trading_day(self, mock_fetch):
        mock_fetch.return_value = ["2026-09-18", "2026-09-21", "2026-09-22"]
        _reset_cache()
        self.assertTrue(dash.is_trading_day(datetime(2026, 9, 22, 10, 0)))

    @patch.object(dash, "_fetch_index_kline_dates")
    def test_holiday_without_today_kline_after_open(self, mock_fetch):
        mock_fetch.return_value = ["2026-09-18", "2026-09-21"]
        _reset_cache()
        # Past 09:30 with no today kline means the exchange did not open.
        self.assertFalse(dash.is_trading_day(datetime(2026, 9, 22, 10, 0)))

    @patch.object(dash, "_fetch_index_kline_dates")
    def test_pre_open_is_conservatively_trading_day(self, mock_fetch):
        mock_fetch.return_value = ["2026-09-21"]
        _reset_cache()
        # Before 09:30 the today kline may not exist yet on a real trading day.
        self.assertTrue(dash.is_trading_day(datetime(2026, 9, 22, 9, 20)))

    @patch.object(dash, "_fetch_index_kline_dates", return_value=[])
    def test_fetch_failure_falls_back_to_weekday_rule(self, _mock):
        _reset_cache()
        # Conservative fallback: treat weekdays as trading days on API failure
        # so screening is never silently skipped.
        self.assertTrue(dash.is_trading_day(datetime(2026, 9, 22, 10, 0)))

    @patch.object(dash, "_fetch_index_kline_dates")
    def test_is_trading_hours_false_on_holiday(self, mock_fetch):
        mock_fetch.return_value = ["2026-09-21"]
        _reset_cache()
        # Pin datetime.now() to a holiday morning inside trading sessions.
        with patch("realtime_dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 22, 10, 0)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            self.assertFalse(dash.is_trading_hours())


if __name__ == "__main__":
    unittest.main()
