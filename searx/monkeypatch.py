# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
"""
Allow to monkey patch code using settings.yml to lower fork maintenance.
"""

import sys
from importlib import import_module


def _get_module_by_name(module_name):
    for forbidden_module in [
        'searx.engines',
        'searx.plugins',
        'searx.webapp',
    ]:
        if module_name.startswith(forbidden_module):
            raise ValueError(f'monkey patch of module {forbidden_module} is not supported')
    if module_name not in sys.modules:
        return import_module(module_name)
    return sys.modules[module_name]


def _get_object_by_name(name):
    module_name, obj_name = name.rsplit('.', 1)
    module = _get_module_by_name(module_name)
    return getattr(module, obj_name, None)


def monkeypatch(logger, settings):
    logger = logger.getChild('monkeypatch')
    patches = []
    # update PYTHONPATH
    additional_python_path = settings['monkeypatch'].get('$PYTHONPATH')
    if additional_python_path:
        del settings['monkeypatch']['$PYTHONPATH']
        if isinstance(additional_python_path, str):
            additional_python_path = [ additional_python_path ]
        if not isinstance(additional_python_path, list):
            raise ValueError('PYTHONPATH must be string or a list')
        for path in additional_python_path:
            sys.path.append(path)
    # load modules
    for name, actual_name in settings['monkeypatch'].items():
        module_name, obj_name = name.rsplit('.', 1)
        module = _get_module_by_name(module_name)
        actual_obj = _get_object_by_name(actual_name)
        if not callable(actual_obj):
            raise ValueError(f"{actual_name} is not callable")
        patches.append((module, obj_name, actual_obj))
        type_str = actual_obj.__qualname__ if isinstance(actual_obj, type) else type(actual_obj).__qualname__
        logger.info('monkey patch "%s" with "%s" (%s)', name, actual_name, type_str)
    # apply patches
    for module, obj_name, actual_obj in patches:
        setattr(module, obj_name, actual_obj)
