# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
"""Semantic Scholar (Science)
"""

from json import dumps, loads
from datetime import datetime

about = {
    "website": 'https://www.semanticscholar.org/',
    "wikidata_id": 'Q22908627',
    "official_api_documentation": 'https://api.semanticscholar.org/',
    "use_official_api": True,
    "require_api_key": False,
    "results": 'JSON',
}

categories = ['science', 'scientific publications']
paging = True
search_url = 'https://www.semanticscholar.org/api/1/search'
paper_url = 'https://www.semanticscholar.org/paper'


def request(query, params):
    params['url'] = search_url
    params['method'] = 'POST'
    params['headers']['content-type'] = 'application/json'
    params['data'] = dumps(
        {
            "queryString": query,
            "page": params['pageno'],
            "pageSize": 10,
            "sort": "relevance",
            "useFallbackRankerService": False,
            "useFallbackSearchCluster": False,
            "getQuerySuggestions": False,
            "authors": [],
            "coAuthors": [],
            "venues": [],
            "performTitleMatch": True,
        }
    )
    return params


def response(resp):
    res = loads(resp.text)
    results = []

    for result in res['results']:
        url = result.get('primaryPaperLink', {}).get('url')
        if not url and result.get('links'):
            url = result.get('links')[0]
        if not url:
            alternatePaperLinks = result.get('alternatePaperLinks')
            if alternatePaperLinks:
                url = alternatePaperLinks[0].get('url')
        if not url:
            url = paper_url + '/%s' % result['id']

        # fields = result.get('fieldsOfStudy')
        # venue = result.get('venue', {}).get('text')
        # if venue:
        #     metadata.append(venue)
        # if metadata:
        #     item['metadata'] = ', '.join(metadata)

        # publishedDate
        if 'pubDate' in result:
            publishedDate = datetime.strptime(result['pubDate'], "%Y-%m-%d")
        else:
            publishedDate = None

        # authors
        authors = [author[0]['name'] for author in result.get('authors', [])]

        results.append(
            {
                'template': 'paper.html',
                'url': url,
                'title': result['title']['text'],
                'content': result['paperAbstract']['text'],
                'journal': result.get('journal', {}).get('name'),
                'doi': result.get('doiInfo', {}).get('doi'),
                'authors': authors,
                'publishedDate': publishedDate,
            }
        )

    return results
