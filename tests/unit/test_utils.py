import asyncio
import io
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pytest
from aiofiles.os import mkdir

from apify._utils import (
    _budget_ow,
    _fetch_and_parse_env_var,
    _filter_out_none_values_recursively,
    _filter_out_none_values_recursively_internal,
    _force_remove,
    _force_rename,
    _get_cpu_usage_percent,
    _get_memory_usage_bytes,
    _guess_file_extension,
    _is_content_type_json,
    _is_content_type_text,
    _is_content_type_xml,
    _is_file_or_bytes,
    _json_dumps,
    _maybe_extract_enum_member_value,
    _maybe_parse_bool,
    _maybe_parse_datetime,
    _maybe_parse_int,
    _parse_date_fields,
    _raise_on_duplicate_storage,
    _raise_on_non_existing_storage,
    _run_func_at_interval_async,
    _unique_key_to_request_id,
    ignore_docs,
)
from apify.consts import ApifyEnvVars, _StorageTypes


def test__fetch_and_parse_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ApifyEnvVars.IS_AT_HOME, 'True')
    monkeypatch.setenv(ApifyEnvVars.MEMORY_MBYTES, '1024')
    monkeypatch.setenv(ApifyEnvVars.META_ORIGIN, 'API')
    monkeypatch.setenv(ApifyEnvVars.STARTED_AT, '2022-12-02T15:19:34.907Z')
    monkeypatch.setenv('DUMMY_BOOL', '1')
    monkeypatch.setenv('DUMMY_DATETIME', '2022-12-02T15:19:34.907Z')
    monkeypatch.setenv('DUMMY_INT', '1')
    monkeypatch.setenv('DUMMY_STRING', 'DUMMY')

    assert _fetch_and_parse_env_var(ApifyEnvVars.IS_AT_HOME) is True
    assert _fetch_and_parse_env_var(ApifyEnvVars.MEMORY_MBYTES) == 1024
    assert _fetch_and_parse_env_var(ApifyEnvVars.META_ORIGIN) == 'API'
    assert _fetch_and_parse_env_var(ApifyEnvVars.STARTED_AT) == \
        datetime(2022, 12, 2, 15, 19, 34, 907000, tzinfo=timezone.utc)

    assert _fetch_and_parse_env_var('DUMMY_BOOL') == '1'  # type: ignore
    assert _fetch_and_parse_env_var('DUMMY_DATETIME') == '2022-12-02T15:19:34.907Z'  # type: ignore
    assert _fetch_and_parse_env_var('DUMMY_INT') == '1'  # type: ignore
    assert _fetch_and_parse_env_var('DUMMY_STRING') == 'DUMMY'  # type: ignore
    assert _fetch_and_parse_env_var('NONEXISTENT_ENV_VAR') is None  # type: ignore
    assert _fetch_and_parse_env_var('NONEXISTENT_ENV_VAR', 'default') == 'default'  # type: ignore


def test__get_cpu_usage_percent() -> None:
    assert _get_cpu_usage_percent() >= 0
    assert _get_cpu_usage_percent() <= 100


def test__get_memory_usage_bytes() -> None:
    assert _get_memory_usage_bytes() >= 0
    assert _get_memory_usage_bytes() <= 1024 * 1024 * 1024 * 1024


def test__maybe_extract_enum_member_value() -> None:
    class TestEnum(Enum):
        A = 'A'
        B = 'B'

    assert _maybe_extract_enum_member_value(TestEnum.A) == 'A'
    assert _maybe_extract_enum_member_value(TestEnum.B) == 'B'
    assert _maybe_extract_enum_member_value('C') == 'C'
    assert _maybe_extract_enum_member_value(1) == 1
    assert _maybe_extract_enum_member_value(None) is None


def test__maybe_parse_bool() -> None:
    assert _maybe_parse_bool('True') is True
    assert _maybe_parse_bool('true') is True
    assert _maybe_parse_bool('1') is True
    assert _maybe_parse_bool('False') is False
    assert _maybe_parse_bool('false') is False
    assert _maybe_parse_bool('0') is False
    assert _maybe_parse_bool(None) is False
    assert _maybe_parse_bool('bflmpsvz') is False


def test__maybe_parse_datetime() -> None:
    assert _maybe_parse_datetime('2022-12-02T15:19:34.907Z') == \
        datetime(2022, 12, 2, 15, 19, 34, 907000, tzinfo=timezone.utc)
    assert _maybe_parse_datetime('2022-12-02T15:19:34.907') == '2022-12-02T15:19:34.907'
    assert _maybe_parse_datetime('anything') == 'anything'


def test__maybe_parse_int() -> None:
    assert _maybe_parse_int('0') == 0
    assert _maybe_parse_int('1') == 1
    assert _maybe_parse_int('-1') == -1
    assert _maybe_parse_int('136749825') == 136749825
    assert _maybe_parse_int('') is None
    assert _maybe_parse_int('abcd') is None


async def test__run_func_at_interval_async__sync_function() -> None:
    # Test that it works with a synchronous functions
    interval = 1.0
    initial_delay = 0.5
    increments = 3

    test_var = 0

    def sync_increment() -> None:
        nonlocal test_var
        test_var += 1

    started_at = time.perf_counter()
    sync_increment_task = asyncio.create_task(_run_func_at_interval_async(sync_increment, interval))

    try:
        await asyncio.sleep(initial_delay)

        for i in range(increments):
            assert test_var == i

            now = time.perf_counter()
            sleep_until = started_at + initial_delay + (i + 1) * interval
            sleep_for_secs = sleep_until - now
            await asyncio.sleep(sleep_for_secs)

        assert test_var == increments
    finally:
        sync_increment_task.cancel()
        try:
            await sync_increment_task
        except asyncio.CancelledError:
            pass

    await asyncio.sleep(1.5)
    assert test_var == increments


async def test__run_func_at_interval_async_async__function() -> None:
    # Test that it works with an asynchronous functions
    interval = 1.0
    initial_delay = 0.5
    increments = 3

    test_var = 0

    async def async_increment() -> None:
        nonlocal test_var
        await asyncio.sleep(0.1)
        test_var += 1

    started_at = time.perf_counter()
    async_increment_task = asyncio.create_task(_run_func_at_interval_async(async_increment, interval))

    try:
        await asyncio.sleep(initial_delay)

        for i in range(increments):
            assert test_var == i

            now = time.perf_counter()
            sleep_until = started_at + initial_delay + (i + 1) * interval
            sleep_for_secs = sleep_until - now
            await asyncio.sleep(sleep_for_secs)

        assert test_var == increments
    finally:
        async_increment_task.cancel()
        try:
            await async_increment_task
        except asyncio.CancelledError:
            pass

    await asyncio.sleep(1.5)
    assert test_var == increments


def test__filter_out_none_values_recursively() -> None:  # Copypasted from client
    assert _filter_out_none_values_recursively({'k1': 'v1'}) == {'k1': 'v1'}
    assert _filter_out_none_values_recursively({'k1': None}) == {}
    assert _filter_out_none_values_recursively({'k1': 'v1', 'k2': None, 'k3': {'k4': 'v4', 'k5': None}, 'k6': {'k7': None}}) \
        == {'k1': 'v1', 'k3': {'k4': 'v4'}}


def test__filter_out_none_values_recursively_internal() -> None:  # Copypasted from client
    assert _filter_out_none_values_recursively_internal({}) == {}
    assert _filter_out_none_values_recursively_internal({'k1': {}}) == {}
    assert _filter_out_none_values_recursively_internal({}, False) == {}
    assert _filter_out_none_values_recursively_internal({'k1': {}}, False) == {'k1': {}}
    assert _filter_out_none_values_recursively_internal({}, True) is None
    assert _filter_out_none_values_recursively_internal({'k1': {}}, True) is None


def test__is_content_type_json() -> None:  # Copypasted from client
    # returns True for the right content types
    assert _is_content_type_json('application/json') is True
    assert _is_content_type_json('application/jsonc') is True
    # returns False for bad content types
    assert _is_content_type_json('application/xml') is False
    assert _is_content_type_json('application/ld+json') is False


def test__is_content_type_xml() -> None:  # Copypasted from client
    # returns True for the right content types
    assert _is_content_type_xml('application/xml') is True
    assert _is_content_type_xml('application/xhtml+xml') is True
    # returns False for bad content types
    assert _is_content_type_xml('application/json') is False
    assert _is_content_type_xml('text/html') is False


def test__is_content_type_text() -> None:  # Copypasted from client
    # returns True for the right content types
    assert _is_content_type_text('text/html') is True
    assert _is_content_type_text('text/plain') is True
    # returns False for bad content types
    assert _is_content_type_text('application/json') is False
    assert _is_content_type_text('application/text') is False


def test__is_file_or_bytes() -> None:  # Copypasted from client
    # returns True for the right value types
    assert _is_file_or_bytes(b'abc') is True
    assert _is_file_or_bytes(bytearray.fromhex('F0F1F2')) is True
    assert _is_file_or_bytes(io.BytesIO(b'\x00\x01\x02')) is True

    # returns False for bad value types
    assert _is_file_or_bytes('abc') is False
    assert _is_file_or_bytes(['a', 'b', 'c']) is False
    assert _is_file_or_bytes({'a': 'b'}) is False
    assert _is_file_or_bytes(None) is False


async def test__force_remove(tmp_path: Path) -> None:
    test_file_path = os.path.join(tmp_path, 'test.txt')
    # Does not crash/raise when the file does not exist
    assert os.path.exists(test_file_path) is False
    await _force_remove(test_file_path)
    assert os.path.exists(test_file_path) is False

    # Removes the file if it exists
    open(test_file_path, 'a', encoding='utf-8').close()
    assert os.path.exists(test_file_path) is True
    await _force_remove(test_file_path)
    assert os.path.exists(test_file_path) is False


def test__raise_on_non_existing_storage() -> None:
    with pytest.raises(ValueError, match='Dataset with id "kckxQw6j6AtrgyA09" does not exist.'):
        _raise_on_non_existing_storage(_StorageTypes.DATASET, 'kckxQw6j6AtrgyA09')


def test__raise_on_duplicate_storage() -> None:
    with pytest.raises(ValueError, match='Dataset with name "test" already exists.'):
        _raise_on_duplicate_storage(_StorageTypes.DATASET, 'name', 'test')


def test__guess_file_extension() -> None:
    # Can guess common types properly
    assert _guess_file_extension('application/json') == 'json'
    assert _guess_file_extension('application/xml') == 'xml'
    assert _guess_file_extension('text/plain') == 'txt'

    # Can handle unusual formats
    assert _guess_file_extension(' application/json ') == 'json'
    assert _guess_file_extension('APPLICATION/JSON') == 'json'
    assert _guess_file_extension('application/json;charset=utf-8') == 'json'

    # Returns None for non-existent content types
    assert _guess_file_extension('clearly not a content type') is None
    assert _guess_file_extension('') is None


def test__json_dumps() -> None:
    expected = """{
  "string": "123",
  "number": 456,
  "nested": {
    "abc": "def"
  },
  "datetime": "2022-01-01 00:00:00+00:00"
}"""
    actual = _json_dumps({
        'string': '123',
        'number': 456,
        'nested': {
            'abc': 'def',
        },
        'datetime': datetime(2022, 1, 1, tzinfo=timezone.utc),
    })
    assert actual == expected


def test__unique_key_to_request_id() -> None:
    # Right side from `uniqueKeyToRequestId` in Crawlee
    assert _unique_key_to_request_id('abc') == 'ungWv48BzpBQUDe'
    assert _unique_key_to_request_id('test') == 'n4bQgYhMfWWaLqg'


async def test__force_rename(tmp_path: Path) -> None:
    src_dir = os.path.join(tmp_path, 'src')
    dst_dir = os.path.join(tmp_path, 'dst')
    src_file = os.path.join(src_dir, 'src_dir.txt')
    dst_file = os.path.join(dst_dir, 'dst_dir.txt')
    # Won't crash if source directory does not exist
    assert os.path.exists(src_dir) is False
    await _force_rename(src_dir, dst_dir)

    # Will remove dst_dir if it exists (also covers normal case)
    # Create the src_dir with a file in it
    await mkdir(src_dir)
    open(src_file, 'a', encoding='utf-8').close()
    # Create the dst_dir with a file in it
    await mkdir(dst_dir)
    open(dst_file, 'a', encoding='utf-8').close()
    assert os.path.exists(src_file) is True
    assert os.path.exists(dst_file) is True
    await _force_rename(src_dir, dst_dir)
    assert os.path.exists(src_dir) is False
    assert os.path.exists(dst_file) is False
    # src_dir.txt should exist in dst_dir
    assert os.path.exists(os.path.join(dst_dir, 'src_dir.txt')) is True


def test__budget_ow() -> None:
    _budget_ow({
        'a': 123,
        'b': 'string',
        'c': datetime.now(timezone.utc),
    }, {
        'a': (int, True),
        'b': (str, False),
        'c': (datetime, True),
    })
    with pytest.raises(ValueError, match='required'):
        _budget_ow({}, {'id': (str, True)})
    with pytest.raises(ValueError, match='must be of type'):
        _budget_ow({'id': 123}, {'id': (str, True)})
    # Check if subclasses pass the check
    _budget_ow({
        'ordered_dict': OrderedDict(),
    }, {
        'ordered_dict': (dict, False),
    })


def test__parse_date_fields() -> None:
    # works correctly on empty dicts
    assert _parse_date_fields({}) == {}

    # correctly parses dates on fields ending with -At
    expected_datetime = datetime(2016, 11, 14, 11, 10, 52, 425000, timezone.utc)
    assert _parse_date_fields({'createdAt': '2016-11-14T11:10:52.425Z'}) == {'createdAt': expected_datetime}

    # doesn't parse dates on fields not ending with -At
    assert _parse_date_fields({'saveUntil': '2016-11-14T11:10:52.425Z'}) == {'saveUntil': '2016-11-14T11:10:52.425Z'}

    # parses dates in dicts in lists
    expected_datetime = datetime(2016, 11, 14, 11, 10, 52, 425000, timezone.utc)
    assert _parse_date_fields([{'createdAt': '2016-11-14T11:10:52.425Z'}]) == [{'createdAt': expected_datetime}]

    # parses nested dates
    expected_datetime = datetime(2020, 2, 29, 10, 9, 8, 100000, timezone.utc)
    assert _parse_date_fields({'a': {'b': {'c': {'createdAt': '2020-02-29T10:09:08.100Z'}}}}) \
        == {'a': {'b': {'c': {'createdAt': expected_datetime}}}}

    # doesn't parse dates nested too deep
    expected_datetime = datetime(2020, 2, 29, 10, 9, 8, 100000, timezone.utc)
    assert _parse_date_fields({'a': {'b': {'c': {'d': {'createdAt': '2020-02-29T10:09:08.100Z'}}}}}) \
        == {'a': {'b': {'c': {'d': {'createdAt': '2020-02-29T10:09:08.100Z'}}}}}

    # doesn't die when the date can't be parsed
    assert _parse_date_fields({'createdAt': 'NOT_A_DATE'}) == {'createdAt': 'NOT_A_DATE'}


def test_ignore_docs() -> None:
    def testing_function(_a: str, _b: str) -> str:
        """Dummy docstring"""
        return 'dummy'

    assert testing_function is ignore_docs(testing_function)
