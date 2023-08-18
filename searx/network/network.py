# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=global-statement
# pylint: disable=missing-module-docstring, missing-class-docstring

import ipaddress
from itertools import cycle
from typing import Dict, Tuple

import httpx

from searx import logger, searx_debug
from .client import ABCHTTPClient, HTTPClientSoftError, TorHTTPClient


logger = logger.getChild('network')
DEFAULT_NAME = '__DEFAULT__'
NETWORKS: Dict[str, 'Network'] = {}
# requests compatibility when reading proxy settings from settings.yml
PROXY_PATTERN_MAPPING = {
    'http': 'http://',
    'https': 'https://',
    'socks4': 'socks4://',
    'socks5': 'socks5://',
    'socks5h': 'socks5h://',
    'http:': 'http://',
    'https:': 'https://',
    'socks4:': 'socks4://',
    'socks5:': 'socks5://',
    'socks5h:': 'socks5h://',
}

ADDRESS_MAPPING = {'ipv4': '0.0.0.0', 'ipv6': '::'}


class Network:

    __slots__ = (
        'enable_http',
        'verify',
        'enable_http2',
        'max_connections',
        'max_keepalive_connections',
        'keepalive_expiry',
        'local_addresses',
        'proxies',
        'using_tor_proxy',
        'max_redirects',
        'retries',
        'retry_on_http_error',
        '_local_addresses_cycle',
        '_proxies_cycle',
        '_clients',
        '_logger',
    )

    _TOR_CHECK_RESULT = {}

    def __init__(
        # pylint: disable=too-many-arguments
        self,
        enable_http=True,
        verify=True,
        enable_http2=False,
        max_connections=None,
        max_keepalive_connections=None,
        keepalive_expiry=None,
        proxies=None,
        using_tor_proxy=False,
        local_addresses=None,
        retries=0,
        retry_on_http_error=None,
        max_redirects=30,
        logger_name=None,
    ):

        self.enable_http = enable_http
        self.verify = verify
        self.enable_http2 = enable_http2
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.keepalive_expiry = keepalive_expiry
        self.proxies = proxies
        self.using_tor_proxy = using_tor_proxy
        self.local_addresses = local_addresses
        self.retries = retries
        self.retry_on_http_error = retry_on_http_error
        self.max_redirects = max_redirects
        self._local_addresses_cycle = self._get_ipaddress_cycle()
        self._proxies_cycle = self._get_proxy_cycles()
        self._clients: Dict[Tuple, HTTPClientSoftError] = {}
        self._logger = logger.getChild(logger_name) if logger_name else logger
        self._check_parameters()

    def _check_parameters(self):
        for address in self._iter_ipaddresses():
            if '/' in address:
                ipaddress.ip_network(address, False)
            else:
                ipaddress.ip_address(address)

        if self.proxies is not None and not isinstance(self.proxies, (str, dict)):
            raise ValueError('proxies type has to be str, dict or None')

    def _iter_ipaddresses(self):
        local_addresses = self.local_addresses
        if not local_addresses:
            return
        if isinstance(local_addresses, str):
            local_addresses = [local_addresses]
        for address in local_addresses:
            yield address

    def _get_ipaddress_cycle(self):
        while True:
            count = 0
            for address in self._iter_ipaddresses():
                if '/' in address:
                    for a in ipaddress.ip_network(address, False).hosts():
                        yield str(a)
                        count += 1
                else:
                    a = ipaddress.ip_address(address)
                    yield str(a)
                    count += 1
            if count == 0:
                yield None

    def _iter_proxies(self):
        if not self.proxies:
            return
        # https://www.python-httpx.org/compatibility/#proxy-keys
        if isinstance(self.proxies, str):
            yield 'all://', [self.proxies]
        else:
            for pattern, proxy_url in self.proxies.items():
                pattern = PROXY_PATTERN_MAPPING.get(pattern, pattern)
                if isinstance(proxy_url, str):
                    proxy_url = [proxy_url]
                yield pattern, proxy_url

    def _get_proxy_cycles(self):
        proxy_settings = {}
        for pattern, proxy_urls in self._iter_proxies():
            proxy_settings[pattern] = cycle(proxy_urls)
        while True:
            # pylint: disable=stop-iteration-return
            yield tuple((pattern, next(proxy_url_cycle)) for pattern, proxy_url_cycle in proxy_settings.items())

    async def _log_response(self, response: httpx.Response):
        request = response.request
        status = f"{response.status_code} {response.reason_phrase}"
        response_line = f"{response.http_version} {status}"
        content_type = response.headers.get("Content-Type")
        content_type = f' ({content_type})' if content_type else ''
        self._logger.debug(f'HTTP Request: {request.method} {request.url} "{response_line}"{content_type}')

    def get_http_client(self) -> ABCHTTPClient:
        """Return an HTTP client.
        If two proxies are defined, the first call to this function returns an HTTP client using the first proxy.
        A second call returns an HTTP client using the second proxy.

        Returns:
            ABCHTTPClient: _description_
        """
        local_addresses = next(self._local_addresses_cycle)
        proxies = next(self._proxies_cycle)  # is a tuple so it can be part of the key
        key = (local_addresses, proxies)
        hook_log_response = self._log_response if searx_debug else None
        if key not in self._clients or self._clients[key].is_closed:
            http_client_cls = TorHTTPClient if self.using_tor_proxy else HTTPClientSoftError
            self._clients[key] = http_client_cls(
                enable_http=self.enable_http,
                enable_http2=self.enable_http2,
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections,
                keepalive_expiry=self.keepalive_expiry,
                proxies=dict(proxies),
                local_addresses=local_addresses,
                hook_log_response=hook_log_response,
                logger=self._logger,
            )
        return self._clients[key]

    def close(self):
        for client in self._clients.values():
            client.close()


def get_network(name=None):
    return NETWORKS.get(name or DEFAULT_NAME)


def check_network_configuration():
    exception_count = 0
    for network in NETWORKS.values():
        if network.using_tor_proxy:
            try:
                network.get_http_client()
            except Exception:  # pylint: disable=broad-except
                network._logger.exception('Error')  # pylint: disable=protected-access
                exception_count += 1
    if exception_count > 0:
        raise RuntimeError("Invalid network configuration")


def initialize(settings_engines=None, settings_outgoing=None):
    # pylint: disable=import-outside-toplevel)
    from searx.engines import engines
    from searx import settings

    # pylint: enable=import-outside-toplevel)

    settings_engines = settings_engines or settings['engines']
    settings_outgoing = settings_outgoing or settings['outgoing']

    # default parameters for AsyncHTTPTransport
    # see https://github.com/encode/httpx/blob/e05a5372eb6172287458b37447c30f650047e1b8/httpx/_transports/default.py#L108-L121  # pylint: disable=line-too-long
    default_params = {
        'enable_http': False,
        'verify': settings_outgoing['verify'],
        'enable_http2': settings_outgoing['enable_http2'],
        'max_connections': settings_outgoing['pool_connections'],
        'max_keepalive_connections': settings_outgoing['pool_maxsize'],
        'keepalive_expiry': settings_outgoing['keepalive_expiry'],
        'local_addresses': settings_outgoing['source_ips'],
        'using_tor_proxy': settings_outgoing['using_tor_proxy'],
        'proxies': settings_outgoing['proxies'],
        'max_redirects': settings_outgoing['max_redirects'],
        'retries': settings_outgoing['retries'],
        'retry_on_http_error': None,
    }

    def new_network(params, logger_name=None):
        nonlocal default_params
        result = {}
        result.update(default_params)
        result.update(params)
        if logger_name:
            result['logger_name'] = logger_name
        return Network(**result)

    def iter_networks():
        nonlocal settings_engines
        for engine_spec in settings_engines:
            engine_name = engine_spec['name']
            engine = engines.get(engine_name)
            if engine is None:
                continue
            network = getattr(engine, 'network', None)
            yield engine_name, engine, network

    NETWORKS.clear()
    NETWORKS[DEFAULT_NAME] = new_network({}, logger_name='default')
    NETWORKS['ipv4'] = new_network({'local_addresses': '0.0.0.0'}, logger_name='ipv4')
    NETWORKS['ipv6'] = new_network({'local_addresses': '::'}, logger_name='ipv6')

    # define networks from outgoing.networks
    for network_name, network in settings_outgoing['networks'].items():
        NETWORKS[network_name] = new_network(network, logger_name=network_name)

    # define networks from engines.[i].network (except references)
    for engine_name, engine, network in iter_networks():
        if network is None:
            network = {}
            for attribute_name, attribute_value in default_params.items():
                if hasattr(engine, attribute_name):
                    network[attribute_name] = getattr(engine, attribute_name)
                else:
                    network[attribute_name] = attribute_value
            NETWORKS[engine_name] = new_network(network, logger_name=engine_name)
        elif isinstance(network, dict):
            NETWORKS[engine_name] = new_network(network, logger_name=engine_name)

    # define networks from engines.[i].network (references)
    for engine_name, engine, network in iter_networks():
        if isinstance(network, str):
            NETWORKS[engine_name] = NETWORKS[network]

    # the /image_proxy endpoint has a dedicated network.
    # same parameters than the default network, but HTTP/2 is disabled.
    # It decreases the CPU load average, and the total time is more or less the same
    if 'image_proxy' not in NETWORKS:
        image_proxy_params = default_params.copy()
        image_proxy_params['enable_http2'] = False
        NETWORKS['image_proxy'] = new_network(image_proxy_params, logger_name='image_proxy')


NETWORKS[DEFAULT_NAME] = Network()
