import asyncio
import os
from notebooklm.client import NotebookLMClient

# 这是一个封装好的工具类，Cursor 可以直接调用这里的方法
class NotebookSkill:
    def __init__(self):
        self.client = None

    async def _ensure_client(self):
        if not self.client:
            # 自动读取本地保存的登录凭证
            self.client = await NotebookLMClient.from_storage()

    async def create_notebook(self, title):
        """创建一个新的笔记本"""
        await self._ensure_client()
        async with self.client as c:
            nb_id = await c.notebooks.create(title)
            print(f"✅ 笔记本已创建: {title} (ID: {nb_id})")
            return nb_id

    async def upload_file(self, notebook_id, file_path):
        """上传本地文件 (PDF/TXT) 到指定笔记本"""
        await self._ensure_client()
        if not os.path.exists(file_path):
            return f"❌ 错误: 文件不存在 {file_path}"
        
        async with self.client as c:
            print(f"正在上传 {file_path} ...")
            # 添加文件资源
            await c.sources.add_file(notebook_id, file_path)
            print(f"✅ 上传成功!")

    async def upload_url(self, notebook_id, url):
        """上传网页链接到指定笔记本"""
        await self._ensure_client()
        async with self.client as c:
            print(f"正在添加链接 {url} ...")
            await c.sources.add_url(notebook_id, url)
            print(f"✅ 链接添加成功!")

    async def ask_question(self, notebook_id, question):
        """向笔记本提问"""
        await self._ensure_client()
        async with self.client as c:
            print(f"🤖 正在思考: {question} ...")
            # 这里的 chat 方法可能需要根据最新库版本微调，这是标准用法
            conversation = await c.chat.ask(notebook_id, question)
            print("\n--- 回答 ---")
            print(conversation.content)
            return conversation.content

    async def list_notebooks(self):
        """列出所有笔记本"""
        await self._ensure_client()
        async with self.client as c:
            notebooks = await c.notebooks.list()
            for nb in notebooks:
                print(f"- {nb.title} (ID: {nb.id})")
            return notebooks

# 下面是供测试用的入口，平时 Cursor 调用上面的类即可
if __name__ == "__main__":
    # 你可以在这里手动测试，例如：
    # tool = NotebookSkill()
    # asyncio.run(tool.list_notebooks())
    pass