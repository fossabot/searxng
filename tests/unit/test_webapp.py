# -*- coding: utf-8 -*-

import unittest
from urllib.parse import ParseResult
from mock import Mock
# from searx.testing import SearxTestCase
from searx.search import Search
import searx.search.processors

from starlette.testclient import TestClient


class ViewsTestCase(unittest.TestCase):

    def setattr4test(self, obj, attr, value):
        """
        setattr(obj, attr, value)
        but reset to the previous value in the cleanup.
        """
        previous_value = getattr(obj, attr)

        def cleanup_patch():
            setattr(obj, attr, previous_value)
        self.addCleanup(cleanup_patch)
        setattr(obj, attr, value)

    def setUp(self):
        # skip init function (no external HTTP request)
        def dummy(*args, **kwargs):
            pass
        self.setattr4test(searx.search.processors, 'initialize_processor', dummy)

        from searx import webapp, templates  # pylint disable=import-outside-toplevel
        self.client = TestClient(webapp.app)

        # set some defaults
        test_results = [
            {
                'content': 'first test content',
                'title': 'First Test',
                'url': 'http://first.test.xyz',
                'engines': ['youtube', 'startpage'],
                'engine': 'startpage',
                'parsed_url': ParseResult(scheme='http', netloc='first.test.xyz', path='/', params='', query='', fragment=''),  # noqa
            }, {
                'content': 'second test content',
                'title': 'Second Test',
                'url': 'http://second.test.xyz',
                'engines': ['youtube', 'startpage'],
                'engine': 'youtube',
                'parsed_url': ParseResult(scheme='http', netloc='second.test.xyz', path='/', params='', query='', fragment=''),  # noqa
            },
        ]

        timings = [
            {
                'engine': 'startpage',
                'total': 0.8,
                'load': 0.7
            },
            {
                'engine': 'youtube',
                'total': 0.9,
                'load': 0.6
            }
        ]

        def search_mock(search_self, *args):
            search_self.result_container = Mock(get_ordered_results=lambda: test_results,
                                                answers=dict(),
                                                corrections=set(),
                                                suggestions=set(),
                                                infoboxes=[],
                                                unresponsive_engines=set(),
                                                results=test_results,
                                                results_number=lambda: 3,
                                                results_length=lambda: len(test_results),
                                                get_timings=lambda: timings,
                                                redirect_url=None,
                                                engine_data={})

        self.setattr4test(Search, 'search', search_mock)

        def get_current_theme_name_mock(request, override=None):
            if override:
                return override
            return 'oscar'

        self.setattr4test(templates, 'get_current_theme_name', get_current_theme_name_mock)

        self.maxDiff = None  # to see full diffs

    def test_index_empty(self):
        result = self.client.post('/')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'<div class="text-hide center-block" id="main-logo">'
                      + b'<img class="center-block img-responsive" src="/static/themes/oscar/img/logo_searx_a.png"'
                      + b' alt="searx logo" />searx</div>', result.data)

    def test_index_html_post(self):
        result = self.client.post('/', data={'q': 'test'})
        self.assertEqual(result.status_code, 308)
        self.assertEqual(result.location, 'http://localhost/search')

    def test_index_html_get(self):
        result = self.client.post('/?q=test')
        self.assertEqual(result.status_code, 308)
        self.assertEqual(result.location, 'http://localhost/search?q=test')

    def test_search_empty_html(self):
        result = self.client.post('/search', data={'q': ''})
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'<span class="instance pull-left"><a href="/">searxng</a></span>', result.data)

    def test_search_empty_json(self):
        result = self.client.post('/search', data={'q': '', 'format': 'json'})
        self.assertEqual(result.status_code, 400)

    def test_search_empty_csv(self):
        result = self.client.post('/search', data={'q': '', 'format': 'csv'})
        self.assertEqual(result.status_code, 400)

    def test_search_empty_rss(self):
        result = self.client.post('/search', data={'q': '', 'format': 'rss'})
        self.assertEqual(result.status_code, 400)

    def test_search_html(self):
        result = self.client.post('/search', data={'q': 'test'})

        self.assertIn(
            b'<h4 class="result_header" id="result-2"><img width="32" height="32" class="favicon"'
            + b' src="/static/themes/oscar/img/icons/youtube.png" alt="youtube" /><a href="http://second.test.xyz"'
            + b' rel="noreferrer" aria-labelledby="result-2">Second <span class="highlight">Test</span></a></h4>',  # noqa
            result.data
        )
        self.assertIn(
            b'<p class="result-content">second <span class="highlight">test</span> content</p>',  # noqa
            result.data
        )

    def test_index_json(self):
        result = self.client.post('/', data={'q': 'test', 'format': 'json'})
        self.assertEqual(result.status_code, 308)

    def test_search_json(self):
        result = self.client.post('/search', data={'q': 'test', 'format': 'json'})
        result_dict = result.json()

        self.assertEqual('test', result_dict['query'])
        self.assertEqual(len(result_dict['results']), 2)
        self.assertEqual(result_dict['results'][0]['content'], 'first test content')
        self.assertEqual(result_dict['results'][0]['url'], 'http://first.test.xyz')

    def test_index_csv(self):
        result = self.client.post('/', data={'q': 'test', 'format': 'csv'})
        self.assertEqual(result.status_code, 308)

    def test_search_csv(self):
        result = self.client.post('/search', data={'q': 'test', 'format': 'csv'})

        self.assertEqual(
            b'title,url,content,host,engine,score,type\r\n'
            b'First Test,http://first.test.xyz,first test content,first.test.xyz,startpage,,result\r\n'  # noqa
            b'Second Test,http://second.test.xyz,second test content,second.test.xyz,youtube,,result\r\n',  # noqa
            result.data
        )

    def test_index_rss(self):
        result = self.client.post('/', data={'q': 'test', 'format': 'rss'})
        self.assertEqual(result.status_code, 308)

    def test_search_rss(self):
        result = self.client.post('/search', data={'q': 'test', 'format': 'rss'})

        self.assertIn(
            b'<description>Search results for "test" - searx</description>',
            result.data
        )

        self.assertIn(
            b'<opensearch:totalResults>3</opensearch:totalResults>',
            result.data
        )

        self.assertIn(
            b'<title>First Test</title>',
            result.data
        )

        self.assertIn(
            b'<link>http://first.test.xyz</link>',
            result.data
        )

        self.assertIn(
            b'<description>first test content</description>',
            result.data
        )

    def test_about(self):
        result = self.client.get('/about')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'<h1>About <a href="/">searxng</a></h1>', result.data)

    def test_preferences(self):
        result = self.client.get('/preferences')
        self.assertEqual(result.status_code, 200)
        self.assertIn(
            b'<form method="post" action="/preferences" id="search_form">',
            result.data
        )
        self.assertIn(
            b'<label class="col-sm-3 col-md-2" for="categories">Default categories</label>',
            result.data
        )
        self.assertIn(
            b'<label class="col-sm-3 col-md-2" for="locale">Interface language</label>',
            result.data
        )

    def test_browser_locale(self):
        result = self.client.get('/preferences', headers={'Accept-Language': 'zh-tw;q=0.8'})
        self.assertEqual(result.status_code, 200)
        self.assertIn(
            b'<option value="zh_TW" selected="selected">',
            result.data,
            'Interface locale ignored browser preference.'
        )
        self.assertIn(
            b'<option value="zh-TW" selected="selected">',
            result.data,
            'Search language ignored browser preference.'
        )

    def test_stats(self):
        result = self.client.get('/stats')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'<h1>Engine stats</h1>', result.data)

    def test_robots_txt(self):
        result = self.client.get('/robots.txt')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'Allow: /', result.data)

    def test_opensearch_xml(self):
        result = self.client.get('/opensearch.xml')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'<Description>a privacy-respecting, hackable metasearch engine</Description>', result.data)

    def test_favicon(self):
        result = self.client.get('/favicon.ico')
        self.assertEqual(result.status_code, 200)

    def test_config(self):
        result = self.client.get('/config')
        self.assertEqual(result.status_code, 200)
        json_result = result.get_json()
        self.assertTrue(json_result)
