"""
Pipeline checkpoint module for state persistence and crash recovery.
Enables resume from any stage after crash.
"""
import json
import os
from datetime import datetime
from typing import Optional

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "pipeline_checkpoint.json")


class PipelineCheckpoint:
    """Manages pipeline state persistence for crash recovery."""

    def __init__(self, checkpoint_path: str = CHECKPOINT_FILE):
        self.checkpoint_path = checkpoint_path
        self.run_id: str = ""
        self.articles: list = []
        self.stage_1_completed: list = []  # Translation completed
        self.stage_2_completed: list = []  # NotebookLM summary completed
        self.stage_3_completed: list = []  # Gemini analysis completed
        self.errors: list = []

    def load(self) -> bool:
        """Load checkpoint from file. Returns True if loaded successfully."""
        if not os.path.exists(self.checkpoint_path):
            return False

        try:
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.run_id = data.get("run_id", "")
            self.articles = data.get("articles", [])
            self.stage_1_completed = data.get("stage_1_completed", [])
            self.stage_2_completed = data.get("stage_2_completed", [])
            self.stage_3_completed = data.get("stage_3_completed", [])
            self.errors = data.get("errors", [])

            print(f"  📂 Loaded checkpoint: run_id={self.run_id}")
            print(f"     Stage 1 (translate): {len(self.stage_1_completed)} completed")
            print(f"     Stage 2 (summarize): {len(self.stage_2_completed)} completed")
            print(f"     Stage 3 (analyze): {len(self.stage_3_completed)} completed")
            return True
        except Exception as e:
            print(f"  ⚠️ Failed to load checkpoint: {e}")
            return False

    def save(self):
        """Save current state to checkpoint file."""
        os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)

        data = {
            "run_id": self.run_id,
            "articles": self.articles,
            "stage_1_completed": self.stage_1_completed,
            "stage_2_completed": self.stage_2_completed,
            "stage_3_completed": self.stage_3_completed,
            "errors": self.errors
        }

        with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def start_new_run(self, raw_articles: list):
        """Initialize a new pipeline run with raw articles."""
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.articles = []
        self.stage_1_completed = []
        self.stage_2_completed = []
        self.stage_3_completed = []
        self.errors = []

        for i, raw_text in enumerate(raw_articles):
            self.articles.append({
                "id": i,
                "raw_text": raw_text,
                "cn_text": "",
                "notebooklm_summary": "",
                "analysis": {}
            })

        self.save()
        print(f"  🆕 Started new run: {self.run_id} with {len(raw_articles)} articles")

    def get_article(self, article_id: int) -> Optional[dict]:
        """Get article data by ID."""
        for article in self.articles:
            if article["id"] == article_id:
                return article
        return None

    def update_article(self, article_id: int, **kwargs):
        """Update article fields and save checkpoint."""
        for article in self.articles:
            if article["id"] == article_id:
                article.update(kwargs)
                self.save()
                return

    def mark_stage_completed(self, stage: int, article_id: int):
        """Mark a stage as completed for an article."""
        stage_list = getattr(self, f"stage_{stage}_completed")
        if article_id not in stage_list:
            stage_list.append(article_id)
            self.save()

    def is_stage_completed(self, stage: int, article_id: int) -> bool:
        """Check if a stage is completed for an article."""
        stage_list = getattr(self, f"stage_{stage}_completed")
        return article_id in stage_list

    def log_error(self, stage: int, article_id: int, error: str):
        """Log an error with timestamp."""
        self.errors.append({
            "stage": stage,
            "article_id": article_id,
            "error": str(error),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.save()
        print(f"  ❌ Error logged: Stage {stage}, Article {article_id}: {error}")

    def clear(self):
        """Clear checkpoint file after successful completion."""
        if os.path.exists(self.checkpoint_path):
            os.remove(self.checkpoint_path)
            print("  🗑️ Checkpoint cleared")

    def get_pending_for_stage(self, stage: int) -> list:
        """Get list of article IDs pending for a stage."""
        stage_list = getattr(self, f"stage_{stage}_completed")

        if stage == 1:
            # Stage 1: all articles not yet translated
            return [a["id"] for a in self.articles if a["id"] not in stage_list]
        elif stage == 2:
            # Stage 2: translated but not summarized
            return [aid for aid in self.stage_1_completed if aid not in stage_list]
        elif stage == 3:
            # Stage 3: summarized but not analyzed
            return [aid for aid in self.stage_2_completed if aid not in stage_list]

        return []
