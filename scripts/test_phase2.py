import unittest
from config.loader import load_config
from core.logic_engine import (
    calculate_ema,
    calculate_tema,
    calculate_linreg_slope,
    scan_universe,
    calculate_composite_score,
    calculate_p_win,
    evaluate_expectancy,
    calculate_kelly_size
)

class TestPhase2Logic(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_ema_calculation(self):
        """Test standard EMA computation."""
        data = [10.0] * 10
        ema = calculate_ema(data, 5)
        self.assertEqual(len(ema), 10)
        self.assertEqual(ema[-1], 10.0)

    def test_tema_calculation(self):
        """Test TEMA calculation and padding limits."""
        # Minimum period for TEMA = 3 * period - 2
        period = 3
        min_len = period * 3 - 2 # 7 elements
        
        # Test insufficient length
        self.assertIsNone(calculate_tema([10.0] * (min_len - 1), period))
        
        # Test sufficient length
        data = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        tema = calculate_tema(data, period)
        self.assertIsNotNone(tema)
        self.assertTrue(isinstance(tema, float))

    def test_linreg_slope(self):
        """Test least-squares regression slope calculation."""
        # Linear uptrend
        uptrend = [1.0, 2.0, 3.0, 4.0, 5.0]
        slope = calculate_linreg_slope(uptrend, 5)
        self.assertAlmostEqual(slope, 1.0)
        
        # Linear downtrend
        downtrend = [10.0, 8.0, 6.0, 4.0, 2.0]
        slope = calculate_linreg_slope(downtrend, 5)
        self.assertAlmostEqual(slope, -2.0)

    def test_scan_universe(self):
        """Test universe scanner filters."""
        # Pass scenario
        passed = scan_universe(
            price=100.0, bid=99.99, ask=100.01,
            volume=2000.0, avg_volume=1000.0, atr=1.0,
            config=self.config
        )
        self.assertTrue(passed)

        # Fail spread check
        fail_spread = scan_universe(
            price=100.0, bid=99.0, ask=101.0, # 2% spread
            volume=2000.0, avg_volume=1000.0, atr=1.0,
            config=self.config
        )
        self.assertFalse(fail_spread)

        # Fail RVOL check
        fail_rvol = scan_universe(
            price=100.0, bid=99.99, ask=100.01,
            volume=500.0, avg_volume=1000.0, atr=1.0,
            config=self.config
        )
        self.assertFalse(fail_rvol)

        # Fail ATR check
        fail_atr = scan_universe(
            price=100.0, bid=99.99, ask=100.01,
            volume=2000.0, avg_volume=1000.0, atr=0.1, # 0.1% ATR (limit is 0.5%)
            config=self.config
        )
        self.assertFalse(fail_atr)

    def test_composite_score(self):
        """Test composite score normalization and clamping."""
        score = calculate_composite_score(
            tema_val=100.0, price=100.5, # TEMA score = 1.0
            linreg_slope=0.05025, # LinReg score = 1.0 (relative to price 100.5)
            llm_bias=0.5, # LLM score = 0.5
            config=self.config
        )
        # Expected: 0.4 * 1.0 + 0.4 * 1.0 + 0.2 * 0.5 = 0.9
        self.assertAlmostEqual(score, 0.9)

    def test_p_win_platt_scaling(self):
        """Test that win probability (Platt scaling) output stays in range (0, 1)."""
        p_win = calculate_p_win(0.5, self.config)
        self.assertTrue(0.0 < p_win < 1.0)
        
        # Test extreme clamping bounds
        p_win_low = calculate_p_win(-20.0, self.config)
        p_win_high = calculate_p_win(20.0, self.config)
        self.assertTrue(0.0 < p_win_low < 1.0)
        self.assertTrue(0.0 < p_win_high < 1.0)

    def test_expectancy_gate(self):
        """Test expectancy calculations factoring cost parameters."""
        # 1. Profitable expectancy trade
        proceed, exp_return = evaluate_expectancy(
            p_win=0.7, entry_price=100.0, stop_loss=98.0, take_profit=105.0,
            is_long=True, config=self.config
        )
        self.assertTrue(proceed)
        self.assertTrue(exp_return > 0)

        # 2. Unprofitable trade (low win rate)
        proceed_low, exp_return_low = evaluate_expectancy(
            p_win=0.2, entry_price=100.0, stop_loss=98.0, take_profit=105.0,
            is_long=True, config=self.config
        )
        self.assertFalse(proceed_low)
        self.assertTrue(exp_return_low < 0)

    def test_kelly_position_sizing(self):
        """Test Kelly sizing output limits and caps."""
        # Win-loss ratio = 2.0 (Reward=10, Risk=5)
        # Kelly Fraction: P_win - (1 - P_win)/W = 0.7 - 0.3/2.0 = 0.55
        # Fractional Kelly = 0.55 * 0.5 = 0.275
        # Kelly Allocation: 10000 * 0.275 = 2750
        # Kelly Qty: 2750 / 5 = 550
        #
        # Cap 1: Max Risk per trade (1% of 10000 = 100). Max Risk Qty = 100 / 5 = 20
        # Cap 2: Max exposure (20% of 10000 = 2000). Max Exposure Qty = 2000 / 100 = 20
        # Final Qty should be capped at 20.
        qty = calculate_kelly_size(
            p_win=0.7, entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            equity=10000.0, config=self.config
        )
        self.assertEqual(qty, 20.0)

if __name__ == "__main__":
    unittest.main()
