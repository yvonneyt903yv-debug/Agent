#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lex Fridman Podcast RSS Monitor
- Monitors RSS feed for new episodes
- Fetches full transcript from transcript pages
- Translates article content using translate_and_review.py
- Runs automatically on startup (macOS launchd)
- Handles sleep/wake properly with missed job recovery
- Only marks episodes as processed after successful translation
"""

import os
import sys
import time
import logging
import feedparser
import requests
import subprocess
import re
import fcntl
import json
import signal
from datetime import datetime
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 邮件通知
sys.path.insert(0, os.path.join(SCRIPT_DIR, "Agent", "gps"))
try:
    from email_notifier import send_publish_notification
    EMAIL_NOTIFY_AVAILABLE = True
except ImportError:
    EMAIL_NOTIFY_AVAILABLE = False
try:
    from server_utils import PROXIES, requests_get_with_retry
except ImportError:
    PROXIES = None
    requests_get_with_retry = None

PROCESSED_FILE = os.path.join(SCRIPT_DIR, "processed_lex_episodes.txt")
PENDING_FILE = os.path.join(SCRIPT_DIR, "pending_lex_episodes.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "lex_rss_monitor.log")
LOG_TXT_FILE = os.path.join(SCRIPT_DIR, "log.txt")
INIT_MARKER_FILE = os.path.join(SCRIPT_DIR, "lex_rss_monitor.initialized")
LOCK_FILE = os.path.join(SCRIPT_DIR, "lex_rss_monitor.lock")
LAST_CHECK_FILE = os.path.join(SCRIPT_DIR, "lex_rss_monitor.lastcheck")
RSS_URL = "https://lexfridman.com/feed/podcast/"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.FileHandler(LOG_TXT_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LexRSSMonitor')


class FileLock:
    """Simple file-based lock to prevent multiple instances"""
    def __init__(self, lock_file):
        self.lock_file = lock_file
        self.fd = None

    def _is_pid_running(self, pid):
        """Check if a process with given PID is still running"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _check_stale_lock(self):
        """Check if lock file exists but the process is dead"""
        if os.path.exists(self.lock_file):
            try:
                with open(self.lock_file, 'r') as f:
                    old_pid = int(f.read().strip())
                if not self._is_pid_running(old_pid):
                    logger.info(f"Removing stale lock file (PID {old_pid} is dead)")
                    os.remove(self.lock_file)
                    return True
            except (ValueError, IOError, OSError):
                # Can't read PID or file issue, try to remove it
                try:
                    os.remove(self.lock_file)
                except:
                    pass
                return True
        return False

    def acquire(self):
        # First check for stale lock
        self._check_stale_lock()

        try:
            self.fd = open(self.lock_file, 'w')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            return True
        except (IOError, OSError):
            if self.fd:
                self.fd.close()
            return False

    def release(self):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                os.remove(self.lock_file)
            except:
                pass


def load_processed_episodes():
    """Load list of successfully processed episode GUIDs"""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_processed_episode(guid):
    """Record an episode as successfully processed"""
    with open(PROCESSED_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{guid}\n")


def load_pending_episodes():
    """Load list of pending (failed) episodes to retry"""
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_pending_episodes(pending):
    """Save pending episodes list"""
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def add_pending_episode(guid, title, transcript_url, retry_count=0):
    """Add an episode to pending list for retry"""
    pending = load_pending_episodes()
    pending[guid] = {
        'title': title,
        'transcript_url': transcript_url,
        'retry_count': retry_count,
        'last_attempt': datetime.now().isoformat()
    }
    save_pending_episodes(pending)


def remove_pending_episode(guid):
    """Remove an episode from pending list"""
    pending = load_pending_episodes()
    if guid in pending:
        del pending[guid]
        save_pending_episodes(pending)


def is_initialized():
    """Check if this is first run (initialization only)"""
    return os.path.exists(INIT_MARKER_FILE)


def mark_initialized():
    """Mark that initialization is complete"""
    with open(INIT_MARKER_FILE, 'w', encoding='utf-8') as f:
        f.write(f"Initialized at {datetime.now()}")


def update_last_check():
    """Update last check timestamp"""
    with open(LAST_CHECK_FILE, 'w', encoding='utf-8') as f:
        f.write(datetime.now().isoformat())


def get_last_check():
    """Get last check timestamp"""
    if os.path.exists(LAST_CHECK_FILE):
        try:
            with open(LAST_CHECK_FILE, 'r', encoding='utf-8') as f:
                return datetime.fromisoformat(f.read().strip())
        except:
            pass
    return None


def should_run_missed_check():
    """Check if we missed scheduled runs due to sleep"""
    last_check = get_last_check()
    if not last_check:
        return True

    now = datetime.now()
    hours_since_last = (now - last_check).total_seconds() / 3600

    # If more than 13 hours since last check, we likely missed a scheduled run
    if hours_since_last > 13:
        logger.info(f"Detected missed check (last: {last_check}, hours since: {hours_since_last:.1f})")
        return True
    return False


def mark_all_current_episodes_processed(feed):
    """Mark all current episodes as processed without translating them"""
    processed = load_processed_episodes()
    new_count = 0
    for entry in feed.entries:
        guid = entry.get('id', entry.get('link', ''))
        if guid not in processed:
            processed.add(guid)
            new_count += 1

    if new_count > 0:
        with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
            for guid in processed:
                f.write(f"{guid}\n")
        logger.info(f"Initialization: Marked {new_count} current episodes as processed (no translation)")

    return new_count


def extract_transcript_url(summary):
    """Extract transcript URL from RSS summary"""
    if not summary:
        return None
    match = re.search(r'href=["\'](https?://lexfridman\.com/[^"\']*transcript[^"\']*)["\']', summary, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'(https?://lexfridman\.com/[a-z0-9-]+-transcript)', summary, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def fetch_transcript_content(url):
    """Fetch full transcript content from transcript page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        if requests_get_with_retry:
            response = requests_get_with_retry(url, headers=headers, timeout=30)
        else:
            response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        content_div = soup.find('div', class_='entry-content')
        if not content_div:
            content_div = soup.find('article')

        if content_div:
            for tag in content_div.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
                tag.decompose()

            transcript_text = content_div.get_text(separator='\n', strip=True)

            start_marker = "This is a transcript of"
            end_markers = ["Go back to this episode", "Posted in", "entry-meta"]

            start_idx = transcript_text.find(start_marker)
            if start_idx == -1:
                start_idx = 0

            end_idx = len(transcript_text)
            for marker in end_markers:
                idx = transcript_text.find(marker, start_idx + 100)
                if idx != -1 and idx < end_idx:
                    end_idx = idx

            transcript_text = transcript_text[start_idx:end_idx].strip()

            if transcript_text and len(transcript_text) > 500:
                return transcript_text

        return None

    except Exception as e:
        logger.error(f"Failed to fetch transcript from {url}: {e}")
        return None


def translate_and_review(content, title, url):
    """Call translate_and_review.py to process the content. Returns True if successful."""
    try:
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
        temp_file = os.path.join(SCRIPT_DIR, f"temp_{safe_title}.txt")

        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\nURL: {url}\n\n{content}")

        logger.info(f"Calling translate_and_review.py for: {title}")

        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "translate_and_review.py"), temp_file, "--auto"],
            capture_output=True,
            text=True,
            timeout=7200
        )

        if os.path.exists(temp_file):
            os.remove(temp_file)

        if result.returncode == 0:
            logger.info(f"Successfully translated: {title}")
            if result.stdout:
                logger.info(f"Output:\n{result.stdout[:500]}")
            return True
        else:
            logger.error(f"Translation failed for {title}")
            if result.stderr:
                logger.error(f"Error:\n{result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"Translation timed out for: {title}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    except Exception as e:
        logger.error(f"Error calling translate_and_review.py: {e}")
        return False


def process_episode(guid, title, transcript_url, is_retry=False):
    """Process a single episode. Returns True if successful."""
    retry_info = " (retry)" if is_retry else ""
    logger.info(f"Processing{retry_info}: {title}")

    content = fetch_transcript_content(transcript_url)

    if not content:
        logger.warning(f"Could not fetch transcript for: {title}")
        return False

    logger.info(f"Fetched transcript ({len(content)} chars), starting translation...")
    success = translate_and_review(content, title, transcript_url)

    return success


def process_pending_episodes():
    """Retry failed episodes from pending list"""
    pending = load_pending_episodes()
    if not pending:
        return

    logger.info(f"Found {len(pending)} pending episodes to retry")

    max_retries = 3
    processed_count = 0

    for guid, info in list(pending.items()):
        if info['retry_count'] >= max_retries:
            logger.warning(f"Max retries reached for: {info['title']}, skipping")
            continue

        title = info['title']
        transcript_url = info['transcript_url']
        retry_count = info['retry_count']

        logger.info(f"Retrying ({retry_count + 1}/{max_retries}): {title}")

        success = process_episode(guid, title, transcript_url, is_retry=True)

        if success:
            save_processed_episode(guid)
            remove_pending_episode(guid)
            logger.info(f"Successfully processed on retry: {title}")
        else:
            # Update retry count
            add_pending_episode(guid, title, transcript_url, retry_count + 1)
            logger.warning(f"Retry failed for: {title}")

        processed_count += 1

        # Limit retries per run to avoid blocking new episodes
        if processed_count >= 2:
            logger.info("Reached retry limit for this run")
            break


def check_rss_feed():
    """Check RSS feed for new episodes"""
    logger.info(f"Checking RSS feed: {RSS_URL}")

    try:
        # First, retry any pending episodes
        process_pending_episodes()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        if requests_get_with_retry:
            response = requests_get_with_retry(RSS_URL, headers=headers, timeout=30)
            feed = feedparser.parse(response.content)
        else:
            feed = feedparser.parse(RSS_URL)

        if feed.bozo:
            logger.warning(f"RSS feed parsing warning: {feed.bozo_exception}")

        if not hasattr(feed, 'entries') or len(feed.entries) == 0:
            logger.warning("No entries found in RSS feed")
            update_last_check()
            return

        # First run: mark all current episodes as processed (no translation)
        if not is_initialized():
            logger.info("First run: Initializing - marking all current episodes as processed")
            count = mark_all_current_episodes_processed(feed)
            mark_initialized()
            logger.info(f"Initialization complete. {count} episodes marked. Future updates will be translated.")
            update_last_check()
            return

        processed = load_processed_episodes()
        pending = load_pending_episodes()
        new_count = 0

        for entry in feed.entries:
            guid = entry.get('id', entry.get('link', ''))

            # Skip if already processed successfully or in pending list
            if guid in processed or guid in pending:
                continue

            title = entry.get('title', 'Unknown Episode')
            summary = entry.get('summary', '')

            logger.info(f"Found new episode: {title}")

            transcript_url = extract_transcript_url(summary)

            if not transcript_url:
                logger.warning(f"No transcript URL found for: {title}")
                # Mark as processed since we can't do anything without transcript
                save_processed_episode(guid)
                continue

            success = process_episode(guid, title, transcript_url)

            if success:
                save_processed_episode(guid)
                # 发送邮件通知
                if EMAIL_NOTIFY_AVAILABLE:
                    try:
                        send_publish_notification(
                            article_title=title,
                            source="Lex Fridman Podcast",
                            saved_path=None,
                            wechat_published=False
                        )
                    except Exception as e:
                        logger.warning(f"邮件通知失败: {e}")
            else:
                # Add to pending for retry
                add_pending_episode(guid, title, transcript_url, retry_count=0)
                logger.info(f"Added to pending for retry: {title}")

            new_count += 1

            # Limit new episodes per run
            if new_count >= 3:
                logger.info("Reached limit of 3 new episodes per run")
                break

        if new_count == 0:
            logger.info("No new episodes found")

        update_last_check()

    except Exception as e:
        logger.error(f"Error checking RSS feed: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Lex Fridman RSS Monitor')
    parser.add_argument('--setup-launchd', action='store_true', help='Generate macOS launchd plist for startup')
    parser.add_argument('--check-now', action='store_true', help='Run a single check and exit')
    args = parser.parse_args()

    if args.setup_launchd:
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lexfridman_rss_monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{os.path.abspath(__file__)}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{os.path.join(SCRIPT_DIR, "lex_rss_monitor.log")}</string>
    <key>StandardErrorPath</key>
    <string>{os.path.join(SCRIPT_DIR, "lex_rss_monitor.err")}</string>
</dict>
</plist>"""

        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.lexfridman_rss_monitor.plist")

        with open(plist_path, 'w', encoding='utf-8') as f:
            f.write(plist_content)

        logger.info(f"Created launchd plist: {plist_path}")
        logger.info("Run: launchctl unload ~/Library/LaunchAgents/com.lexfridman_rss_monitor.plist")
        logger.info("Run: launchctl load ~/Library/LaunchAgents/com.lexfridman_rss_monitor.plist")
        return

    # Acquire lock to prevent multiple instances
    lock = FileLock(LOCK_FILE)
    if not lock.acquire():
        logger.warning("Another instance is already running. Exiting.")
        sys.exit(0)

    # Setup signal handler for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        lock.release()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        logger.info("="*60)
        logger.info("Lex Fridman RSS Monitor Started")
        logger.info(f"Time: {datetime.now()}")
        logger.info(f"RSS URL: {RSS_URL}")
        logger.info("="*60)

        if not os.path.exists(PROCESSED_FILE):
            with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
                f.write("")

        # Single check mode
        if args.check_now:
            check_rss_feed()
            return

        # Check if we missed scheduled runs due to sleep
        if should_run_missed_check():
            logger.info("Running missed check after wake...")
            check_rss_feed()

        # Setup scheduler with misfire_grace_time to handle sleep/wake
        scheduler = BackgroundScheduler(
            job_defaults={
                'coalesce': True,  # Combine multiple missed runs into one
                'max_instances': 1,  # Only one instance at a time
                'misfire_grace_time': 3600 * 6  # Allow 6 hours grace period
            }
        )

        scheduler.add_job(
            check_rss_feed,
            CronTrigger(hour=9, minute=0),
            id='morning_job',
            replace_existing=True
        )
        scheduler.add_job(
            check_rss_feed,
            CronTrigger(hour=21, minute=0),
            id='evening_job',
            replace_existing=True
        )
        scheduler.start()

        logger.info("Lex Fridman RSS Monitor service started.")
        logger.info("- Runs at 9:00 AM and 9:00 PM daily")
        logger.info("- Missed runs will be executed on wake (up to 6 hours grace)")
        logger.info("- Failed translations will be retried automatically")

        logger.info("Running initial check...")
        check_rss_feed()

        try:
            while True:
                time.sleep(3600)
                # Periodic check for missed runs (in case scheduler missed it)
                if should_run_missed_check():
                    logger.info("Periodic check: running missed check...")
                    check_rss_feed()
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
