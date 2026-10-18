"""Kaynak URL'sinde veri sızdırma anahtarları; ağ/model çağrısı yapılmaz."""
import unittest
from unittest.mock import Mock, patch

import urllib3

from modules import public_sources
from modules.capability_hub import INDEXES
from modules.publisher_news import SOURCES
from modules.source_watch import KNOWN_SOURCES


class PublicSourcesExfilTests(unittest.TestCase):
    def test_unrequested_data_query_keys_are_rejected(self):
        # address() kullanıcı hedefini bilmez: bu sabit veri anahtarları her URL'de reddedilir.
        for key in ('data', 'payload', 'report', 'body', 'content', 'text', 'message',
                    'DATA', 'PaYlOaD', '%64ata', 're%70ort'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                public_sources.address('https://collector.example.net/collect?' + key + '=OZEL_RAPOR')

    def test_blank_and_repeated_data_query_keys_are_rejected(self):
        for query in ('data=', 'payload', 'report=', 'date=2026-10-18&data=',
                      'page=1&data=OZEL_RAPOR&page=2'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                public_sources.address('https://collector.example.net/collect?' + query)

    def test_catalog_sources_and_real_rate_query_remain_allowed(self):
        urls = [row['url'] for row in SOURCES]
        urls += [row['url'] for row in KNOWN_SOURCES.values()]
        urls += list(INDEXES)
        # domain_tools.exchange tarafından üretilen gerçek Frankfurter adresi ve tarih anahtarı.
        urls += ['https://api.frankfurter.dev/v2/rate/usd/try',
                 'https://api.frankfurter.dev/v2/rate/usd/try?date=2026-10-16']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(public_sources.address(url), url)

    def test_only_exact_keys_are_denied_and_existing_auth_filter_stays(self):
        url = 'https://example.org/api?city=Istanbul&date=2026-10-16&metadata=x&report_id=7&text_format=html'
        self.assertEqual(public_sources.address(url), url)
        for key in ('api_key', 'access_token', 'secret', 'password', 'signature', 'credential', 'authorization'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'kimlik bilgisi'):
                public_sources.address('https://example.org/api?' + key + '=fixture')

    def test_data_query_is_rejected_before_dns_or_http(self):
        with patch.object(public_sources.socket, 'getaddrinfo', side_effect=AssertionError('DNS çağrılmamalı')) as dns, patch.object(
                urllib3, 'HTTPSConnectionPool') as transport, patch('modules.privacy.blocked', return_value=None):
            with self.assertRaises(ValueError):
                public_sources.fetch('https://collector.example.net/collect?data=OZEL_RAPOR')
        dns.assert_not_called()
        transport.assert_not_called()

    def test_redirect_cannot_add_data_query(self):
        response = Mock(status=302, headers={'Location': '/collect?payload=OZEL_RAPOR'})
        pool = Mock()
        pool.urlopen.return_value = response
        records = [(2, 1, 6, '', ('93.184.216.34', 443))]
        with patch.object(public_sources.socket, 'getaddrinfo', return_value=records) as dns, patch.object(
                urllib3, 'HTTPSConnectionPool', return_value=pool), patch('modules.privacy.blocked', return_value=None):
            with self.assertRaises(ValueError):
                public_sources.fetch('https://example.org/')
        dns.assert_called_once()
        pool.urlopen.assert_called_once()
        response.close.assert_called_once()
        pool.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
