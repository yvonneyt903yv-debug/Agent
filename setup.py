import os

def create_structure():
    # 1. 定义根文件夹名称（核心修改：添加根目录）
    root_folder = "MyWechatAgent"
    
    # 2. 定义原始目录结构（保持不变）
    dirs = [
        "src",
        "prompts",
        "output/final_articles",
        "logs"
    ]
    
    # 3. 定义原始文件及其初始内容（保持不变）
    files = {
        ".env": "DEEPSEEK_API_KEY=你的密钥填在这里\n",
        "requirements.txt": "openai\n",
        "prompts/editor_instruction.md": "# 角色\n你是一个微信公众号主编...",
        "src/__init__.py": "",
        "src/main.py": "# 启动入口",
        "src/agent.py": "# Agent 大脑",
        "src/tools.py": "# 工具箱"
    }

    # 4. 给所有目录添加根文件夹前缀（核心修改：拼接路径）
    full_dirs = [os.path.join(root_folder, d) for d in dirs]
    
    # 5. 创建根文件夹及子目录（exist_ok=True 避免已存在时报错）
    os.makedirs(root_folder, exist_ok=True)
    print(f"✅ 根目录创建: {root_folder}")
    for d in full_dirs:
        os.makedirs(d, exist_ok=True)
        print(f"✅ 子目录创建: {d}")

    # 6. 给所有文件添加根文件夹前缀（核心修改：拼接路径）
    full_files = {os.path.join(root_folder, path): content for path, content in files.items()}
    
    # 7. 创建文件（在根文件夹内）
    for path, content in full_files.items():
        if not os.path.exists(path):
            # 确保文件所在的子目录存在（比如 prompts/ 目录）
            file_dir = os.path.dirname(path)
            os.makedirs(file_dir, exist_ok=True)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"📄 文件创建: {path}")

if __name__ == "__main__":
    create_structure()
    print(f"\n🎉 项目结构搭建完成！所有文件已生成到 MyWechatAgent 文件夹中，请删除 setup.py 并开始下一步。")