# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=missing-module-docstring

import threading
import os
import io
import gc
import signal

from guppy import hpy

from searx import logger


def hpy_to_str(hpy_instance, title):
    output = io.StringIO()
    heap = hpy_instance.heap()
    byrcs = heap.byrcs
    print(f'==[ {title} ]===============================', file=output)
    print('-- head --', file=output)
    print(heap, file=output)
    print('-- byrcs --', file=output)
    print(byrcs, file=output)
    for i in range(0, 10):
        print(f'-- byrcs[{i}] --', file=output)
        print(byrcs[i].byid, file=output)
    return output.getvalue()


def run():
    print(hpy_to_str(hpy(), 'before GC'))
    gc.collect()
    print(hpy_to_str(hpy(), 'after GC'))


def _signal_handler(_signum, _frame):
    logger.warning('memory dump')
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()


def initialize():
    if hasattr(signal, 'SIGUSR2'):
        # Windows doesn't support SIGUSR1
        logger.info('Send SIGUSR2 signal to pid %i to create a memory dump', os.getpid())
        signal.signal(signal.SIGUSR2, _signal_handler)
