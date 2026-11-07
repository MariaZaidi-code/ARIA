import { useEffect, useState } from "react";
import { apiFetch } from "../../services/api";

interface LLMSelectionProps {
  onSelectLLM: (mode: string, apiKey?: string, model?: string) => Promise<void> | void;
}
interface Provider { id: string; label: string; model: string; has_key: boolean }

const isConnectionIssue = (message: string) =>
  /connection error|apiconnectionerror|connecterror|timeout|timed out|network is unreachable/i.test(message);

export default function LLMSelection({ onSelectLLM }: LLMSelectionProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selected, setSelected] = useState("");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const provider = providers.find(p => p.id === selected);
  const hosted = !!selected && selected !== "local";
  const locked = busy || loading;
  async function loadOptions() {
    setLoading(true); setError("");
    try { const data = await apiFetch("/provider/options"); setProviders(data.providers); }
    catch (e: any) { setError(e?.message || "Could not load providers."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void loadOptions(); }, []);
  async function loadModels() {
    setLoading(true); setError("");
    try {
      const data = await apiFetch("/provider/models", { method: "POST",
        body: JSON.stringify({ provider: selected, api_key: key.trim() || undefined }) });
      setModels(data.models);
      if (!data.models.length) setError("No model IDs returned. Enter an accessible chat model ID manually.");
    } catch (e: any) { setError(e?.message || "Could not load the list of AI models."); }
    finally { setLoading(false); }
  }
  async function confirm() {
    if (!selected || locked) return;
    if (hosted && !key.trim() && !provider?.has_key) { setError("Enter the API key for this AI service."); return; }
    if (hosted && !model.trim()) { setError("Choose an AI model, or type its name."); return; }
    setBusy(true); setError("");
    try { await onSelectLLM(selected, hosted ? key.trim() || undefined : undefined, hosted ? model.trim() : undefined); }
    catch (e: any) { setError(e?.message || "Could not connect to this model."); }
    finally { setBusy(false); }
  }
  const field = "w-full px-4 py-2.5 rounded-xl text-sm border bg-transparent";
  return <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "var(--background)", color: "var(--foreground)" }}>
    <div className="w-full max-w-xl space-y-6">
      <div className="text-center"><p className="font-semibold mb-4">ARIA</p><h1 className="text-2xl font-bold">Choose your AI engine</h1>
        <p className="text-sm mt-2" style={{ color: "var(--muted-foreground)" }}>Choose where ARIA's AI runs: on this computer, or on a cloud AI service with your own key.</p></div>
      <div className="grid grid-cols-2 gap-3">
        {providers.map(p => <button key={p.id} type="button" disabled={locked} aria-pressed={selected === p.id}
          onClick={() => { setSelected(p.id); setKey(""); setModel(p.model); setModels([]); setError(""); }}
          className="rounded-xl p-4 text-left border disabled:opacity-50"
          style={{ background: "var(--card)", borderColor: selected === p.id ? "var(--primary)" : "var(--border)" }}>
          <span className="font-semibold">{p.label}</span><span className="block text-xs mt-1">{p.id === "local" ? "Runs on this computer (Ollama)" : "Cloud service · uses your API key"}</span>
        </button>)}
      </div>
      {hosted && <div className="space-y-3">
        <label className="block text-sm" htmlFor="provider-key">{provider?.label} API key {provider?.has_key && "(a saved key is available)"}</label>
        <input id="provider-key" type="password" autoComplete="off" disabled={locked} value={key}
          onChange={e => { setKey(e.target.value); setModels([]); }} placeholder={provider?.has_key ? "Leave blank to use your saved key" : "Paste your API key"} className={field} />
        <div className="flex justify-between items-center"><label htmlFor="provider-model" className="text-sm">AI model</label>
          <button type="button" disabled={locked || (!key.trim() && !provider?.has_key)} onClick={loadModels} className="text-sm underline disabled:opacity-40">{loading ? "Loading…" : "Show available models"}</button></div>
        <input id="provider-model" list="provider-models" disabled={locked} value={model} onChange={e => setModel(e.target.value)} placeholder="Choose a model from the list or type its name" className={field} />
        <datalist id="provider-models">{models.map(id => <option key={id} value={id} />)}</datalist>
        <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>Pick a chat model offered by this service. Continue sends one small test request, which may count toward your usage or bill. A larger model costs more but is not guaranteed to be more accurate. Cloud AI must also be allowed in ARIA's server settings.</p>
      </div>}
      {selected === "local" && <p className="text-sm">Uses the AI models installed on this computer. Make sure Ollama is running and ARIA's models are installed.</p>}
      {error && <p role="alert" className="text-sm" style={{ color: "var(--negative)" }}>{error}</p>}
      {!providers.length && <button disabled={loading} onClick={loadOptions} className="underline">{loading ? "Loading AI options…" : "Try loading AI options again"}</button>}
      <button disabled={!selected || locked} onClick={confirm} className="w-full rounded-lg py-3 text-white font-semibold disabled:opacity-40" style={{ background: "var(--gradient-primary)" }}>{busy ? "Testing the AI model…" : "Continue"}</button>
    </div>
  </div>;
}
