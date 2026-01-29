export interface PageMeta {
  total: number | null;
  limit: number;
  offset: number;
  next_cursor?: string | null;
  has_more?: boolean | null;
}

export interface Article {
  article_id: number;
  journal_id: number;
  issue_id?: number;
  title?: string;
  date?: string;
  authors?: string;
  abstract?: string;
  doi?: string;
  journal_title?: string;
  open_access?: number;
  in_press?: number;
  volume?: string;
  number?: string;
  full_text_file?: string;
}

export interface ArticlePage {
  items: Article[];
  page: PageMeta;
}

export interface ValueCount {
  value: string;
  count: number;
}

export interface YearSummary {
  year: number;
  issue_count: number;
  journal_count: number;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
export const DEFAULT_DB = 'utd24.sqlite';
const DB_STORAGE_KEY = 'selected_database';

function getStoredDatabase(): string {
    if (typeof window !== 'undefined') {
        return localStorage.getItem(DB_STORAGE_KEY) || DEFAULT_DB;
    }
    return DEFAULT_DB;
}

let currentDb = getStoredDatabase();

export function setDatabase(db: string) {
    currentDb = db;
    if (typeof window !== 'undefined') {
        localStorage.setItem(DB_STORAGE_KEY, db);
    }
}

export function getCurrentDatabase() {
    return currentDb;
}

function withDb(url: string, params?: URLSearchParams): string {
    const urlObj = new URL(url, API_BASE_URL); // Handle relative or absolute
    const p = urlObj.searchParams;
    
    // Merge provided params
    if (params) {
        params.forEach((value, key) => {
            p.append(key, value);
        });
    }

    // Set DB if not present
    if (!p.has('db')) {
        p.set('db', currentDb);
    }
    return urlObj.toString();
}

export async function getDatabases(): Promise<string[]> {
    const res = await fetch(`${API_BASE_URL}/meta/databases`);
    if (!res.ok) {
        return [DEFAULT_DB];
    }
    return res.json();
}

export async function getArticles(
  params: URLSearchParams,
  pageParam: string | number | null = null,
): Promise<ArticlePage> {
  const newParams = new URLSearchParams(params);
  const includeTotal = pageParam === null || pageParam === 0;

  if (typeof pageParam === 'string' && pageParam.length > 0) {
    newParams.set('cursor', pageParam);
    newParams.delete('offset');
  } else if (typeof pageParam === 'number') {
    newParams.set('offset', pageParam.toString());
  }
  newParams.set('include_total', includeTotal ? '1' : '0');

  const res = await fetch(withDb('/articles', newParams));
  if (!res.ok) {
    throw new Error('Failed to fetch articles');
  }
  return res.json();
}

export async function getAreas(): Promise<ValueCount[]> {
  const res = await fetch(withDb('/meta/areas'));
  if (!res.ok) {
    throw new Error('Failed to fetch areas');
  }
  return res.json();
}

export async function getRanks(): Promise<ValueCount[]> {
  const res = await fetch(withDb('/meta/ranks'));
  if (!res.ok) {
    throw new Error('Failed to fetch ranks');
  }
  return res.json();
}

export async function getYears(): Promise<YearSummary[]> {
    const res = await fetch(withDb('/years'));
    if (!res.ok) {
      throw new Error('Failed to fetch years');
    }
    return res.json();
  }
