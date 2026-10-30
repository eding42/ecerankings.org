import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import harvest_ml, s2_discovery as s2


class MLS2IntegrationTests(unittest.TestCase):
    def test_ml_routes_s2_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            fetch = harvest_ml.Fetcher(Path(temporary))
            with patch.object(harvest_ml.s2_discovery.Client, 'request',
                              return_value=(200, {'data': []})) as request:
                self.assertEqual(fetch.get_json(s2.BASE + 'paper/search?query=test')[0], 200)
                self.assertEqual(request.call_args.args[:2], ('paper/search', {'query': 'test'}))
