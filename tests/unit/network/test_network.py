# SPDX-License-Identifier: AGPL-3.0-or-later

from mock import patch

import httpx

from searx.network.client import HTTPClient, HTTPMultiClientConf
from searx.network.network import Network, NETWORKS, initialize
from tests import SearxTestCase


class TestHTTPClient(SearxTestCase):
    def test_get_client(self):
        # FIXME : to rewrite
        httpclient = HTTPClient(verify=True)
        client1 = httpclient._get_client_and_update_kwargs()
        client2 = httpclient._get_client_and_update_kwargs(verify=True)
        client3 = httpclient._get_client_and_update_kwargs(max_redirects=10)
        client4 = httpclient._get_client_and_update_kwargs(verify=True)
        client5 = httpclient._get_client_and_update_kwargs(verify=False)
        client6 = httpclient._get_client_and_update_kwargs(max_redirects=10)

        self.assertEqual(client1, client2)
        self.assertEqual(client1, client4)
        self.assertNotEqual(client1, client3)
        self.assertNotEqual(client1, client5)
        self.assertEqual(client3, client6)

        httpclient.close()


class TestNetwork(SearxTestCase):
    def setUp(self):
        initialize()

    def test_simple(self):
        network = Network()

        self.assertEqual(next(network._local_addresses_cycle), None)
        self.assertEqual(next(network._proxies_cycle), ())

    def test_ipaddress_cycle(self):
        network = NETWORKS['ipv6']
        self.assertEqual(next(network._local_addresses_cycle), '::')
        self.assertEqual(next(network._local_addresses_cycle), '::')

        network = NETWORKS['ipv4']
        self.assertEqual(next(network._local_addresses_cycle), '0.0.0.0')
        self.assertEqual(next(network._local_addresses_cycle), '0.0.0.0')

        network = Network(local_addresses=['192.168.0.1', '192.168.0.2'])
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.1')
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.2')
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.1')

        network = Network(local_addresses=['192.168.0.0/30'])
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.1')
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.2')
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.1')
        self.assertEqual(next(network._local_addresses_cycle), '192.168.0.2')

        network = Network(local_addresses=['fe80::/10'])
        self.assertEqual(next(network._local_addresses_cycle), 'fe80::1')
        self.assertEqual(next(network._local_addresses_cycle), 'fe80::2')
        self.assertEqual(next(network._local_addresses_cycle), 'fe80::3')

        with self.assertRaises(ValueError):
            Network(local_addresses=['not_an_ip_address'])

    def test_proxy_cycles(self):
        network = Network(proxies='http://localhost:1337')
        self.assertEqual(next(network._proxies_cycle), (('all://', 'http://localhost:1337'),))

        network = Network(proxies={'https': 'http://localhost:1337', 'http': 'http://localhost:1338'})
        self.assertEqual(
            next(network._proxies_cycle), (('https://', 'http://localhost:1337'), ('http://', 'http://localhost:1338'))
        )
        self.assertEqual(
            next(network._proxies_cycle), (('https://', 'http://localhost:1337'), ('http://', 'http://localhost:1338'))
        )

        network = Network(
            proxies={'https': ['http://localhost:1337', 'http://localhost:1339'], 'http': 'http://localhost:1338'}
        )
        self.assertEqual(
            next(network._proxies_cycle), (('https://', 'http://localhost:1337'), ('http://', 'http://localhost:1338'))
        )
        self.assertEqual(
            next(network._proxies_cycle), (('https://', 'http://localhost:1339'), ('http://', 'http://localhost:1338'))
        )

        with self.assertRaises(ValueError):
            Network(proxies=1)

    def test_get_kwargs_clients(self):
        kwargs = {
            'verify': True,
            'max_redirects': 5,
            'timeout': 2,
            'allow_redirects': True,
        }
        kwargs_client = HTTPClient._extract_kwargs_clients(kwargs)

        self.assertIsInstance(kwargs_client, HTTPMultiClientConf)
        self.assertEqual(len(kwargs), 2)

        self.assertEqual(kwargs['timeout'], 2)
        self.assertEqual(kwargs['follow_redirects'], True)

        self.assertTrue(kwargs_client.verify)
        self.assertEqual(kwargs_client.max_redirects, 5)

    def test_close(self):
        network = Network(verify=True)
        network.get_http_client()
        network.close()

    def test_request(self):
        a_text = 'Lorem Ipsum'
        response = httpx.Response(status_code=200, text=a_text)
        with patch.object(httpx.AsyncClient, 'request', return_value=response):
            network = Network(enable_http=True)
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/')
            self.assertEqual(response.text, a_text)
            network.close()


class TestNetworkRequestRetries(SearxTestCase):

    TEXT = 'Lorem Ipsum'

    @classmethod
    def get_response_404_then_200(cls):
        first = True

        async def get_response(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                return httpx.Response(status_code=403, text=TestNetworkRequestRetries.TEXT)
            return httpx.Response(status_code=200, text=TestNetworkRequestRetries.TEXT)

        return get_response

    def test_retries_ok(self):
        with patch.object(httpx.AsyncClient, 'request', new=TestNetworkRequestRetries.get_response_404_then_200()):
            network = Network(enable_http=True, retries=1, retry_on_http_error=403)
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.text, TestNetworkRequestRetries.TEXT)
            network.close()

    def test_retries_fail_int(self):
        with patch.object(httpx.AsyncClient, 'request', new=TestNetworkRequestRetries.get_response_404_then_200()):
            network = Network(enable_http=True, retries=0, retry_on_http_error=403)
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.status_code, 403)
            network.close()

    def test_retries_fail_list(self):
        with patch.object(httpx.AsyncClient, 'request', new=TestNetworkRequestRetries.get_response_404_then_200()):
            network = Network(enable_http=True, retries=0, retry_on_http_error=[403, 429])
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.status_code, 403)
            network.close()

    def test_retries_fail_bool(self):
        with patch.object(httpx.AsyncClient, 'request', new=TestNetworkRequestRetries.get_response_404_then_200()):
            network = Network(enable_http=True, retries=0, retry_on_http_error=True)
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.status_code, 403)
            network.close()

    def test_retries_exception_then_200(self):
        request_count = 0

        async def get_response(*args, **kwargs):
            nonlocal request_count
            request_count += 1
            if request_count < 3:
                raise httpx.RequestError('fake exception', request=None)
            return httpx.Response(status_code=200, text=TestNetworkRequestRetries.TEXT)

        with patch.object(httpx.AsyncClient, 'request', new=get_response):
            network = Network(enable_http=True, retries=2)
            http_client = network.get_http_client()
            response = http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, TestNetworkRequestRetries.TEXT)
            network.close()

    def test_retries_exception(self):
        async def get_response(*args, **kwargs):
            raise httpx.RequestError('fake exception', request=None)

        with patch.object(httpx.AsyncClient, 'request', new=get_response):
            network = Network(enable_http=True, retries=0)
            http_client = network.get_http_client()
            with self.assertRaises(httpx.RequestError):
                http_client.request('GET', 'https://example.com/', raise_for_httperror=False)
            network.close()


class TestNetworkStreamRetries(SearxTestCase):

    TEXT = 'Lorem Ipsum'

    @classmethod
    def get_response_exception_then_200(cls):
        first = True

        def stream(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                raise httpx.RequestError('fake exception', request=None)
            return httpx.Response(status_code=200, text=TestNetworkStreamRetries.TEXT)

        return stream

    def test_retries_ok(self):
        with patch.object(httpx.AsyncClient, 'stream', new=TestNetworkStreamRetries.get_response_exception_then_200()):
            network = Network(enable_http=True, retries=1, retry_on_http_error=403)
            http_client = network.get_http_client()
            response = http_client._stream_sync_response('GET', 'https://example.com/')
            self.assertEqual(response.text, TestNetworkStreamRetries.TEXT)
            network.close()

    def test_retries_fail(self):
        with patch.object(httpx.AsyncClient, 'stream', new=TestNetworkStreamRetries.get_response_exception_then_200()):
            network = Network(enable_http=True, retries=0, retry_on_http_error=403)
            http_client = network.get_http_client()
            with self.assertRaises(httpx.RequestError):
                http_client._stream_sync_response('GET', 'https://example.com/')
            network.close()

    def test_retries_exception(self):
        first = True

        def stream(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                return httpx.Response(status_code=403, text=TestNetworkRequestRetries.TEXT)
            return httpx.Response(status_code=200, text=TestNetworkRequestRetries.TEXT)

        with patch.object(httpx.AsyncClient, 'stream', new=stream):
            network = Network(enable_http=True, retries=0, retry_on_http_error=403)
            http_client = network.get_http_client()
            response = http_client._stream_sync_response('GET', 'https://example.com/', raise_for_httperror=False)
            self.assertEqual(response.status_code, 403)
            network.close()
