# Arbor · 京东云部署指南

## 1. 选购服务器

推荐 **京东云轻量云主机**（适合个人/小团队）：

| 配置 | 建议 |
|---|---|
| **地域** | 华北-北京（离你用户群最近） |
| **镜像** | CentOS 8.2 / Ubuntu 22.04 LTS |
| **规格** | 2核 4G 内存（最低配置） |
| **带宽** | 3Mbps（静态站点足够） |
| **磁盘** | 60GB SSD |
| **价格** | 约 ¥60-100/月 |

> 如果预算充足，选 **4核 8G**，Playwright 生成 PDF 时更流畅。

购买后，在控制台获取：
- 公网 IP（如 `114.67.85.123`）
- root 密码（或上传 SSH 公钥）

---

## 2. 连接服务器

```bash
ssh root@<你的公网IP>
```

首次登录后建议：
```bash
# 更新系统
yum update -y          # CentOS
apt update && apt upgrade -y   # Ubuntu

# 创建非 root 用户
useradd -m -s /bin/bash coffee
passwd coffee
usermod -aG wheel coffee   # CentOS
usermod -aG sudo coffee    # Ubuntu
```

---

## 3. 安装依赖

### 3.1 Python 3.11+

**CentOS 8/9:**
```bash
yum install -y python3.11 python3.11-pip git
```

**Ubuntu 22.04:**
```bash
# 22.04 默认 python3 为 3.10，pyproject 要求 >=3.11，走 deadsnakes
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update && apt install -y python3.11 python3.11-venv git
```

### 3.2 安装项目依赖

```bash
su - coffee
cd ~
git clone <你的代码仓库> coffee-v3
cd coffee-v3

python3.11 -m ensurepip --user 2>/dev/null || true
python3.11 -m pip install --user -e .
```

> 依赖以 `pyproject.toml` 为单一事实源（editable install 自动装齐），
> 不再维护手写 requirements 列表。

### 3.3 安装 Playwright 浏览器

```bash
python3.11 -m playwright install chromium
python3.11 -m playwright install-deps chromium
```

> 这一步会下载约 150MB 的 Chromium 浏览器，可能需要几分钟。

---

## 4. 部署代码

### 4.1 目录结构

```
/home/coffee/coffee-v3/
├── web/
│   ├── app.py
│   ├── static/
│   │   ├── css/
│   │   └── reports/      ← 报告存放目录
│   └── templates/
├── scripts/
│   └── scheduler.py
├── reports/
├── sources/
├── coffee.py
└── requirements.txt
```

### 4.2 先手动跑一次，生成第一份报告

```bash
cd ~/coffee-v3
python3.11 scripts/scheduler.py --now --format both
```

确认 `web/static/reports/` 下已生成报告文件。

---

## 5. 配置 systemd 服务

### 5.1 Web 服务

创建 `/etc/systemd/system/coffee-web.service`：

```ini
[Unit]
Description=Arbor Web Report
After=network.target

[Service]
Type=simple
User=coffee
Group=coffee
WorkingDirectory=/home/coffee/coffee-v3
Environment=PYTHONPATH=/home/coffee/coffee-v3
Environment=PATH=/home/coffee/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/usr/bin/python3.11 -m uvicorn web.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 5.2 定时调度服务

创建 `/etc/systemd/system/coffee-scheduler.service`：

```ini
[Unit]
Description=Arbor Report Scheduler
After=network.target

[Service]
Type=simple
User=coffee
Group=coffee
WorkingDirectory=/home/coffee/coffee-v3
Environment=PYTHONPATH=/home/coffee/coffee-v3
Environment=PATH=/home/coffee/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/usr/bin/python3.11 scripts/scheduler.py --format both
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

### 5.3 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable coffee-web coffee-scheduler
sudo systemctl start coffee-web coffee-scheduler

# 查看状态
sudo systemctl status coffee-web
sudo systemctl status coffee-scheduler

# 查看日志
sudo journalctl -u coffee-web -f
sudo journalctl -u coffee-scheduler -f
```

---

## 6. Nginx 反向代理

### 6.1 安装 Nginx

```bash
# CentOS
yum install -y nginx
systemctl enable nginx

# Ubuntu
apt install -y nginx
systemctl enable nginx
```

### 6.2 配置

创建 `/etc/nginx/conf.d/coffee.conf`：

```nginx
server {
    listen 80;
    server_name _;   # 或你的域名，如 coffee.example.com

    # 静态资源（CSS、报告文件）
    location /static/ {
        alias /home/coffee/coffee-v3/web/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    # 报告 PDF 文件
    location /reports/ {
        alias /home/coffee/coffee-v3/web/static/reports/;
        expires 1d;
    }

    # 反向代理到 FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 长连接优化
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### 6.3 启动 Nginx

```bash
sudo nginx -t          # 测试配置
sudo systemctl restart nginx
```

---

## 7. 安全组/防火墙

在 **京东云控制台 → 安全组** 中放行：

| 协议 | 端口 | 来源 | 说明 |
|---|---|---|---|
| TCP | 80 | 0.0.0.0/0 | HTTP 访问 |
| TCP | 443 | 0.0.0.0/0 | HTTPS（如需） |
| TCP | 22 | 你的IP/24 | SSH（限制来源更安全） |

> 不要放行 8000 端口！Nginx 只监听 80，内部转发到 8000。

---

## 8. 绑定域名 + HTTPS（可选）

如果你有域名，建议开启 HTTPS。

### 8.1 DNS 解析

在域名服务商添加 A 记录：
```
coffee.yourdomain.com → <你的京东云公网IP>
```

### 8.2 申请 SSL 证书（Let's Encrypt）

```bash
# 安装 certbot
yum install -y certbot python3-certbot-nginx    # CentOS
apt install -y certbot python3-certbot-nginx    # Ubuntu

# 申请证书
certbot --nginx -d coffee.yourdomain.com

# 自动续期测试
certbot renew --dry-run
```

### 8.3 修改 Nginx 配置

Certbot 会自动修改。确认后重启：
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 9. 验证部署

```bash
# 本机测试
curl -s http://<你的公网IP>/api/health

# 浏览器访问
http://<你的公网IP>/
http://<你的公网IP>/reports/
```

---

## 10. 日常运维

### 查看日志
```bash
# Web 服务日志
sudo journalctl -u coffee-web -n 100 --no-pager

# 调度器日志
sudo journalctl -u coffee-scheduler -n 100 --no-pager

# Nginx 访问日志
sudo tail -f /var/log/nginx/access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 手动触发报告生成
```bash
sudo systemctl stop coffee-scheduler
cd /home/coffee/coffee-v3
python3.11 scripts/scheduler.py --now --format both
sudo systemctl start coffee-scheduler
```

### 更新代码
```bash
su - coffee
cd ~/coffee-v3
git pull
sudo systemctl restart coffee-web coffee-scheduler
```

---

## 11. 备份策略（建议）

报告数据保存在 `web/static/reports/`，建议定期备份：

```bash
# 添加定时备份到对象存储
# 京东云 OSS / AWS S3 / 其他
0 4 * * * tar czf /tmp/reports-$(date +\%Y\%m\%d).tar.gz /home/coffee/coffee-v3/web/static/reports/
```

---

## 一键部署脚本（可选）

仓库内置一键部署脚本（涵盖上文第 2–6 步：系统依赖、运行用户、代码部署、
Python 依赖、Playwright、首份报告、systemd、Nginx）：

```bash
# 1. 把项目打包上传到服务器
scp coffee-v3.tar.gz root@<你的公网IP>:/tmp/

# 2. 以 root 执行
bash deploy/provision.sh
```

- Python 依赖走 `pip3 install --user -e .`（pyproject.toml 单一事实源）
- systemd unit 文件为 `deploy/coffee-web.service` / `deploy/coffee-scheduler.service`
- Nginx 配置由脚本内 heredoc 写入 `/etc/nginx/conf.d/coffee.conf`

---

## 7. macOS 本地常驻（launchd）

周报调度器（`scripts/scheduler.py`，APScheduler，每周六 03:00 CST 触发）可通过 launchd 常驻：

```bash
cp deploy/com.arbor.weekly-report.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.arbor.weekly-report.plist
launchctl list | grep arbor        # 验证已加载
```

- 崩溃自动重启（KeepAlive，节流 60s）；日志在 `output/logs/scheduler.err.log`
- 卸载：`launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.arbor.weekly-report.plist`
- 注意：gui 域代理在用户注销后停止；服务器场景请用上文 systemd 方案

### 运维告警（Telegram）

数据源降级或生成失败时自动推送 Telegram 告警：

```bash
cp deploy/arbor.env.example ~/.arbor/.env   # 填入 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
python scripts/scheduler.py --alert-test     # 验证告警链路
```

---

有问题随时问我。
