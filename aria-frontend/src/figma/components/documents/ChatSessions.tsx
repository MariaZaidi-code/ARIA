import { useState } from "react";
import { History, MessageSquarePlus, Trash2 } from "lucide-react";

export interface ChatSummary {
  conversation_id: string;
  title: string;
  updated_at?: string;
  message_count?: number;
  scope_document_ids?: string[] | null;
}

function when(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Saved document chats: reopen a previous session or start a new one. */
export function ChatSessions({
  chats,
  activeId,
  loading,
  error,
  onOpen,
  onNew,
  onDelete,
  onReload,
}: {
  chats: ChatSummary[];
  activeId: string | null;
  loading: boolean;
  error: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (chat: ChatSummary) => void;
  onReload: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="doc-sessions">
      <div className="doc-sessions-bar">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="doc-sessions-list"
          onClick={() => {
            if (!open) onReload();
            setOpen((value) => !value);
          }}
        >
          <History size={14} /> Chats{chats.length ? ` (${chats.length})` : ""}
        </button>
        <button type="button" onClick={() => { onNew(); setOpen(false); }}>
          <MessageSquarePlus size={14} /> New chat
        </button>
      </div>
      {open && (
        <div id="doc-sessions-list" className="doc-sessions-list" role="list" aria-label="Saved chats">
          {loading && !chats.length && (
            <div className="doc-skeleton-list" aria-label="Loading chats">
              <span className="doc-skeleton" /><span className="doc-skeleton" /><span className="doc-skeleton" />
            </div>
          )}
          {error && !loading && (
            <p className="doc-sessions-empty">
              {error} <button type="button" className="doc-link-button" onClick={onReload}>Try again</button>
            </p>
          )}
          {!loading && !error && !chats.length && <p className="doc-sessions-empty">No saved chats yet.</p>}
          {chats.map((chat) => (
            <div
              role="listitem"
              key={chat.conversation_id}
              className={`doc-session ${chat.conversation_id === activeId ? "is-active" : ""}`}
            >
              <button
                type="button"
                className="doc-session-open"
                onClick={() => { onOpen(chat.conversation_id); setOpen(false); }}
                aria-current={chat.conversation_id === activeId ? "true" : undefined}
              >
                <strong title={chat.title}>{chat.title || "Untitled chat"}</strong>
                <small>
                  {when(chat.updated_at)}
                  {chat.scope_document_ids?.length
                    ? ` · ${chat.scope_document_ids.length} document${chat.scope_document_ids.length === 1 ? "" : "s"}`
                    : " · all documents"}
                </small>
              </button>
              <button type="button" aria-label={`Delete chat ${chat.title}`} onClick={() => onDelete(chat)}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
