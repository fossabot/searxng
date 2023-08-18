# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=missing-module-docstring, global-statement

from abc import ABC, abstractmethod
import asyncio
import concurrent.futures
from collections import namedtuple
import logging
import random
from ssl import SSLContext
import threading
from typing import Any, Dict, Generator, Tuple
from queue import SimpleQueue
from types import MethodType

import anyio
import httpx
from httpx_socks import AsyncProxyTransport
from python_socks import parse_proxy_url, ProxyConnectionError, ProxyTimeoutError, ProxyError

from .raise_for_httperror import raise_for_httperror


# Optional uvloop (support Python 3.6)
try:
    import uvloop
except ImportError:
    pass
else:
    uvloop.install()


LOOP = None
SSLCONTEXTS: Dict[Any, SSLContext] = {}


class SoftRetryHTTPException(Exception):
    """Make Pylint happy

    Args:
        Exception (_type_): _description_
    """


def shuffle_ciphers(ssl_context):
    """Shuffle httpx's default ciphers of a SSL context randomly.

    From `What Is TLS Fingerprint and How to Bypass It`_

    > When implementing TLS fingerprinting, servers can't operate based on a
    > locked-in whitelist database of fingerprints.  New fingerprints appear
    > when web clients or TLS libraries release new versions. So, they have to
    > live off a blocklist database instead.
    > ...
    > It's safe to leave the first three as is but shuffle the remaining ciphers
    > and you can bypass the TLS fingerprint check.

    .. _What Is TLS Fingerprint and How to Bypass It:
       https://www.zenrows.com/blog/what-is-tls-fingerprint#how-to-bypass-tls-fingerprinting

    """
    c_list = httpx._config.DEFAULT_CIPHERS.split(':')  # pylint: disable=protected-access
    sc_list, c_list = c_list[:3], c_list[3:]
    random.shuffle(c_list)
    ssl_context.set_ciphers(":".join(sc_list + c_list))


def get_sslcontexts(proxy_url=None, cert=None, verify=True, trust_env=True, http2=False):
    key = (proxy_url, cert, verify, trust_env, http2)
    if key not in SSLCONTEXTS:
        SSLCONTEXTS[key] = httpx.create_ssl_context(cert, verify, trust_env, http2)
    shuffle_ciphers(SSLCONTEXTS[key])
    return SSLCONTEXTS[key]


### Transport


class AsyncHTTPTransportNoHttp(httpx.AsyncHTTPTransport):
    """Block HTTP request"""

    async def handle_async_request(self, request):
        raise httpx.UnsupportedProtocol('HTTP protocol is disabled')


class AsyncProxyTransportFixed(AsyncProxyTransport):
    """Fix httpx_socks.AsyncProxyTransport

    Map python_socks exceptions to httpx.ProxyError exceptions
    """

    async def handle_async_request(self, request):
        try:
            return await super().handle_async_request(request)
        except ProxyConnectionError as e:
            raise httpx.ProxyError("ProxyConnectionError: " + e.strerror, request=request) from e
        except ProxyTimeoutError as e:
            raise httpx.ProxyError("ProxyTimeoutError: " + e.args[0], request=request) from e
        except ProxyError as e:
            raise httpx.ProxyError("ProxyError: " + e.args[0], request=request) from e


def get_transport_for_socks_proxy(verify, http2, local_address, proxy_url, limit, retries):
    # support socks5h (requests compatibility):
    # https://requests.readthedocs.io/en/master/user/advanced/#socks
    # socks5://   hostname is resolved on client side
    # socks5h://  hostname is resolved on proxy side
    rdns = False
    socks5h = 'socks5h://'
    if proxy_url.startswith(socks5h):
        proxy_url = 'socks5://' + proxy_url[len(socks5h) :]
        rdns = True

    proxy_type, proxy_host, proxy_port, proxy_username, proxy_password = parse_proxy_url(proxy_url)
    verify = get_sslcontexts(proxy_url, None, verify, True, http2) if verify is True else verify
    return AsyncProxyTransportFixed(
        proxy_type=proxy_type,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        username=proxy_username,
        password=proxy_password,
        rdns=rdns,
        loop=get_loop(),
        verify=verify,
        http2=http2,
        local_address=local_address,
        limits=limit,
        retries=retries,
    )


def get_transport(verify, http2, local_address, proxy_url, limit, retries):
    verify = get_sslcontexts(None, None, verify, True, http2) if verify is True else verify
    return httpx.AsyncHTTPTransport(
        # pylint: disable=protected-access
        verify=verify,
        http2=http2,
        limits=limit,
        proxy=httpx._config.Proxy(proxy_url) if proxy_url else None,
        local_address=local_address,
        retries=retries,
    )


### STREAM


def _close_response_method(self):
    asyncio.run_coroutine_threadsafe(self.aclose(), get_loop())
    # reach the end of _self.generator ( _stream_generator ) to an avoid memory leak.
    # it makes sure that :
    # * the httpx response is closed (see the stream_chunk_to_queue function)
    # * to call future.result() in _stream_generator
    for _ in self._generator:  # pylint: disable=protected-access
        continue


def _iter_generator(self):
    yield from self._generator  # pylint: disable=protected-access


### Clients


class ABCHTTPClient(ABC):
    """Make Pylint happy

    Args:
        ABC (_type_): _description_

    Returns:
        _type_: _description_
    """

    @abstractmethod
    def send(self, stream, method, url, timeout=None, **kwargs) -> httpx.Response:
        pass

    @abstractmethod
    def close(self):
        pass

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        pass

    def request(self, method, url, timeout=None, **kwargs) -> httpx.Response:
        return self.send(False, method, url, timeout, **kwargs)

    def stream(self, method, url, timeout=None, **kwargs) -> httpx.Response:
        return self.send(True, method, url, timeout, **kwargs)


class OneHTTPClient(ABCHTTPClient):
    """Wrap a httpx.AsyncClient

    Use httpx_socks for socks proxies.

    Deal with httpx.RemoteProtocolError exception: httpx raises this exception when the
    HTTP/2 server disconnect. It is excepted to reconnect.
    Related to https://github.com/encode/httpx/issues/1478
    Perhaps it can be removed now : TODO check in production.

    In Response, "ok" is set to "not response.is_error()"
    """

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
        local_addresses=None,
        max_redirects=30,
        follow_redirects=False,
        hook_log_response=None,
        logger=None,
    ) -> "OneHTTPClient":
        self.enable_http = enable_http
        self.verify = verify
        self.enable_http2 = enable_http2
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.keepalive_expiry = keepalive_expiry
        self.proxies = proxies
        self.local_address = local_addresses
        self.max_redirects = max_redirects
        self.follow_redirects = follow_redirects
        self.hook_log_response = hook_log_response
        self.logger = logger
        self._new_client()

    def send(self, stream, method, url, timeout=None, **kwargs):
        if timeout is None:
            timeout = 120
            raise Exception()  # FIXME
        future = asyncio.run_coroutine_threadsafe(
            self._async_send(stream, method, url, timeout=timeout, **kwargs), get_loop()
        )
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as e:
            raise httpx.TimeoutException('Timeout', request=None) from e

    def close(self, timeout=10):
        future = asyncio.run_coroutine_threadsafe(self.client.aclose, get_loop())
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as e:
            raise httpx.TimeoutException('Timeout', request=None) from e

    @property
    def is_closed(self) -> bool:
        return self.client.is_closed

    def _new_client(self):
        limit = httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            keepalive_expiry=self.keepalive_expiry,
        )
        # See https://www.python-httpx.org/advanced/#routing
        mounts = {}
        for pattern, proxy_url in self.proxies.items():
            if not self.enable_http and pattern.startswith('http://'):
                continue
            if (
                proxy_url.startswith('socks4://')
                or proxy_url.startswith('socks5://')
                or proxy_url.startswith('socks5h://')
            ):
                mounts[pattern] = get_transport_for_socks_proxy(
                    self.verify, self.enable_http2, self.local_address, proxy_url, limit, 0
                )
            else:
                mounts[pattern] = get_transport(self.verify, self.enable_http2, self.local_address, proxy_url, limit, 0)

        if not self.enable_http:
            mounts['http://'] = AsyncHTTPTransportNoHttp()

        transport = get_transport(self.verify, self.enable_http2, self.local_address, None, limit, 0)

        event_hooks = None
        if self.hook_log_response:
            event_hooks = {'response': [self.hook_log_response]}

        self.client = httpx.AsyncClient(
            transport=transport,
            mounts=mounts,
            max_redirects=self.max_redirects,
            event_hooks=event_hooks,
        )

    async def _reconnect_client(self):
        await self.client.aclose()
        self._new_client()

    async def _async_send(self, stream: bool, method: str, url: str, **kwargs) -> httpx.Response:
        retry = 1
        while retry >= 0:  # pragma: no cover
            retry -= 1
            try:
                if stream:
                    response = await self._stream_sync_response(method, url, **kwargs)
                else:
                    response = await self.client.request(method, url, **kwargs)
                self._patch_response(response)
                return response
            except httpx.RemoteProtocolError as e:
                if retry >= 0:
                    # the server has closed the connection:
                    # try again without decreasing the retries variable & with a new HTTP client
                    await self._reconnect_client()
                    if self.logger:
                        self.logger.warning('httpx.RemoteProtocolError: the server has disconnected, retrying')
                    continue
                raise e
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                raise e
        return response

    @staticmethod
    def _patch_response(response):
        if isinstance(response, httpx.Response):
            # requests compatibility (response is not streamed)
            # see also https://www.python-httpx.org/compatibility/#checking-for-4xx5xx-responses
            response.ok = not response.is_error

        return response

    def _stream_sync_response(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Replace httpx.stream.

        Usage:
        response = http_client.stream(...)
        for chunk in stream.iter_bytes():
            ...

        httpx.Client.stream requires to write the httpx.HTTPTransport version of the
        the httpx.AsyncHTTPTransport declared above.
        """
        generator = self._stream_generator(method, url, **kwargs)

        # yield response
        response = next(generator)  # pylint: disable=stop-iteration-return
        if isinstance(response, Exception):
            raise response

        response._generator = generator  # pylint: disable=protected-access
        response.close = MethodType(_close_response_method, response)
        response.iter_bytes = MethodType(_iter_generator, response)

        return response

    def _stream_generator(self, method: str, url: str, **kwargs) -> Generator[bytes, None, None]:
        queue = SimpleQueue()
        future = asyncio.run_coroutine_threadsafe(self._stream_chunk_to_queue(queue, method, url, **kwargs), get_loop())

        # yield chunks
        obj_or_exception = queue.get()
        while obj_or_exception is not None:
            if isinstance(obj_or_exception, Exception):
                raise obj_or_exception
            yield obj_or_exception
            obj_or_exception = queue.get()
        future.result()

    async def _stream_chunk_to_queue(self, queue: SimpleQueue, method: str, url: str, **kwargs):
        try:
            async with await self.send(True, method, url, **kwargs) as response:
                queue.put(response)
                # aiter_raw: access the raw bytes on the response without applying any HTTP content decoding
                # https://www.python-httpx.org/quickstart/#streaming-responses
                async for chunk in response.aiter_raw(65536):
                    if len(chunk) > 0:
                        queue.put(chunk)
        except (httpx.StreamClosed, anyio.ClosedResourceError):
            # the response was queued before the exception.
            # the exception was raised on aiter_raw.
            # we do nothing here: in the finally block, None will be queued
            # so stream(method, url, **kwargs) generator can stop
            pass
        except Exception as e:  # pylint: disable=broad-except
            # broad except to avoid this scenario:
            # exception in network.stream(method, url, **kwargs)
            # -> the exception is not catch here
            # -> queue None (in finally)
            # -> the function below steam(method, url, **kwargs) has nothing to return
            queue.put(e)
        finally:
            queue.put(None)


HTTPMultiClientConf = namedtuple('HTTPMultiClientConf', ['verify', 'max_redirects', 'follow_redirects'])


class HTTPClient(ABCHTTPClient):
    """Some parameter like verify, max_redirects and allow_redirects are defined at the client level,
    not at the request level.

    This class allow to specify these parameters at the request level.
    The implementation uses multi instances of OneHTTPClient
    """

    def __init__(
        # pylint: disable=too-many-arguments
        self,
        **kwargs,
    ) -> "HTTPClient":
        self.kwargs = kwargs
        self.clients: Dict[Tuple, OneHTTPClient] = {}

    @staticmethod
    def _extract_kwargs_clients(kwargs) -> HTTPMultiClientConf:
        # default values
        verify = True
        max_redirects = 10
        follow_redirects = True

        if 'verify' in kwargs:
            verify = kwargs.pop('verify')
        if 'max_redirects' in kwargs:
            max_redirects = kwargs.pop('max_redirects')
        if 'allow_redirects' in kwargs:
            # see https://github.com/encode/httpx/pull/1808
            follow_redirects = kwargs.pop('allow_redirects')
        return HTTPMultiClientConf(verify, max_redirects, follow_redirects)

    def _get_client_and_update_kwargs(self, **kwargs) -> OneHTTPClient:
        kwargs_clients = self._extract_kwargs_clients(kwargs)
        if kwargs_clients not in self.clients:
            self.clients[kwargs_clients] = OneHTTPClient(
                verify=kwargs_clients.verify,
                max_redirects=kwargs_clients.max_redirects,
                follow_redirects=kwargs_clients.follow_redirects,
                **self.kwargs,
            )
        return self.clients[kwargs_clients]

    def send(self, stream, method, url, timeout=None, **kwargs):
        client = self._get_client_and_update_kwargs(**kwargs)
        return client.send(method, stream, url, timeout, **kwargs)

    def close(self):
        for client in self.clients.values():
            client.close()

    @property
    def is_closed(self) -> bool:
        return any(client.is_closed for client in self.clients.values())


class HTTPClientSoftError(HTTPClient):
    """Inherit from HTTPClient, raise exception according the retry_on_http_error argument"""

    def __init__(self, retry_on_http_error=None, **kwargs):
        super().__init__(**kwargs)
        self.retry_on_http_error = retry_on_http_error

    def is_error_but_retry(self, response):
        # pylint: disable=too-many-boolean-expressions
        if (
            (self.retry_on_http_error is True and 400 <= response.status_code <= 599)
            or (isinstance(self.retry_on_http_error, list) and response.status_code in self.retry_on_http_error)
            or (isinstance(self.retry_on_http_error, int) and response.status_code == self.retry_on_http_error)
        ):
            return False
        return True

    @staticmethod
    def extract_do_raise_for_httperror(kwargs):
        do_raise_for_httperror = True
        if 'raise_for_httperror' in kwargs:
            do_raise_for_httperror = kwargs['raise_for_httperror']
            del kwargs['raise_for_httperror']
        return do_raise_for_httperror

    def send(self, stream, method, url, timeout=None, **kwargs):
        try:
            do_raise_for_httperror = self.extract_do_raise_for_httperror(kwargs)
            response = super().send(stream, method, url, timeout=timeout, **kwargs)
            if isinstance(response, httpx.Response) and do_raise_for_httperror:
                raise_for_httperror(response)
            if self.is_error_but_retry(response):
                response.raise_for_status()
                raise SoftRetryHTTPException()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise e


class TorHTTPClient(HTTPClientSoftError):
    """Extend HTTPClientSoftError client. To use with Tor configuration.

    The class checks if the client is really connected through Tor.
    """

    _TOR_CHECK_RESULT = {}

    def __init__(self, proxies=None, **kwargs):
        super().__init__(proxies, **kwargs)
        if not self._is_connected_through_tor(proxies):
            self.close()
            raise httpx.ProxyError('Network configuration problem: not using Tor')

    def _is_connected_through_tor(self, proxies) -> bool:
        """TODO : rewrite to check the proxies variable instead of checking the HTTPTransport ?"""
        if proxies in TorHTTPClient._TOR_CHECK_RESULT:
            return TorHTTPClient._TOR_CHECK_RESULT[proxies]

        # get one httpx client through get_client_and_update_kwargs
        one_http_client = self._get_client_and_update_kwargs(verify=True)
        httpx_client = one_http_client.client
        # ignore client._transport because it is not used with all://
        for transport in httpx_client._mounts.values():  # pylint: disable=protected-access
            if isinstance(transport, AsyncHTTPTransportNoHttp):
                # ignore the NO HTTP transport
                continue
            if getattr(transport, "_pool") and getattr(
                transport._pool, "_rdns", False  # pylint: disable=protected-access
            ):
                # ignore socks5://, check only socks5h://
                continue
            # ??? why return ???
            return False

        # actual check
        response = one_http_client.request("GET", "https://check.torproject.org/api/ip", timeout=60)
        result = bool(response.json()["IsTor"])
        TorHTTPClient._TOR_CHECK_RESULT[proxies] = result
        return result


def get_loop():
    return LOOP


def init():
    # log
    for logger_name in (
        'httpx',
        'httpcore.proxy',
        'httpcore.connection',
        'httpcore.http11',
        'httpcore.http2',
        'hpack.hpack',
        'hpack.table',
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # loop
    def loop_thread():
        global LOOP
        LOOP = asyncio.new_event_loop()
        LOOP.run_forever()

    thread = threading.Thread(
        target=loop_thread,
        name='asyncio_loop',
        daemon=True,
    )
    thread.start()


init()
