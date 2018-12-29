import pytest

import pydantic


@pytest.mark.xfail('sys.version_info < (3, 7)', raises=SyntaxError)
@pytest.mark.xfail('sys.version_info >= (3, 7)', raises=RuntimeError, reason='annotations are strings...')
def test_py37_annotations(working_dir):
    module = working_dir.inline_module(
        r"""
        from __future__ import annotations

        from typing import Mapping, MutableMapping, TypeVar, Generic

        from pydantic import BaseModel, constr

        _T = TypeVar("_T")
        CustomKey = constr(regex=r"^([\w][\w\d]*)$")


        class CustomValue(BaseModel, Generic[_T]):
            alias: CustomKey = ...
            value: _T = None


        class CustomMapping(BaseModel, MutableMapping[CustomKey, CustomValue]):
            alias: CustomKey = ...
            another_property: str = None
            _mapping: Mapping[CustomKey, CustomValue] = {}

            def __getitem__(self, key):
                return self._mapping[key]

            def __setitem__(self, key, value):
                self._mapping[key] = value

            def __delitem__(self, key):
                del self._mapping[key]

            def __iter__(self):
                return iter(self._mapping)

            def __len__(self):
                return len(self._mapping)
        """
    )
    assert module
    assert module.BaseModel is pydantic.BaseModel
    assert issubclass(module.CustomValue, pydantic.BaseModel)
    assert issubclass(module.CustomMapping, pydantic.BaseModel)


@pytest.mark.xfail(raises=RuntimeError, reason='Unsupported FutureRef')
def test_future_ref(working_dir):
    module = working_dir.inline_module(
        """
        from pydantic import BaseModel


        class Model(BaseModel):
            name: str = ...
            value: 'Model' = None
        """
    )

    assert module
    assert module.BaseModel is pydantic.BaseModel
    assert issubclass(module.Model, pydantic.BaseModel)

    m = module.Model(name='test')
    assert m.name == 'test'

    v = module.Model(name='test2', value=m)
    assert v.name == 'test2'
    assert v.value is m

    assert v.dict() == {'name': 'test2', 'value': {'name': 'test'}}
