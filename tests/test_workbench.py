from fastapi.testclient import TestClient
from web.app import app


def test_workbench_is_explicit_demo_and_assets_are_available():
    with TestClient(app) as client:
        response = client.get('/workbench/')
        assert response.status_code == 200
        for text in ('采购风险工作台', '演示数据', '未连接账户数据库', 'DEMO-LOT-002', '/track-record/', '/reports/'):
            assert text in response.text
        assert '<form' not in response.text
        assert client.get('/static/css/workbench.css').status_code == 200
        assert client.get('/static/js/workbench.js').status_code == 200
