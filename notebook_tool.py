import asyncio
import os
import tempfile
from datetime import datetime
from notebooklm.client import NotebookLMClient

class NotebookSkill:
    def __init__(self):
        self.client = None

    async def _ensure_client(self):
        if not self.client:
            # 自动读取本地保存的登录凭证
            self.client = await NotebookLMClient.from_storage()
    
    # ==========================================
    # 🟢【核心修改】添加上下文管理器支持
    # ==========================================
    async def __aenter__(self):
        await self._ensure_client()
        # 显式调用内部 client 的 __aenter__
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.client:
            # 显式调用内部 client 的 __aexit__
            await self.client.__aexit__(exc_type, exc_value, traceback)

    async def create_notebook(self, title):
        """创建一个新的笔记本"""
        # 注意：这里不需要再 verify client 了，因为 __aenter__ 已经做了
        # 直接使用 self.client
        nb = await self.client.notebooks.create(title)
        # 提取 ID 字符串
        nb_id = nb.id if hasattr(nb, 'id') else str(nb)
        print(f"✅ 笔记本已创建: {title} (ID: {nb_id})")
        return nb_id

    async def upload_file(self, notebook_id, file_path):
        """上传本地文件 (PDF/TXT) 到指定笔记本"""
        if not os.path.exists(file_path):
            return f"❌ 错误: 文件不存在 {file_path}"
        
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        print(f"正在上传 {file_path} ...")
        await self.client.sources.add_file(notebook_id, file_path)
        print(f"✅ 上传成功!")

    async def upload_url(self, notebook_id, url):
        """上传网页链接到指定笔记本"""
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        print(f"正在添加链接 {url} ...")
        await self.client.sources.add_url(notebook_id, url)
        print(f"✅ 链接添加成功!")

    async def ask_question(self, notebook_id, question):
        """向笔记本提问"""
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        print(f"🤖 正在思考: {question} ...")
        result = await self.client.chat.ask(notebook_id, question)
        
        answer_text = None
        if hasattr(result, 'answer'):
            answer_text = result.answer
        elif hasattr(result, 'content'):
            answer_text = result.content
        elif hasattr(result, 'text'):
            answer_text = result.text
        
        print("\n--- 回答 ---")
        if answer_text:
            print(answer_text)
        else:
            print(f"（无法提取回答内容，原始对象: {result}）")
        
        return answer_text if answer_text else str(result)

    async def list_notebooks(self):
        """列出所有笔记本"""
        notebooks = await self.client.notebooks.list()
        for nb in notebooks:
            print(f"- {nb.title} (ID: {nb.id})")
        return notebooks

    async def upload_text(self, notebook_id, text, title="Article"):
        """上传文本内容到指定笔记本（通过创建临时文件）"""
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(text)
            temp_path = f.name
        
        try:
            print(f"正在上传文本内容到笔记本 {notebook_id}...")
            await self.client.sources.add_file(notebook_id, temp_path, wait=True)
            print(f"✅ 文本内容上传成功!")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def generate_podcast(self, notebook_id, instructions="请生成一个全中文的播客音频，两位主持人用中文对话讨论文中内容，语速适中，发音清晰", timeout=600):
        """生成播客音频"""
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        print(f"🎙️ 正在为笔记本 {notebook_id} 生成播客...")
        
        try:
            status = await self.client.artifacts.generate_audio(notebook_id, instructions=instructions)
            
            if not status or not hasattr(status, 'task_id') or not status.task_id:
                print("⚠️ 警告：播客生成任务创建失败")
                return None
            
            task_id = status.task_id
            print(f"✅ 播客生成任务已启动，任务ID: {task_id}")
            
            print(f"⏳ 等待播客生成完成（最多等待 {timeout} 秒）...")
            await self.client.artifacts.wait_for_completion(notebook_id, task_id, timeout=timeout)
            
            # 下载播客
            output_dir = "output/podcasts"
            os.makedirs(output_dir, exist_ok=True)
            # Respect NotebookLM original container format instead of forcing ".mp3".
            podcast_path = os.path.join(output_dir, f"podcast_{notebook_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.m4a")
            
            await self.client.artifacts.download_audio(notebook_id, podcast_path)
            print(f"✅ 播客已保存到: {podcast_path}")
            return podcast_path
            
        except Exception as e:
            print(f"❌ 生成播客时发生错误: {str(e)}")
            return None
