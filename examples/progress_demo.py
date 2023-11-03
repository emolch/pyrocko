import logging
from time import sleep
import random
from threading import Thread

import pyrocko
from pyrocko import progress

pyrocko.app_init('info', 'terminal')

logger = logging.getLogger('main')


def main():
    with progress.view():
        counting_generator()
        counting_generator_no_len()
        counting_context_manager()
        counting_multiline_message()
        counting_fails()
        counting_nested()
        counting_multi()
        counting_threads()


def counting_generator():
    task = progress.task('counting (generator)', logger=logger)
    nitems = 50
    for iitem in task(range(nitems)):
        sleep(0.1)


def counting_generator_no_len():
    def my_range(n):
        for i in range(n):
            yield i

    task = progress.task('counting (generator, no len)', logger=logger)
    nitems = 50
    for iitem in task(my_range(nitems)):
        sleep(0.1)


def counting_context_manager():
    nitems = 50
    with progress.task(
            'counting (context manager)',
            nitems,
            logger=logger) as task:

        for iitem in range(nitems):
            if iitem > nitems // 2:
                message = 'over half already done!'
            else:
                message = None
            task.update(iitem, message)
            sleep(0.1)


def counting_multiline_message():
    nitems = 50
    with progress.task(
            'counting (multiline message)',
            nitems,
            logger=logger) as task:

        for iitem in range(nitems):
            message = '\nWe are now at %i.' % iitem
            task.update(iitem, message)
            sleep(0.1)


def counting_fails():
    nitems = 50
    with progress.task(
            'failing task',
            nitems,
            logger=logger) as task:

        try:
            for counter in task(range(nitems)):
                sleep(0.1)
                if counter == 35:
                    1 // 0

        except Exception as e:
            logger.warning('Caught an exception: %s' % e)


def counting_nested():
    task1 = progress.task('outer', logger=logger)
    for i in task1(range(5)):
        task2 = progress.task('inner %i' % i, logger=logger)
        for j in task2(range(5)):
            task3 = progress.task('inner inner %i %i' % (i, j), logger=logger)
            for k in task3(range(50)):
                sleep(0.01)


def counting_multi():
    ntasks = 4
    nitems = 30
    with progress.task('counting multi', ntasks*nitems, logger=logger) as task:
        subtasks = [
            task.task('worker %i' % itask, nitems, logger=logger)
            for itask in range(ntasks)]

        counters = [0] * ntasks
        try:
            while any(counter < nitems for counter in counters):
                for itask in range(ntasks):
                    if random.random() < 0.5:
                        if counters[itask] < nitems:
                            counters[itask] += 1
                            subtasks[itask].update(counters[itask])
                            task.update(sum(counters))

                sleep(0.1)

        except Exception:
            for subtask in subtasks:
                subtask.fail()

        finally:
            for subtask in subtasks:
                subtask.done()

        sleep(0.5)


def counting_threads():
    ntasks = 4
    nitems = 30

    def count(itask, nitems):
        with progress.task('thread %i' % itask, nitems, logger=logger) as task:
            for iitem in task(range(nitems)):
                sleep(0.1)

    threads = [
        Thread(target=count, args=[itask, nitems])
        for itask in range(ntasks)]

    for thread in threads:
        thread.start()

    while threads:
        thread = threads.pop(0)
        thread.join(0.05)
        if thread.is_alive():
            threads.append(thread)

        # calling idle() only needed for threads with
        # GUITerminalViewer which should only draw from
        # MainThread.
        progress.idle()


main()
