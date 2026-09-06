import { useState, useEffect } from "react";
import { Search, Trash2, Bookmark, ExternalLink, ChevronDown, Clock } from "lucide-react";

type Category = "All" | "Analytics" | "Insight" | "Prediction" | "Prescription" | "Hypothesis";

const typeStyle: Record<string, string> = {
  Analytics: "text-primary bg-primary/10",
  Insight: "text-positive bg-positive/10",
  Prediction: "text-warning bg-warning/10",
  Prescription: "text-negative bg-negative/10",
  Hypothesis: "text-primary bg-primary/10",
};

const categories: Category[] = ["All", "Analytics", "Insight", "Prediction", "Prescription", "Hypothesis"];

interface HistoryItem {
  id: string;
  type: string;
  title: string;
  date: string;
  source: string;
  summary: string;
  has_insights?: boolean;
}

interface Props {
  historyRefreshKey?: number;
  onOpenHistory?: (session: any) => void;
  onDeleteHistory?: (id: string) => void;
}

export default function History({ historyRefreshKey = 0, onOpenHistory, onDeleteHistory }: Props) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<Category>("All");
  const [sort, setSort] = useState("newest");
  const [deleted, setDeleted] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchHistory();
  }, [historyRefreshKey]);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/history?limit=100", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        const mapped = (data.history || []).map((h: any) => ({
          id: String(h.id),
          type: h.source_type || "Analytics",
          title: h.goal || "Untitled analysis",
          date: h.created_at ? new Date(h.created_at).toLocaleDateString() : "Unknown",
          source: h.db_name || "Unknown",
          summary: h.sql_used ? `Query executed (${h.row_count || 0} rows)` : "Analysis completed",
          has_insights: h.has_insights,
        }));
        setItems(mapped);
      }
    } catch (err) {
      console.error("Failed to fetch history:", err);
    } finally {
      setLoading(false);
    }
  };

  const filtered = items.filter((h) => {
    if (deleted.includes(h.id)) return false;
    if (category !== "All" && h.type !== category) return false;
    if (search && !h.title.toLowerCase().includes(search.toLowerCase()) && !h.summary.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sort === "newest") return b.id.localeCompare(a.id);
    if (sort === "oldest") return a.id.localeCompare(b.id);
    return a.type.localeCompare(b.type);
  });

  const handleDelete = async (id: string) => {
    setDeleted((d) => [...d, id]);
    onDeleteHistory?.(id);
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">History</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Your previous analyses, insights, and queries.</p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3 focus-within:border-primary transition-colors">
          <Search size={14} className="text-muted-foreground flex-shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search history..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-xs text-muted-foreground hover:text-foreground transition-colors">Clear</button>
          )}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex gap-1.5 flex-wrap">
            {categories.map((c) => (
              <button key={c} onClick={() => setCategory(c)}
                className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                  category === c ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground border-border hover:text-foreground"
                }`}>{c}</button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{sorted.length} items</span>
            <div className="relative">
              <select value={sort} onChange={(e) => setSort(e.target.value)}
                className="appearance-none bg-card border border-border rounded-lg pl-3 pr-7 py-1.5 text-xs text-foreground outline-none cursor-pointer">
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="type">By type</option>
              </select>
              <ChevronDown size={11} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-4 animate-pulse">
            <Clock size={20} className="text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">Loading history...</p>
        </div>
      ) : sorted.length > 0 ? (
        <div className="space-y-2 stagger-children">
          {sorted.map((item) => {
            const isSaved = saved.includes(item.id);
            return (
              <div key={item.id} className="premium-card bg-card border border-border rounded-xl p-4 flex items-center gap-4 group cursor-default">
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${typeStyle[item.type] || "text-muted-foreground bg-secondary"}`}>
                      {item.type}
                    </span>
                    <span className="text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded-full">{item.source}</span>
                  </div>
                  <p className="text-sm font-medium text-foreground truncate">{item.title}</p>
                  <p className="text-xs text-muted-foreground truncate">{item.summary}</p>
                </div>

                <div className="flex-shrink-0 flex items-center gap-2">
                  <span className="text-xs text-muted-foreground hidden md:block whitespace-nowrap">{item.date}</span>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => onOpenHistory?.(item)}
                      className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
                      <ExternalLink size={13} />
                    </button>
                    <button
                      onClick={() => setSaved((s) => isSaved ? s.filter((x) => x !== item.id) : [...s, item.id])}
                      className={`p-1.5 rounded-lg hover:bg-secondary transition-colors ${isSaved ? "text-primary" : "text-muted-foreground hover:text-foreground"}`}>
                      <Bookmark size={13} fill={isSaved ? "currentColor" : "none"} />
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-negative transition-colors">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-4">
            <Clock size={20} className="text-muted-foreground" />
          </div>
          <p className="text-sm font-medium text-foreground">
            {search ? "No results found" : "No history yet"}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            {search ? `No items match "${search}"` : "Start analyzing your data to see history here."}
          </p>
          {search && (
            <button onClick={() => setSearch("")} className="mt-4 text-xs text-primary hover:underline">Clear search</button>
          )}
        </div>
      )}
    </div>
  );
}
