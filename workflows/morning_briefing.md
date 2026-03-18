# Workflow: Morning Briefing

## Objective
Fetch the latest market news from the past 7 days across 5 business categories, analyse it with Claude for business impact on Hakarindo / Tjipta Group / R6B Group, and write the enriched results to the Google Sheet that powers the intelligence dashboard.

## Triggers
Run this workflow when the user says any of the following:
- "run the briefing"
- "run market briefing"
- "update the dashboard"
- "morning briefing"
- "run market_briefing"
- "fetch the latest news"

## Pre-flight Checklist
Before running, verify:
1. `.env` file contains all three keys:
   - `ANTHROPIC_API_KEY`
   - `NEWS_API_KEY`
   - `GOOGLE_SHEET_ID`
2. `token.pickle` exists in the project root (Google OAuth token). If missing, run:
   ```
   python3 tools/auth_google.py
   ```
   and complete the browser-based authentication flow.

## Command
```bash
cd "/Users/enricotjioe/Desktop/Claude/VS Code" && python3 tools/market_briefing.py
```

Expected runtime: 3–6 minutes (20 NewsAPI calls + article scraping + 5 Claude analyses).

## Verification
After the script finishes:
1. Open the Google Sheet at: https://docs.google.com/spreadsheets/d/1cHU26DFkgUgjbTRTUAw1f8UJ50ECU1xd9pKTvijxcbg
2. Navigate to the **Morning Briefing** tab
3. Confirm new rows have been added with today's date in column A
4. Verify columns A–L are populated (Date, Category, Headline, Explanation, Hakarindo Impact, Tjipta Impact, R6B Impact, Action, Severity Score, Severity Reason, Urgency, Source URLs)
5. Confirm at least 5–10 rows were written (2–3 items per category × 5 categories)

## Error Handling

### NewsAPI rate limit (HTTP 429 or status: "error")
- **Cause**: Free tier allows 100 requests/day. Each briefing run uses ~20 requests.
- **Fix**: Wait 1 hour and retry. Or reduce `pageSize` from 5 to 3 in `search_news()`.
- **Note**: The `from` date parameter requires at minimum the Developer plan. If you see results ignoring the 7-day filter, your plan may not support it.

### Google Sheets write failure (authentication error)
- **Cause**: `token.pickle` has expired (OAuth tokens expire periodically).
- **Fix**: Delete `token.pickle` and re-run auth:
  ```bash
  rm token.pickle
  python3 tools/auth_google.py
  ```
  Then retry the briefing.

### Article scraping blocked (empty body text)
- **Cause**: Some sites (e.g. kompas.com dynamic pages) block scrapers or use JavaScript rendering.
- **Behaviour**: The `scrape_article_body()` function returns an empty string on failure. Claude falls back to headline-only analysis. This is acceptable degradation — the briefing still runs.
- **No action needed**: The script handles this silently.

### Claude JSON parse error
- **Cause**: Claude occasionally returns malformed JSON or adds extra text outside the JSON array.
- **Behaviour**: The script logs a warning and inserts a placeholder `"No analysis available"` item for that category.
- **Fix if persistent**: Check terminal output for the raw Claude response. If Claude is being cut off, increase `max_tokens` in `analyse_with_claude()` (currently 3000).

### Script crashes mid-run
- **Fix**: Simply re-run. The script appends new rows to the sheet rather than overwriting, so partial results from the failed run remain. You can delete the incomplete rows from the sheet if needed.

## Output Format
The script writes to the **Morning Briefing** tab with these 12 columns:

| Col | Field | Description |
|-----|-------|-------------|
| A | Date | YYYY-MM-DD of the run |
| B | Category | One of 5 topic categories |
| C | Headline | One-sentence news summary |
| D | Explanation | 2–3 paragraph plain-English explanation |
| E | Hakarindo Impact | Specific impact on Hakarindo / Deli Corp |
| F | Tjipta Impact | Specific impact on Tjipta Group |
| G | R6B Impact | Specific impact on R6B Group |
| H | Action | Recommended next step |
| I | Severity Score | Integer 1–10 |
| J | Severity Reason | One sentence rationale for the score |
| K | Urgency | High / Medium / Watch |
| L | Source URLs | Comma-separated real article URLs |

## Dashboard
The HTML dashboard (`hakarindo_terminal.html`) reads from this sheet when `CONFIG.SHEET_ID` and `CONFIG.API_KEY` are set. To display live data:
1. Open `hakarindo_terminal.html` in a text editor
2. Find the `CONFIG` block near the top of the `<script>` section
3. Paste your `GOOGLE_SHEET_ID` into `SHEET_ID`
4. Create a Google API key (Cloud Console → APIs & Services → Credentials → Create API key, restrict to Sheets API)
5. Paste it into `API_KEY`
6. Share the Google Sheet as "Anyone with link can view" (not edit)
7. Open the HTML file in a browser — it will load live data from the sheet
