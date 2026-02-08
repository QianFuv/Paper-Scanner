'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { ExternalLink, ArrowLeft } from 'lucide-react';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const DEFAULT_DB = 'utd24.sqlite';

async function getArticle(id: string) {
    const res = await fetch(`${API_BASE_URL}/api/articles/${id}?db=${DEFAULT_DB}`);
    if (!res.ok) {
        throw new Error('Failed to fetch article');
    }
    return res.json();
}

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: article, isLoading, isError, error } = useQuery({
    queryKey: ['article', id],
    queryFn: () => getArticle(id),
    enabled: !!id,
  });

  if (isLoading) {
      return (
          <div className="mx-auto w-full max-w-4xl px-4 sm:px-6 py-6 space-y-6">
               <Skeleton className="h-8 w-1/4" />
               <Skeleton className="h-64 w-full" />
          </div>
      )
  }

  if (isError) {
      return (
          <div className="container mx-auto p-6 text-red-500">
              Error: {error instanceof Error ? error.message : 'Unknown error'}
          </div>
      )
  }

  if (!article) return null;

  return (
    <div className="mx-auto w-full max-w-4xl px-4 sm:px-6 py-6">
      <Button 
        variant="ghost" 
        className="mb-4 pl-0 hover:pl-0 hover:bg-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
        onClick={() => router.back()}
      >
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Search
      </Button>
      
      <Card>
          <CardHeader>
              <div className="space-y-2">
                <div className="flex justify-between items-start gap-4">
                    <CardTitle className="text-2xl font-bold text-slate-900 dark:text-slate-100 leading-tight">
                        {article.title}
                    </CardTitle>
                    <div className="flex gap-2 shrink-0">
                         {article.open_access === 1 && <Badge variant="secondary">OA</Badge>}
                         {article.in_press === 1 && <Badge variant="outline">In Press</Badge>}
                    </div>
                </div>
                <CardDescription className="text-base">
                    {article.journal_title} • {article.date} • Vol. {article.volume || 'N/A'}, Issue {article.issue_id || 'N/A'}
                </CardDescription>
              </div>
          </CardHeader>
          <CardContent className="space-y-6">
              <div>
                  <h3 className="font-semibold mb-2">Abstract</h3>
                  <p className="text-slate-700 dark:text-slate-300 leading-relaxed text-justify">
                      {article.abstract || "No abstract available."}
                  </p>
              </div>

              {article.authors && (
                  <div>
                      <h3 className="font-semibold mb-2">Authors</h3>
                      <p className="text-slate-600 dark:text-slate-400">
                          {article.authors}
                      </p>
                  </div>
              )}

              <div className="flex flex-wrap gap-4 pt-4 border-t">
                  {(article.doi || article.platform_id) && (
                      <a
                          href={
                                  article.doi
                                      ? `https://doi.org/${article.doi}`
                                      : `${API_BASE_URL}/api/articles/${article.article_id}/fulltext?db=${DEFAULT_DB}`
                              }
                          target="_blank"
                          rel="noreferrer"
                      >
                          <Button>
                              Read Full Text <ExternalLink className="ml-2 h-4 w-4" />
                          </Button>
                      </a>
                  )}
                  {article.pdf_url && (
                       <a href={article.pdf_url} target="_blank" rel="noreferrer">
                          <Button variant="outline">
                              Download PDF
                          </Button>
                       </a>
                  )}
              </div>
          </CardContent>
      </Card>
    </div>
  );
}
