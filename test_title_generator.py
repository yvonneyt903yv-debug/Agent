#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试标题生成功能
这个脚本演示如何使用新添加的标题生成功能
"""

from src.tools import generate_attractive_title

# 测试文章内容
test_content = """
这是一篇关于人工智能发展的文章。文章讨论了AI技术如何改变我们的生活，
包括自动驾驶、智能助手、医疗诊断等领域的应用。专家认为，AI将在未来
十年内带来革命性的变化。
"""

test_summary = "AI技术正在改变世界，专家预测未来十年将有重大突破"

print("🧪 测试标题生成功能\n")
print("=" * 50)
print("文章内容预览：")
print(test_content[:100] + "...")
print("\n文章摘要：")
print(test_summary)
print("=" * 50)

print("\n🎯 正在生成标题...\n")

# 调用标题生成函数
title = generate_attractive_title(test_content, test_summary)

print(f"✨ 生成的标题：《{title}》")
print("\n✅ 测试完成！")
