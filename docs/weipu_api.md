# WeiPu (CQVIP) Journal Article Extraction API

**Version**: 2.0.0
**Date**: 2026-02-01
**Technology Stack**: Python + httpx + selectolax + Node.js

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Data Structures](#data-structures)
- [Implementation Details](#implementation-details)
- [Error Handling](#error-handling)
- [Performance](#performance)
- [Best Practices](#best-practices)
- [Complete Examples](#complete-examples)
- [Troubleshooting](#troubleshooting)

---

## Overview

### What is WeiPu API?

The WeiPu API is a Python library for extracting academic journal article metadata from the CQVIP (China Science Periodical Database) website at https://www.cqvip.com/.

### Key Features

- ✅ **Fast**: 3-5x faster than browser-based solutions (1-3s per request vs 8-10s)
- ✅ **Lightweight**: Uses only 60 MB RAM (vs 1.3 GB for Playwright)
- ✅ **Reliable**: Uses selectolax HTML parser for robust extraction
- ✅ **Complete**: Extracts 30+ metadata fields per article
- ✅ **Async**: Built with asyncio for efficient concurrent requests

### What Data Can You Extract?

**Journal Level**:
- Journal ID, name, ISSN, CN number
- Publisher information
- All available years and issues

**Issue Level**:
- All articles in a specific issue
- Article categorization

**Article Level**:
- Title (Chinese/English)
- Authors (names, order, corresponding author flag)
- Keywords
- Abstract
- Page numbers (start, end, count)
- DOI
- Funding information
- Author affiliations
- Classification codes

---

## Architecture

### Technology Stack

```
┌─────────────────────────────────────────────┐
│           Python Application                │
│  ┌─────────────────────────────────────┐   │
│  │   WeipuAPISelectolax                │   │
│  │                                     │   │
│  │  ┌──────────┐  ┌──────────────┐   │   │
│  │  │  httpx   │  │  selectolax  │   │   │
│  │  └────┬─────┘  └──────┬───────┘   │   │
│  │       │                │           │   │
│  │       ▼                ▼           │   │
│  │   HTTP Request    HTML Parsing    │   │
│  └───────────────┬────────────────────┘   │
│                  │                         │
│                  ▼                         │
│         Extract <script> tag              │
│         containing window.__NUXT__        │
│                  │                         │
│                  ▼                         │
│  ┌───────────────────────────────────┐   │
│  │    JavaScript Execution           │   │
│  │    ┌─────────────────────────┐   │   │
│  │    │      Node.js             │   │   │
│  │    │  (subprocess.run)        │   │   │
│  │    └──────────┬──────────────┘   │   │
│  │               │                   │   │
│  │               ▼                   │   │
│  │      Evaluate obfuscated JS      │   │
│  │      Return JSON data             │   │
│  └───────────────┬───────────────────┘   │
│                  │                         │
│                  ▼                         │
│         Parse JSON & Extract Data         │
└─────────────────────────────────────────────┘
```

### How It Works

1. **HTTP Request**: Use `httpx` to fetch HTML from CQVIP website
2. **HTML Parsing**: Use `selectolax` to parse HTML and find `<script>` tags
3. **Script Extraction**: Locate the script containing `window.__NUXT__` object
4. **JS Execution**: Execute obfuscated JavaScript using Node.js subprocess
5. **Data Extraction**: Parse JSON output and extract article metadata

### Why This Architecture?

**Problem**: CQVIP uses Nuxt.js SSR (Server-Side Rendering). The data is embedded in HTML as an obfuscated JavaScript function:

```javascript
window.__NUXT__=(function(a,b,c,d,e,f,g,...){
  return {layout:"default",data:[...],state:{...}}
})(null,1,"正常","龙猫",2,false,...)
```

This cannot be parsed as plain JSON - it must be executed as JavaScript.

**Solution**:
1. Use `selectolax` (not regex) for reliable HTML parsing
2. Use Node.js to execute the obfuscated JavaScript
3. Parse the resulting JSON data

---

## Installation

### Prerequisites

1. **Python 3.8+**
   ```bash
   python --version  # Should be >= 3.8
   ```

2. **Node.js** (Required for JavaScript execution)
   ```bash
   node --version  # Should be >= v14.0.0
   ```

   Download: https://nodejs.org/

### Install Python Dependencies

```bash
pip install httpx selectolax
# or with uv
uv pip install httpx selectolax
```

### Verify Installation

```bash
python -c "import httpx, selectolax; print('OK')"
node --version
```

---

## Quick Start

### Basic Usage

```python
import asyncio
from weipu_api_selectolax import WeipuAPISelectolax

async def main():
    api = WeipuAPISelectolax()

    # 1. Search journal by ISSN
    journal = await api.search_journal_by_issn("1002-5502")
    print(f"Found: {journal['name']}")
    # Output: Found: 管理世界

    # 2. Get journal details (all years and issues)
    details = await api.get_journal_details(journal['journalId'])
    print(f"Years: {details['totalYears']}, Issues: {details['totalIssues']}")
    # Output: Years: 41, Issues: 492

    # 3. Get articles from a specific issue
    issue_id = details['years'][0]['issues'][0]['id']
    articles = await api.get_issue_articles(
        journal['journalId'],
        issue_id
    )

    # 4. Print results
    print(f"\nArticles in this issue: {articles['totalArticles']}")
    for i, article in enumerate(articles['articles'][:3], 1):
        print(f"{i}. {article['title']}")
        authors = [a['name'] for a in article['authors']]
        print(f"   Authors: {', '.join(authors)}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Expected Output

```
Found: 管理世界
Years: 41, Issues: 492

Articles in this issue: 20
1. 美欧关税与全球新能源汽车供应链的重构
   Authors: 李坤望, 王方
2. 数实技术融合与企业出口韧性
   Authors: 谢谦, 李骏, 熊维勤
3. 贸易暴露对中国碳配额市场的影响——基于欧盟碳边境调节机制的视角
   Authors: 李星光, 黄树青, 张德远
```

---

## API Reference

### Class: `WeipuAPISelectolax`

Main class for interacting with the CQVIP website.

```python
from weipu_api_selectolax import WeipuAPISelectolax

api = WeipuAPISelectolax()
```

---

### Method: `search_journal_by_issn()`

Search for a journal using its ISSN number.

#### Signature

```python
async def search_journal_by_issn(
    issn: str
) -> Optional[Dict[str, Any]]
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issn` | `str` | Yes | The ISSN number of the journal (e.g., "1002-5502") |

#### Returns

Returns a dictionary containing journal information, or `None` if not found.

**Success Response**:
```python
{
    "journalId": "95499X",          # Journal ID (used in other API calls)
    "name": "管理世界",              # Journal name (Chinese)
    "issn": "1002-5502",             # ISSN number
    "cnno": "11-1235/F",             # CN number (Chinese serial number)
    "publisher": "...",              # Publisher name
    "url": "https://www.cqvip.com/journal/95499X/95499X"
}
```

**Error Response**: `None`

#### Example

```python
journal = await api.search_journal_by_issn("1002-5502")
if journal:
    print(f"Journal ID: {journal['journalId']}")
    print(f"Name: {journal['name']}")
else:
    print("Journal not found")
```

#### Common ISSN Numbers

| ISSN | Journal Name | Field |
|------|-------------|-------|
| 1002-5502 | 管理世界 | Management |
| 1000-6788 | 会计研究 | Accounting |
| 1002-0241 | 经济学动态 | Economics |

#### Error Cases

- Returns `None` if ISSN not found
- Returns `None` if HTTP request fails
- Returns `None` if data extraction fails

---

### Method: `get_journal_details()`

Get complete details about a journal, including all years and issues.

#### Signature

```python
async def get_journal_details(
    journal_id: str
) -> Optional[Dict[str, Any]]
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `journal_id` | `str` | Yes | Journal ID obtained from `search_journal_by_issn()` |

#### Returns

Returns a dictionary containing journal details and issue list.

**Note**: The CQVIP HTML page usually embeds full issue lists only for the most
recent year. The client automatically falls back to the signed `/newsite`
endpoints (`/journal/getYears` and `/journal/getNums`) to retrieve all years and
issue IDs.

**Success Response**:
```python
{
    "journalId": "95499X",
    "journalName": "管理世界",
    "issn": "1002-5502",
    "cnno": "11-1235/F",
    "years": [                        # List of years (newest first)
        {
            "year": 2025,             # Year
            "issueCount": 12,         # Number of issues in this year
            "issues": [               # List of issues
                {
                    "id": "8687909",  # Issue ID (for get_issue_articles)
                    "name": "12",     # Issue number/name
                    "coverImage": "https://..."  # Cover image URL
                },
                # ... more issues
            ]
        },
        # ... more years
    ],
    "totalYears": 41,                 # Total number of years
    "totalIssues": 492                # Total number of issues
}
```

**Error Response**: `None`

#### Example

```python
details = await api.get_journal_details("95499X")

print(f"Total years: {details['totalYears']}")
print(f"Total issues: {details['totalIssues']}")

# Get latest issue
latest_year = details['years'][0]
latest_issue = latest_year['issues'][0]

print(f"Latest: {latest_year['year']} Issue {latest_issue['name']}")
print(f"Issue ID: {latest_issue['id']}")
```

#### Data Structure Details

**Years Array**: Sorted by year in descending order (newest first)

**Issues Array**: Order depends on the journal's publication schedule. Typically sorted by issue number.

**Issue ID**: This is the critical identifier needed for `get_issue_articles()`.

#### Error Cases

- Returns `None` if journal ID not found
- Returns `None` if HTTP request fails
- Returns `None` if data structure is unexpected

---

### Method: `get_issue_articles()`

Extract all articles from a specific journal issue with complete metadata.

#### Signature

```python
async def get_issue_articles(
    journal_id: str,
    issue_id: str
) -> Optional[Dict[str, Any]]
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `journal_id` | `str` | Yes | Journal ID (e.g., "95499X") |
| `issue_id` | `str` | Yes | Issue ID obtained from `get_journal_details()` |

#### Returns

Returns a dictionary containing article list and metadata.

**Note**: The issue page does not always include abstract, DOI, or publish date.
The client follows the `/doc/journal/{articleId}` links (already present on the
issue page) and merges `abstr`, `doi`, and `pubDate` into the article records.

**Success Response**:
```python
{
    "journal": {                      # Journal information
        "journalId": "95499X",
        "journalName": "管理世界",
        "issn": "1002-5502",
        "cnno": "11-1235/F"
    },
    "issueId": "8687909",             # Issue ID
    "totalArticles": 20,              # Total number of articles
    "totalPages": 223,                # Total page count in this issue
    "articles": [                     # Array of articles
        {
            "id": "7202582565",       # Article ID
            "title": "美欧关税与全球新能源汽车供应链的重构",  # Title
            "category": "重大选题征文",  # Category/Section
            "detailUrl": "https://www.cqvip.com/doc/journal/7202582565?sign=...",
            "authors": [               # Authors array
                {
                    "name": "李坤望",   # Chinese name
                    "name_en": "Li Kunwang",  # English name
                    "is_corresponding": False,  # Corresponding author flag
                    "order": 1         # Author order
                },
                {
                    "name": "王方",
                    "name_en": "Wang Fang",
                    "is_corresponding": True,  # This is corresponding author
                    "order": 2
                }
            ],
            "firstAuthor": {           # First author (separate field)
                "name": "李坤望",
                "id": 3759
            },
            "keywords": [              # Keywords array
                "关税",
                "新能源汽车",
                "供应链"
            ],
            "abstract": "文章摘要内容...",  # Abstract (Chinese)
            "pages": {                 # Page information
                "begin": "1",          # Start page
                "end": "20",           # End page
                "count": 20            # Total pages
            },
            "language": "zh",          # Language code (zh/en)
            "isPdf": True,             # PDF available flag
            "doi": "10.19744/j...",   # DOI
            "funds": [                 # Funding sources
                "国家自然科学基金",
                "教育部人文社会科学研究项目"
            ],
            "organizations": [         # Author affiliations
                "浙江大学经济学院",
                "中国人民大学商学院"
            ]
        },
        // ... more articles (19 more in this example)
    ]
}
```

**Error Response**: `None`

#### Example

```python
# Get articles from issue
articles = await api.get_issue_articles("95499X", "8687909")

print(f"Total articles: {articles['totalArticles']}")
print(f"Total pages: {articles['totalPages']}")

# Iterate through articles
for article in articles['articles']:
    print(f"\nTitle: {article['title']}")

    # Print authors
    authors_str = ', '.join([
        f"{a['name']}{'*' if a['is_corresponding'] else ''}"
        for a in article['authors']
    ])
    print(f"Authors: {authors_str}")

    # Print keywords
    if article['keywords']:
        print(f"Keywords: {', '.join(article['keywords'])}")

    # Print page range
    pages = article['pages']
    print(f"Pages: {pages['begin']}-{pages['end']} ({pages['count']} pages)")
```

#### Field Details

##### Author Information

**Structure**:
```python
{
    "name": str,              # Chinese name (always present)
    "name_en": str or None,   # English name (may be None)
    "is_corresponding": bool, # True if corresponding author
    "order": int              # Author order (1-indexed)
}
```

**Corresponding Author**: Marked with `is_corresponding: True`. Only one author typically has this flag.

**Author Order**: Indicates authorship sequence. Important for citation purposes.

##### Page Information

**Structure**:
```python
{
    "begin": str,    # Start page (e.g., "1", "23")
    "end": str,      # End page (e.g., "20", "45")
    "count": int     # Total page count (may be None for some articles)
}
```

**Note**: Some non-article entries (e.g., advertisements, announcements) may have `count: None`.

##### Categories

Articles are grouped into categories/sections such as:
- "重大选题征文" (Major Topic Call for Papers)
- "经济学" (Economics)
- "管理学" (Management)
- "研究论文" (Research Articles)

##### Language Codes

- `"zh"`: Chinese
- `"en"`: English
- `"zh_en"`: Bilingual

#### Performance

- **Speed**: ~2-3 seconds per issue
- **Memory**: ~60 MB RAM
- **Success Rate**: ~90% (with proper rate limiting)

#### Error Cases

- Returns `None` if issue not found (404)
- Returns `None` if HTTP request fails
- Returns `None` if JavaScript execution fails
- Returns `None` if data extraction fails

---

## Data Structures

### Complete Type Definitions

```python
from typing import TypedDict, List, Optional

class Author(TypedDict):
    name: str                    # Chinese name
    name_en: Optional[str]       # English name (may be None)
    is_corresponding: bool       # Corresponding author flag
    order: int                   # Author order (1-indexed)

class FirstAuthor(TypedDict):
    name: str                    # Author name
    id: int                      # Author ID in database

class PageInfo(TypedDict):
    begin: str                   # Start page number
    end: str                     # End page number
    count: Optional[int]         # Total pages (may be None)

class Article(TypedDict):
    id: str                      # Article ID
    title: str                   # Article title
    category: str                # Category/section name
    authors: List[Author]        # List of authors
    firstAuthor: Optional[FirstAuthor]  # First author info
    keywords: List[str]          # List of keywords
    abstract: Optional[str]      # Abstract text
    pages: PageInfo              # Page information
    language: str                # Language code (zh/en)
    isPdf: bool                  # PDF availability
    doi: Optional[str]           # DOI
    funds: List[str]             # Funding sources
    organizations: List[str]     # Author affiliations

class JournalInfo(TypedDict):
    journalId: str               # Journal ID
    journalName: str             # Journal name
    issn: str                    # ISSN number
    cnno: str                    # CN number

class Issue(TypedDict):
    id: str                      # Issue ID
    name: str                    # Issue number/name
    coverImage: str              # Cover image URL

class Year(TypedDict):
    year: int                    # Year
    issueCount: int              # Number of issues
    issues: List[Issue]          # List of issues

class JournalDetails(TypedDict):
    journalId: str               # Journal ID
    journalName: str             # Journal name
    issn: str                    # ISSN
    cnno: str                    # CN number
    years: List[Year]            # List of years
    totalYears: int              # Total years
    totalIssues: int             # Total issues

class ArticlesResponse(TypedDict):
    journal: JournalInfo         # Journal information
    issueId: str                 # Issue ID
    totalArticles: int           # Total article count
    totalPages: int              # Total page count
    articles: List[Article]      # List of articles
```

---

## Implementation Details

### URL Structure

#### Journal Search
```
https://www.cqvip.com/journal/search?k={issn}
```

#### Journal Details
```
https://www.cqvip.com/journal/{journal_id}/{journal_id}
```

#### Issue Articles
```
https://www.cqvip.com/journal/{journal_id}/{issue_id}
```

**Example**: https://www.cqvip.com/journal/95499X/8687909

### Data Extraction Flow

```python
# 1. HTTP Request
response = await httpx.get(url)

# 2. HTML Parsing with selectolax
tree = HTMLParser(response.text)
scripts = tree.css('script')

# 3. Find __NUXT__ script
for script in scripts:
    if 'window.__NUXT__' in script.text():
        js_code = script.text()
        break

# 4. Execute JavaScript with Node.js
temp_file = create_temp_js_file(js_code)
result = subprocess.run(['node', temp_file])
json_data = json.loads(result.stdout)

# 5. Extract data from JSON
data = json_data['data']
periodical = data[0]['periodical']
catalog = data[1]['catalog']
articles = extract_articles(catalog)
```

### Why selectolax?

**selectolax vs Regular Expressions**:

| Feature | Regex | selectolax |
|---------|-------|-----------|
| Speed | Fast for simple cases | Very fast (C-based) |
| Reliability | Poor (breaks with HTML changes) | Excellent (proper HTML parsing) |
| Maintainability | Difficult | Easy |
| Error handling | Manual | Automatic |

**selectolax vs BeautifulSoup**:

| Feature | BeautifulSoup | selectolax |
|---------|---------------|-----------|
| Speed | Slow (50ms) | **Fast (2ms)** |
| Memory | High | **Low** |
| API | Complex | **Simple** |
| Parser | lxml/html.parser | Lexbor (C) |

### JavaScript Execution

**Why Node.js?**

The `window.__NUXT__` data is an **obfuscated JavaScript IIFE** (Immediately Invoked Function Expression):

```javascript
window.__NUXT__=(function(a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,_,$,aa,ab,ac,ad,ae,af,ag,ah,ai,aj,ak,al,am,an,ao,ap,aq,ar,as,at,au,av,aw,ax,ay,az,aA,aB,aC,aD,aE,aF,aG,aH,aI,aJ,aK,aL,aM,aN,aO,aP,aQ,aR,aS,aT,aU,aV,aW,aX,aY,aZ,a_,a$,ba,bb,bc,bd,be,bf,bg,bh,bi,bj,bk,bl,bm,bn,bo,bp,bq,br,bs,bt,bu,bv,bw,bx,by,bz,bA,bB,bC,bD,bE,bF,bG,bH,bI,bJ,bK,bL,bM,bN,bO,bP,bQ,bR,bS,bT,bU,bV,bW,bX,bY,bZ,b_,b$,ca,cb,cc,cd,ce,cf,cg,ch,ci,cj,ck,cl,cm,cn,co,cp,cq,cr,cs,ct,cu,cv,cw,cx,cy,cz,cA,cB,cC,cD,cE,cF,cG,cH,cI,cJ,cK,cL,cM,cN,cO,cP,cQ,cR,cS,cT,cU,cV,cW,cX,cY,cZ,c_,c$,da,db,dc,dd,de,df){return {layout:"default",data:[{listData:{count:b,records:[...]}}],fetch:{},error:a,state:{...}}}(null,1,"正常","龙猫",2,false,void 0,"2022-12-19",true,"CSTPCD","R","",3,"BDHX",...));
```

This cannot be parsed as JSON. It must be executed as JavaScript code.

**Execution Process**:

```python
# Create temp JS file
with tempfile.NamedTemporaryFile(mode='w', suffix='.js') as f:
    f.write('var window = {};\n')          # Define window object
    f.write(js_code + '\n')                # The obfuscated code
    f.write('console.log(JSON.stringify(window.__NUXT__));\n')  # Output JSON
    temp_file = f.name

# Execute with Node.js
result = subprocess.run(
    ['node', temp_file],
    capture_output=True,
    text=True,
    timeout=10,
    encoding='utf-8'
)

# Parse output
if result.returncode == 0:
    data = json.loads(result.stdout)
```

**Why not PyExecJS or other Python JS engines?**

- Node.js is **faster** and more **stable**
- Direct subprocess call is **simple** and **reliable**
- No additional Python dependencies needed
- Better error messages

---

## Error Handling

### Error Types

#### 1. HTTP Errors

**Symptoms**: `httpx.HTTPError`, `httpx.TimeoutException`

**Causes**:
- Network issues
- Server downtime
- Rate limiting (429 Too Many Requests)
- Blocked IP

**Solution**:
```python
import asyncio

async def get_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            return response
        except httpx.HTTPError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Retry {attempt+1}/{max_retries} after {wait_time}s")
                await asyncio.sleep(wait_time)
            else:
                raise
```

#### 2. JavaScript Execution Errors

**Symptoms**: `Node.js execution failed`, `JSON parsing error`

**Causes**:
- Node.js not installed
- Malformed JavaScript code
- Encoding issues

**Solution**:
```python
try:
    result = subprocess.run(
        ['node', temp_file],
        capture_output=True,
        text=True,
        timeout=10,
        encoding='utf-8'
    )

    if result.returncode != 0:
        print(f"Node.js error: {result.stderr}")
        return None

except FileNotFoundError:
    print("Node.js not found. Install from: https://nodejs.org/")
    return None

except subprocess.TimeoutExpired:
    print("Node.js execution timeout")
    return None
```

#### 3. Data Structure Errors

**Symptoms**: `KeyError`, `IndexError`, `TypeError`

**Causes**:
- Website structure changed
- Unexpected data format
- Missing fields

**Solution**:
```python
def safe_get(data, *keys, default=None):
    """Safely get nested dictionary values"""
    for key in keys:
        try:
            if isinstance(data, list):
                data = data[int(key)]
            else:
                data = data[key]
        except (KeyError, IndexError, TypeError):
            return default
    return data

# Usage
journal_name = safe_get(data, 0, 'periodical', 'journalName', default='Unknown')
```

#### 4. Rate Limiting

**Symptoms**: 429 status code, empty responses, blocked requests

**Causes**:
- Too many requests in short time
- IP blacklisted

**Solution**:
```python
import random

async def extract_with_rate_limit(api, journal_id, issue_ids):
    results = []

    for issue_id in issue_ids:
        # Extract articles
        articles = await api.get_issue_articles(journal_id, issue_id)
        results.append(articles)

        # Random delay 2-4 seconds
        delay = random.uniform(2, 4)
        await asyncio.sleep(delay)

    return results
```

### Complete Error Handling Example

```python
async def robust_extraction(api, journal_id, issue_id, max_retries=3):
    """Extract articles with comprehensive error handling"""

    for attempt in range(max_retries):
        try:
            # Attempt extraction
            articles = await api.get_issue_articles(journal_id, issue_id)

            if articles is None:
                raise ValueError("Extraction returned None")

            # Validate data
            if articles['totalArticles'] == 0:
                print(f"Warning: No articles found in issue {issue_id}")

            return articles

        except httpx.HTTPError as e:
            print(f"HTTP error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        except ValueError as e:
            print(f"Data error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(5)

        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

    print(f"Failed after {max_retries} attempts")
    return None
```

---

## Performance

### Benchmarks

**Test Setup**:
- Extract 100 issues
- Each issue contains ~20 articles
- Total: ~2000 articles

**Results**:

| Metric | Value |
|--------|-------|
| Total time | ~7 minutes |
| Average per issue | ~4 seconds |
| Peak memory | 60 MB |
| Success rate | 90% (with 2s delay) |
| CPU usage | 5-10% |

**Comparison with Playwright**:

| Metric | Playwright | selectolax + httpx | Improvement |
|--------|-----------|-------------------|-------------|
| Time per issue | 8-10s | 2-3s | **3-4x faster** |
| Memory | 1.3 GB | 60 MB | **95% less** |
| Disk space | 320 MB | 5 MB | **98% less** |
| Success rate | 99% | 90% | -9% |

### Optimization Tips

#### 1. Concurrent Requests

```python
import asyncio

async def extract_concurrent(api, journal_id, issue_ids, max_concurrent=3):
    """Extract multiple issues concurrently"""

    semaphore = asyncio.Semaphore(max_concurrent)

    async def extract_one(issue_id):
        async with semaphore:
            articles = await api.get_issue_articles(journal_id, issue_id)
            await asyncio.sleep(random.uniform(1, 2))  # Small delay
            return articles

    tasks = [extract_one(issue_id) for issue_id in issue_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
```

**Caution**: High concurrency increases risk of being blocked. Recommended: max 3-5 concurrent requests.

#### 2. Session Reuse

```python
class WeipuAPISelectolax:
    def __init__(self):
        self.client = None  # Persistent client

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=30.0,
            limits=httpx.Limits(max_connections=5)
        )
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

# Usage
async with WeipuAPISelectolax() as api:
    for issue_id in issue_ids:
        articles = await api.get_issue_articles(journal_id, issue_id)
```

#### 3. Caching

```python
import json
import hashlib
from pathlib import Path

class CachedWeipuAPI(WeipuAPISelectolax):
    def __init__(self, cache_dir="./cache"):
        super().__init__()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _get_cache_key(self, url):
        return hashlib.md5(url.encode()).hexdigest()

    async def get_issue_articles(self, journal_id, issue_id):
        # Check cache
        cache_file = self.cache_dir / f"{journal_id}_{issue_id}.json"

        if cache_file.exists():
            print(f"Cache hit: {issue_id}")
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        # Fetch from API
        articles = await super().get_issue_articles(journal_id, issue_id)

        if articles:
            # Save to cache
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(articles, f, ensure_ascii=False, indent=2)

        return articles
```

---

## Best Practices

### 1. Rate Limiting

**Always add delays between requests to avoid being blocked:**

```python
import random
import asyncio

async def extract_all_issues(api, journal_id, issue_ids):
    results = []

    for i, issue_id in enumerate(issue_ids):
        print(f"Extracting {i+1}/{len(issue_ids)}: {issue_id}")

        # Extract
        articles = await api.get_issue_articles(journal_id, issue_id)
        results.append(articles)

        # Random delay 2-4 seconds (avoid pattern detection)
        if i < len(issue_ids) - 1:  # No delay after last request
            delay = random.uniform(2, 4)
            await asyncio.sleep(delay)

    return results
```

**Recommended Delays**:
- Single request: No delay needed
- Sequential requests: 2-4 seconds between requests
- Concurrent requests: 1-2 seconds per request, max 3 concurrent

### 2. Error Logging

```python
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'extraction_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)

async def extract_with_logging(api, journal_id, issue_id):
    logging.info(f"Starting extraction: {journal_id}/{issue_id}")

    try:
        articles = await api.get_issue_articles(journal_id, issue_id)

        if articles:
            logging.info(f"Success: {articles['totalArticles']} articles")
            return articles
        else:
            logging.warning(f"No data returned for {issue_id}")
            return None

    except Exception as e:
        logging.error(f"Error extracting {issue_id}: {e}", exc_info=True)
        return None
```

### 3. Progress Tracking

```python
from tqdm import tqdm

async def extract_with_progress(api, journal_id, issue_ids):
    results = []
    failed = []

    with tqdm(total=len(issue_ids), desc="Extracting issues") as pbar:
        for issue_id in issue_ids:
            try:
                articles = await api.get_issue_articles(journal_id, issue_id)

                if articles:
                    results.append(articles)
                    pbar.set_postfix({"success": len(results), "failed": len(failed)})
                else:
                    failed.append(issue_id)

            except Exception as e:
                failed.append(issue_id)
                logging.error(f"Failed: {issue_id} - {e}")

            finally:
                pbar.update(1)
                await asyncio.sleep(random.uniform(2, 4))

    return results, failed
```

### 4. Data Validation

```python
def validate_article(article):
    """Validate article data structure"""
    required_fields = ['id', 'title', 'authors']

    # Check required fields
    for field in required_fields:
        if field not in article or not article[field]:
            return False, f"Missing or empty field: {field}"

    # Validate authors
    if not isinstance(article['authors'], list) or len(article['authors']) == 0:
        return False, "Authors must be a non-empty list"

    # Validate page count
    if article['pages']['count'] is not None and article['pages']['count'] <= 0:
        return False, "Invalid page count"

    return True, "Valid"

# Usage
articles = await api.get_issue_articles(journal_id, issue_id)

valid_articles = []
for article in articles['articles']:
    is_valid, message = validate_article(article)
    if is_valid:
        valid_articles.append(article)
    else:
        logging.warning(f"Invalid article {article['id']}: {message}")
```

### 5. Graceful Degradation

```python
async def extract_with_fallback(issue_id):
    """Try multiple strategies if extraction fails"""

    # Strategy 1: Normal extraction
    try:
        articles = await api.get_issue_articles(journal_id, issue_id)
        if articles:
            return articles
    except Exception as e:
        logging.warning(f"Strategy 1 failed: {e}")

    # Strategy 2: Retry with longer timeout
    try:
        await asyncio.sleep(5)
        articles = await api_with_longer_timeout.get_issue_articles(
            journal_id, issue_id
        )
        if articles:
            return articles
    except Exception as e:
        logging.warning(f"Strategy 2 failed: {e}")

    # Strategy 3: Skip and mark for manual review
    logging.error(f"All strategies failed for {issue_id}")
    return None
```

---

## Complete Examples

### Example 1: Extract Latest Issue

```python
import asyncio
from weipu_api_selectolax import WeipuAPISelectolax

async def extract_latest_issue():
    """Extract articles from the latest issue of a journal"""

    api = WeipuAPISelectolax()

    # 1. Search journal
    issn = "1002-5502"  # 管理世界
    journal = await api.search_journal_by_issn(issn)

    if not journal:
        print(f"Journal not found: {issn}")
        return

    print(f"Found: {journal['name']} ({journal['issn']})")

    # 2. Get journal details
    details = await api.get_journal_details(journal['journalId'])

    # 3. Get latest issue
    latest_year = details['years'][0]
    latest_issue = latest_year['issues'][0]

    print(f"Latest issue: {latest_year['year']} Issue {latest_issue['name']}")

    # 4. Extract articles
    articles = await api.get_issue_articles(
        journal['journalId'],
        latest_issue['id']
    )

    # 5. Display results
    print(f"\nTotal articles: {articles['totalArticles']}")
    print(f"Total pages: {articles['totalPages']}\n")

    for i, article in enumerate(articles['articles'], 1):
        print(f"{i}. {article['title']}")

        # Authors
        authors_str = ', '.join([
            f"{a['name']}{'*' if a['is_corresponding'] else ''}"
            for a in article['authors']
        ])
        print(f"   Authors: {authors_str}")

        # Pages
        pages = article['pages']
        print(f"   Pages: {pages['begin']}-{pages['end']} ({pages['count']} pages)")
        print()

if __name__ == "__main__":
    asyncio.run(extract_latest_issue())
```

### Example 2: Batch Extract All Issues from a Year

```python
import asyncio
import json
import random
from pathlib import Path
from weipu_api_selectolax import WeipuAPISelectolax

async def extract_year(journal_id, year, output_dir="./data"):
    """Extract all issues from a specific year"""

    api = WeipuAPISelectolax()
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # 1. Get journal details
    details = await api.get_journal_details(journal_id)

    # 2. Find the specified year
    year_data = None
    for y in details['years']:
        if y['year'] == year:
            year_data = y
            break

    if not year_data:
        print(f"Year {year} not found")
        return

    print(f"Extracting {year_data['issueCount']} issues from {year}")

    # 3. Extract each issue
    results = []
    failed = []

    for i, issue in enumerate(year_data['issues'], 1):
        print(f"\n[{i}/{year_data['issueCount']}] Issue {issue['name']}...", end=" ")

        try:
            articles = await api.get_issue_articles(journal_id, issue['id'])

            if articles:
                # Save to file
                filename = output_path / f"{journal_id}_{year}_issue{issue['name']}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(articles, f, ensure_ascii=False, indent=2)

                print(f"✓ {articles['totalArticles']} articles")
                results.append({
                    "issue": issue['name'],
                    "articles": articles['totalArticles'],
                    "file": str(filename)
                })
            else:
                print("✗ Failed")
                failed.append(issue['name'])

        except Exception as e:
            print(f"✗ Error: {e}")
            failed.append(issue['name'])

        # Rate limiting
        if i < year_data['issueCount']:
            delay = random.uniform(2, 4)
            await asyncio.sleep(delay)

    # 4. Summary
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Success: {len(results)}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed issues: {', '.join(failed)}")

    # Save summary
    summary_file = output_path / f"{journal_id}_{year}_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            "year": year,
            "total": year_data['issueCount'],
            "success": len(results),
            "failed": len(failed),
            "results": results
        }, f, ensure_ascii=False, indent=2)

    print(f"\nSummary saved to: {summary_file}")

if __name__ == "__main__":
    asyncio.run(extract_year("95499X", 2025))
```

### Example 3: Export to CSV

```python
import asyncio
import csv
from weipu_api_selectolax import WeipuAPISelectolax

async def export_to_csv(journal_id, issue_id, output_file="articles.csv"):
    """Export articles to CSV format"""

    api = WeipuAPISelectolax()

    # Extract articles
    articles = await api.get_issue_articles(journal_id, issue_id)

    if not articles:
        print("Extraction failed")
        return

    # Write to CSV
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'ID',
            'Title',
            'Authors',
            'Corresponding Author',
            'Keywords',
            'Abstract',
            'Start Page',
            'End Page',
            'Total Pages',
            'Category',
            'DOI',
            'Funding',
            'Organizations'
        ])

        # Data
        for article in articles['articles']:
            # Format authors
            authors = '; '.join([a['name'] for a in article['authors']])

            # Find corresponding author
            corr_author = next(
                (a['name'] for a in article['authors'] if a['is_corresponding']),
                ''
            )

            # Format keywords
            keywords = '; '.join(article['keywords'])

            # Format funding
            funding = '; '.join(article['funds'])

            # Format organizations
            organizations = '; '.join(article['organizations'])

            # Write row
            writer.writerow([
                article['id'],
                article['title'],
                authors,
                corr_author,
                keywords,
                article['abstract'] or '',
                article['pages']['begin'],
                article['pages']['end'],
                article['pages']['count'] or 0,
                article['category'],
                article['doi'] or '',
                funding,
                organizations
            ])

    print(f"Exported {articles['totalArticles']} articles to {output_file}")

if __name__ == "__main__":
    asyncio.run(export_to_csv("95499X", "8687909"))
```

### Example 4: Search Articles by Keyword

```python
async def search_articles_by_keyword(keyword, year=2025):
    """Search for articles containing a specific keyword"""

    api = WeipuAPISelectolax()
    journal_id = "95499X"

    # Get journal details
    details = await api.get_journal_details(journal_id)

    # Find year
    year_data = next((y for y in details['years'] if y['year'] == year), None)

    if not year_data:
        print(f"Year {year} not found")
        return

    # Search in each issue
    matching_articles = []

    for issue in year_data['issues']:
        articles = await api.get_issue_articles(journal_id, issue['id'])

        if articles:
            for article in articles['articles']:
                # Check if keyword in title or keywords
                if (keyword in article['title'] or
                    keyword in article['keywords']):
                    matching_articles.append({
                        "issue": issue['name'],
                        "title": article['title'],
                        "authors": [a['name'] for a in article['authors']],
                        "keywords": article['keywords']
                    })

        await asyncio.sleep(random.uniform(2, 4))

    # Display results
    print(f"\nFound {len(matching_articles)} articles containing '{keyword}':\n")

    for i, article in enumerate(matching_articles, 1):
        print(f"{i}. {article['title']}")
        print(f"   Issue: {article['issue']}")
        print(f"   Authors: {', '.join(article['authors'])}")
        print(f"   Keywords: {', '.join(article['keywords'])}")
        print()

if __name__ == "__main__":
    asyncio.run(search_articles_by_keyword("数字经济", year=2025))
```

---

## Troubleshooting

### Issue 1: "Node.js not found"

**Error**:
```
[X] 未找到Node.js，请先安装Node.js
```

**Solution**:
1. Install Node.js from https://nodejs.org/
2. Verify installation: `node --version`
3. Restart terminal/IDE

**Windows Users**: Make sure Node.js is in PATH:
```cmd
node --version
# If not found, add Node.js to PATH:
# C:\Program Files\nodejs\
```

---

### Issue 2: "No data returned" / Returns None

**Possible Causes**:

1. **Invalid journal/issue ID**
   ```python
   # Check if journal exists
   journal = await api.search_journal_by_issn("1002-5502")
   if not journal:
       print("Journal not found")
   ```

2. **Rate limiting** (too many requests)
   ```python
   # Add delay between requests
   await asyncio.sleep(3)
   ```

3. **Network issues**
   ```python
   # Add retry logic
   for retry in range(3):
       result = await api.get_issue_articles(...)
       if result:
           break
       await asyncio.sleep(5)
   ```

4. **Website structure changed**
   - Check if CQVIP website updated
   - Update extraction logic

---

### Issue 3: "JavaScript execution failed"

**Error**:
```
[X] Node.js执行失败
```

**Debugging Steps**:

1. **Check Node.js works**:
   ```bash
   echo 'console.log("Hello")' > test.js
   node test.js
   # Should print: Hello
   ```

2. **Check encoding**:
   - Ensure UTF-8 encoding for all files
   - Check `encoding='utf-8'` in file operations

3. **Save JS code for inspection**:
   ```python
   # In _execute_js method, add:
   with open('debug_script.js', 'w', encoding='utf-8') as f:
       f.write('var window = {};\n')
       f.write(js_code + '\n')
       f.write('console.log(JSON.stringify(window.__NUXT__));\n')

   # Then manually test:
   # node debug_script.js
   ```

---

### Issue 4: Slow Extraction Speed

**If extraction is slower than expected:**

1. **Check network**:
   ```python
   import time

   start = time.time()
   response = await client.get(url)
   elapsed = time.time() - start
   print(f"Network time: {elapsed:.2f}s")
   ```

2. **Use concurrent requests** (carefully):
   ```python
   async def extract_concurrent(issue_ids, max_concurrent=3):
       semaphore = asyncio.Semaphore(max_concurrent)

       async def extract_one(issue_id):
           async with semaphore:
               return await api.get_issue_articles(journal_id, issue_id)

       return await asyncio.gather(*[extract_one(id) for id in issue_ids])
   ```

3. **Enable caching**:
   ```python
   # Use CachedWeipuAPI (see Performance section)
   ```

---

### Issue 5: Memory Leak with Large Batch Extraction

**If memory grows during batch extraction:**

1. **Clear article data after saving**:
   ```python
   for issue_id in issue_ids:
       articles = await api.get_issue_articles(journal_id, issue_id)

       # Save to file
       save_to_file(articles)

       # Clear reference
       articles = None
   ```

2. **Process in chunks**:
   ```python
   chunk_size = 50
   for i in range(0, len(issue_ids), chunk_size):
       chunk = issue_ids[i:i+chunk_size]
       results = await process_chunk(chunk)
       save_results(results)
   ```

---

### Issue 6: Encoding Errors (Chinese Characters)

**Error**:
```
UnicodeEncodeError: 'gbk' codec can't encode character
```

**Solution**:
```python
# Always use UTF-8
with open(file, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)

# For CSV, use utf-8-sig (includes BOM for Excel)
with open(file, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
```

---

## Appendix

### A. System Requirements

**Minimum Requirements**:
- Python 3.8+
- Node.js 14.0+
- 2 GB RAM
- 100 MB disk space

**Recommended**:
- Python 3.10+
- Node.js 18.0+
- 4 GB RAM
- 500 MB disk space (for caching)

### B. Dependencies

```txt
httpx>=0.24.0       # Async HTTP client
selectolax>=0.3.0   # Fast HTML parser
```

**Optional**:
```txt
tqdm>=4.65.0        # Progress bars
```

### C. Performance Comparison Matrix

| Operation | Playwright | httpx + regex | httpx + selectolax |
|-----------|-----------|---------------|-------------------|
| Single request | 8-10s | 1-3s | 1-3s |
| 10 requests | ~90s | ~25s | ~25s |
| 100 requests | ~900s (15min) | ~300s (5min) | ~300s (5min) |
| Memory | 1.3 GB | 50 MB | 60 MB |
| Reliability | 99% | 85% | 90% |
| Setup time | ~5min | ~1min | ~1min |
| Dependencies | Large | Small | Small |

### D. Common ISSN Numbers

| ISSN | Journal Name | Field |
|------|-------------|-------|
| 1002-5502 | 管理世界 | Management |
| 1000-6788 | 会计研究 | Accounting |
| 1002-0241 | 经济学动态 | Economics |
| 1000-596X | 中国工业经济 | Industrial Economics |
| 1002-2104 | 中国人口·资源与环境 | Population & Environment |

### E. HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process data |
| 404 | Not found | Check journal/issue ID |
| 412 | Precondition failed | Anti-bot detection, add delay |
| 429 | Too many requests | Rate limiting, add longer delay |
| 500 | Server error | Retry after delay |
| 503 | Service unavailable | Server down, retry later |

### F. Anti-Bot Best Practices

1. **Realistic User-Agent**:
   ```python
   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
   ```

2. **Add Referer**:
   ```python
   "Referer": "https://www.cqvip.com/"
   ```

3. **Random delays**:
   ```python
   await asyncio.sleep(random.uniform(2, 4))
   ```

4. **Limit concurrency**:
   ```python
   semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
   ```

5. **Rotate proxies** (if available):
   ```python
   proxies = {"https://": "http://proxy.example.com:8080"}
   ```

---

## License

This API is for research and educational purposes only. Please respect the CQVIP website's terms of service and use responsibly.

---

## Support & Contact

**Issues**: For bugs or questions, please check:
1. This documentation
2. Troubleshooting section
3. Error logs

**Contributing**: Improvements and bug fixes are welcome!

---

**Document Version**: 2.0.0
**Last Updated**: 2026-02-01
**API Implementation**: [weipu_api_selectolax.py](weipu_api_selectolax.py)

---

**End of Documentation**
