'use client';

import { useInfiniteQuery, type InfiniteData } from '@tanstack/react-query';
import { useQueryState, parseAsString, parseAsArrayOf, parseAsInteger } from 'nuqs';
import { getArticles, getFullTextUrl, type Article, type ArticlePage } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from '@/components/ui/dialog';
import { ExternalLink, Copy, Check } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useInView } from 'react-intersection-observer';

export function ResultsList() {
  const { ref: prefetchRef, inView: prefetchInView } = useInView({ threshold: 0 });
  const { ref: loadMoreRef, inView: loadMoreInView } = useInView({ threshold: 0 });
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [visiblePages, setVisiblePages] = useState(1);

  const [q] = useQueryState('q', parseAsString);
  const [areas] = useQueryState('area', parseAsArrayOf(parseAsString));
  const [journalIds] = useQueryState('journal_id', parseAsArrayOf(parseAsString));
  const [yearMin] = useQueryState('year_min', parseAsInteger);
  const [yearMax] = useQueryState('year_max', parseAsInteger);
  const searchParams = useSearchParams();
  const searchKey = searchParams.toString();
  const includeTotal = true;

  const handleCopyArticleInfo = async (article: Article) => {
      const info = [
          `Title: ${article.title || 'N/A'}`,
          `Authors: ${article.authors || 'N/A'}`,
          `Journal: ${article.journal_title || 'N/A'}`,
          `Date: ${article.date || 'N/A'}`,
          article.volume && `Volume: ${article.volume}`,
          article.number && `Issue: ${article.number}`,
          article.doi && `DOI: ${article.doi}`,
          article.doi && `URL: https://doi.org/${article.doi}`
      ].filter(Boolean).join('\n');

      await navigator.clipboard.writeText(info);
      setCopyStatus(`${article.article_id}-info`);
      setTimeout(() => setCopyStatus(null), 3000);
  };

  const handleCopyTitle = async (article: Article) => {
      await navigator.clipboard.writeText(article.title || '');
      setCopyStatus(`${article.article_id}-title`);
      setTimeout(() => setCopyStatus(null), 3000);
  };

  const params = new URLSearchParams();
  if (q) params.set('q', q);

  if (areas && areas.length > 0) {
      areas.forEach(a => params.append('area', a));
  }
  if (journalIds && journalIds.length > 0) {
      journalIds.forEach(id => params.append('journal_id', id));
  }

  if (yearMin) params.set('date_from', `${yearMin}-01-01`);
  if (yearMax) params.set('date_to', `${yearMax}-12-31`);
  const paramsString = params.toString();

  const {
    data,
    isLoading,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery<
    ArticlePage,
    Error,
    InfiniteData<ArticlePage, string | null>,
    string[],
    string | null
  >({
    queryKey: ['articles', paramsString],
    queryFn: ({ pageParam }) => getArticles(params, pageParam, includeTotal),
    initialPageParam: null,
    getNextPageParam: (lastPage) => lastPage.page.next_cursor ?? undefined,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  useEffect(() => {
    setVisiblePages(1);
    const scrollContainer = document.getElementById('results-scroll-container');
    if (scrollContainer) {
      scrollContainer.scrollTo({ top: 0 });
      return;
    }
    window.scrollTo({ top: 0 });
  }, [searchKey]);

  const pages = data?.pages ?? [];
  const loadedPages = pages.length;
  const visiblePageCount = Math.min(visiblePages, loadedPages);
  const visibleArticles = pages.slice(0, visiblePageCount).flatMap((page) => page.items);

  useEffect(() => {
    if (!prefetchInView || !hasNextPage || isFetchingNextPage) {
      return;
    }
    if (loadedPages > visiblePages) {
      return;
    }
    fetchNextPage();
  }, [prefetchInView, hasNextPage, isFetchingNextPage, fetchNextPage, loadedPages, visiblePages]);

  useEffect(() => {
    if (!loadMoreInView) {
      return;
    }
    if (visiblePages < loadedPages) {
      setVisiblePages((current) => Math.min(current + 1, loadedPages));
      return;
    }
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [loadMoreInView, visiblePages, loadedPages, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const highlightTerms = useMemo(() => {
    if (!q) return [];
    const isCjk = (value: string) => /[\u4e00-\u9fff]/.test(value);
    const meetsLength = (value: string) => (isCjk(value) ? value.length >= 2 : value.length > 2);
    const terms: string[] = [];
    const phraseRegex = /"([^"]+)"/g;
    let match = phraseRegex.exec(q);
    while (match) {
      const phrase = match[1].trim();
      if (meetsLength(phrase)) {
        terms.push(phrase);
      }
      match = phraseRegex.exec(q);
    }

    const stripped = q.replace(phraseRegex, ' ');
    const tokens = stripped.split(/\s+/).filter(Boolean);
    for (const token of tokens) {
      const upper = token.toUpperCase();
      if (upper === 'AND' || upper === 'OR' || upper === 'NOT' || upper === 'NEAR') {
        continue;
      }
      let cleaned = token.replace(/[()]/g, '');
      if (!cleaned) {
        continue;
      }
      if ((cleaned.includes('{') || cleaned.includes('}')) && !cleaned.includes(':')) {
        continue;
      }
      const colonIndex = cleaned.indexOf(':');
      if (colonIndex >= 0) {
        cleaned = cleaned.slice(colonIndex + 1);
      }
      cleaned = cleaned.replace(/\*+$/, '');
      if (meetsLength(cleaned)) {
        terms.push(cleaned);
      }
    }

    return Array.from(new Set(terms));
  }, [q]);

  const highlightPattern = useMemo(() => {
    if (highlightTerms.length === 0) return null;
    const escaped = highlightTerms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    return new RegExp(`(${escaped.join('|')})`, 'gi');
  }, [highlightTerms]);

  const highlightText = useCallback(
    (text: string | undefined) => {
      if (!text) return null;
      if (!highlightPattern) return text;

      try {
        return text.split(highlightPattern).map((part, index) =>
          index % 2 === 1 ? (
            <span
              key={index}
              className="text-blue-600 font-bold bg-blue-50 dark:text-blue-400 dark:bg-blue-950/30 rounded-xs"
            >
              {part}
            </span>
          ) : (
            part
          ),
        );
      } catch {
        return text;
      }
    },
    [highlightPattern],
  );

  const prefetchThreshold = 25;
  const prefetchIndex = Math.max(0, visibleArticles.length - prefetchThreshold);

  if (isError) {
      return (
          <div className="p-4 text-red-500 bg-red-50 dark:bg-red-900/20 rounded-md">
              Error: {error instanceof Error ? error.message : 'Unknown error'}
          </div>
      );
  }

  if (isLoading) {
      return (
          <div className="space-y-4">
              {Array.from({ length: 5 }).map((_, i) => (
                  <Card key={i}>
                      <CardHeader>
                          <Skeleton className="h-6 w-3/4" />
                          <Skeleton className="h-4 w-1/4 mt-2" />
                      </CardHeader>
                      <CardContent>
                          <Skeleton className="h-4 w-full" />
                          <Skeleton className="h-4 w-full mt-2" />
                      </CardContent>
                  </Card>
              ))}
          </div>
      );
  }

  if (visibleArticles.length === 0) {
      return <div className="text-center p-8 text-slate-500">No articles found.</div>;
  }

  const total = data?.pages[0]?.page.total ?? null;

  return (
    <div className="space-y-4">
      {includeTotal && typeof total === 'number' && (
        <div className="text-sm text-slate-500">
          Found {total} results
        </div>
      )}
      {visibleArticles.map((article, index) => (
        <div key={article.article_id}>
          {index === prefetchIndex && (
            <div ref={prefetchRef} className="h-0" />
          )}
          <Dialog>
            <DialogTrigger asChild>
                <div className="block group cursor-pointer text-left">
                    <Card className="hover:shadow-md transition-all duration-200 border-transparent hover:border-slate-200 dark:hover:border-slate-800">
                    <CardHeader>
                        <div className="flex justify-between items-start gap-4">
                            <CardTitle className="text-lg text-slate-900 dark:text-slate-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                                {highlightText(article.title)}
                            </CardTitle>
                            <div className="flex gap-2 shrink-0">
                                {article.open_access === 1 && <Badge variant="secondary" className="text-xs">OA</Badge>}
                                {article.in_press === 1 && <Badge variant="outline" className="text-xs">In Press</Badge>}
                            </div>
                        </div>
                        <CardDescription>
                            <span>{article.journal_title}</span>
                            {(article.volume || article.number) && (
                              <span>
                                {' '}
                                •{' '}
                                {[
                                  article.volume && `Vol. ${article.volume}`,
                                  article.number && `Issue ${article.number}`,
                                ]
                                  .filter(Boolean)
                                  .join(', ')}
                              </span>
                            )}
                            {article.date && <span> • {article.date}</span>}
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-3 leading-relaxed">
                            {highlightText(article.abstract)}
                        </p>
                    </CardContent>
                    </Card>
                </div>
            </DialogTrigger>
            <DialogContent className="w-[calc(100%-2rem)] max-w-[calc(100%-2rem)] md:max-w-4xl max-h-[90vh] overflow-y-auto [&>button]:hidden">
                <DialogHeader>
                    <DialogTitle className="text-xl leading-snug">
                        {article.title}
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 ml-2 inline-flex align-middle"
                            onClick={() => handleCopyTitle(article)}
                        >
                            {copyStatus === `${article.article_id}-title` ? (
                                <Check className="h-3 w-3 text-green-600" />
                            ) : (
                                <Copy className="h-3 w-3" />
                            )}
                        </Button>
                    </DialogTitle>
                    <DialogDescription>
                        {article.journal_title}
                        {(article.volume || article.number) && ` • ${[
                            article.volume && `Vol. ${article.volume}`,
                            article.number && `Issue ${article.number}`
                        ].filter(Boolean).join(', ')}`}
                        {article.date && ` • ${article.date}`}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-6 py-4">
                    {article.authors && (
                        <div>
                            <h3 className="font-semibold mb-2 text-sm text-foreground/80">Authors</h3>
                            <p className="text-sm text-muted-foreground">
                                {article.authors}
                            </p>
                        </div>
                    )}
                    
                    <div>
                        <h3 className="font-semibold mb-2 text-sm text-foreground/80">Abstract</h3>
                        <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                            {article.abstract || "No abstract available."}
                        </p>
                    </div>

                    <div className="pt-4 border-t">
                        <div className="flex flex-wrap gap-4">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleCopyArticleInfo(article)}
                            >
                                {copyStatus === `${article.article_id}-info` ? (
                                    <>
                                        <Check className="mr-2 h-4 w-4 text-green-600" />
                                        Copied
                                    </>
                                ) : (
                                    <>
                                        <Copy className="mr-2 h-4 w-4" />
                                        Copy Info
                                    </>
                                )}
                            </Button>
                            {(article.doi || article.platform_id) && (
                                <a
                                    href={
                                        article.doi
                                            ? `https://doi.org/${article.doi}`
                                            : getFullTextUrl(article.article_id)
                                    }
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <Button variant="outline" size="sm">
                                        Read Full Text <ExternalLink className="ml-2 h-4 w-4" />
                                    </Button>
                                </a>
                            )}
                        </div>
                    </div>
                </div>
            </DialogContent>
          </Dialog>
        </div>
      ))}
      
      <div ref={loadMoreRef} className="h-1" />
      {isFetchingNextPage && (
        <div className="py-4 flex justify-center">
          <Skeleton className="h-8 w-48" />
        </div>
      )}
    </div>
  );
}
