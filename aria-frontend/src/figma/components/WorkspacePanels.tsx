import { useEffect, useState } from "react";
import {
  BookOpen, Plus, Target as TargetIcon, Webhook as WebhookIcon,
  MessageSquare as SlackIcon, CheckCheck, Trash2, Send, X,
} from "lucide-react";
import { workspaceApi } from "../../services/api";

const inputCls =
  "w-full bg-secondary border border-border rounded-lg px-3 py-2 text-[12.5px] text-foreground outline-none focus:border-primary focus:shadow-[0_0_0_3px_rgba(99,102,241,0.08)] transition-all duration-150";
const cardCls = "bg-card border border-border rounded-xl p-4 space-y-3";
const smallBtn =
  "inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold border border-border text-secondary-foreground hover:bg-secondary disabled:opacity-50";
const primaryBtn =
  "inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold text-white bg-primary hover:bg-primary/90 disabled:opacity-50";

function Note({ msg }: { msg: string }) {
  if (!msg) return null;
  return <p className="text-[11.5px] text-muted-foreground" role="status">{msg}</p>;
}

export default function WorkspacePanels() {
  /* ---- Glossary ---- */
  const [glossary, setGlossary] = useState<{ term: string; maps_to: string }[]>([]);
  const [glossaryMsg, setGlossaryMsg] = useState("");
  const [glossaryBusy, setGlossaryBusy] = useState(false);

  /* ---- Targets ---- */
  const [targets, setTargets] = useState<{ metric: string; target: string; direction: string }[]>([]);
  const [targetsMsg, setTargetsMsg] = useState("");
  const [targetsBusy, setTargetsBusy] = useState(false);

  /* ---- Webhooks ---- */
  const [hooks, setHooks] = useState<any[]>([]);
  const [hookName, setHookName] = useState("");
  const [hookUrl, setHookUrl] = useState("");
  const [hookMsg, setHookMsg] = useState("");
  const [hookBusy, setHookBusy] = useState(false);

  /* ---- Slack ---- */
  const [slack, setSlack] = useState<any>(null);
  const [slackMsg, setSlackMsg] = useState("");
  const [slackBusy, setSlackBusy] = useState(false);

  useEffect(() => {
    let dead = false;
    (async () => {
      const [g, t, w, s] = await Promise.all([
        workspaceApi.getGlossary().catch(() => null),
        workspaceApi.getTargets().catch(() => null),
        workspaceApi.listWebhooks().catch(() => null),
        workspaceApi.getIntegrations().catch(() => null),
      ]);
      if (dead) return;
      if (g) setGlossary((Array.isArray(g.data) ? g.data : []).map((e: any) => ({ term: String(e?.term || ""), maps_to: String(e?.maps_to || "") })));
      if (t) setTargets((Array.isArray(t.data) ? t.data : []).map((e: any) => ({ metric: String(e?.metric || ""), target: String(e?.target ?? ""), direction: String(e?.direction || "above") })));
      if (w) setHooks(Array.isArray(w.data) ? w.data : []);
      if (s) setSlack(s.data || null);
    })();
    return () => { dead = true; };
  }, []);

  const saveGlossary = async () => {
    setGlossaryBusy(true); setGlossaryMsg("");
    try {
      const entries = glossary
        .map((g) => ({ term: g.term.trim(), maps_to: g.maps_to.trim() }))
        .filter((g) => g.term && g.maps_to);
      const r = await workspaceApi.putGlossary(entries);
      setGlossary((Array.isArray(r?.data) ? r.data : entries).map((e: any) => ({ term: String(e?.term || ""), maps_to: String(e?.maps_to || "") })));
      setGlossaryMsg("Glossary saved. New questions will use these meanings.");
    } catch (e: any) {
      setGlossaryMsg(e?.message || "Couldn't save the glossary.");
    } finally { setGlossaryBusy(false); }
  };

  const saveTargets = async () => {
    setTargetsBusy(true); setTargetsMsg("");
    try {
      const list = targets
        .map((t) => ({ metric: t.metric.trim(), target: Number(t.target), direction: t.direction }))
        .filter((t) => t.metric && Number.isFinite(t.target));
      const r = await workspaceApi.putTargets(list);
      setTargets((Array.isArray(r?.data) ? r.data : list).map((e: any) => ({ metric: String(e?.metric || ""), target: String(e?.target ?? ""), direction: String(e?.direction || "above") })));
      setTargetsMsg("Targets saved. Matching KPI cards on the dashboard show progress.");
    } catch (e: any) {
      setTargetsMsg(e?.message || "Couldn't save targets.");
    } finally { setTargetsBusy(false); }
  };

  const addWebhook = async () => {
    const url = hookUrl.trim();
    if (!url || hookBusy) return;
    setHookBusy(true); setHookMsg("");
    try {
      const r = await workspaceApi.createWebhook({ name: hookName.trim() || "Webhook", url });
      setHooks((hs) => [...hs, r?.data].filter(Boolean));
      setHookName(""); setHookUrl("");
      setHookMsg("Webhook added. Use “Test” to send a sample alert.");
    } catch (e: any) {
      setHookMsg(e?.message || "Couldn't add the webhook.");
    } finally { setHookBusy(false); }
  };

  const removeWebhook = async (id: string) => {
    try {
      await workspaceApi.deleteWebhook(id);
      setHooks((hs) => hs.filter((h) => String(h?.id) !== id));
    } catch (e: any) {
      setHookMsg(e?.message || "Couldn't remove the webhook.");
    }
  };

  const testWebhook = async (id: string) => {
    setHookMsg("");
    try {
      const r = await workspaceApi.testWebhook(id);
      const ok = r?.data?.ok ?? r?.ok;
      setHookMsg(ok ? "Test alert delivered." : `Test failed${r?.data?.error ? `: ${String(r.data.error).slice(0, 120)}` : "."}`);
    } catch (e: any) {
      setHookMsg(e?.message || "Test failed.");
    }
  };

  const regenSlack = async () => {
    setSlackBusy(true); setSlackMsg("");
    try {
      const r = await workspaceApi.regenerateSlackToken();
      setSlack(r?.data || null);
      setSlackMsg("New token generated — copy it into your Slack slash command now; it won't be shown in full again.");
    } catch (e: any) {
      setSlackMsg(e?.message || "Couldn't generate a token.");
    } finally { setSlackBusy(false); }
  };

  const clearSlack = async () => {
    setSlackBusy(true); setSlackMsg("");
    try {
      const r = await workspaceApi.clearSlackToken();
      setSlack(r?.data || null);
      setSlackMsg("Slack command disconnected.");
    } catch (e: any) {
      setSlackMsg(e?.message || "Couldn't disconnect Slack.");
    } finally { setSlackBusy(false); }
  };

  const copySlackUrl = async () => {
    const url = String(slack?.slack_command_url || "");
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setSlackMsg("Request URL copied — paste it into Slack's slash-command settings.");
    } catch {
      setSlackMsg(url);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-foreground">Workspace</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Business meanings, KPI targets, alert webhooks, and the Slack command — stored with your account.
        </p>
      </div>

      {/* Glossary */}
      <section className={cardCls} aria-label="Business glossary">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-primary" />
          <h3 className="text-[13px] font-semibold text-foreground">Business glossary</h3>
        </div>
        <p className="text-[11.5px] text-muted-foreground">
          Tell ARIA what your words mean (e.g. “sales” → revenue). Questions matching a term get rewritten before the engine runs.
        </p>
        {glossary.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              value={row.term}
              onChange={(e) => setGlossary((gs) => gs.map((g, j) => (j === i ? { ...g, term: e.target.value } : g)))}
              placeholder="term (e.g. sales)"
              className={inputCls}
              style={{ maxWidth: 180 }}
              aria-label={`Glossary term ${i + 1}`}
            />
            <input
              value={row.maps_to}
              onChange={(e) => setGlossary((gs) => gs.map((g, j) => (j === i ? { ...g, maps_to: e.target.value } : g)))}
              placeholder="means (e.g. revenue)"
              className={inputCls}
              aria-label={`Meaning for glossary term ${i + 1}`}
            />
            <button
              onClick={() => setGlossary((gs) => gs.filter((_, j) => j !== i))}
              className={smallBtn}
              aria-label={`Remove glossary term ${i + 1}`}>
              <X size={12} />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <button onClick={() => setGlossary((gs) => [...gs, { term: "", maps_to: "" }])} className={smallBtn}>
            <Plus size={12} /> Add term
          </button>
          <button onClick={saveGlossary} disabled={glossaryBusy} className={primaryBtn}>
            {glossaryBusy ? "Saving…" : "Save glossary"}
          </button>
        </div>
        <Note msg={glossaryMsg} />
      </section>

      {/* KPI targets */}
      <section className={cardCls} aria-label="KPI targets">
        <div className="flex items-center gap-2">
          <TargetIcon size={14} className="text-primary" />
          <h3 className="text-[13px] font-semibold text-foreground">KPI targets</h3>
        </div>
        <p className="text-[11.5px] text-muted-foreground">
          Set a number to aim for. Dashboard cards whose metric matches will show hit / shortfall.
        </p>
        {targets.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              value={row.metric}
              onChange={(e) => setTargets((ts) => ts.map((t, j) => (j === i ? { ...t, metric: e.target.value } : t)))}
              placeholder="metric (e.g. revenue)"
              className={inputCls}
              style={{ maxWidth: 200 }}
              aria-label={`Target metric ${i + 1}`}
            />
            <input
              value={row.target}
              onChange={(e) => setTargets((ts) => ts.map((t, j) => (j === i ? { ...t, target: e.target.value } : t)))}
              placeholder="target value"
              inputMode="decimal"
              className={inputCls}
              style={{ maxWidth: 140 }}
              aria-label={`Target value ${i + 1}`}
            />
            <select
              value={row.direction}
              onChange={(e) => setTargets((ts) => ts.map((t, j) => (j === i ? { ...t, direction: e.target.value } : t)))}
              className={inputCls}
              style={{ maxWidth: 150 }}
              aria-label={`Target direction ${i + 1}`}>
              <option value="above">aim above</option>
              <option value="below">keep below</option>
            </select>
            <button
              onClick={() => setTargets((ts) => ts.filter((_, j) => j !== i))}
              className={smallBtn}
              aria-label={`Remove target ${i + 1}`}>
              <X size={12} />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <button onClick={() => setTargets((ts) => [...ts, { metric: "", target: "", direction: "above" }])} className={smallBtn}>
            <Plus size={12} /> Add target
          </button>
          <button onClick={saveTargets} disabled={targetsBusy} className={primaryBtn}>
            {targetsBusy ? "Saving…" : "Save targets"}
          </button>
        </div>
        <Note msg={targetsMsg} />
      </section>

      {/* Webhooks */}
      <section className={cardCls} aria-label="Alert webhooks">
        <div className="flex items-center gap-2">
          <WebhookIcon size={14} className="text-primary" />
          <h3 className="text-[13px] font-semibold text-foreground">Alert webhooks</h3>
        </div>
        <p className="text-[11.5px] text-muted-foreground">
          Monitor triggers post here too — Slack and Teams URLs get native message formatting.
        </p>
        {hooks.map((h) => (
          <div key={String(h?.id || "")} className="flex items-center gap-2 min-w-0">
            <p className="text-[12px] font-medium text-foreground truncate" style={{ minWidth: 120 }}>
              {String(h?.name || "Webhook")}
            </p>
            <p className="text-[11px] text-muted-foreground truncate flex-1">{String(h?.url || "")}</p>
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${String(h?.last_status || "") === "ok" ? "bg-positive/10 text-positive" : h?.last_status ? "bg-negative/10 text-negative" : "bg-secondary text-muted-foreground"}`}>
              {String(h?.last_status || "untested")}
            </span>
            <button onClick={() => testWebhook(String(h?.id || ""))} className={smallBtn} aria-label={`Test webhook ${String(h?.name || "")}`}>
              <Send size={11} /> Test
            </button>
            <button onClick={() => removeWebhook(String(h?.id || ""))} className={smallBtn} aria-label={`Remove webhook ${String(h?.name || "")}`}>
              <Trash2 size={11} />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <input value={hookName} onChange={(e) => setHookName(e.target.value)} placeholder="name (optional)" className={inputCls} style={{ maxWidth: 160 }} aria-label="Webhook name" />
          <input value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} placeholder="https://hooks.slack.com/services/…" className={inputCls} aria-label="Webhook URL" />
          <button onClick={addWebhook} disabled={hookBusy || !hookUrl.trim()} className={primaryBtn}>
            <Plus size={12} /> Add
          </button>
        </div>
        <Note msg={hookMsg} />
      </section>

      {/* Slack */}
      <section className={cardCls} aria-label="Slack integration">
        <div className="flex items-center gap-2">
          <SlackIcon size={14} className="text-primary" />
          <h3 className="text-[13px] font-semibold text-foreground">Slack command</h3>
        </div>
        <p className="text-[11.5px] text-muted-foreground">
          Ask ARIA from Slack: create a slash command and paste the Request URL below. Use <code>/aria [question]</code>.
        </p>
        {slack?.slack_configured ? (
          <>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-[11px] bg-secondary border border-border rounded-lg px-2.5 py-2 truncate text-secondary-foreground">
                {String(slack?.slack_command_url || "")}
              </code>
              <button onClick={copySlackUrl} className={smallBtn} aria-label="Copy Slack request URL">
                <CheckCheck size={11} /> Copy
              </button>
            </div>
            <p className="text-[10.5px] text-muted-foreground">
              Token: {String(slack?.slack_command_token || "••••")} · shown in full only right after generating.
            </p>
          </>
        ) : (
          <p className="text-[11.5px] text-muted-foreground">No Slack command connected yet.</p>
        )}
        <div className="flex items-center gap-2">
          <button onClick={regenSlack} disabled={slackBusy} className={primaryBtn}>
            {slack?.slack_configured ? "Regenerate token" : "Connect Slack"}
          </button>
          {slack?.slack_configured ? (
            <button onClick={clearSlack} disabled={slackBusy} className={smallBtn}>
              Disconnect
            </button>
          ) : null}
        </div>
        {slackMsg?.startsWith("New token") && slack?.slack_command_token ? (
          <p className="text-[11px] text-foreground bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/25 rounded-lg px-2.5 py-2 break-all">
            Token (copy now): <code>{String(slack.slack_command_token)}</code>
          </p>
        ) : null}
        <Note msg={slackMsg} />
      </section>
    </div>
  );
}
