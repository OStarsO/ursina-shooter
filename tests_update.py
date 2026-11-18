# -*- coding: utf-8 -*-
"""updater.py 单元测试（不依赖网络：用桩替换网络层）。"""
import io
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, ".")

import updater

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def test_version():
    check('解析 v1.3.0', updater.parse_version('v1.3.0') == ((1, 3, 0), '', 0))
    check('解析 1.2', updater.parse_version('1.2') == ((1, 2), '', 0))
    check('解析预发布', updater.parse_version('v1.3.0-beta.2')[1:] == ('beta', 2))
    check('主版本更新', updater.is_newer('v2.0', '1.9.9'))
    check('补丁版本更新', updater.is_newer('v1.2.1', '1.2.0'))
    check('同版本不算新', not updater.is_newer('1.2.0', 'v1.2.0'))
    check('旧版本不算新', not updater.is_newer('1.1.9', '1.2.0'))
    check('预发布低于正式版', not updater.is_newer('1.2.0-beta', '1.2.0'))
    check('正式版高于同号预发布', updater.is_newer('1.2.0', '1.2.0-rc1'))


def test_pick_asset():
    assets = [
        {'name': 'screenshots.zip', 'url': 'u1', 'size': 1},
        {'name': 'ursina-shooter-launcher-v1.3.0.exe', 'url': 'u2', 'size': 2},
        {'name': '射击启动器.exe', 'url': 'u3', 'size': 3},
    ]
    picked = updater.pick_asset(assets)
    check('优先挑启动器 exe', picked and picked['name'].endswith('launcher-v1.3.0.exe'))
    check('无关键字回退首个 exe',
          updater.pick_asset([{'name': 'a.zip'}, {'name': 'b.exe'}])['name'] == 'b.exe')
    check('没有 exe 返回 None', updater.pick_asset([{'name': 'a.zip'}]) is None)
    check('空资产返回 None', updater.pick_asset([]) is None)


def test_fetch_with_stub():
    origin = updater._request_json
    fake = {
        'tag_name': 'v1.3.0',
        'name': 'v1.3.0',
        'body': '更新说明',
        'html_url': 'https://example.com/rel',
        'published_at': '2026-11-17T00:00:00Z',
        'assets': [{'name': 'ursina-shooter-launcher-v1.3.0.exe',
                    'browser_download_url': 'https://example.com/a.exe', 'size': 123}],
    }
    updater._request_json = lambda url=None, timeout=10: fake
    try:
        rel = updater.fetch_latest_release()
        check('解析 Release 版本', rel['version'] == '1.3.0', rel['version'])
        check('解析 Release 资产', rel['asset']['name'].endswith('.exe')
              and rel['asset']['size'] == 123)
        check('版本比较链路', updater.is_newer(rel['version'], '1.2.0'))
    finally:
        updater._request_json = origin


def test_fetch_errors():
    origin = updater._request_json

    def raise404(url=None, timeout=10):
        raise updater.UpdateError('仓库或 Release 不存在（可能尚未发布版本）')

    updater._request_json = raise404
    try:
        try:
            updater.fetch_latest_release()
            check('404 抛 UpdateError', False)
        except updater.UpdateError as exc:
            check('404 抛 UpdateError', '不存在' in str(exc))
    finally:
        updater._request_json = origin


def test_download_fallback():
    """直连失败 → 镜像回退；并校验大小一致性。"""
    calls = []
    payload = b'x' * 4096

    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError('直连超时')
        return FakeResp(payload)

    origin = updater.urllib.request.urlopen
    updater.urllib.request.urlopen = fake_urlopen
    try:
        with tempfile.TemporaryDirectory() as td:
            asset = {'name': 'demo.exe', 'url': 'https://example.com/demo.exe',
                     'size': len(payload)}
            out = updater.download_asset(asset, td)
            check('直连失败后镜像回退成功', out.is_file()
                  and out.stat().st_size == len(payload))
            check('回退时切换了下载前缀', len(calls) == 2 and calls[1] != calls[0],
                  calls[1][:32])
    finally:
        updater.urllib.request.urlopen = origin


def test_download_size_mismatch():
    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    origin = updater.urllib.request.urlopen
    updater.urllib.request.urlopen = lambda req, timeout=0: FakeResp(b'y' * 10)
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                updater.download_asset({'name': 'x.exe', 'url': 'https://e/x.exe',
                                        'size': 999}, td)
                check('大小不符判失败', False)
            except updater.UpdateError:
                check('大小不符判失败', True)
    finally:
        updater.urllib.request.urlopen = origin


def test_stage_update():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        target = td / '射击启动器.exe'
        new = td / 'downloaded.exe'
        target.write_bytes(b'old')
        new.write_bytes(b'new')
        bat = updater.stage_self_update(new, target_exe=target)
        content = bat.read_text(encoding='utf-8')
        check('生成替换脚本', bat.is_file() and bat.name == '_apply_update.bat')
        check('脚本包含覆盖与重启', 'move /Y' in content and 'start ""' in content)
        check('脚本路径为绝对路径', str(target).replace('/', '\\') in content
              or str(target) in content)
    check('非打包环境禁止自替换',
          not updater.is_frozen() or updater.current_executable() is not None)


def main():
    test_version()
    test_pick_asset()
    test_fetch_with_stub()
    test_fetch_errors()
    test_download_fallback()
    test_download_size_mismatch()
    test_stage_update()
    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print('失败项:', FAIL)
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
