# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Database interface code.
'''

import sys
import os
import logging
import sqlite3
import re
import time

from pyrocko.io.io_common import FileLoadError
from pyrocko import util
from pyrocko.guts import Object, Int, List, Dict, Tuple, String
from . import error, io
from .model import Nut, to_kind_id, to_kind, to_codes_simple, \
    codes_patterns_for_kind
from .error import SquirrelError

logger = logging.getLogger('psq.database')

guts_prefix = 'squirrel'


def abspath(path):
    if not path.startswith('virtual:') and not path.startswith('client:'):
        return os.path.abspath(path)
    else:
        return path


def versiontuple(s):
    fill = [0, 0, 0]
    vals = [int(x) for x in s.split('.')]
    fill[:len(vals)] = vals
    return tuple(fill)


class ExecuteGet1Error(SquirrelError):
    pass


def execute_get1(connection, sql, args=()):
    rows = list(connection.execute(sql, args))
    if len(rows) == 1:
        return rows[0]
    else:
        raise ExecuteGet1Error('Expected database entry not found.')


g_databases = {}


def get_database(path):
    path = os.path.abspath(path)
    if path not in g_databases:
        g_databases[path] = Database(path)

    return g_databases[path]


def close_database(database):
    path = os.path.abspath(database._database_path)
    database._conn.close()
    if path in g_databases:
        del g_databases[path]


class Transaction(object):
    def __init__(
            self, conn,
            label='',
            mode='immediate',
            retry_interval=0.1,
            callback=None):

        self.cursor = conn.cursor()
        assert mode in ('deferred', 'immediate', 'exclusive')
        self.mode = mode
        self.depth = 0
        self.rollback_wanted = False
        self.retry_interval = retry_interval
        self.callback = callback
        self.label = label
        self.started = False

    def begin(self):
        if self.depth == 0:
            tries = 0
            while True:
                try:
                    tries += 1
                    self.cursor.execute('BEGIN %s' % self.mode.upper())
                    self.started = True
                    logger.debug(
                        'Transaction started:   %-30s (pid: %s, mode: %s)'
                        % (self.label, os.getpid(), self.mode))

                    self.total_changes_begin \
                        = self.cursor.connection.total_changes
                    break

                except sqlite3.OperationalError as e:
                    if not str(e) == 'database is locked':
                        raise

                    logger.info(
                        'Database is locked retrying in %s s: %s '
                        '(pid: %s, tries: %i)' % (
                            self.retry_interval, self.label,
                            os.getpid(), tries))

                    time.sleep(self.retry_interval)

        self.depth += 1

    def commit(self):
        if not self.started:
            raise Exception(
                'Trying to commit without having started a transaction.')

        self.depth -= 1
        if self.depth == 0:
            if not self.rollback_wanted:
                self.cursor.execute('COMMIT')
                self.started = False
                if self.total_changes_begin is not None:
                    total_changes = self.cursor.connection.total_changes \
                        - self.total_changes_begin
                else:
                    total_changes = None

                if self.callback is not None and total_changes:
                    self.callback('modified', total_changes)

                logger.debug(
                        'Transaction completed: %-30s '
                        '(pid: %s, changes: %i)' % (
                            self.label, os.getpid(), total_changes or 0))

            else:
                self.cursor.execute('ROLLBACK')
                self.started = False
                logger.warning('Deferred rollback executed.')
                logger.debug(
                    'Transaction failed:   %-30s (pid: %s)' % (
                        self.label, os.getpid()))
                self.rollback_wanted = False

    def rollback(self):
        if not self.started:
            raise Exception(
                'Trying to rollback without having started a transaction.')

        self.depth -= 1
        if self.depth == 0:
            self.cursor.execute('ROLLBACK')
            self.started = False

            logger.debug(
                'Transaction failed:   %-30s (pid: %s)' % (
                    self.label, os.getpid()))

            self.rollback_wanted = False
        else:
            logger.warning('Deferred rollback scheduled.')
            self.rollback_wanted = True

    def close(self):
        self.cursor.close()

    def __enter__(self):
        self.begin()
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

        if self.depth == 0:
            self.close()
            self.callback = None


class Database(object):
    '''
    Shared meta-information database used by Squirrel.
    '''

    def __init__(self, database_path=':memory:', log_statements=False):
        self._database_path = database_path
        if database_path != ':memory:':
            util.ensuredirs(database_path)

        try:
            logger.debug(
                'Opening connection to database (threadsafety: %i): %s',
                sqlite3.threadsafety,
                database_path)

            self._conn = sqlite3.connect(
                database_path,
                isolation_level=None,
                check_same_thread=False if sqlite3.threadsafety else True)

        except sqlite3.OperationalError:
            raise error.SquirrelError(
                'Cannot connect to database: %s' % database_path)

        self._conn.text_factory = str
        self._tables = {}

        if log_statements:
            self._conn.set_trace_callback(self._log_statement)

        self._listeners = []
        self._initialize_db()
        self._basepath = None

        self.version = None

    def set_basepath(self, basepath):
        if basepath is not None:
            self._basepath = os.path.abspath(basepath)
        else:
            self._basepath = None

    def relpath(self, path):
        if self._basepath is not None and path.startswith(
                self._basepath + os.path.sep):
            return path[len(self._basepath) + 1:]
        else:
            return path

    def abspath(self, path):
        if self._basepath is not None and not path.startswith('virtual:') \
                and not path.startswith('client:') \
                and not os.path.isabs(path):
            return os.path.join(self._basepath, path)
        else:
            return path

    def _log_statement(self, statement):
        logger.debug(statement)

    def get_connection(self):
        return self._conn

    def transaction(self, label='', mode='immediate'):
        return Transaction(
            self._conn,
            label=label,
            mode=mode,
            callback=self._notify_listeners)

    def add_listener(self, listener):
        listener_ref = util.smart_weakref(listener)
        self._listeners.append(listener_ref)
        return listener_ref

    def remove_listener(self, listener_ref):
        self._listeners.remove(listener_ref)

    def _notify_listeners(self, event, *args):
        dead = []
        for listener_ref in self._listeners:
            listener = listener_ref()
            if listener is not None:
                listener(event, *args)
            else:
                dead.append(listener_ref)

            for listener_ref in dead:
                self.remove_listener(listener_ref)

    def _register_table(self, s):
        m = re.search(r'(\S+)\s*\(([^)]+)\)', s)
        table_name = m.group(1)
        dtypes = m.group(2)
        table_header = []
        for dele in dtypes.split(','):
            table_header.append(dele.split()[:2])

        self._tables[table_name] = table_header

        return s

    def _initialize_db(self):
        with self.transaction('initialize') as cursor:
            cursor.execute(
                '''PRAGMA recursive_triggers = true''')

            cursor.execute(
                '''PRAGMA busy_timeout = 30000''')

            if 2 == len(list(
                    cursor.execute(
                        '''
                            SELECT name FROM sqlite_master
                                WHERE type = 'table' AND name IN (
                                    'files',
                                    'persistent')
                        '''))):

                try:
                    self.version = versiontuple(execute_get1(
                        cursor,
                        '''
                        SELECT value FROM settings
                            WHERE key == "version"
                        ''')[0])
                except sqlite3.OperationalError:
                    raise error.SquirrelError(
                        'Squirrel database in pre-release format found: %s\n'
                        'Please remove the database file and reindex.'
                        % self._database_path)

                if self.version >= (1, 1, 0):
                    raise error.SquirrelError(
                        'Squirrel database "%s" is of version %i.%i.%i which '
                        'is not supported by this version of Pyrocko. Please '
                        'upgrade the Pyrocko library.'
                        % ((self._database_path, ) + self.version))

                return

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS settings (
                        key text PRIMARY KEY,
                        value text)
                '''))

            cursor.execute(
                'INSERT OR IGNORE INTO settings VALUES ("version", "1.0")')

            self.version = execute_get1(
                cursor,
                'SELECT value FROM settings WHERE key == "version"')

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS files (
                        file_id integer PRIMARY KEY,
                        path text,
                        format text,
                        mtime float,
                        size integer)
                '''))

            cursor.execute(
                '''
                    CREATE UNIQUE INDEX IF NOT EXISTS index_files_path
                    ON files (path)
                ''')

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS nuts (
                        nut_id integer PRIMARY KEY AUTOINCREMENT,
                        file_id integer,
                        file_segment integer,
                        file_element integer,
                        kind_id integer,
                        kind_codes_id integer,
                        tmin_seconds integer,
                        tmin_offset integer,
                        tmax_seconds integer,
                        tmax_offset integer,
                        kscale integer)
                '''))

            cursor.execute(
                '''
                    CREATE UNIQUE INDEX IF NOT EXISTS index_nuts_file_element
                    ON nuts (file_id, file_segment, file_element)
                ''')

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS kind_codes (
                        kind_codes_id integer PRIMARY KEY,
                        kind_id integer,
                        codes text,
                        deltat float)
                '''))

            cursor.execute(
                '''
                    CREATE UNIQUE INDEX IF NOT EXISTS index_kind_codes
                    ON kind_codes (kind_id, codes, deltat)
                ''')

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS kind_codes_count (
                        kind_codes_id integer PRIMARY KEY,
                        count integer)
                '''))

            cursor.execute(
                '''
                    CREATE INDEX IF NOT EXISTS index_nuts_file_id
                    ON nuts (file_id)
                ''')

            cursor.execute(
                '''
                    CREATE TRIGGER IF NOT EXISTS delete_nuts_on_delete_file
                    BEFORE DELETE ON files FOR EACH ROW
                    BEGIN
                      DELETE FROM nuts where file_id == old.file_id;
                    END
                ''')

            # trigger only on size to make silent update of mtime possible
            cursor.execute(
                '''
                    CREATE TRIGGER IF NOT EXISTS delete_nuts_on_update_file
                    BEFORE UPDATE OF size ON files FOR EACH ROW
                    BEGIN
                      DELETE FROM nuts where file_id == old.file_id;
                    END
                ''')

            cursor.execute(
                '''
                    CREATE TRIGGER IF NOT EXISTS increment_kind_codes
                    BEFORE INSERT ON nuts FOR EACH ROW
                    BEGIN
                        INSERT OR IGNORE INTO kind_codes_count
                        VALUES (new.kind_codes_id, 0);
                        UPDATE kind_codes_count
                        SET count = count + 1
                        WHERE new.kind_codes_id == kind_codes_id;
                    END
                ''')

            cursor.execute(
                '''
                    CREATE TRIGGER IF NOT EXISTS decrement_kind_codes
                    BEFORE DELETE ON nuts FOR EACH ROW
                    BEGIN
                        UPDATE kind_codes_count
                        SET count = count - 1
                        WHERE old.kind_codes_id == kind_codes_id;
                    END
                ''')

            cursor.execute(self._register_table(
                '''
                    CREATE TABLE IF NOT EXISTS persistent (
                        name text UNIQUE)
                '''))

    def dig(self, nuts, transaction=None):
        '''
        Store or update content meta-information.

        Given ``nuts`` are assumed to represent an up-to-date and complete
        inventory of a set of files. Any old information about these files is
        first pruned from the database (via database triggers). If such content
        is part of a live selection, it is also removed there. Then the new
        content meta-information is inserted into the main database. The
        content is not automatically inserted into the live selections again.
        It is in the responsibility of the selection object to perform this
        step.
        '''

        nuts = list(nuts)

        if not nuts:
            return

        files = set()
        kind_codes = set()
        for nut in nuts:
            files.add((
                self.relpath(nut.file_path),
                nut.file_format,
                nut.file_mtime,
                nut.file_size))
            kind_codes.add(
                (nut.kind_id, nut.codes.safe_str, nut.deltat or 0.0))

        with (transaction or self.transaction('dig')) as c:

            c.executemany(
                'INSERT OR IGNORE INTO files VALUES (NULL,?,?,?,?)', files)

            c.executemany(
                '''UPDATE files SET
                    format = ?, mtime = ?, size = ?
                    WHERE path == ?
                ''',
                ((x[1], x[2], x[3], x[0]) for x in files))

            c.executemany(
                'INSERT OR IGNORE INTO kind_codes VALUES (NULL,?,?,?)',
                kind_codes)

            c.executemany(
                '''
                    INSERT INTO nuts VALUES
                        (NULL, (
                            SELECT file_id FROM files
                            WHERE path == ?
                         ),?,?,?,
                         (
                            SELECT kind_codes_id FROM kind_codes
                            WHERE kind_id == ? AND codes == ? AND deltat == ?
                         ), ?,?,?,?,?)
                ''',
                ((self.relpath(nut.file_path),
                  nut.file_segment, nut.file_element,
                  nut.kind_id,
                  nut.kind_id, nut.codes.safe_str, nut.deltat or 0.0,
                  nut.tmin_seconds, nut.tmin_offset,
                  nut.tmax_seconds, nut.tmax_offset,
                  nut.kscale) for nut in nuts))

    def undig(self, path):

        path = self.relpath(abspath(path))

        sql = '''
            SELECT
                files.path,
                files.format,
                files.mtime,
                files.size,
                nuts.file_segment,
                nuts.file_element,
                kind_codes.kind_id,
                kind_codes.codes,
                nuts.tmin_seconds,
                nuts.tmin_offset,
                nuts.tmax_seconds,
                nuts.tmax_offset,
                kind_codes.deltat
            FROM files
            INNER JOIN nuts ON files.file_id = nuts.file_id
            INNER JOIN kind_codes
                ON nuts.kind_codes_id == kind_codes.kind_codes_id
            WHERE path == ?
        '''

        return [Nut(values_nocheck=(self.abspath(row[0]),) + row[1:])
                for row in self._conn.execute(sql, (path,))]

    def undig_all(self):
        sql = '''
            SELECT
                files.path,
                files.format,
                files.mtime,
                files.size,
                nuts.file_segment,
                nuts.file_element,
                kind_codes.kind_id,
                kind_codes.codes,
                nuts.tmin_seconds,
                nuts.tmin_offset,
                nuts.tmax_seconds,
                nuts.tmax_offset,
                kind_codes.deltat
            FROM files
            INNER JOIN nuts ON files.file_id == nuts.file_id
            INNER JOIN kind_codes
                ON nuts.kind_codes_id == kind_codes.kind_codes_id
        '''

        nuts = []
        path = None
        for values in self._conn.execute(sql):
            if path is not None and values[0] != path:
                yield path, nuts
                nuts = []

            path = self.abspath(values[0])

            if values[1] is not None:
                nuts.append(Nut(values_nocheck=(path,) + values[1:]))

        if path is not None:
            yield path, nuts

    def undig_few(self, paths, format='detect'):
        for path in paths:
            nuts = self.undig(path)
            if nuts:
                yield (nuts[0].file_format, path), nuts
            else:
                yield (format, path), []

    def undig_many(self, paths, show_progress=True):
        selection = self.new_selection(paths, show_progress=show_progress)

        for (_, path), nuts in selection.undig_grouped():
            yield path, nuts

        del selection

    def new_selection(self, paths=None, format='detect', show_progress=True):
        from .selection import Selection
        selection = Selection(self)
        if paths:
            selection.add(paths, format=format, show_progress=show_progress)
        return selection

    def undig_content(self, nut):
        return None

    def remove(self, path):
        '''
        Prune content meta-information about a given file.

        All content pieces belonging to file ``path`` are removed from the
        main database and any attached live selections (via database triggers).
        '''

        path = self.relpath(abspath(path))

        with self.transaction('remove file') as cursor:
            cursor.execute(
                'DELETE FROM files WHERE path = ?', (path,))

    def remove_glob(self, pattern):
        '''
        Prune content meta-information about files matching given pattern.

        All content pieces belonging to files who's pathes match the given
        ``pattern`` are removed from the main database and any attached live
        selections (via database triggers).
        '''

        with self.transaction('remove file glob') as cursor:
            return cursor.execute(
                'DELETE FROM files WHERE path GLOB ?', (pattern,)).rowcount

    def _remove_volatile(self):
        '''
        Prune leftover volatile content from database.

        If the cleanup handler of an attached selection is not called, e.g. due
        to a crash or terminated process, volatile content will not be removed
        properly. This method will delete such leftover entries.

        This is a mainenance operatation which should only be called when no
        apps are using the database because it would remove volatile content
        currently used by the apps.
        '''

        with self.transaction('remove volatile') as cursor:
            return cursor.execute(
                '''
                    DELETE FROM files
                    WHERE path LIKE 'virtual:volatile:%'
                ''').rowcount

    def reset(self, path, transaction=None):
        '''
        Prune information associated with a given file, but keep the file path.

        This method is called when reading a file failed. File attributes,
        format, size and modification time are set to NULL. File content
        meta-information is removed from the database and any attached live
        selections (via database triggers).
        '''

        path = self.relpath(abspath(path))

        with (transaction or self.transaction('reset file')) as cursor:
            cursor.execute(
                '''
                    UPDATE files SET
                        format = NULL,
                        mtime = NULL,
                        size = NULL
                    WHERE path = ?
                ''', (path,))

    def silent_touch(self, path):
        '''
        Update modification time of file without initiating reindexing.

        Useful to prolong validity period of data with expiration date.
        '''

        apath = abspath(path)
        path = self.relpath(apath)

        with self.transaction('silent touch') as cursor:

            sql = 'SELECT format, size FROM files WHERE path = ?'
            fmt, size = execute_get1(cursor, sql, (path,))

            mod = io.get_backend(fmt)
            mod.touch(apath)
            file_stats = mod.get_stats(apath)

            if file_stats[1] != size:
                raise FileLoadError(
                    'Silent update for file "%s" failed: size has changed.'
                    % apath)

            sql = '''
                UPDATE files
                SET mtime = ?
                WHERE path = ?
            '''
            cursor.execute(sql, (file_stats[0], path))

    def _iter_codes_info(
            self, kind=None, codes=None, kind_codes_count='kind_codes_count'):

        args = []
        sel = ''
        if kind is not None:
            kind_id = to_kind_id(kind)

            sel = 'AND kind_codes.kind_id == ?'
            args.append(to_kind_id(kind))

        if codes is not None:
            assert kind is not None   # TODO supp by recursing possible kinds
            kind_id = to_kind_id(kind)
            pats = codes_patterns_for_kind(kind_id, codes)

            if pats:
                # could optimize this by using IN for non-patterns
                sel += ' AND ( %s ) ' % ' OR '.join(
                    ('kind_codes.codes GLOB ?',) * len(pats))

                args.extend(pat.safe_str for pat in pats)

        sql = ('''
            SELECT
                kind_codes.kind_id,
                kind_codes.codes,
                kind_codes.deltat,
                kind_codes.kind_codes_id,
                %(kind_codes_count)s.count
            FROM %(kind_codes_count)s
            INNER JOIN kind_codes
                ON %(kind_codes_count)s.kind_codes_id
                    == kind_codes.kind_codes_id
            WHERE %(kind_codes_count)s.count > 0
                ''' + sel + '''
        ''') % {'kind_codes_count': kind_codes_count}

        for kind_id, scodes, deltat, kcid, count in self._conn.execute(
                sql, args):

            yield (
                kind_id, to_codes_simple(kind_id, scodes), deltat, kcid, count)

    def _iter_deltats(self, kind=None, kind_codes_count='kind_codes_count'):
        args = []
        sel = ''
        if kind is not None:
            assert isinstance(kind, str)
            sel = 'AND kind_codes.kind_id == ?'
            args.append(to_kind_id(kind))

        sql = ('''
            SELECT DISTINCT kind_codes.deltat FROM %(kind_codes_count)s
            INNER JOIN kind_codes
                ON %(kind_codes_count)s.kind_codes_id
                    == kind_codes.kind_codes_id
            WHERE %(kind_codes_count)s.count > 0
                ''' + sel + '''
            ORDER BY kind_codes.deltat
        ''') % {'kind_codes_count': kind_codes_count}

        for row in self._conn.execute(sql, args):
            yield row[0]

    def _iter_codes(self, kind=None, kind_codes_count='kind_codes_count'):
        args = []
        sel = ''
        if kind is not None:
            assert isinstance(kind, str)
            sel = 'AND kind_codes.kind_id == ?'
            args.append(to_kind_id(kind))

        sql = ('''
            SELECT DISTINCT kind_codes.kind_id, kind_codes.codes
            FROM %(kind_codes_count)s
            INNER JOIN kind_codes
                ON %(kind_codes_count)s.kind_codes_id
                    == kind_codes.kind_codes_id
            WHERE %(kind_codes_count)s.count > 0
                ''' + sel + '''
            ORDER BY kind_codes.codes

        ''') % dict(kind_codes_count=kind_codes_count)

        for row in self._conn.execute(sql, args):
            yield to_codes_simple(*row)

    def _iter_kinds(self, codes=None, kind_codes_count='kind_codes_count'):
        args = []
        sel = ''
        if codes is not None:
            sel = 'AND kind_codes.codes == ?'
            args.append(codes.safe_str)

        sql = ('''
            SELECT DISTINCT kind_codes.kind_id FROM %(kind_codes_count)s
            INNER JOIN kind_codes
                ON %(kind_codes_count)s.kind_codes_id
                    == kind_codes.kind_codes_id
            WHERE %(kind_codes_count)s.count > 0
                ''' + sel + '''
            ORDER BY kind_codes.kind_id
        ''') % {'kind_codes_count': kind_codes_count}

        for row in self._conn.execute(sql, args):
            yield to_kind(row[0])

    def iter_paths(self):
        for row in self._conn.execute('''SELECT path FROM files'''):
            yield self.abspath(row[0])

    def iter_nnuts_by_file(self):
        sql = '''
            SELECT
                path,
                (SELECT COUNT(*) FROM nuts WHERE nuts.file_id = files.file_id)
            FROM files
        '''
        for row in self._conn.execute(sql):
            yield (self.abspath(row[0]),) + row[1:]

    def iter_kinds(self, codes=None):
        return self._iter_kinds(codes=codes)

    def iter_codes(self, kind=None):
        return self._iter_codes(kind=kind)

    def get_paths(self):
        return list(self.iter_paths())

    def get_kinds(self, codes=None):
        return list(self.iter_kinds(codes=codes))

    def get_codes(self, kind=None):
        return list(self.iter_codes(kind=kind))

    def get_counts(self, kind=None):
        d = {}
        for kind_id, codes, _, _, count in self._iter_codes_info(kind=kind):
            if kind_id not in d:
                v = d[kind_id] = {}
            else:
                v = d[kind_id]

            if codes not in v:
                v[codes] = 0

            v[codes] += count

        if kind is not None:
            return d[to_kind_id(kind)]
        else:
            return dict((to_kind(kind_id), v) for (kind_id, v) in d.items())

    def get_nfiles(self):
        sql = '''SELECT COUNT(*) FROM files'''
        for row in self._conn.execute(sql):
            return row[0]

    def get_nnuts(self):
        sql = '''SELECT COUNT(*) FROM nuts'''
        for row in self._conn.execute(sql):
            return row[0]

    def get_nnuts_by_file(self):
        return list(self.iter_nnuts_by_file())

    def get_total_size(self):
        sql = '''
            SELECT SUM(files.size) FROM files
        '''

        for row in self._conn.execute(sql):
            return row[0] or 0

    def get_persistent_names(self):
        sql = '''
            SELECT name FROM persistent
        '''
        return [row[0] for row in self._conn.execute(sql)]

    def get_stats(self):
        return DatabaseStats(
            nfiles=self.get_nfiles(),
            nnuts=self.get_nnuts(),
            kinds=self.get_kinds(),
            codes=self.get_codes(),
            counts=self.get_counts(),
            total_size=self.get_total_size(),
            persistent=self.get_persistent_names())

    def __str__(self):
        return str(self.get_stats())

    def print_tables(self, stream=None):
        for table in [
                'persistent',
                'files',
                'nuts',
                'kind_codes',
                'kind_codes_count']:

            self.print_table(table, stream=stream)

    def print_table(self, name, stream=None):

        if stream is None:
            stream = sys.stdout

        class hstr(str):
            def __repr__(self):
                return self

        w = stream.write
        w('\n')
        w('\n')
        w(name)
        w('\n')
        sql = 'SELECT * FROM %s' % name
        tab = []
        if name in self._tables:
            headers = self._tables[name]
            tab.append([None for _ in headers])
            tab.append([hstr(x[0]) for x in headers])
            tab.append([hstr(x[1]) for x in headers])
            tab.append([None for _ in headers])

        for row in self._conn.execute(sql):
            tab.append([x for x in row])

        widths = [
            max((len(repr(x)) if x is not None else 0) for x in col)
            for col in zip(*tab)]

        for row in tab:
            w(' '.join(
                (repr(x).ljust(wid) if x is not None else ''.ljust(wid, '-'))
                for (x, wid) in zip(row, widths)))

            w('\n')

        w('\n')


class DatabaseStats(Object):
    '''
    Container to hold statistics about contents cached in meta-information db.
    '''

    nfiles = Int.T(
        help='Number of files in database.')
    nnuts = Int.T(
        help='Number of index nuts in database.')
    codes = List.T(
        Tuple.T(content_t=String.T()),
        help='Available code sequences in database, e.g. '
             '(agency, network, station, location) for stations nuts.')
    kinds = List.T(
        String.T(),
        help='Available content types in database.')
    total_size = Int.T(
        help='Aggregated file size [bytes] of files referenced in database.')
    counts = Dict.T(
        String.T(), Dict.T(Tuple.T(content_t=String.T()), Int.T()),
        help='Breakdown of how many nuts of any content type and code '
             'sequence are available in database, ``counts[kind][codes]``.')
    persistent = List.T(
        String.T(),
        help='Names of persistent selections stored in database.')

    def __str__(self):
        kind_counts = dict(
            (kind, sum(self.counts[kind].values())) for kind in self.kinds)

        codes = [c.safe_str for c in self.codes]

        if len(codes) > 20:
            scodes = '\n' + util.ewrap(codes[:10], indent='  ') \
                + '\n  [%i more]\n' % (len(codes) - 20) \
                + util.ewrap(codes[-10:], indent='  ')
        else:
            scodes = '\n' + util.ewrap(codes, indent='  ') \
                if codes else '<none>'

        s = '''
Available codes:               %s
Number of files:               %i
Total size of known files:     %s
Number of index nuts:          %i
Available content kinds:       %s
Persistent selections:         %s''' % (
            scodes,
            self.nfiles,
            util.human_bytesize(self.total_size),
            self.nnuts,
            ', '.join('%s: %i' % (
                kind, kind_counts[kind]) for kind in sorted(self.kinds)),
            ', '.join(self.persistent))

        return s


__all__ = [
    'Database',
    'DatabaseStats',
]
