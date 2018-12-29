import hashlib
import importlib
import importlib.util
import operator
import os
import pathlib
import sys
import textwrap
from typing import Iterable

import pytest
from _pytest.fixtures import FixtureRequest
from _pytest.tmpdir import TempPathFactory


@pytest.fixture
def working_dir(request, tmp_path_factory):
    """
    A helper fixture that provides a temporary working directory for an executing test
    that is automatically cleaned up when each test is finalized. Prior to executing the
    test, takes a snapshot of the `os.getcwd()`, `os.environ`, `sys.path`, `sys.meta_path`,
    and `sys.modules` which is also restored upon finalization.
    """
    return WorkingDir(request, tmp_path_factory)


def pipe(obj, *series):
    """Pipe an object through a series of functions."""
    for func in series:
        obj = func(obj)

    return obj


def prepare_text(obj, encoding='utf-8', dedent=True):
    dedent = textwrap.dedent if dedent else lambda x: x

    def to_text(s):
        return str(s, encoding) if isinstance(s, (bytes, bytearray)) else str(s)

    def to_body(s):
        return os.linesep.join(map(to_text, s)).strip() + os.linesep

    chain = []

    if not isinstance(obj, Iterable) or isinstance(obj, (str, bytes, bytearray)):
        chain.extend([to_text, dedent, operator.methodcaller('splitlines')])

    chain.append(to_body)

    if encoding:
        chain.append(operator.methodcaller('encode', encoding))

    return pipe(obj, *chain)


class WorkingDir:
    __slots__ = (
        'request',
        'name',
        'tmpdir',
        '__os_cwd_snapshot',
        '__os_environ_snapshot',
        '__sys_path_snapshot',
        '__sys_meta_path_snapshot',
        '__sys_modules_snapshot',
    )

    def __init__(self, request: FixtureRequest, tmp_path_factory: TempPathFactory):
        self.request = request
        self.name = request.function.__name__
        self.tmpdir: pathlib.Path = tmp_path_factory.mktemp(self.name, numbered=True).resolve()
        self.__snapshot()
        self.chdir()

    def __snapshot(self):
        self.__os_cwd_snapshot = os.getcwd()
        self.__os_environ_snapshot = dict(os.environ)
        self.__sys_path_snapshot = list(sys.path)
        self.__sys_meta_path_snapshot = list(sys.meta_path)
        self.__sys_modules_snapshot = dict(sys.modules)
        self.request.addfinalizer(self.__restore)

    def __restore(self):
        sys.modules.clear()
        sys.modules.update(self.__sys_modules_snapshot)
        sys.meta_path[:] = sys.meta_path
        sys.path[:] = sys.path
        os.environ.clear()
        os.environ.update(self.__os_environ_snapshot)
        os.chdir(self.__os_cwd_snapshot)

    def _makefile(self, ext, args, kwargs, root=None, encoding='utf-8', dedent=True, parent=None):
        root = root or self.name
        parent = parent or self.tmpdir
        items = list(kwargs.items())

        if args:
            items.insert(0, (root, args))

        rv = None
        for name, value in items:
            path = parent.joinpath(name).with_suffix(ext)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=False)  # we should have a fresh fs for every test run
            path.write_bytes(prepare_text(value, encoding, dedent))

            if rv is None:
                rv = path

        return rv

    def __repr__(self):
        return '<TestDir %r>' % (self.tmpdir,)

    def __str__(self):
        return str(self.tmpdir)

    def __fspath__(self):
        return os.fspath(self.tmpdir)

    def chdir(self):
        """
        Change the current working directory to the test directory. This is reverted when
        the test is finalized. This is called automatically upon instantiation.
        """
        os.chdir(os.fspath(self))

    def makefile(self, ext, *args, **kwargs):
        """Create new file(s) in the temporary test directory.

        Contents are de-dented and encoded via utf-8 before writing.

        :param str ext: The extension should include the period, e.g., `.py`.
        :param * args: All args will be treated as strings and joined using the os line separator.
            The result will be written as contents to the file. The name of the file will be based on the
            test function requesting this fixture.
        :param * kwargs: Each keyword is the base name of a file, while the value of it will be written as
            the contents of the file.
        :return: The path of the first file written.

        Examples:

        .. code-block:: python

            testdir.makefile('.txt', 'line1', 'line2')

            testdir.makefile('.ini', pytest='[pytest]\naddopts=-rs\n')

        """
        return self._makefile(ext, args, kwargs)

    def makepyfile(self, *args, **kwargs):
        """Shortcut method for `.makefile()` for the `.py` extension."""
        return self._makefile('.py', args, kwargs)

    def maketxtfile(self, *args, **kwargs):
        """Shortcut method for `.makefile()` for the `.txt` extension."""
        return self._makefile('.txt', args, kwargs)

    def syspathinsert(self, path=None):
        """Prepend a directory to `sys.path`; defaults to `self.tmpdir` if not provided.

        This is automatically undone when the object is finalized at the end of each test.
        """
        if path is None:
            path = self.tmpdir

        sys.path.insert(0, str(path))
        importlib.invalidate_caches()

    def pypackage(self, name, *args, **kwargs):
        """
        Create a python package with `name`, i.e., ensure an __init__.py file exists.

        Any positional arguments are forwarded along to `makepyfile` as the contents of `__init__.py`.

        Any keyword arguments are forwarded along to `makepyfile` as children of the new package.
        """
        module = self.tmpdir / name / '__init__.py'
        module.parent.mkdir(parents=True, exist_ok=True)
        self._makefile('.py', args, kwargs, root='__init__', parent=module.parent)
        module.touch(exist_ok=bool(args))
        return module

    def inline_module(self, source):
        """Save the contents of `source` as a python module, immediately import it, and return it."""
        source = prepare_text(source)
        fingerprint = hashlib.sha224(source).hexdigest()
        path = self.tmpdir.joinpath(fingerprint).with_suffix('.py')
        path.write_bytes(source)
        name = f'mem:{fingerprint}'

        # I am specifically not handling any exceptions that may occur from this block so
        # that I may test for SyntaxErrors
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        sys.modules[name] = module
        return module
