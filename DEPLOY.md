# 运行

本仓库不再部署周报网站、PDF 或消息推送。预测和套保在本机运行：

```bash
pip install -e .
python coffee.py --demo
python -m reports.cli --demo
python coffee.py --paper
python -m pytest tests/ -q
```
