# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=missing-module-docstring, global-statement

import asyncio
import threading
import concurrent.futures
import ssl
from timeit import default_timer
from typing import NamedTuple, List, Dict, Union
from contextlib import contextmanager

import httpx

from .network import get_network, initialize, check_network_configuration, Network  # pylint:disable=cyclic-import
from .client import get_loop, SoftRetryHTTPException
from .raise_for_httperror import raise_for_httperror


THREADLOCAL = threading.local()
"""Thread-local data is data for thread specific values."""


def reset_time_for_thread():
    THREADLOCAL.total_time = 0


def get_time_for_thread():
    """returns thread's total time or None"""
    return THREADLOCAL.__dict__.get('total_time')


def set_timeout_for_thread(timeout, start_time=None):
    THREADLOCAL.timeout = timeout
    THREADLOCAL.start_time = start_time


def set_context_network_name(network_name):
    THREADLOCAL.network = get_network(network_name)


def get_context_network() -> Network:
    """If set return thread's network.

    If unset, return value from :py:obj:`get_network`.
    """
    return THREADLOCAL.__dict__.get('network') or get_network()


@contextmanager
def _record_http_time():
    # pylint: disable=too-many-branches
    time_before_request = default_timer()
    start_time = getattr(THREADLOCAL, 'start_time', time_before_request)
    try:
        yield start_time
    finally:
        # update total_time.
        # See get_time_for_thread() and reset_time_for_thread()
        if hasattr(THREADLOCAL, 'total_time'):
            time_after_request = default_timer()
            THREADLOCAL.total_time += time_after_request - time_before_request


def _get_timeout(start_time, kwargs):
    # pylint: disable=too-many-branches

    # timeout (httpx)
    if 'timeout' in kwargs:
        timeout = kwargs['timeout']
    else:
        timeout = getattr(THREADLOCAL, 'timeout', None)
        if timeout is not None:
            kwargs['timeout'] = timeout

    # 2 minutes timeout for the requests without timeout
    timeout = timeout or 120

    # ajdust actual timeout
    timeout += 0.2  # overhead
    if start_time:
        timeout -= default_timer() - start_time

    return timeout


def call_with_http_client_context(self, start_time, func, *args, **kwargs):
    try:
        retries = self.retries
        while retries >= 0 and _get_timeout(start_time, {}) > 0:  # pragma: no cover
            THREADLOCAL.http_client = get_context_network().get_http_client()
            try:
                return func(*args, **kwargs)
            except (ssl.SSLError, httpx.RequestError, httpx.HTTPStatusError) as e:
                if retries <= 0:
                    raise e
            except SoftRetryHTTPException as e:
                if retries <= 0:
                    raise e
            except Exception as e:
                raise e
            retries -= 1
        raise httpx.TimeoutException("Timeout")
    finally:
        THREADLOCAL.http_client = None


def request(method, url, **kwargs):
    """same as requests/requests/api.py request(...)"""
    http_client = THREADLOCAL.__dict__.get('http_client') or get_network().get_http_client()
    with _record_http_time() as start_time:
        timeout = _get_timeout(start_time, kwargs)
        kwargs.pop('timeout', None)
        return http_client.request(method, url, timeout=timeout, **kwargs)


def multi_requests(request_list: List["Request"]) -> List[Union[httpx.Response, Exception]]:
    """send multiple HTTP requests in parallel. Wait for all requests to finish."""
    with _record_http_time() as start_time:
        # send the requests
        loop = get_loop()
        future_list = []
        for request_desc in request_list:
            timeout = _get_timeout(start_time, request_desc.kwargs)
            future = asyncio.run_coroutine_threadsafe(
                THREADLOCAL.http_client.request(request_desc.method, request_desc.url, **request_desc.kwargs), loop
            )
            future_list.append((future, timeout))

        # read the responses
        responses = []
        for future, timeout in future_list:
            try:
                responses.append(future.result(timeout))
            except concurrent.futures.TimeoutError:
                responses.append(httpx.TimeoutException('Timeout', request=None))
            except Exception as e:  # pylint: disable=broad-except
                responses.append(e)
        return responses


class Request(NamedTuple):
    """Request description for the multi_requests function"""

    method: str
    url: str
    kwargs: Dict[str, str] = {}

    @staticmethod
    def get(url, **kwargs):
        return Request('GET', url, kwargs)

    @staticmethod
    def options(url, **kwargs):
        return Request('OPTIONS', url, kwargs)

    @staticmethod
    def head(url, **kwargs):
        return Request('HEAD', url, kwargs)

    @staticmethod
    def post(url, **kwargs):
        return Request('POST', url, kwargs)

    @staticmethod
    def put(url, **kwargs):
        return Request('PUT', url, kwargs)

    @staticmethod
    def patch(url, **kwargs):
        return Request('PATCH', url, kwargs)

    @staticmethod
    def delete(url, **kwargs):
        return Request('DELETE', url, kwargs)


def get(url, **kwargs):
    kwargs.setdefault('allow_redirects', True)
    return request('get', url, **kwargs)


def options(url, **kwargs):
    kwargs.setdefault('allow_redirects', True)
    return request('options', url, **kwargs)


def head(url, **kwargs):
    kwargs.setdefault('allow_redirects', False)
    return request('head', url, **kwargs)


def post(url, data=None, **kwargs):
    return request('post', url, data=data, **kwargs)


def put(url, data=None, **kwargs):
    return request('put', url, data=data, **kwargs)


def patch(url, data=None, **kwargs):
    return request('patch', url, data=data, **kwargs)


def delete(url, **kwargs):
    return request('delete', url, **kwargs)
