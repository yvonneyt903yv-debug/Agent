#!/bin/bash
# 设置 ClashX 代理环境变量并运行 main.py

# 使用 SOCKS5 代理（ClashX 推荐方式）
export HTTP_PROXY=socks5://127.0.0.1:7890
export HTTPS_PROXY=socks5://127.0.0.1:7890

# 可选：如果使用 HTTP 代理，请取消下面两行的注释并注释掉上面的
# export HTTP_PROXY=http://127.0.0.1:7890
# export HTTPS_PROXY=http://127.0.0.1:7890

echo "代理设置: HTTP_PROXY=$HTTP_PROXY"
echo "代理设置: HTTPS_PROXY=$HTTPS_PROXY"

# 测试代理连接
echo "正在测试代理连接..."
python3 -c "import requests; print('✅ 代理测试成功'); print(requests.get('https://ipinfo.io').json())" 2>&1 && echo -e "\n✅ 代理工作正常！" || echo -e "\n❌ 代理测试失败"

# 运行主程序
echo -e "\n正在启动 main.py..."
python3 main.py
