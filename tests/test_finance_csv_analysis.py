import unittest

from modules import finance_analysis


class FinanceCsvAnalysisTests(unittest.TestCase):
    def test_finance_summary_is_owned_by_finance_module(self):
        self.assertTrue(callable(finance_analysis.csv_summary))


if __name__ == '__main__':
    unittest.main()
