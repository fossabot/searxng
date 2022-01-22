from searx import settings
from searx.engines import unregister_engine, engines
from searx.network import get_network


def iter_engine(settings_engines):
    for engine_spec in settings_engines:
        engine_name = engine_spec['name']
        engine = engines.get(engine_name)
        if engine is None:
            continue
        yield engine


def if_no_tor_del_onion_engines(settings_engines):
    for engine in iter_engine(settings_engines):
        # unregister onion engine without tor
        if 'onions' in engine.categories and not get_network(engine.name).using_tor_proxy:
            engine.logger.warning('Unregistered (the engine requires a tor proxy)')
            unregister_engine(engine)


def configure_settings(settings_engines):
    for engine in iter_engine(settings_engines):
        # exclude onion engines if not using tor
        if get_network(engine.name).using_tor_proxy and hasattr(engine, 'onion_url'):
            engine.search_url = engine.onion_url + getattr(engine, 'search_path', '')
            engine.timeout += settings['outgoing'].get('extra_proxy_timeout', 0)
            engine.logger.debug('search_url=%s', engine.search_url)


def initialize_tor_engines(settings_engines):
    if_no_tor_del_onion_engines(settings_engines)
    configure_settings(settings_engines)
