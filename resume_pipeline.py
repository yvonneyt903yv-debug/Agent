"""
Resume script: Re-fetch articles and create checkpoint from saved translations.
Run this once to resume the pipeline from where it crashed.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.crawler import fetch_latest_articles
from src.checkpoint import PipelineCheckpoint
from main import run_staged_pipeline

def read_translated_file(filepath):
    """Read translated content from saved file."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Remove the header "# 翻译稿 - IDx\n\n"
            if content.startswith("# 翻译稿"):
                lines = content.split('\n', 2)
                if len(lines) > 2:
                    return lines[2]
            return content
    return None

def main():
    print("="*60)
    print("🔄 Resume Pipeline - Recovering from crash")
    print("="*60)

    # Step 1: Re-fetch articles
    print("\n📡 Re-fetching articles from website...")
    articles = fetch_latest_articles()

    if not articles:
        print("❌ Failed to fetch articles")
        return

    print(f"✅ Fetched {len(articles)} articles")

    # Step 2: Create checkpoint
    checkpoint = PipelineCheckpoint()
    checkpoint.start_new_run(articles)

    # Step 3: Load saved translations
    translated_dir = "output/translated"
    saved_translations = {
        0: "TRANSLATED_20260211_211839_ID0_分析失败.md",
        1: "TRANSLATED_20260211_211839_ID1_分析失败.md",
    }

    print("\n📂 Loading saved translations...")
    for article_id, filename in saved_translations.items():
        filepath = os.path.join(translated_dir, filename)
        cn_text = read_translated_file(filepath)
        if cn_text and len(cn_text) > 100:
            checkpoint.update_article(article_id, cn_text=cn_text)
            checkpoint.mark_stage_completed(1, article_id)
            print(f"  ✅ Loaded translation for article {article_id} ({len(cn_text)} chars)")
        else:
            print(f"  ⚠️ Could not load translation for article {article_id}")

    print(f"\n📊 Checkpoint created:")
    print(f"   - Total articles: {len(checkpoint.articles)}")
    print(f"   - Already translated: {len(checkpoint.stage_1_completed)}")
    print(f"   - Pending translation: {len(checkpoint.articles) - len(checkpoint.stage_1_completed)}")

    # Step 4: Ask user to continue (or auto-continue with --yes flag)
    print("\n" + "="*60)
    if "--yes" in sys.argv or "-y" in sys.argv:
        response = 'y'
        print("Continue with staged pipeline? (y/n): y (auto)")
    else:
        response = input("Continue with staged pipeline? (y/n): ")
    if response.lower() == 'y':
        # Import stage functions
        from main import stage_1_translate_all, stage_2_summarize_all, stage_3_analyze_summaries, stage_4_filter_and_publish
        import asyncio

        # Run remaining stages
        stage_1_translate_all(checkpoint)
        asyncio.run(stage_2_summarize_all(checkpoint))
        stage_3_analyze_summaries(checkpoint)
        stage_4_filter_and_publish(checkpoint)

        print("\n✅ Pipeline complete!")
    else:
        print("\n📂 Checkpoint saved. Run 'python main.py' to continue later.")

if __name__ == "__main__":
    main()
