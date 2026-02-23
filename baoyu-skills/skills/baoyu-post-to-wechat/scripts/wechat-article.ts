import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import process from 'node:process';
import { launchChrome, getPageSession, waitForNewTab, clickElement, typeText, evaluate, sleep, type ChromeSession, type CdpConnection } from './cdp.ts';

const WECHAT_URL = 'https://mp.weixin.qq.com/';

interface ImageInfo {
  placeholder: string;
  localPath: string;
  originalPath: string;
}

interface ArticleOptions {
  title: string;
  content?: string;
  htmlFile?: string;
  markdownFile?: string;
  theme?: string;
  author?: string;
  summary?: string;
  images?: string[];
  contentImages?: ImageInfo[];
  submit?: boolean;
  profileDir?: string;
}

// WeChat inline styles based on wechat-nice theme (optimized for WeChat Official Account)
// Reference: https://markdown.com.cn/editor/ style
const WECHAT_INLINE_STYLES: Record<string, string> = {
  'h1': 'color: rgb(89, 89, 89); font-size: 24px; margin-top: 1.2em; margin-bottom: 0.6em; font-weight: bold; line-height: 1.4;',
  'h2': 'border-bottom: 2px solid rgb(89, 89, 89); margin-bottom: 8px; margin-top: 1.5em; color: rgb(89, 89, 89); font-size: 22px; padding-bottom: 6px; font-weight: bold; line-height: 1.4;',
  'h3': 'color: rgb(89, 89, 89); font-size: 20px; margin-top: 1.2em; margin-bottom: 0.5em; border-left: 4px solid rgb(71, 193, 168); padding-left: 10px; font-weight: bold; line-height: 1.4;',
  'h4': 'color: rgb(89, 89, 89); font-size: 18px; margin-top: 1em; margin-bottom: 0.5em; font-weight: bold; line-height: 1.4;',
  'p': 'margin-top: 8px; margin-bottom: 8px; line-height: 1.75; letter-spacing: 1.5px; text-align: justify; color: #3e3e3e; font-size: 17px; word-spacing: 2px;',
  'blockquote': 'font-style: normal; padding: 12px 16px; line-height: 1.75; border: none; color: #888; background: #f7f7f7; border-left: 4px solid rgb(71, 193, 168); margin: 1em 0; font-size: 16px;',
  'ul': 'padding-left: 1.5em; list-style: disc; margin: 0.8em 0;',
  'ol': 'padding-left: 1.5em; margin: 0.8em 0;',
  'li': 'margin: 0.5em 0; line-height: 1.75; color: #3e3e3e; font-size: 17px;',
  'a': 'color: rgb(71, 193, 168); border-bottom: 1px solid rgb(71, 193, 168); text-decoration: none;',
  'strong': 'color: rgb(89, 89, 89); font-weight: bold;',
  'em': 'color: rgb(71, 193, 168); font-style: italic;',
  'code': 'color: rgb(71, 193, 168); background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 90%; font-family: Menlo, Monaco, Consolas, monospace;',
  'pre': 'background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; margin: 1em 0; font-size: 14px; line-height: 1.6;',
  'table': 'border-collapse: collapse; width: 100%; margin: 1em 0;',
  'th': 'font-size: 16px; border: 1px solid #ccc; padding: 10px 14px; text-align: left; background: #f5f5f5; font-weight: bold;',
  'td': 'font-size: 16px; border: 1px solid #ccc; padding: 10px 14px; text-align: left;',
  'hr': 'height: 1px; border: none; margin: 2em 0; background: linear-gradient(to right, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.2), rgba(0, 0, 0, 0));',
  'img': 'max-width: 100%; border-radius: 4px; margin: 1em 0; display: block;',
  'figcaption': 'text-align: center; color: #888; font-size: 14px; margin-top: 8px;',
  'figure': 'margin: 1em 0; text-align: center;',
  'section': 'font-family: -apple-system-font, BlinkMacSystemFont, Helvetica Neue, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, Microsoft YaHei, Arial, sans-serif; font-size: 17px; line-height: 1.75; text-align: left; color: #3e3e3e;',
};

function addInlineStylesToHtml(html: string): string {
  let result = html;

  // Remove class attributes and add inline styles
  for (const [tag, style] of Object.entries(WECHAT_INLINE_STYLES)) {
    // Match opening tags with or without class attribute, preserving other attributes
    const tagRegex = new RegExp(`<${tag}(\\s+class="[^"]*")?(\\s+[^>]*)?>`, 'gi');
    result = result.replace(tagRegex, (match, classAttr, otherAttrs) => {
      const attrs = otherAttrs ? otherAttrs.trim() : '';
      // Check if style already exists
      if (attrs.includes('style="')) {
        // Merge styles
        return match.replace(/style="([^"]*)"/, `style="${style} $1"`);
      }
      return `<${tag} style="${style}"${attrs ? ' ' + attrs : ''}>`;
    });
  }

  // Remove bullet prefix from list items (WeChat adds its own)
  result = result.replace(/<li([^>]*)>•\s*/gi, '<li$1>');

  // Clean up any remaining class attributes that weren't handled
  result = result.replace(/\s+class="[^"]*"/gi, '');

  // Remove any data- attributes that might cause issues
  result = result.replace(/\s+data-[a-z-]+="[^"]*"/gi, '');

  return result;
}

async function waitForLogin(session: ChromeSession, timeoutMs = 120_000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const url = await evaluate<string>(session, 'window.location.href');
    if (url.includes('/cgi-bin/home')) return true;
    await sleep(2000);
  }
  return false;
}

async function clickMenuByText(session: ChromeSession, text: string): Promise<void> {
  console.log(`[wechat] Clicking "${text}" menu...`);
  const posResult = await session.cdp.send<{ result: { value: string } }>('Runtime.evaluate', {
    expression: `
      (function() {
        const items = document.querySelectorAll('.new-creation__menu .new-creation__menu-item');
        for (const item of items) {
          const title = item.querySelector('.new-creation__menu-title');
          if (title && title.textContent?.trim() === '${text}') {
            item.scrollIntoView({ block: 'center' });
            const rect = item.getBoundingClientRect();
            return JSON.stringify({ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 });
          }
        }
        return 'null';
      })()
    `,
    returnByValue: true,
  }, { sessionId: session.sessionId });

  if (posResult.result.value === 'null') throw new Error(`Menu "${text}" not found`);
  const pos = JSON.parse(posResult.result.value);

  await session.cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: pos.x, y: pos.y, button: 'left', clickCount: 1 }, { sessionId: session.sessionId });
  await sleep(100);
  await session.cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: pos.x, y: pos.y, button: 'left', clickCount: 1 }, { sessionId: session.sessionId });
}

async function copyImageToClipboard(imagePath: string): Promise<boolean> {
  const scriptDir = path.dirname(new URL(import.meta.url).pathname);
  const copyScript = path.join(scriptDir, './copy-to-clipboard.ts');
  const result = spawnSync('npx', ['-y', 'bun', copyScript, 'image', imagePath], { stdio: 'pipe' });
  if (result.status !== 0) {
    console.warn(`[wechat] Warning: Failed to copy image: ${imagePath}`);
    return false;
  }
  return true;
}

async function pasteInEditor(session: ChromeSession): Promise<void> {
  const modifiers = process.platform === 'darwin' ? 4 : 2;
  await session.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'v', code: 'KeyV', modifiers, windowsVirtualKeyCode: 86 }, { sessionId: session.sessionId });
  await sleep(50);
  await session.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'v', code: 'KeyV', modifiers, windowsVirtualKeyCode: 86 }, { sessionId: session.sessionId });
}

async function copyHtmlFromBrowser(cdp: CdpConnection, htmlFilePath: string): Promise<void> {
  const absolutePath = path.isAbsolute(htmlFilePath) ? htmlFilePath : path.resolve(process.cwd(), htmlFilePath);
  const fileUrl = `file://${absolutePath}`;

  console.log(`[wechat] Opening HTML file in new tab: ${fileUrl}`);

  const { targetId } = await cdp.send<{ targetId: string }>('Target.createTarget', { url: fileUrl });
  const { sessionId } = await cdp.send<{ sessionId: string }>('Target.attachToTarget', { targetId, flatten: true });

  await cdp.send('Page.enable', {}, { sessionId });
  await cdp.send('Runtime.enable', {}, { sessionId });
  await sleep(2000);

  console.log('[wechat] Selecting #output content...');
  await cdp.send<{ result: { value: unknown } }>('Runtime.evaluate', {
    expression: `
      (function() {
        const output = document.querySelector('#output') || document.body;
        const range = document.createRange();
        range.selectNodeContents(output);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        return true;
      })()
    `,
    returnByValue: true,
  }, { sessionId });
  await sleep(500);

  // 激活Chrome窗口并发送Cmd+C
  console.log('[wechat] Activating Chrome and copying...');
  if (process.platform === 'darwin') {
    spawnSync('osascript', ['-e', 'tell application "Google Chrome" to activate']);
    await sleep(300);
    spawnSync('osascript', ['-e', 'tell application "System Events" to keystroke "c" using command down']);
  } else {
    spawnSync('xdotool', ['key', 'ctrl+c']);
  }
  await sleep(1000);

  console.log('[wechat] Closing HTML tab...');
  await cdp.send('Target.closeTarget', { targetId });
}

async function pasteFromClipboardInEditor(): Promise<void> {
  if (process.platform === 'darwin') {
    spawnSync('osascript', ['-e', 'tell application "Google Chrome" to activate']);
    await sleep(300);
    spawnSync('osascript', ['-e', 'tell application "System Events" to keystroke "v" using command down']);
  } else {
    spawnSync('xdotool', ['key', 'ctrl+v']);
  }
  await sleep(1000);
}

async function parseMarkdownWithPlaceholders(markdownPath: string, theme?: string): Promise<{ title: string; author: string; summary: string; htmlPath: string; contentImages: ImageInfo[] }> {
  const scriptDir = path.dirname(new URL(import.meta.url).pathname);
  const mdToWechatScript = path.join(scriptDir, 'md-to-wechat.ts');
  const args = ['-y', 'bun', mdToWechatScript, markdownPath];
  if (theme) args.push('--theme', theme);

  const result = spawnSync('npx', args, { stdio: ['inherit', 'pipe', 'pipe'] });
  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || '';
    throw new Error(`Failed to parse markdown: ${stderr}`);
  }

  const output = result.stdout.toString();
  return JSON.parse(output);
}

function parseHtmlMeta(htmlPath: string): { title: string; author: string; summary: string } {
  const content = fs.readFileSync(htmlPath, 'utf-8');

  let title = '';
  const titleMatch = content.match(/<title>([^<]+)<\/title>/i);
  if (titleMatch) title = titleMatch[1]!;

  let author = '';
  const authorMatch = content.match(/<meta\s+name=["']author["']\s+content=["']([^"']+)["']/i);
  if (authorMatch) author = authorMatch[1]!;

  let summary = '';
  const descMatch = content.match(/<meta\s+name=["']description["']\s+content=["']([^"']+)["']/i);
  if (descMatch) summary = descMatch[1]!;

  if (!summary) {
    const firstPMatch = content.match(/<p[^>]*>([^<]+)<\/p>/i);
    if (firstPMatch) {
      const text = firstPMatch[1]!.replace(/<[^>]+>/g, '').trim();
      if (text.length > 20) {
        summary = text.length > 120 ? text.slice(0, 117) + '...' : text;
      }
    }
  }

  return { title, author, summary };
}

async function selectAndReplacePlaceholder(session: ChromeSession, placeholder: string): Promise<boolean> {
  const result = await session.cdp.send<{ result: { value: boolean } }>('Runtime.evaluate', {
    expression: `
      (function() {
        const editor = document.querySelector('.ProseMirror');
        if (!editor) return false;

        const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT, null, false);
        let node;

        while ((node = walker.nextNode())) {
          const text = node.textContent || '';
          const idx = text.indexOf(${JSON.stringify(placeholder)});
          if (idx !== -1) {
            node.parentElement.scrollIntoView({ behavior: 'smooth', block: 'center' });

            const range = document.createRange();
            range.setStart(node, idx);
            range.setEnd(node, idx + ${placeholder.length});
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            return true;
          }
        }
        return false;
      })()
    `,
    returnByValue: true,
  }, { sessionId: session.sessionId });

  return result.result.value;
}

async function pressDeleteKey(session: ChromeSession): Promise<void> {
  await session.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 }, { sessionId: session.sessionId });
  await sleep(50);
  await session.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 }, { sessionId: session.sessionId });
}

export async function postArticle(options: ArticleOptions): Promise<void> {
  const { title, content, htmlFile, markdownFile, theme, author, summary, images = [], submit = false, profileDir } = options;
  let { contentImages = [] } = options;
  let effectiveTitle = title || '';
  let effectiveAuthor = author || '';
  let effectiveSummary = summary || '';
  let effectiveHtmlFile = htmlFile;

  if (markdownFile) {
    console.log(`[wechat] Parsing markdown: ${markdownFile}`);
    const parsed = await parseMarkdownWithPlaceholders(markdownFile, theme);
    effectiveTitle = effectiveTitle || parsed.title;
    effectiveAuthor = effectiveAuthor || parsed.author;
    effectiveSummary = effectiveSummary || parsed.summary;
    effectiveHtmlFile = parsed.htmlPath;
    contentImages = parsed.contentImages;
    console.log(`[wechat] Title: ${effectiveTitle || '(empty)'}`);
    console.log(`[wechat] Author: ${effectiveAuthor || '(empty)'}`);
    console.log(`[wechat] Summary: ${effectiveSummary || '(empty)'}`);
    console.log(`[wechat] Found ${contentImages.length} images to insert`);
  } else if (htmlFile && fs.existsSync(htmlFile)) {
    console.log(`[wechat] Parsing HTML: ${htmlFile}`);
    const meta = parseHtmlMeta(htmlFile);
    effectiveTitle = effectiveTitle || meta.title;
    effectiveAuthor = effectiveAuthor || meta.author;
    effectiveSummary = effectiveSummary || meta.summary;
    effectiveHtmlFile = htmlFile;
    console.log(`[wechat] Title: ${effectiveTitle || '(empty)'}`);
    console.log(`[wechat] Author: ${effectiveAuthor || '(empty)'}`);
    console.log(`[wechat] Summary: ${effectiveSummary || '(empty)'}`);
  }

  if (effectiveTitle && effectiveTitle.length > 64) throw new Error(`Title too long: ${effectiveTitle.length} chars (max 64)`);
  if (!content && !effectiveHtmlFile) throw new Error('Either --content, --html, or --markdown is required');

  const { cdp, chrome } = await launchChrome(WECHAT_URL, profileDir);

  try {
    console.log('[wechat] Waiting for page load...');
    await sleep(3000);

    // 优先查找已登录的页面（URL包含token）
    const targets = await cdp.send<{ targetInfos: Array<{ targetId: string; url: string; type: string }> }>('Target.getTargets');
    let loggedInTarget = targets.targetInfos.find(t => t.type === 'page' && t.url.includes('/cgi-bin/home') && t.url.includes('token='));

    let session: ChromeSession;
    if (loggedInTarget) {
      console.log('[wechat] Found logged-in tab, using it...');
      const { sessionId } = await cdp.send<{ sessionId: string }>('Target.attachToTarget', { targetId: loggedInTarget.targetId, flatten: true });
      await cdp.send('Page.enable', {}, { sessionId });
      await cdp.send('Runtime.enable', {}, { sessionId });
      await cdp.send('DOM.enable', {}, { sessionId });
      session = { cdp, sessionId, targetId: loggedInTarget.targetId };
    } else {
      session = await getPageSession(cdp, 'mp.weixin.qq.com');
      const url = await evaluate<string>(session, 'window.location.href');
      if (!url.includes('/cgi-bin/home')) {
        console.log('[wechat] Not logged in. Please scan QR code...');
        const loggedIn = await waitForLogin(session);
        if (!loggedIn) throw new Error('Login timeout');
      }
    }
    console.log('[wechat] Logged in.');
    await sleep(2000);

    const targets2 = await cdp.send<{ targetInfos: Array<{ targetId: string; url: string; type: string }> }>('Target.getTargets');
    const initialIds = new Set(targets2.targetInfos.map(t => t.targetId));

    await clickMenuByText(session, '文章');
    await sleep(3000);

    const editorTargetId = await waitForNewTab(cdp, initialIds, 'mp.weixin.qq.com');
    console.log('[wechat] Editor tab opened.');

    const { sessionId } = await cdp.send<{ sessionId: string }>('Target.attachToTarget', { targetId: editorTargetId, flatten: true });
    session = { cdp, sessionId, targetId: editorTargetId };

    await cdp.send('Page.enable', {}, { sessionId });
    await cdp.send('Runtime.enable', {}, { sessionId });
    await cdp.send('DOM.enable', {}, { sessionId });

    // 等待页面完全加载
    console.log('[wechat] Waiting for page to fully load...');
    await sleep(5000);

    // 填入标题（带重试）
    if (effectiveTitle) {
      console.log('[wechat] Filling title...');
      for (let i = 0; i < 3; i++) {
        try {
          await evaluate(session, `
            (function() {
              const titleInput = document.querySelector('#title') || document.querySelector('input[placeholder*="标题"]');
              if (titleInput) {
                titleInput.value = ${JSON.stringify(effectiveTitle)};
                titleInput.dispatchEvent(new Event('input', { bubbles: true }));
                titleInput.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
              }
              return false;
            })()
          `);
          console.log('[wechat] Title filled successfully');
          break;
        } catch (e) {
          console.log(`[wechat] Title fill attempt ${i + 1} failed, retrying...`);
          await sleep(1000);
        }
      }
    }

    // 填入作者
    if (effectiveAuthor) {
      console.log('[wechat] Filling author...');
      try {
        await evaluate(session, `
          (function() {
            const authorInput = document.querySelector('#author') || document.querySelector('input[placeholder*="作者"]');
            if (authorInput) {
              authorInput.value = ${JSON.stringify(effectiveAuthor)};
              authorInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
          })()
        `);
      } catch (e) {
        console.log('[wechat] Author fill skipped');
      }
    }

    // 等待编辑器加载
    console.log('[wechat] Waiting for editor to load...');
    await sleep(2000);

    // 点击编辑器
    console.log('[wechat] Clicking on editor...');
    try {
      await clickElement(session, '.ProseMirror');
    } catch (e) {
      console.log('[wechat] Could not click .ProseMirror, trying alternative...');
      try {
        await clickElement(session, '[contenteditable="true"]');
      } catch (e2) {
        console.log('[wechat] Could not find editor element');
      }
    }
    await sleep(1000);

    if (effectiveHtmlFile && fs.existsSync(effectiveHtmlFile)) {
      console.log(`[wechat] Reading HTML content from: ${effectiveHtmlFile}`);
      const htmlContent = fs.readFileSync(effectiveHtmlFile, 'utf-8');

      // 提取 #output 内部的内容
      const outputMatch = htmlContent.match(/<div id="output">([\s\S]*?)<\/div>\s*<\/body>/);
      if (!outputMatch) {
        throw new Error('Could not find #output content in HTML file');
      }
      const rawOutputHtml = outputMatch[1].trim();

      // 添加内联样式以便在微信编辑器中正确显示
      console.log('[wechat] Adding inline styles for WeChat editor...');
      const outputHtml = addInlineStylesToHtml(rawOutputHtml);

      console.log('[wechat] Inserting content into editor via innerHTML...');
      const insertResult = await evaluate(session, `
        (function() {
          // 尝试多种选择器找到编辑器
          let editor = document.querySelector('.ProseMirror') || 
                       document.querySelector('[contenteditable="true"]') ||
                       document.querySelector('#js_editor');
          
          if (!editor) {
            // 如果找不到，尝试在 iframe 中找
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
              try {
                const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
                if (iframeDoc) {
                  editor = iframeDoc.querySelector('.ProseMirror') || 
                          iframeDoc.querySelector('[contenteditable="true"]');
                  if (editor) break;
                }
              } catch (e) {}
            }
          }
          
          if (editor) {
            // 清空现有内容
            editor.innerHTML = '';
            
            // 插入新内容
            editor.innerHTML = ${JSON.stringify(outputHtml)};
            
            // 触发多种事件确保内容被识别
            editor.dispatchEvent(new Event('input', { bubbles: true }));
            editor.dispatchEvent(new Event('change', { bubbles: true }));
            editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
            editor.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }));
            
            // 滚动到顶部
            editor.scrollTop = 0;
            
            return { success: true, htmlLength: ${JSON.stringify(outputHtml)}.length };
          }
          
          return { success: false, error: 'Editor not found' };
        })()
      `);
      
      if (insertResult && insertResult.success) {
        console.log('[wechat] Content inserted successfully, length:', insertResult.htmlLength);
      } else {
        console.error('[wechat] Failed to insert content:', insertResult?.error || 'Unknown error');
      }
      
      await sleep(3000);

      if (contentImages.length > 0) {
        console.log(`[wechat] Inserting ${contentImages.length} images...`);
        for (let i = 0; i < contentImages.length; i++) {
          const img = contentImages[i]!;
          console.log(`[wechat] [${i + 1}/${contentImages.length}] Processing: ${img.placeholder}`);

          const found = await selectAndReplacePlaceholder(session, img.placeholder);
          if (!found) {
            console.warn(`[wechat] Placeholder not found: ${img.placeholder}`);
            continue;
          }

          await sleep(500);

          console.log(`[wechat] Copying image: ${path.basename(img.localPath)}`);
          const copied = await copyImageToClipboard(img.localPath);
          if (!copied) {
            console.warn(`[wechat] Skipping image due to copy failure`);
            continue;
          }
          await sleep(300);

          console.log('[wechat] Deleting placeholder with Backspace...');
          await pressDeleteKey(session);
          await sleep(200);

          console.log('[wechat] Pasting image...');
          await pasteFromClipboardInEditor();
          await sleep(3000);
        }
        console.log('[wechat] All images inserted.');
      }
    } else if (content) {
      for (const img of images) {
        if (fs.existsSync(img)) {
          console.log(`[wechat] Pasting image: ${img}`);
          await copyImageToClipboard(img);
          await sleep(500);
          await pasteInEditor(session);
          await sleep(2000);
        }
      }

      console.log('[wechat] Typing content...');
      await typeText(session, content);
      await sleep(1000);
    }

    if (effectiveSummary) {
      console.log(`[wechat] Filling summary: ${effectiveSummary}`);
      await evaluate(session, `document.querySelector('#js_description').value = ${JSON.stringify(effectiveSummary)}; document.querySelector('#js_description').dispatchEvent(new Event('input', { bubbles: true }));`);
    }

    console.log('[wechat] Saving as draft...');
    await evaluate(session, `document.querySelector('#js_submit button').click()`);
    await sleep(3000);

    const saved = await evaluate<boolean>(session, `!!document.querySelector('.weui-desktop-toast')`);
    if (saved) {
      console.log('[wechat] Draft saved successfully!');
    } else {
      console.log('[wechat] Waiting for save confirmation...');
      await sleep(5000);
    }

    console.log('[wechat] Done. Browser window left open.');
  } finally {
    cdp.close();
  }
}

function printUsage(): never {
  console.log(`Post article to WeChat Official Account

Usage:
  npx -y bun wechat-article.ts [options]

Options:
  --title <text>     Article title (auto-extracted from markdown)
  --content <text>   Article content (use with --image)
  --html <path>      HTML file to paste (alternative to --content)
  --markdown <path>  Markdown file to convert and post (recommended)
  --theme <name>     Theme for markdown (default, grace, simple)
  --author <name>    Author name (default: 宝玉)
  --summary <text>   Article summary
  --image <path>     Content image, can repeat (only with --content)
  --submit           Save as draft
  --profile <dir>    Chrome profile directory

Examples:
  npx -y bun wechat-article.ts --markdown article.md
  npx -y bun wechat-article.ts --markdown article.md --theme grace --submit
  npx -y bun wechat-article.ts --title "标题" --content "内容" --image img.png
  npx -y bun wechat-article.ts --title "标题" --html article.html --submit

Markdown mode:
  Images in markdown are converted to placeholders. After pasting HTML,
  each placeholder is selected, scrolled into view, deleted, and replaced
  with the actual image via paste.
`);
  process.exit(0);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) printUsage();

  const images: string[] = [];
  let title: string | undefined;
  let content: string | undefined;
  let htmlFile: string | undefined;
  let markdownFile: string | undefined;
  let theme: string | undefined;
  let author: string | undefined;
  let summary: string | undefined;
  let submit = false;
  let profileDir: string | undefined;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i]!;
    if (arg === '--title' && args[i + 1]) title = args[++i];
    else if (arg === '--content' && args[i + 1]) content = args[++i];
    else if (arg === '--html' && args[i + 1]) htmlFile = args[++i];
    else if (arg === '--markdown' && args[i + 1]) markdownFile = args[++i];
    else if (arg === '--theme' && args[i + 1]) theme = args[++i];
    else if (arg === '--author' && args[i + 1]) author = args[++i];
    else if (arg === '--summary' && args[i + 1]) summary = args[++i];
    else if (arg === '--image' && args[i + 1]) images.push(args[++i]!);
    else if (arg === '--submit') submit = true;
    else if (arg === '--profile' && args[i + 1]) profileDir = args[++i];
  }

  if (!markdownFile && !htmlFile && !title) { console.error('Error: --title is required (or use --markdown/--html)'); process.exit(1); }
  if (!markdownFile && !htmlFile && !content) { console.error('Error: --content, --html, or --markdown is required'); process.exit(1); }

  await postArticle({ title: title || '', content, htmlFile, markdownFile, theme, author, summary, images, submit, profileDir });
}

await main().catch((err) => {
  console.error(`Error: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
