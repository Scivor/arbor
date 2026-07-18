#!/bin/bash
set -euo pipefail

echo "========================================"
echo "  Arbor · 京东云一键部署"
echo "========================================"

USER="coffee"
DIR="/home/$USER/coffee-v3"

echo ""
echo "Step 1/8 — 系统更新 & 安装基础依赖"
echo "========================================"
if command -v apt-get &>/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    # pyproject 要求 Python >=3.11；Ubuntu 22.04 默认 python3 为 3.10，走 deadsnakes
    apt-get install -y -qq software-properties-common 2>/dev/null || true
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv git nginx curl \
        fonts-noto-cjk fonts-wqy-zenhei 2>/dev/null || true
elif command -v yum &>/dev/null; then
    yum update -y -q
    yum install -y -q python3.11 python3.11-pip git nginx curl \
        pango libXcomposite libXcursor libXdamage libXext libXi libXtst \
        cups-libs libXScrnSaver libXrandr alsa-lib atk gtk3 \
        xorg-x11-fonts-100dpi xorg-x11-fonts-75dpi \
        xorg-x11-fonts-cyrillic xorg-x11-fonts-Type1 xorg-x11-fonts-misc \
        wqy-zenhei-fonts 2>/dev/null || true
else
    echo "Unsupported OS"
    exit 1
fi

# 版本守卫：pyproject requires-python >=3.11
if ! command -v python3.11 &>/dev/null; then
    echo "ERROR: 未找到 python3.11（pyproject requires-python >=3.11），请手动安装后重跑"
    exit 1
fi

echo ""
echo "Step 2/8 — 创建运行用户"
echo "========================================"
if ! id "$USER" &>/dev/null; then
    useradd -m -s /bin/bash "$USER"
    echo "User $USER created"
else
    echo "User $USER already exists"
fi

echo ""
echo "Step 3/8 — 部署代码"
echo "========================================"
if [ -f /tmp/coffee-v3.tar.gz ]; then
    su - "$USER" -c "mkdir -p $DIR && tar xzf /tmp/coffee-v3.tar.gz -C $DIR --strip-components=1"
    echo "Code deployed from /tmp/coffee-v3.tar.gz"
else
    echo "WARNING: /tmp/coffee-v3.tar.gz not found"
    echo "Please upload the project archive first."
    exit 1
fi

echo ""
echo "Step 4/8 — 安装 Python 依赖"
echo "========================================"
# 依赖单一事实源: pyproject.toml（editable install）
su - "$USER" -c "
    cd $DIR
    python3.11 -m ensurepip --user 2>/dev/null || true
    python3.11 -m pip install --user --quiet -e . 2>&1 | tail -5
"

echo ""
echo "Step 5/8 — 安装 Playwright 浏览器"
echo "========================================"
su - "$USER" -c "python3.11 -m playwright install chromium 2>&1 | tail -3"

echo ""
echo "Step 6/8 — 生成首份报告"
echo "========================================"
su - "$USER" -c "cd $DIR && PYTHONPATH=$DIR python3.11 scripts/scheduler.py --now --format both 2>&1 | tail -3"

echo ""
echo "Step 7/8 — 配置 systemd 服务"
echo "========================================"

# unit 文件单一事实源: deploy/coffee-*.service
cp $DIR/deploy/coffee-web.service $DIR/deploy/coffee-scheduler.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable coffee-web coffee-scheduler
systemctl restart coffee-web coffee-scheduler

echo ""
echo "Step 8/8 — 配置 Nginx"
echo "========================================"

rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true

cat > /etc/nginx/conf.d/coffee.conf <<'EOF'
server {
    listen 80;
    server_name _;

    location /static/ {
        alias /home/coffee/coffee-v3/web/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

nginx -t && systemctl reload nginx
systemctl enable nginx

echo ""
echo "========================================"
echo "  部署完成！"
echo "========================================"
echo ""
echo "  访问地址: http://$(curl -s -4 ip.sb)"
echo ""
echo "  服务状态:"
systemctl is-active coffee-web >/dev/null && echo "    ✓ coffee-web (running)" || echo "    ✗ coffee-web (failed)"
systemctl is-active coffee-scheduler >/dev/null && echo "    ✓ coffee-scheduler (running)" || echo "    ✗ coffee-scheduler (failed)"
systemctl is-active nginx >/dev/null && echo "    ✓ nginx (running)" || echo "    ✗ nginx (failed)"
echo ""
