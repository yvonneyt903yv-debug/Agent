#!/usr/bin/env python3
"""
服务器环境适配基础模块
自动处理代理、重试、日志和路径配置
"""

import os
import sys
import platform
import logging
import time
import functools
from datetime import datetime

# ==================== 1. 自动代理配置 ====================
def get_proxy_config():
    """
    自动判断系统环境并返回代理配置
    - Linux (服务器): 不使用代理
    - Darwin (Mac): 使用本地 Clash 代理
    """
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        return {
            'http': 'http://127.0.0.1:7890',
            'https': 'http://127.0.0.1:7890'
        }
    else:  # Linux 或其他系统，不使用代理
        return None

# 全局代理配置
PROXIES = get_proxy_config()

# ==================== 2. 重试装饰器 ====================
def retry_on_failure(max_retries=3, delay=2, backoff=2):
    """
    网络请求重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟倍数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logging.warning(f"{func.__name__} 第 {attempt + 1} 次尝试失败: {str(e)[:100]}，{current_delay}秒后重试...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logging.error(f"{func.__name__} 已重试 {max_retries} 次，最终失败: {str(e)[:100]}")
                        raise last_exception
            
            return None
        return wrapper
    return decorator

# ==================== 3. 统一的日志配置 ====================
def setup_server_logging(log_filename, log_dir=None):
    """
    设置服务器环境的日志配置
    
    Args:
        log_filename: 日志文件名
        log_dir: 日志目录（默认为脚本所在目录）
    """
    if log_dir is None:
        log_dir = os.path.dirname(os.path.abspath(__file__))
    
    log_path = os.path.join(log_dir, log_filename)
    
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger()
    logger.info(f"日志系统初始化完成，日志文件: {log_path}")
    logger.info(f"运行环境: {platform.system()} ({platform.platform()})")
    logger.info(f"代理配置: {'使用 ' + str(PROXIES) if PROXIES else '不使用代理'}")
    
    return logger

# ==================== 4. 路径处理工具 ====================
def get_script_dir():
    """获取当前脚本所在目录（处理不同部署路径）"""
    return os.path.dirname(os.path.abspath(__file__))

def ensure_dir(path):
    """确保目录存在，如果不存在则创建"""
    os.makedirs(path, exist_ok=True)
    return path

# ==================== 5. 网络请求包装函数 ====================
@retry_on_failure(max_retries=3, delay=2, backoff=2)
def requests_get_with_retry(url, headers=None, timeout=30, **kwargs):
    """
    带重试机制的 requests.get
    自动使用代理配置
    """
    import requests
    
    # 如果没有指定 proxies，使用自动配置的代理
    if 'proxies' not in kwargs and PROXIES:
        kwargs['proxies'] = PROXIES
    
    response = requests.get(url, headers=headers, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response

@retry_on_failure(max_retries=3, delay=2, backoff=2)
def requests_post_with_retry(url, headers=None, timeout=30, **kwargs):
    """
    带重试机制的 requests.post
    自动使用代理配置
    """
    import requests
    
    if 'proxies' not in kwargs and PROXIES:
        kwargs['proxies'] = PROXIES
    
    response = requests.post(url, headers=headers, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response

# ==================== 6. 兼容旧代码的导入映射 ====================
# 这些是为了让旧代码可以继续使用 PROXIES 变量
__all__ = [
    'PROXIES',
    'get_proxy_config',
    'retry_on_failure',
    'setup_server_logging',
    'get_script_dir',
    'ensure_dir',
    'requests_get_with_retry',
    'requests_post_with_retry'
]
