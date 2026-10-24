import os
import sqlite3

SCHEMA = """
create table if not exists companies (
    uid text primary key, group_id text, okved text, okved2 text, okved_name text, revenue real,
    region text, city text, cl_type text,
    p_rko int, p_gar int, p_loa int, p_lea int, p_dep int, p_zpp int,
    fts_flag int, fts_country text, factoring int, negative int, age_grad text, workers_fns text
);
create index if not exists companies_group on companies(group_id);
create table if not exists groups (
    group_id text primary key, display_name text, revenue_total real, n_companies int,
    main_okved2 text, is_target int, profile text
);
create table if not exists counterparties (
    group_id text, direction text, cp_uid text, cp_okved2 text, amount real, cnt int, rank int
);
create index if not exists cp_group on counterparties(group_id, direction);
create table if not exists users (login text primary key, group_id text, role text);

create table if not exists bank_chunks (
    chunk_id text primary key, doc_id text, doc_title text, doc_date text, page int, text text, stale int
);
create virtual table if not exists bank_fts using fts5(
    text, doc_title, content='bank_chunks', content_rowid='rowid', tokenize='unicode61'
);
create trigger if not exists bank_chunks_ai after insert on bank_chunks begin
    insert into bank_fts(rowid, text, doc_title) values (new.rowid, new.text, new.doc_title);
end;

create table if not exists news (
    news_id text primary key, source text, url text, published_at text, title text, body text,
    hash text unique, cluster_id text, origin text, classification text, owner_group text
);
create virtual table if not exists news_fts using fts5(
    title, body, content='news', content_rowid='rowid', tokenize='unicode61'
);
create trigger if not exists news_ai after insert on news begin
    insert into news_fts(rowid, title, body) values (new.rowid, new.title, new.body);
end;

create table if not exists insights (
    insight_id text primary key, group_id text, news_id text, score real, payload text,
    status text, trace_id text, created_at text, unique(group_id, news_id)
);
create table if not exists trace_steps (
    trace_id text, idx int, kind text, name text, input text, output text,
    tokens int, cost_rub real, ms int, ts text default (datetime('now'))
);
create index if not exists trace_steps_id on trace_steps(trace_id, idx);
create table if not exists llm_calls (
    id integer primary key, ts text default (datetime('now')), model text, purpose text,
    prompt_tokens int, completion_tokens int, cost_rub real, cache_hit int, trace_id text
);
create table if not exists llm_cache (key text primary key, response text);
create table if not exists feedback (
    insight_id text, login text, verdict text, reason text, comment text, ts text default (datetime('now'))
);
create table if not exists eval_runs (ts text default (datetime('now')), payload text);
create table if not exists chat_messages (
    insight_id text, login text, role text, content text, trace_id text, ts text default (datetime('now'))
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or os.environ.get("DB_PATH", "data/app.db")
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("pragma table_info(news)")}
    if "owner_group" not in cols:  # миграция БД, созданных до появления колонки
        conn.execute("alter table news add column owner_group text")
    conn.commit()
