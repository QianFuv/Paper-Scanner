'use client';

import { useQuery } from '@tanstack/react-query';
import { useQueryState, parseAsString, parseAsArrayOf, parseAsInteger } from 'nuqs';
import { useTheme } from 'next-themes';
import { getAreas, getRanks, getYears, getCurrentDatabase, getDatabases, setDatabase } from '@/lib/api';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Moon, Sun, Database } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useEffect, useState } from 'react';

export function Sidebar({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();

  const [selectedDb, setSelectedDb] = useState(getCurrentDatabase());
  const [, setQ] = useQueryState('q', parseAsString);
  const [areas, setAreas] = useQueryState('area', parseAsArrayOf(parseAsString).withDefault([]));
  const [ranks, setRanks] = useQueryState('rank', parseAsArrayOf(parseAsString).withDefault([]));
  const [yearMin, setYearMin] = useQueryState('year_min', parseAsInteger);
  const [yearMax, setYearMax] = useQueryState('year_max', parseAsInteger);

  const { data: databases, isLoading: loadingDatabases } = useQuery({
    queryKey: ['meta', 'databases'],
    queryFn: getDatabases,
  });

  useEffect(() => {
    if (!databases || databases.length === 0) {
      return;
    }
    if (databases.includes(selectedDb)) {
      return;
    }
    const fallback = databases[0];
    setDatabase(fallback);
    setSelectedDb(fallback);
  }, [databases, selectedDb]);

  const { data: areaOptions, isLoading: loadingAreas } = useQuery({
    queryKey: ['meta', 'areas', selectedDb],
    queryFn: getAreas,
  });

  const { data: rankOptions, isLoading: loadingRanks } = useQuery({
    queryKey: ['meta', 'ranks', selectedDb],
    queryFn: getRanks,
  });

  const { data: yearData, isLoading: loadingYears } = useQuery({
      queryKey: ['meta', 'years', selectedDb],
      queryFn: getYears
  });

  const handleDatabaseChange = (dbName: string) => {
    setDatabase(dbName);
    setSelectedDb(dbName);
    window.location.href = window.location.pathname;
  };

  const handleClearFilters = () => {
    setQ(null);
    setAreas([]);
    setRanks([]);
    setYearMin(null);
    setYearMax(null);
  };

  const minYearAvailable = yearData && yearData.length > 0 ? Math.min(...yearData.map(y => y.year)) : 1900;
  const maxYearAvailable = yearData && yearData.length > 0 ? Math.max(...yearData.map(y => y.year)) : new Date().getFullYear();

  const [localYearRange, setLocalYearRange] = useState([minYearAvailable, maxYearAvailable]);

  useEffect(() => {
     if (yearData) {
         const newMin = yearMin ?? minYearAvailable;
         const newMax = yearMax ?? maxYearAvailable;
         setLocalYearRange(prev => {
             if (prev[0] === newMin && prev[1] === newMax) return prev;
             return [newMin, newMax];
         });
     }
  }, [yearMin, yearMax, minYearAvailable, maxYearAvailable, yearData]);


  const handleAreaChange = (value: string, checked: boolean) => {
    setAreas((current) => {
      if (checked) {
        return current.includes(value) ? current : [...current, value];
      }
      return current.filter((item) => item !== value);
    });
  };

  const handleRankChange = (value: string, checked: boolean) => {
    setRanks((current) => {
      if (checked) {
        return current.includes(value) ? current : [...current, value];
      }
      return current.filter((item) => item !== value);
    });
  };

  const handleYearChange = (value: number[]) => {
      setLocalYearRange(value);
  };

  const handleYearCommit = (value: number[]) => {
      const nextMin = value[0] === minYearAvailable ? null : value[0];
      const nextMax = value[1] === maxYearAvailable ? null : value[1];
      setYearMin(nextMin);
      setYearMax(nextMax);
  };

  return (
    <aside className={cn("w-[19.2rem] flex flex-col h-full border-r bg-background", className)}>
      <div className="flex-1 space-y-8 p-6 overflow-y-auto">

        <div className="space-y-4">
            <div className="grid grid-cols-2 items-center gap-4">
                <div className="flex items-center justify-center">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={handleClearFilters}
                      aria-label="Clear all filters"
                      title="Clear all filters"
                      className="h-20 w-20"
                    >
                      <img
                        src="https://cdn.sa.net/2026/01/29/6uRXpHqQfC89kF7.png"
                        alt="Home"
                        className="h-16 w-16 object-contain"
                      />
                    </Button>
                </div>
                <div className="space-y-2 self-center">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground w-full">
                        <Database className="h-4 w-4" />
                        <span>Database</span>
                    </div>
                    <div className="w-full">
                        {loadingDatabases ? (
                            <Skeleton className="h-9 w-full" />
                        ) : (
                            <Select value={selectedDb} onValueChange={handleDatabaseChange}>
                                <SelectTrigger size="sm" className="w-full">
                                    <SelectValue placeholder="Select database" />
                                </SelectTrigger>
                                <SelectContent>
                                    {databases?.map((dbName) => (
                                        <SelectItem key={dbName} value={dbName}>
                                            {dbName.replace('.sqlite', '')}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}
                    </div>
                </div>
            </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm text-foreground">Journal Metrics</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearFilters}
              className="h-6 px-2 text-xs"
              title="Clear all filters"
            >
              Clear
            </Button>
          </div>

          <div className="space-y-3">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Areas</h4>
              {loadingAreas ? (
                  <div className="space-y-2">
                      <Skeleton className="h-4 w-full" />
                      <Skeleton className="h-4 w-3/4" />
                  </div>
              ) : (
                  <div className="space-y-2">
                      {areaOptions?.map((opt) => (
                          <div key={opt.value} className="flex items-center space-x-2">
                              <Checkbox 
                                  id={`area-${opt.value}`} 
                                  checked={areas.includes(opt.value)}
                                  onCheckedChange={(c) => handleAreaChange(opt.value, c as boolean)}
                              />
                              <Label htmlFor={`area-${opt.value}`} className="text-sm font-normal truncate flex-1 cursor-pointer" title={opt.value}>{opt.value}</Label>
                              <span className="text-xs text-muted-foreground">{opt.count}</span>
                          </div>
                      ))}
                  </div>
              )}
          </div>

          <div className="space-y-3">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Ranks</h4>
              {loadingRanks ? (
                  <div className="space-y-2">
                      <Skeleton className="h-4 w-full" />
                  </div>
              ) : (
                  <div className="space-y-2">
                      {rankOptions?.map((opt) => (
                          <div key={opt.value} className="flex items-center space-x-2">
                              <Checkbox 
                                  id={`rank-${opt.value}`} 
                                  checked={ranks.includes(opt.value)}
                                  onCheckedChange={(c) => handleRankChange(opt.value, c as boolean)}
                              />
                              <Label htmlFor={`rank-${opt.value}`} className="text-sm font-normal flex-1 cursor-pointer">{opt.value}</Label>
                              <span className="text-xs text-muted-foreground">{opt.count}</span>
                          </div>
                      ))}
                  </div>
              )}
          </div>
        </div>

        <div className="space-y-4">
          <h3 className="font-semibold text-sm text-foreground">Publication Year</h3>
          {loadingYears ? (
              <Skeleton className="h-8 w-full" />
          ) : (
              <div className="px-1 pt-2">
                  <Slider
                      min={minYearAvailable}
                      max={maxYearAvailable}
                      step={1}
                      value={localYearRange}
                      onValueChange={handleYearChange}
                      onValueCommit={handleYearCommit}
                      className="mb-6"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground font-medium">
                      <span>{localYearRange[0]}</span>
                      <span>{localYearRange[1]}</span>
                  </div>
              </div>
          )}
        </div>
      </div>
      
      <div className="flex-shrink-0 p-4 border-t bg-background">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span>Toggle Theme</span>
          </Button>
      </div>
    </aside>
  );
}
