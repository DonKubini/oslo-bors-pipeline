import unittest
from unittest.mock import patch
from matplotlib import dates
import pandas as pd
import numpy as np

# Import the modules you wrote
import transform
import extract

class TestOsloBorsPipeline(unittest.TestCase):

    def test_engineer_features_logic(self):
        """
        Tests if transform.py correctly calculates rolling features 
        and cross-sectional Z-scores using a mock DataFrame.
        """
        # 1. Create a Mock DataFrame simulating 15 months of raw Azure data
        dates = pd.date_range(start="2025-01-31", periods=15, freq="ME")
        tickers = ["AAA", "BBB", "CCC"]

        rows = []

        np.random.seed(42)

        for ticker in tickers:
            price = 100 + np.random.uniform(-5, 5)

            for date in dates:
                ret = np.random.normal(0.01, 0.03)
                price *= (1 + ret)

                rows.append({
                    "TradeDate": date,
                    "Ticker": ticker,
                    "Generic": price,
                    "Volume": np.random.randint(900, 1200),
                    "ReturnGeneric": ret,
                    "ReturnAdjGeneric": ret,
                })

        mock_df = pd.DataFrame(rows)

        # 2. Run your actual transformation logic on the fake data
        result_df = transform.engineer_features(mock_df)

        # 3. Assertions (The Test Conditions)
        # Because we need 12 months for momentum, the first 11 months should be dropped
        # 15 total months - 11 dropped = 4 remaining valid rows
        self.assertFalse(result_df.empty, "The resulting DataFrame should not be empty.")
        self.assertTrue(len(result_df) > 0, "Rolling windows should leave valid data.")
        
        # Check if the Z-score columns were actually created
        expected_columns = ['log_size_z', 'mom_12m_z', 'Target_z']
        for col in expected_columns:
            self.assertIn(col, result_df.columns, f"Missing engineered column: {col}")

    @patch('extract.os.getenv')
    def test_database_connection_string(self, mock_getenv):
        """
        Tests if extract.py formats the SQLAlchemy connection string properly
        without actually connecting to Azure.
        """
        # Provide fake environment variables
        mock_getenv.side_effect = lambda key: {
            'AZURE_SQL_SERVER': 'fake-server',
            'AZURE_SQL_DATABASE': 'fake-db',
            'AZURE_SQL_USER': 'fake-user',
            'AZURE_SQL_PASSWORD': 'fake-password'
        }.get(key)

        # Call the connection function (it will throw an error if the string is malformed)
        try:
            engine = extract.get_db_connection()
            # Verify the connection string was formatted with the fake credentials
            self.assertIn("fake-server", str(engine.url))
            self.assertIn("fake-user", str(engine.url))
        except Exception as e:
            self.fail(f"get_db_connection() raised an exception: {e}")

if __name__ == '__main__':
    unittest.main()