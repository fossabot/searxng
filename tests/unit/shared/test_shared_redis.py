import time

from tests import SearxTestCase

import redislite

from searx.shared import shared_redis
import searx.shared.redisdb
import searx.redislib


class TestEnginesInit(SearxTestCase):
    def setUp(self):
        searx.shared.redisdb._client = redislite.Redis()
        searx.shared.redisdb.init()
        return super().setUp()

    def tearDown(self) -> None:
        shared_redis.reset_scheduler()
        return super().tearDown()

    def test_scheduler_one_function(self):
        call_count = 0

        def f():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # check that exceptions don't stop the scheduler thread
                raise Exception()

        shared_redis.schedule(1, f)
        client = searx.shared.redisdb.client()

        redis_key = tuple(shared_redis.SCHEDULED_FUNCTIONS.keys())[0]

        self.assertIsNotNone(shared_redis.SCHEDULER_THREAD)
        self.assertTrue(shared_redis.SCHEDULER_THREAD.is_alive())
        self.assertEqual(client.hlen('SearXNG_scheduler_ts'), 1)
        self.assertEqual(client.hlen('SearXNG_scheduler_delay'), 1)
        self.assertEqual(client.hget('SearXNG_scheduler_delay', redis_key), b'1')
        time.sleep(2)
        self.assertGreater(call_count, 0)

    def test_scheduler_two_function(self):
        f_count = 0
        g_count = 0

        def f():
            nonlocal f_count
            f_count += 1

        def g():
            nonlocal g_count
            g_count += 1

        shared_redis.schedule(0, f)
        shared_redis.schedule(1, g)
        client = searx.shared.redisdb.client()

        self.assertIsNotNone(shared_redis.SCHEDULER_THREAD)
        self.assertEqual(client.hlen('SearXNG_scheduler_ts'), 2)
        self.assertEqual(client.hlen('SearXNG_scheduler_delay'), 2)
        time.sleep(2)
        self.assertGreater(g_count, 0)
        self.assertGreater(f_count, g_count)

    def test_set_get(self):
        searx.shared.redisdb.client().ping()
        d = shared_redis.RedisCacheSharedDict()
        d.set_str('a', 'bc')
        d.set_int('d', 12)
        self.assertEqual(d.get_str('a'), 'bc')
        self.assertEqual(d.get_int('d'), 12)
