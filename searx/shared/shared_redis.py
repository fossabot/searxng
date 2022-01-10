# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import typing

from searx import get_setting
from . import shared_abstract

import redis


logger = logging.getLogger('searx.shared.redis')
_client: typing.Optional[redis.Redis] = None


def client() -> redis.Redis:
    return _client


class RedisCacheSharedDict(shared_abstract.SharedDict):
    def get_int(self, key):
        value = _client.get(key)
        if value is None:
            return value
        else:
            return int.from_bytes(value, 'big')

    def set_int(self, key, value):
        b = value.to_bytes(4, 'big')
        _client.set(key, b)

    def get_str(self, key):
        value = _client.get(key)
        if value is None:
            return value
        else:
            return value.decode('utf-8')

    def set_str(self, key, value):
        b = value.encode('utf-8')
        _client.set(key, b)


def schedule(delay, func, *args):
    # TODO
    pass


def init():
    global _client
    if get_setting('redis.url') is None:
        return False
    try:
        _client = redis.Redis.from_url(get_setting('redis.url'))
        logger.info("connected redis DB %s", _client.acl_whoami())
        return True
    except redis.exceptions.ConnectionError:
        logger.exception("can't connet redis DB at %s", get_setting('redis.url'))
    return False
