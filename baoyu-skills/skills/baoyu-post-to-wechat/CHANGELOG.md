# Changelog

## 2026-02-10

### Fixed

#### Chrome CDP Connection (`scripts/cdp.ts`)
- Added support for connecting to existing Chrome instance on port 9222
- Script now reuses existing logged-in WeChat tabs instead of creating new ones
- Added retry logic to `clickElement` function (5 retries with 1s delay)
- Improved login detection by checking for existing tabs with valid token

#### Markdown Rendering (`scripts/md/render.ts`)
- Fixed compatibility with marked v17 API changes
- Changed renderer functions to use `text` property instead of deprecated `this.parser.parseInline(tokens)`
- Updated affected functions: `heading`, `paragraph`, `blockquote`, `strong`, `em`, `table`, `tablecell`, `listitem`, `link`

#### WeChat Article Posting (`scripts/wechat-article.ts`)
- Added re-click on `.ProseMirror` editor before paste to ensure focus
- Improved content paste reliability

### Usage Notes

#### Running with Existing Chrome
To use with an existing Chrome instance, start Chrome with remote debugging enabled:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

Then run the script:
```bash
NO_PROXY=localhost,127.0.0.1 npx -y bun scripts/wechat-article.ts --markdown article.md
```

The `NO_PROXY` environment variable is needed to bypass proxy settings when connecting to localhost.

### Technical Details

#### marked v17 Migration
The marked library v17 changed how renderer functions receive token data. Previously:
```typescript
heading(text: string, level: number) { ... }
```

Now uses token objects:
```typescript
heading({ text, depth, raw }: Tokens.Heading) { ... }
```

#### CDP Connection Flow
1. Try connecting to existing Chrome on port 9222
2. If connected, check for existing logged-in WeChat tabs (URL contains `/cgi-bin/home` and `token=`)
3. If logged-in tab found, reuse it; otherwise create new tab
4. If no Chrome found on 9222, launch new Chrome instance
