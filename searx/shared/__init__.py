# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
from . import shared_redis


logger = logging.getLogger('searx.shared')


def has_uwsgi():
    try:
        import uwsgi
    except ImportError:
        return False

    try:
        uwsgi.cache_update('dummy', b'dummy')
        if uwsgi.cache_get('dummy') != b'dummy':
            raise Exception()
        return True
    except:
        # uwsgi.ini configuration problem: disable all scheduling
        logger.exception(
            'uwsgi.ini configuration error, add this line to your uwsgi.ini\n'
            'cache2 = name=searxcache,items=2000,blocks=2000,blocksize=4096,bitmap=1'
        )
        return False


if shared_redis.init():
    logger.info('Use shared_redis implementation')
    SharedDict = shared_redis.RedisCacheSharedDict
    schedule = shared_redis.schedule
elif has_uwsgi():
    logger.info('Use shared_uwsgi implementation')
    from .shared_uwsgi import UwsgiCacheSharedDict as SharedDict, schedule
else:
    logger.info('Use shared_simple implementation')
    from .shared_simple import SimpleSharedDict as SharedDict, schedule

storage = SharedDict()
