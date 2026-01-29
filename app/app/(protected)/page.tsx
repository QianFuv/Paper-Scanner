import { Sidebar } from "@/components/feature/sidebar";
import { SearchBar } from "@/components/feature/search-bar";
import { ResultsList } from "@/components/feature/results-list";

export default function Home() {
  return (
    <div className="flex h-screen w-full bg-background text-foreground">
      <Sidebar className="hidden md:flex flex-shrink-0 h-screen" />
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        <div className="p-6 border-b bg-background/95 backdrop-blur z-10 sticky top-0">
          <SearchBar className="max-w-4xl mx-auto" />
        </div>
        <div className="flex-1 overflow-y-auto p-6 scroll-smooth">
          <div className="max-w-4xl mx-auto w-full">
            <ResultsList />
          </div>
        </div>
      </main>
    </div>
  );
}
