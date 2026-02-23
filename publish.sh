#!/bin/bash
# 微信公众号发布快捷脚本

cd "$(dirname "$0")"
python3 publish_to_wechat.py "$@"
