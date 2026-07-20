"""
tests/conftest.py
默认阻断真实网络访问 —— README 声称测试套件"无网络依赖"，这里把承诺
变成硬约束：任何测试试图建立 socket 连接都会立刻抛错，而不是悄悄把请求
打到外网（拖慢测试、引入网络脆弱性、消耗第三方 API 配额）。

注意：不能只放行 loopback（127.0.0.1）—— 本机配置了系统级 HTTP(S) 代理
（scutil --proxy 显示 127.0.0.1:1082），requests 等库默认信任该系统代理，
"只挡外部地址"的白名单会被代理透明穿透，等于没挡。因此这里不做任何地址
判别，无条件挡住全部 socket 连接。

确实需要用到真实 socket（联网，或本机起 mock server 如
test_agent_e2e.py）的测试用 @pytest.mark.integration 标记后放行
（该标记已在 pyproject.toml 中注册，语义为 "may need network"）。
"""

import socket

import pytest


class NetworkBlockedError(RuntimeError):
    """测试默认禁止 socket 连接时抛出。"""


def _blocked(*_args, **_kwargs):
    raise NetworkBlockedError(
        "测试默认禁止网络访问；如该测试确实需要联网（或起本机 mock server），"
        "打上 @pytest.mark.integration 放行。"
    )


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
