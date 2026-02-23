import asyncio
import os
import tempfile
from datetime import datetime
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
            nb = await c.notebooks.create(title)
            # 提取 ID 字符串
            nb_id = nb.id if hasattr(nb, 'id') else str(nb)
            print(f"✅ 笔记本已创建: {title} (ID: {nb_id})")
            return nb_id

    async def upload_file(self, notebook_id, file_path):
        """上传本地文件 (PDF/TXT) 到指定笔记本"""
        await self._ensure_client()
        if not os.path.exists(file_path):
            return f"❌ 错误: 文件不存在 {file_path}"
        
        # 确保 notebook_id 是字符串
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        async with self.client as c:
            print(f"正在上传 {file_path} ...")
            # 添加文件资源
            await c.sources.add_file(notebook_id, file_path)
            print(f"✅ 上传成功!")

    async def upload_url(self, notebook_id, url):
        """上传网页链接到指定笔记本"""
        await self._ensure_client()
        
        # 确保 notebook_id 是字符串
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        async with self.client as c:
            print(f"正在添加链接 {url} ...")
            await c.sources.add_url(notebook_id, url)
            print(f"✅ 链接添加成功!")

    async def ask_question(self, notebook_id, question):
        """向笔记本提问"""
        await self._ensure_client()
        
        # 确保 notebook_id 是字符串
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        async with self.client as c:
            print(f"🤖 正在思考: {question} ...")
            # 调用 chat.ask 获取回答
            result = await c.chat.ask(notebook_id, question)
            
            # 尝试多种可能的属性名来获取回答内容
            answer_text = None
            if hasattr(result, 'answer'):
                answer_text = result.answer
            elif hasattr(result, 'content'):
                answer_text = result.content
            elif hasattr(result, 'text'):
                answer_text = result.text
            elif hasattr(result, 'message'):
                answer_text = result.message
            elif hasattr(result, 'response'):
                answer_text = result.response
            else:
                # 如果都没有，尝试转换为字符串或查看所有属性
                print(f"⚠️ 警告: AskResult 对象属性: {dir(result)}")
                answer_text = str(result)
            
            print("\n--- 回答 ---")
            if answer_text:
                print(answer_text)
            else:
                print("（无法提取回答内容）")
            
            return answer_text if answer_text else str(result)

    async def list_notebooks(self):
        """列出所有笔记本"""
        await self._ensure_client()
        async with self.client as c:
            notebooks = await c.notebooks.list()
            for nb in notebooks:
                print(f"- {nb.title} (ID: {nb.id})")
            return notebooks

    async def upload_text(self, notebook_id, text, title="Article"):
        """上传文本内容到指定笔记本（通过创建临时文件）"""
        await self._ensure_client()
        
        # 确保 notebook_id 是字符串
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(text)
            temp_path = f.name
        
        try:
            async with self.client as c:
                print(f"正在上传文本内容到笔记本 {notebook_id}...")
                await c.sources.add_file(notebook_id, temp_path, wait=True)
                print(f"✅ 文本内容上传成功!")
        finally:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def generate_podcast(self, notebook_id, instructions="make it engaging and informative", timeout=600):
        """
        生成播客音频
        
        :param notebook_id: 笔记本ID
        :param instructions: 生成指令
        :param timeout: 超时时间（秒），默认600秒（10分钟）
        :return: 播客文件路径，如果失败返回 None
        """
        await self._ensure_client()
        
        # 确保 notebook_id 是字符串
        if hasattr(notebook_id, 'id'):
            notebook_id = notebook_id.id
        notebook_id = str(notebook_id)
        
        try:
            async with self.client as c:
                print(f"🎙️ 正在为笔记本 {notebook_id} 生成播客...")
                
                # 尝试创建播客任务
                try:
                    status = await c.artifacts.generate_audio(notebook_id, instructions=instructions)
                    
                    # 检查 task_id 是否有效
                    if not status or not hasattr(status, 'task_id') or not status.task_id:
                        print("⚠️ 警告：播客生成任务创建失败，未返回有效的任务ID")
                        return None
                    
                    task_id = status.task_id
                    print(f"✅ 播客生成任务已启动，任务ID: {task_id}")
                    
                except Exception as e:
                    print(f"❌ 创建播客生成任务失败: {str(e)}")
                    return None
                
                # 等待完成（增加超时时间）
                print(f"⏳ 等待播客生成完成（最多等待 {timeout} 秒）...")
                try:
                    await c.artifacts.wait_for_completion(notebook_id, task_id, timeout=timeout)
                except TimeoutError:
                    print(f"⚠️ 警告：播客生成超时（{timeout}秒），任务可能仍在后台进行中")
                    print(f"   您可以在 NotebookLM 网页上查看任务状态，任务ID: {task_id}")
                    return None
                except Exception as e:
                    print(f"⚠️ 警告：等待播客生成时出错: {str(e)}")
                    return None
                
                # 下载播客
                output_dir = "output/podcasts"
                os.makedirs(output_dir, exist_ok=True)
                podcast_path = os.path.join(output_dir, f"podcast_{notebook_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3")
                
                try:
                    await c.artifacts.download_audio(notebook_id, podcast_path)
                    print(f"✅ 播客已保存到: {podcast_path}")
                    return podcast_path
                except Exception as e:
                    print(f"⚠️ 警告：下载播客失败: {str(e)}")
                    return None
                    
        except Exception as e:
            print(f"❌ 生成播客时发生错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

# 下面是供测试用的入口，平时 Cursor 调用上面的类即可
if __name__ == "__main__":
    # 你可以在这里手动测试，例如：
    # tool = NotebookSkill()
    # asyncio.run(tool.list_notebooks())
    pass