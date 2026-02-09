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
  platform_id?: string;
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

export interface JournalOption {
  journal_id: number;
  title?: string;
}

export interface WeeklyArticle {
  article_id: number;
  journal_id: number;
  issue_id?: number;
  title?: string;
  date?: string;
  doi?: string;
  journal_title?: string;
  open_access?: number;
  in_press?: number;
}

export interface WeeklyJournalUpdate {
  journal_id: number;
  journal_title?: string;
  new_article_count: number;
  articles: WeeklyArticle[];
}

export interface WeeklyDatabaseUpdate {
  db_name: string;
  run_id?: string;
  generated_at: string;
  new_article_count: number;
  journals: WeeklyJournalUpdate[];
}

export interface WeeklyUpdatesResponse {
  generated_at: string;
  window_start: string;
  window_end: string;
  databases: WeeklyDatabaseUpdate[];
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

function resolveBase(): string {
    if (API_BASE_URL) return API_BASE_URL;
    if (typeof window !== 'undefined') return window.location.origin;
    return 'http://localhost:8000';
}
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

export function getFullTextUrl(articleId: number): string {
    return withDb(`/api/articles/${articleId}/fulltext`);
}

export function getFullTextUrlForDatabase(articleId: number, dbName: string): string {
    const url = new URL(`/api/articles/${articleId}/fulltext`, resolveBase());
    url.searchParams.set('db', dbName);
    return url.toString();
}

function withDb(url: string, params?: URLSearchParams): string {
    const urlObj = new URL(url, resolveBase());
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
    const res = await fetch(`${resolveBase()}/api/meta/databases`);
    if (!res.ok) {
        return [DEFAULT_DB];
    }
    return res.json();
}

export async function getArticles(
  params: URLSearchParams,
  pageParam: string | number | null = null,
  includeTotal: boolean = false,
): Promise<ArticlePage> {
  const newParams = new URLSearchParams(params);
  const shouldIncludeTotal = includeTotal && (pageParam === null || pageParam === 0);

  if (typeof pageParam === 'string' && pageParam.length > 0) {
    newParams.set('cursor', pageParam);
    newParams.delete('offset');
  } else if (typeof pageParam === 'number') {
    newParams.set('offset', pageParam.toString());
  }
  newParams.set('include_total', shouldIncludeTotal ? '1' : '0');

  const res = await fetch(withDb('/api/articles', newParams));
  if (!res.ok) {
    throw new Error('Failed to fetch articles');
  }
  return res.json();
}

export async function getAreas(): Promise<ValueCount[]> {
  const res = await fetch(withDb('/api/meta/areas'));
  if (!res.ok) {
    throw new Error('Failed to fetch areas');
  }
  return res.json();
}

export async function getYears(): Promise<YearSummary[]> {
    const res = await fetch(withDb('/api/years'));
    if (!res.ok) {
      throw new Error('Failed to fetch years');
    }
    return res.json();
  }

export async function getJournalOptions(): Promise<JournalOption[]> {
  const res = await fetch(withDb('/api/meta/journals'));
  if (!res.ok) {
    throw new Error('Failed to fetch journals');
  }
  return res.json();
}

export async function getWeeklyUpdates(windowDays: number = 7): Promise<WeeklyUpdatesResponse> {
  const params = new URLSearchParams();
  params.set('window_days', String(windowDays));
  const url = new URL('/api/weekly-updates', resolveBase());
  url.search = params.toString();
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error('Failed to fetch weekly updates');
  }
  return res.json();
}

export async function getArticleById(articleId: number, dbName: string): Promise<Article> {
  const url = new URL(`/api/articles/${articleId}`, resolveBase());
  url.searchParams.set('db', dbName);
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error('Failed to fetch article detail');
  }
  return res.json();
}
