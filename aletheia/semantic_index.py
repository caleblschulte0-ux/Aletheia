"""A local semantic index over her history: it FINDS things, it never KNOWS them.

The brief (docs/JARVIS_BRIEF.md §2): "Complement exact state with a local
semantic index over code, docs, journal, application history, employer
notes, browser failures and prior fixes; facts come from the ledger,
embeddings only find history. Distinguish knowing, looking and guessing."

So `recall` answers in three honest registers, and says which:

    KNOWN              a row in a store she keeps (a task, a plan, a
                       browser mission, an application, an employer, a
                       remembered fact) whose key the question names
    FOUND IN HISTORY   a passage the index matched: similar, not certain
    GUESS              neither - and the observation says so, so a model
                       that answers anyway is told it is guessing

NOTHING HERE IS KEYED TO ONE GOAL. Sources are a table (`SOURCES`) and the
ledger is a table (`LEDGER_PROBES`); applications and employers are two rows
of each, next to code, docs, the journal, agent sessions, browser missions,
notifications and commit messages. A new store joins by adding a row.

WHAT IS NEVER INDEXED. The sources are an ALLOWLIST: a store nobody added
is not read. The secret store, access tokens, authority grants, his
profile answers and training captures are simply not on it, and
`_refuse_private` makes reading one an error rather than an omission. Code
and docs are git-TRACKED files only (the same confinement as `repo_tools`),
application records travel as `state_tools.summarise_record` (never the
values he filled in), browser missions never carry their inputs or event
values (verification codes), and every chunk passes `sensitivity.scrub`
before it is stored.

TWO ENGINES, AND IT SAYS WHICH ANSWERED. Text is chunked and put in an
SQLite FTS5 table on every run (BM25 ranking, stdlib only; a pure-Python
BM25 when FTS5 is missing). Embeddings come from a tiny local model through
Ollama (`all-minilm`, 384 dimensions) and are filled in under a time budget,
highest-value sources first, keyed by the chunk's text hash so an unchanged
chunk is never embedded twice. When Ollama or the model is not there, recall
is lexical and says so; when some chunks are embedded, both rank and the
answer says what fraction the semantic side covered.

POLITE IN THE BACKGROUND. The Core never builds the index in its own
process: `background_loop` (a daemon thread started by `core.main`) checks a
small JSON stamp every few minutes and, when a run is due and none is alive,
starts `python -m aletheia.semantic_index build` windowless at below-normal
priority with a time budget. Embedding runs inside Ollama, whose priority is
not ours to lower, so the run uses two threads and skips the embedding pass
entirely while a chat model is loaded (she is thinking; the index can wait).

    python -m aletheia.semantic_index build [--budget-s 90] [--no-embed]
    python -m aletheia.semantic_index recall "why did the submit fail" [--sources journal,fixes]
    python -m aletheia.semantic_index status
"""
from __future__ import annotations

import array
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

KNOWN = "KNOWN"
FOUND = "FOUND IN HISTORY"
GUESS = "GUESS"
BASES = (KNOWN, FOUND, GUESS)

DEFAULT_MODEL = "all-minilm"
EMBED_THREADS = 2
EMBED_BATCH = 16
EMBED_TIMEOUT_S = 120.0
QUERY_EMBED_TIMEOUT_S = 15.0
#: all-minilm reads 256 tokens; what it is shown of a chunk is the header
#: plus the start. The lexical side always has the whole chunk.
EMBED_CHARS = 900
CHUNK_CHARS = 1_400
MIN_CHUNK_CHARS = 200
MAX_FILE_BYTES = 512 * 1024
MAX_SNIPPET = 360
DEFAULT_K = 5
MAX_K = 12
DEFAULT_BUDGET_S = 90.0
RUN_INTERVAL_S = 15 * 60
LOOP_FIRST_WAIT_S = 120.0
LOOP_POLL_S = 300.0
SCHEMA_VERSION = 1

#: Tracked files that are code or docs. Everything else (images, the
#: committed pulse and journal under state/, the intercom lane) is not.
DOC_SUFFIXES = (".md", ".txt")
CODE_SUFFIXES = (".py", ".js", ".ps1", ".yml", ".yaml", ".json", ".bat", ".toml", ".cfg")
SKIP_PREFIXES = ("state/", "exchange/", "prototypes/", ".git/")

#: Private stores that are NEVER read by this module, whatever a caller asks.
#: The allowlist below already omits them; this makes the omission an error.
NEVER_PRIVATE = frozenset({"secrets", "access", "authority", "profile", "training",
                           "code-trust", "work-trust", "audio", "recording"})

_WORD = re.compile(r"[A-Za-z0-9_]{2,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
STOPWORDS = frozenset("""
a an and are as at be been but by can can't cannot could did do does doing don't for
from had has have how i if in into is it its just me my no not of on or our so than
that the their them then there these they this to too up was we were what when where
which who why will with would you your yours she her he his him handle handled
happen happened going get got make made about any all also more most some such
""".split())
#: Words that name a KIND of record rather than a particular one. "Why did the
#: application fail" names no application; "the Palantir application" does.
GENERIC = frozenset("""
application applications apply applied job jobs task tasks plan plans project projects
mission missions goal goals record records thing things form forms site page error
errors fail failed failing failure failures work working problem issue wrong broke
broken stuck today yesterday week help need needs
""".split())


class IndexUnavailable(RuntimeError):
    """The index could not be opened. Never the same as 'nothing matched'."""


# ---- where things live -------------------------------------------------------

def index_dir() -> Path:
    override = os.environ.get("ALETHEIA_SEMANTIC_INDEX", "").strip()
    if override:
        return Path(override).expanduser()
    from aletheia import stateio
    return stateio.private_dir("semantic-index")


def db_path() -> Path:
    return index_dir() / "index.sqlite3"


def stamp_path() -> Path:
    return index_dir() / "last-run.json"


def model_name() -> str:
    return os.environ.get("ALETHEIA_EMBED_MODEL", "").strip() or DEFAULT_MODEL


def _refuse_private(path: Path) -> None:
    """A private store off the allowlist is an error, never a silent read."""
    from aletheia import stateio
    try:
        rel = Path(path).resolve().relative_to(stateio.private_root().resolve())
    except (ValueError, OSError):
        return
    if rel.parts and rel.parts[0] in NEVER_PRIVATE:
        raise PermissionError(f"the semantic index never reads private/{rel.parts[0]}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _clean(text: str) -> str:
    from aletheia import sensitivity
    return sensitivity.clean(_CONTROL.sub(" ", str(text or "")))


def tokens(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(str(text or ""))]


def significant(text: str) -> list[str]:
    seen, out = set(), []
    for word in tokens(text):
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


# ---- documents and chunks ----------------------------------------------------

@dataclass(frozen=True)
class Doc:
    source: str
    ref: str
    digest: str
    load: Callable[[], list["Chunk"]]


@dataclass(frozen=True)
class Chunk:
    title: str
    text: str
    ts: str = ""
    locator: str = ""


def split_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-first, then line, then hard cut; never an empty piece."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    current = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip("\n")
        if not block.strip():
            continue
        if len(block) > limit:
            lines = block.splitlines() or [block]
            for line in lines:
                while len(line) > limit:
                    if current:
                        pieces.append(current)
                        current = ""
                    pieces.append(line[:limit])
                    line = line[limit:]
                if len(current) + len(line) + 1 > limit and current:
                    pieces.append(current)
                    current = ""
                current = f"{current}\n{line}" if current else line
            continue
        if len(current) + len(block) + 2 > limit and current:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current.strip():
        pieces.append(current)
    # A tiny tail reads better attached to what came before it.
    if len(pieces) > 1 and len(pieces[-1]) < MIN_CHUNK_CHARS:
        tail = pieces.pop()
        pieces[-1] = pieces[-1] + "\n" + tail
    return [p for p in pieces if p.strip()]


def chunk_python(path: str, text: str) -> list[Chunk]:
    """One chunk per top-level definition (a class split by its methods when
    long), plus the module head. Every chunk names its file and line, which
    is what makes a hit something `repo.read` can open."""
    import ast
    import warnings
    lines = text.splitlines()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")        # another file's escape sequences are not ours
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return chunk_plain(path, text)
    spans: list[tuple[int, int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        end = getattr(node, "end_lineno", node.lineno)
        body = "\n".join(lines[start - 1:end])
        if isinstance(node, ast.ClassDef) and len(body) > CHUNK_CHARS * 2:
            head_end = node.body[0].lineno - 1 if node.body else end
            spans.append((start, head_end, f"class {node.name}"))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    s = min([item.lineno] + [d.lineno for d in item.decorator_list])
                    spans.append((s, getattr(item, "end_lineno", item.lineno),
                                  f"{node.name}.{item.name}"))
        else:
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            spans.append((start, end, f"{kind} {node.name}"))
    out: list[Chunk] = []
    first = spans[0][0] if spans else len(lines) + 1
    for line_no, piece in split_lines(lines[:first - 1], 1):
        out.append(Chunk(f"{path} (module)", piece, locator=f"{path}:{line_no}"))
    for start, end, name in spans:
        for line_no, piece in split_lines(lines[start - 1:end], start):
            out.append(Chunk(f"{path} {name}", piece, locator=f"{path}:{line_no}"))
    return out


def split_lines(lines: list[str], first_line: int, limit: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """Whole lines grouped up to `limit`, each group with the line it starts on."""
    out: list[tuple[int, str]] = []
    current: list[str] = []
    start = first_line
    size = 0
    for offset, line in enumerate(lines):
        line = line[:limit]
        if current and size + len(line) + 1 > limit:
            out.append((start, "\n".join(current)))
            current, size, start = [], 0, first_line + offset
        current.append(line)
        size += len(line) + 1
    if current and "\n".join(current).strip():
        if out and size < MIN_CHUNK_CHARS:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + "\n".join(current))
        else:
            out.append((start, "\n".join(current)))
    return [(n, text) for n, text in out if text.strip()]


def chunk_markdown(path: str, text: str) -> list[Chunk]:
    out: list[Chunk] = []
    heading, start, buf = path, 1, []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            for piece in split_text(body):
                out.append(Chunk(f"{path} - {heading}", piece, locator=f"{path}:{start}"))
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^#{1,4}\s+\S", line):
            flush()
            heading, start, buf = line.lstrip("#").strip()[:120], number, [line]
        else:
            buf.append(line)
    flush()
    return out


def chunk_plain(path: str, text: str) -> list[Chunk]:
    return [Chunk(path, piece, locator=path) for piece in split_text(text)]


# ---- sources -------------------------------------------------------------------

def _repo_files() -> list[str]:
    from aletheia import repo_tools
    try:
        return repo_tools.tracked(fresh=True)
    except Exception:
        return []


def _stat_digest(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def _file_docs(source: str, suffixes: tuple[str, ...]) -> Iterator[Doc]:
    from aletheia import repo_tools
    base = repo_tools.root()
    for name in _repo_files():
        if name.startswith(SKIP_PREFIXES) or not name.endswith(suffixes):
            continue
        if source == "code" and name.endswith(".json") and not name.startswith(("config/", "plans/")):
            continue
        full = base / name
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                continue
            digest = _stat_digest(full)
        except OSError:
            continue

        def load(full=full, name=name) -> list[Chunk]:
            raw = full.read_bytes()
            if b"\0" in raw[:4096]:
                return []
            text = raw.decode("utf-8", "replace")
            if name.endswith(".py"):
                return chunk_python(name, text)
            if name.endswith(".md"):
                return chunk_markdown(name, text)
            return chunk_plain(name, text)
        yield Doc(source, name, digest, load)


def code_docs() -> Iterator[Doc]:
    return _file_docs("code", CODE_SUFFIXES)


def doc_docs() -> Iterator[Doc]:
    return _file_docs("docs", DOC_SUFFIXES)


def journal_docs() -> Iterator[Doc]:
    """One document per day: a past day never changes, so only today re-chunks."""
    from aletheia import journal
    by_day: dict[str, list[dict]] = {}
    for entry in journal.entries():
        by_day.setdefault(str(entry.get("ts", ""))[:10] or "undated", []).append(entry)
    for day, rows in sorted(by_day.items()):
        lines = [f"{e.get('ts', '')} {e.get('kind', '')} {e.get('subject', '')}: "
                 f"{' '.join(str(e.get('text', '')).split())[:600]}" for e in rows]
        digest = _sha("\n".join(lines))

        def load(day=day, lines=lines) -> list[Chunk]:
            out, current, first_ts = [], [], ""
            for line in lines:
                if not current:
                    first_ts = line[:20]
                current.append(line)
                if sum(len(x) + 1 for x in current) >= CHUNK_CHARS:
                    out.append(Chunk(f"journal {day}", "\n".join(current), ts=first_ts,
                                     locator=f"journal {first_ts}"))
                    current = []
            if current:
                out.append(Chunk(f"journal {day}", "\n".join(current), ts=first_ts,
                                 locator=f"journal {first_ts}"))
            return out
        yield Doc("journal", f"journal/{day}", digest, load)


def _json_dir_docs(source: str, folder: Path, render: Callable[[dict], Chunk | None],
                   pattern: str = "*.json") -> Iterator[Doc]:
    _refuse_private(folder)
    if not folder.is_dir():
        return
    for path in sorted(folder.glob(pattern)):
        try:
            digest = _stat_digest(path)
        except OSError:
            continue

        def load(path=path) -> list[Chunk]:
            from aletheia import stateio
            try:
                record = stateio.read_json(path)
            except (OSError, ValueError):
                return []
            chunk = render(record)
            if chunk is None:
                return []
            return [Chunk(chunk.title, piece, chunk.ts, chunk.locator)
                    for piece in split_text(chunk.text)]
        yield Doc(source, f"{source}/{path.stem}", digest, load)


def _render_session(record: dict) -> Chunk | None:
    if not record.get("question"):
        return None
    steps = "; ".join(f"{r.get('tool')} -> {r.get('verdict')}/{r.get('outcome')}"
                      + (f" ({r.get('reason')})" if r.get("reason") else "")
                      for r in (record.get("receipts") or [])[:12])
    text = (f"Asked: {record.get('question')}\nOutcome: {record.get('outcome')}"
            f" basis: {record.get('basis')}\nAnswer: {record.get('answer') or record.get('note') or ''}"
            f"\nSteps: {steps}")
    return Chunk(f"agent session {record.get('id')}", text, ts=str(record.get("saved_at") or ""),
                 locator=f"agent session {record.get('id')}")


def _render_mission(record: dict) -> Chunk | None:
    """Goal, state, the boundary it stopped at and how it got there. Never
    `inputs` (his answers) and never event values (verification codes)."""
    if not record.get("id"):
        return None
    boundary = record.get("boundary") or {}
    stop = {k: boundary.get(k) for k in ("kind", "say", "url", "step", "needs", "at")
            if boundary.get(k)}
    history = [str(h.get("did") or "") for h in (record.get("history") or [])][-12:]
    submits = [f"{s.get('button')}: {s.get('verdict')}" for s in (record.get("submits") or [])]
    text = (f"Browser mission: {record.get('goal')}\nStart: {record.get('start_url')}\n"
            f"State: {record.get('state')} skill: {record.get('skill')} mode: {record.get('mode')}\n"
            f"Stopped at: {json.dumps(stop, ensure_ascii=False)}\n"
            f"Checkpoints: {', '.join(str(c.get('name')) for c in (record.get('checkpoints') or [])[-15:])}\n"
            f"Submits: {'; '.join(submits)}\nHistory: {' | '.join(history)}")
    return Chunk(f"browser mission {record.get('id')}", text, ts=str(record.get("beat") or ""),
                 locator=f"browser mission {record.get('id')}")


def _render_application(record: dict) -> Chunk | None:
    if "state" not in record or not record.get("id"):
        return None
    from aletheia import state_tools
    summary = state_tools.summarise_record(record)
    text = "Application record: " + json.dumps(summary, ensure_ascii=False, default=str)
    return Chunk(f"application {record.get('id')}", text,
                 ts=str(record.get("submitted_at") or record.get("staged_at") or ""),
                 locator=f"application {record.get('id')}")


def _render_notification(record: dict) -> Chunk | None:
    if not record.get("id"):
        return None
    text = (f"Notification ({record.get('source')}, {record.get('priority')}): "
            f"{record.get('title', '')}\n{record.get('body', '')}")
    return Chunk(f"notification {record.get('id')}", text, ts=str(record.get("created_at") or ""),
                 locator=f"notification {record.get('id')}")


def _render_study(record: dict) -> Chunk | None:
    """What a study compared, proposed and learned. Never the raw text of a page: that is
    untrusted, and memory is read back into prompts."""
    if not str(record.get("id") or "").startswith("study-"):
        return None
    subject = (record.get("subject") or {}).get("name") or ""
    comparison = record.get("comparison") or {}
    rows = "; ".join(str(r.get("said") or "") for r in (comparison.get("rows") or [])[:8])
    claims = "; ".join(str(c.get("text") or "") for c in (comparison.get("claims") or [])[:6])
    hyps = "; ".join(f"{h.get('title')} [{h.get('state')}] metric {(h.get('metric') or {}).get('name')}"
                     + (f" result: {(h.get('measurement') or {}).get('said')}" if h.get("measurement") else "")
                     for h in (record.get("hypotheses") or [])[:8])
    learned = "; ".join(f"{l.get('title')}: {l.get('metric')} {l.get('baseline')} -> {l.get('after')} "
                        f"({l.get('verdict')})" for l in (record.get("learned") or [])[-6:])
    text = (f"Study of {subject} against {', '.join(c.get('name') or '' for c in record.get('comparables') or [])}\n"
            f"Asked: {record.get('words')}\nMeasured: {rows}\nClaims: {claims}\nProposals: {hyps}\n"
            f"What worked: {learned}")
    return Chunk(f"study {record.get('id')}", text, ts=str(record.get("updated_at") or ""),
                 locator=f"study {record.get('id')}")


def study_docs() -> Iterator[Doc]:
    from aletheia import studies
    return _json_dir_docs("studies", studies.studies_dir(), _render_study, pattern="study-*.json")


def session_docs() -> Iterator[Doc]:
    from aletheia import stateio
    return _json_dir_docs("sessions", stateio.private_dir("agent-sessions"), _render_session)


def mission_docs() -> Iterator[Doc]:
    from aletheia import browser_mission
    return _json_dir_docs("missions", browser_mission.missions_dir(), _render_mission)


def application_docs() -> Iterator[Doc]:
    from aletheia import apply_run
    return _json_dir_docs("applications", apply_run.staged_dir(), _render_application,
                          pattern="apply-*.json")


def notification_docs() -> Iterator[Doc]:
    from aletheia import stateio
    return _json_dir_docs("notifications", stateio.private_dir("notifications"),
                          _render_notification)


def employer_docs() -> Iterator[Doc]:
    from aletheia import employers
    _refuse_private(employers.path())
    try:
        rows = employers.all_rows()
    except Exception:
        return
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        material = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)

        def load(row=row, name=name) -> list[Chunk]:
            text = (f"Employer: {name}\nDomains: {', '.join(row.get('domains') or [])}\n"
                    f"Careers: {', '.join(row.get('career_urls') or [])}\nATS: {row.get('ats') or ''}\n"
                    f"Locations: {', '.join(row.get('locations') or [])}\n"
                    f"Jobs seen: {row.get('jobs_seen')} last crawled: {row.get('last_crawled') or 'never'}\n"
                    f"Found via: {row.get('source') or ''}\nNotes: {row.get('notes') or ''}")
            return [Chunk(f"employer {name}", text, ts=str(row.get("last_seen") or ""),
                          locator=f"employer {name}")]
        yield Doc("employers", f"employers/{_sha(name.casefold())[:16]}", _sha(material), load)


def fix_docs() -> Iterator[Doc]:
    """Every commit message: what changed and why, which is how a past fix
    for a similar failure is found."""
    from aletheia import repo_tools
    try:
        out = repo_tools._git("log", "--no-merges", "--format=%H%x1f%cI%x1f%s%x1f%b%x1e")
    except Exception:
        return
    for record in out.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) < 4 or not parts[0].strip():
            continue
        commit, when, subject, body = parts[0].strip(), parts[1], parts[2], parts[3]

        def load(commit=commit, when=when, subject=subject, body=body) -> list[Chunk]:
            body = "\n".join(l for l in body.splitlines()
                             if not l.startswith(("Co-Authored-By:", "Claude-Session:")))
            text = f"Commit {commit[:10]}: {subject}\n\n{body.strip()}"
            return [Chunk(f"commit {commit[:10]} {subject[:80]}", piece, ts=when,
                          locator=f"commit {commit[:10]}")
                    for piece in split_text(text, CHUNK_CHARS * 2)[:3]]
        yield Doc("fixes", f"fixes/{commit}", commit, load)


#: The allowlist, in the order embeddings are filled: what diagnosis needs
#: most first. A new store joins here, and nowhere else needs to know.
SOURCES: dict[str, Callable[[], Iterable[Doc]]] = {
    "missions": mission_docs,
    "applications": application_docs,
    "sessions": session_docs,
    "studies": study_docs,
    "notifications": notification_docs,
    "journal": journal_docs,
    "fixes": fix_docs,
    "employers": employer_docs,
    "docs": doc_docs,
    "code": code_docs,
}
PRIVATE_SOURCES = frozenset({"missions", "applications", "sessions", "notifications",
                             "journal", "employers", "studies"})


# ---- storage -------------------------------------------------------------------

def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path is not None else db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        _ensure_schema(conn)
        return conn
    except sqlite3.Error as exc:
        raise IndexUnavailable(f"the index could not be opened ({type(exc).__name__}: {exc})") from None


def has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key='fts'").fetchone()
    return bool(row and row[0] == "1")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS docs (source TEXT, ref TEXT, digest TEXT, indexed_at TEXT,
                                         PRIMARY KEY (source, ref));
        CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, source TEXT, ref TEXT,
                                           title TEXT, text TEXT, ts TEXT, locator TEXT, sha TEXT);
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks (source, ref);
        CREATE INDEX IF NOT EXISTS chunks_sha ON chunks (sha);
        CREATE TABLE IF NOT EXISTS vectors (sha TEXT, model TEXT, dim INTEGER, vec BLOB, at TEXT,
                                            PRIMARY KEY (sha, model));
    """)
    if conn.execute("SELECT value FROM meta WHERE key='fts'").fetchone() is None:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title, text)")
            fts = "1"
        except sqlite3.OperationalError:
            fts = "0"
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('fts', ?)", (fts,))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        conn.commit()


def _bump_generation(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('generation', ?)",
                 (str(int(row[0]) + 1 if row else 1),))


def _delete_doc(conn: sqlite3.Connection, source: str, ref: str, fts: bool) -> int:
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE source=? AND ref=?", (source, ref))]
    if fts and ids:
        conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    conn.execute("DELETE FROM chunks WHERE source=? AND ref=?", (source, ref))
    conn.execute("DELETE FROM docs WHERE source=? AND ref=?", (source, ref))
    return len(ids)


def _insert_chunks(conn: sqlite3.Connection, doc: Doc, chunks: list[Chunk], fts: bool) -> int:
    n = 0
    for chunk in chunks:
        text = _clean(chunk.text).strip()
        if not text:
            continue
        title = _clean(chunk.title)[:200]
        cur = conn.execute(
            "INSERT INTO chunks (source, ref, title, text, ts, locator, sha) VALUES (?,?,?,?,?,?,?)",
            (doc.source, doc.ref, title, text, chunk.ts, _clean(chunk.locator)[:200],
             _sha(title + "\n" + text)))
        if fts:
            conn.execute("INSERT INTO chunks_fts (rowid, title, text) VALUES (?,?,?)",
                         (cur.lastrowid, title, text))
        n += 1
    conn.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)", (doc.source, doc.ref, doc.digest, _now()))
    return n


# ---- the embedder --------------------------------------------------------------

class EmbedderUnavailable(RuntimeError):
    pass


class OllamaEmbedder:
    """The tiny local embedding model, through the same loopback-only
    transport her chat models use (`local_brain`)."""

    def __init__(self, model: str | None = None, *, threads: int = EMBED_THREADS,
                 timeout_s: float = EMBED_TIMEOUT_S):
        self.model = model or model_name()
        self.threads = threads
        self.timeout_s = timeout_s
        self._available: bool | None = None
        self.why = ""

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def _config(self, timeout_s: float | None = None):
        from aletheia import local_brain
        return local_brain.OllamaConfig.for_model(self.model, timeout_s=timeout_s or self.timeout_s)

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        from aletheia import local_brain
        try:
            listed = local_brain.request_json(self._config(4.0), "/api/tags")
            names = {str(m.get("name") or "") for m in listed.get("models") or []}
            ok = self.model in names or f"{self.model}:latest" in names
            self.why = "" if ok else f"the embedding model {self.model} is not pulled"
        except Exception as exc:                              # noqa: BLE001
            ok, self.why = False, f"Ollama did not answer ({type(exc).__name__})"
        self._available = ok
        return ok

    def busy(self) -> bool:
        """Is a chat model loaded (so she is, or just was, thinking)? Loaded
        models expire 30 s after their last use by default."""
        from aletheia import local_brain
        try:
            loaded = local_brain.request_json(self._config(4.0), "/api/ps")
        except Exception:                                     # noqa: BLE001
            return False
        for row in loaded.get("models") or []:
            name = str(row.get("name") or row.get("model") or "")
            if name.split(":")[0] != self.model.split(":")[0]:
                return True
        return False

    def embed(self, texts: list[str], *, timeout_s: float | None = None) -> list[list[float]]:
        from aletheia import local_brain
        if not texts:
            return []
        payload = {"model": self.model, "input": list(texts), "truncate": True,
                   "keep_alive": "2m", "options": {"num_thread": self.threads}}
        try:
            out = local_brain.request_json(self._config(timeout_s), "/api/embed", payload)
        except Exception as exc:                              # noqa: BLE001
            raise EmbedderUnavailable(f"embedding failed ({type(exc).__name__})") from None
        vectors = out.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedderUnavailable(str(out.get("error") or "the embedding reply had the wrong shape")[:160])
        return vectors


def _normalise(vector: list[float]) -> array.array:
    norm = math.sqrt(sum(float(x) * float(x) for x in vector)) or 1.0
    return array.array("f", (float(x) / norm for x in vector))


def _embed_text(title: str, text: str) -> str:
    return (title + "\n" + text)[:EMBED_CHARS]


# ---- building --------------------------------------------------------------------

def _lock_path() -> Path:
    return index_dir() / "build.lock"


def _take_lock() -> bool:
    from aletheia import proc
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        holder = json.loads(path.read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        holder = None
    if holder and holder != os.getpid() and proc.pid_alive(holder) is not False:
        return False
    path.write_text(json.dumps({"pid": os.getpid(), "at": _now()}), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        if json.loads(_lock_path().read_text(encoding="utf-8")).get("pid") == os.getpid():
            _lock_path().unlink()
    except (OSError, ValueError, AttributeError):
        pass


def build(*, budget_s: float = DEFAULT_BUDGET_S, embed: bool = True,
          sources: Iterable[str] | None = None, embedder: Any = None,
          path: Path | None = None, polite: bool = True,
          source_table: dict[str, Callable[[], Iterable[Doc]]] | None = None) -> dict:
    """One incremental pass. Text first (cheap, every changed document),
    then embeddings for whatever has none, until the budget is spent."""
    started = time.monotonic()
    deadline = started + max(1.0, float(budget_s))
    table = source_table if source_table is not None else SOURCES
    wanted = [s for s in (list(sources) if sources else list(table)) if s in table]
    report: dict[str, Any] = {"started_at": _now(), "sources": {}, "embedded": 0,
                              "embedder": None, "embed_skipped": "", "errors": []}
    use_lock = path is None
    if use_lock and not _take_lock():
        report["embed_skipped"] = "another build is running"
        report["skipped"] = True
        return report
    conn = connect(path)
    try:
        fts = has_fts(conn)
        known = {(s, r): d for s, r, d in conn.execute("SELECT source, ref, digest FROM docs")}
        changed_any = False
        for source in wanted:
            stats = {"docs": 0, "changed": 0, "removed": 0, "chunks_added": 0, "complete": True}
            seen: set[str] = set()
            try:
                for doc in table[source]():
                    if time.monotonic() > deadline:
                        stats["complete"] = False
                        break
                    stats["docs"] += 1
                    seen.add(doc.ref)
                    if known.get((source, doc.ref)) == doc.digest:
                        continue
                    try:
                        chunks = doc.load()
                    except PermissionError:
                        raise
                    except Exception as exc:                          # noqa: BLE001
                        report["errors"].append(f"{source}/{doc.ref}: {type(exc).__name__}")
                        continue
                    _delete_doc(conn, source, doc.ref, fts)
                    stats["chunks_added"] += _insert_chunks(conn, doc, chunks, fts)
                    stats["changed"] += 1
                    changed_any = True
                    if stats["changed"] % 200 == 0:
                        conn.commit()
            except PermissionError:
                raise
            except Exception as exc:                                  # noqa: BLE001
                stats["complete"] = False
                report["errors"].append(f"{source}: {type(exc).__name__}: {str(exc)[:120]}")
            if stats["complete"]:
                for (s, ref) in [k for k in known if k[0] == source and k[1] not in seen]:
                    _delete_doc(conn, s, ref, fts)
                    stats["removed"] += 1
                    changed_any = True
            report["sources"][source] = stats
            conn.commit()
        if changed_any:
            _bump_generation(conn)
            conn.commit()

        model = None
        if embed and time.monotonic() < deadline:
            embedder = embedder if embedder is not None else OllamaEmbedder()
            model = getattr(embedder, "model", None)
            _embed_pass(conn, report, deadline, embedder, wanted, polite)
        # Vectors whose text no chunk holds any more are dead weight.
        conn.execute("DELETE FROM vectors WHERE sha NOT IN (SELECT sha FROM chunks)")
        conn.commit()
        report.update(counts(conn, model))
    finally:
        conn.close()
        if use_lock:
            _release_lock()
    report["seconds"] = round(time.monotonic() - started, 1)
    report["finished_at"] = _now()
    return report


def _embed_pass(conn, report, deadline, embedder, wanted, polite) -> None:
    report["embedder"] = getattr(embedder, "name", type(embedder).__name__)
    model = getattr(embedder, "model", report["embedder"])
    if hasattr(embedder, "available") and not embedder.available():
        report["embed_skipped"] = getattr(embedder, "why", "") or "the embedder is unavailable"
        return
    if polite and hasattr(embedder, "busy") and embedder.busy():
        report["embed_skipped"] = "a chat model is loaded, so she is thinking; embeddings wait"
        return
    order = {s: n for n, s in enumerate(wanted)}
    rows = conn.execute(
        "SELECT MIN(c.id), c.sha, c.source, c.title, c.text FROM chunks c "
        "LEFT JOIN vectors v ON v.sha = c.sha AND v.model = ? WHERE v.sha IS NULL "
        "GROUP BY c.sha", (model,)).fetchall()
    rows = [r for r in rows if r[2] in order]
    rows.sort(key=lambda r: (order[r[2]], r[0]))
    batch_started = time.monotonic()
    for i in range(0, len(rows), EMBED_BATCH):
        if time.monotonic() > deadline:
            break
        batch = rows[i:i + EMBED_BATCH]
        try:
            vectors = embedder.embed([_embed_text(r[3], r[4]) for r in batch])
        except Exception as exc:                                      # noqa: BLE001
            report["embed_skipped"] = f"embedding stopped: {str(exc)[:160]}"
            break
        for row, vector in zip(batch, vectors):
            vec = _normalise(vector)
            conn.execute("INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?)",
                         (row[1], model, len(vec), vec.tobytes(), _now()))
        report["embedded"] += len(batch)
        conn.commit()
    spent = time.monotonic() - batch_started
    if report["embedded"]:
        report["embed_rate_per_s"] = round(report["embedded"] / max(spent, 1e-6), 1)
    _bump_generation(conn)


def counts(conn: sqlite3.Connection, model: str | None = None) -> dict:
    model = model or model_name()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedded = conn.execute(
        "SELECT COUNT(*) FROM chunks c JOIN vectors v ON v.sha = c.sha AND v.model = ?",
        (model,)).fetchone()[0]
    by_source = {s: n for s, n in conn.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source")}
    return {"chunks": chunks, "embedded_chunks": embedded, "by_source": by_source,
            "docs": conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0], "model": model}


def status(path: Path | None = None) -> dict:
    target = Path(path) if path is not None else db_path()
    if not target.exists():
        return {"built": False, "path": str(target),
                "note": "the index has not been built yet"}
    conn = connect(target)
    try:
        out = counts(conn)
    finally:
        conn.close()
    size = sum(p.stat().st_size for p in target.parent.glob(target.name + "*") if p.is_file())
    out.update({"built": True, "path": str(target), "bytes": size, "last_run": read_stamp()})
    return out


# ---- the ledger: what she KNOWS -------------------------------------------------

def _name_hit(words: set[str], name: str) -> bool:
    parts = [t for t in tokens(name) if len(t) >= 3 and t not in STOPWORDS and t not in GENERIC]
    return bool(parts) and all(p in words for p in parts)


def _desc_hit(words: list[str], text: str) -> bool:
    specific = [w for w in words if w not in GENERIC]
    if not specific:
        return False
    have = set(tokens(text))
    hits = sum(1 for w in specific if w in have)
    return hits >= min(2, len(specific)) and hits * 2 >= len(specific)


def _probe_missions(words: list[str], raw: str) -> list[dict]:
    from aletheia import browser_mission
    out = []
    for record in browser_mission.all_missions():
        if record.get("id") in raw or _desc_hit(words, str(record.get("goal") or "")):
            out.append({"store": "browser missions", "id": record.get("id"),
                        "fact": browser_mission.describe(record),
                        "state": record.get("state"), "boundary": record.get("boundary")})
    return out


def _probe_applications(words: list[str], raw: str) -> list[dict]:
    from aletheia import apply_run, state_tools
    wordset = set(words)
    out = []
    for record in apply_run.all_runs():
        if (str(record.get("id") or "") and str(record.get("id")) in raw) \
                or _name_hit(wordset, str(record.get("company") or "")) \
                or _desc_hit(words, str(record.get("job_title") or "")):
            out.append({"store": "applications", "id": record.get("id"),
                        "fact": state_tools.summarise_record(record)})
    out.sort(key=lambda f: str(f["fact"].get("submitted_at") or f["fact"].get("staged_at") or ""),
             reverse=True)
    return out


def _probe_employers(words: list[str], raw: str) -> list[dict]:
    from aletheia import employers
    wordset = set(words)
    return [{"store": "employers", "id": row.get("name"), "fact": employers.describe(row)}
            for row in employers.all_rows() if _name_hit(wordset, str(row.get("name") or ""))]


def _probe_tasks(words: list[str], raw: str) -> list[dict]:
    from aletheia import tasks
    return [{"store": "tasks", "id": t.get("id"),
             "fact": {k: t.get(k) for k in ("id", "description", "status", "deadline", "goal") if t.get(k)}}
            for t in tasks.all_tasks()
            if str(t.get("id") or "") in raw or _desc_hit(words, str(t.get("description") or ""))]


def _probe_plans(words: list[str], raw: str) -> list[dict]:
    from aletheia import plans
    out = []
    for plan in plans.all_plans():
        slug = str(plan.get("slug") or plan.get("id") or "")
        if (slug and slug in raw) or _desc_hit(words, f"{plan.get('title', '')} {plan.get('goal', '')}"):
            out.append({"store": "plans", "id": slug,
                        "fact": {k: plan.get(k) for k in ("title", "goal", "state") if plan.get(k)}})
    return out


def _probe_memory(words: list[str], raw: str) -> list[dict]:
    from aletheia import memory
    wordset = set(words)
    out = []
    for domain in ("people", "organizations", "preferences"):
        try:
            entries = memory._load(domain)
        except (OSError, ValueError):
            continue
        for key, entry in entries.items():
            if isinstance(entry, dict) and _name_hit(wordset, key.replace("_", " ")):
                out.append({"store": f"memory {domain}", "id": key,
                            "fact": {"value": entry.get("value"), "kind": entry.get("kind"),
                                     "source": str(entry.get("source") or "")[:120]}})
    return out


#: The stores she keeps exact facts in, as a table. Two of them are about the
#: job hunt; none of the code below knows which.
LEDGER_PROBES: dict[str, Callable[[list[str], str], list[dict]]] = {
    "missions": _probe_missions,
    "applications": _probe_applications,
    "employers": _probe_employers,
    "tasks": _probe_tasks,
    "plans": _probe_plans,
    "memory": _probe_memory,
}
MAX_FACTS = 6


def ledger(query: str, *, probes: dict | None = None) -> tuple[list[dict], list[str]]:
    """(facts, stores that could not be read). A probe that fails says so;
    it never reads as 'nothing there'."""
    words = significant(query)
    raw = str(query or "")
    facts, unreadable = [], []
    for name, probe in (probes if probes is not None else LEDGER_PROBES).items():
        try:
            found = probe(words, raw)
        except Exception:                                            # noqa: BLE001
            unreadable.append(name)
            continue
        facts.extend(found)
    cleaned = []
    for fact in facts[:MAX_FACTS]:
        try:
            cleaned.append(json.loads(_clean(json.dumps(fact, ensure_ascii=False, default=str))))
        except ValueError:
            continue
    return cleaned, unreadable


# ---- recall -------------------------------------------------------------------------

_VECTOR_CACHE: dict[str, Any] = {"key": None, "ids": None, "matrix": None, "sources": None}


def _fts_query(words: list[str]) -> str:
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words[:24])


def _lexical(conn, words: list[str], sources: list[str] | None, limit: int) -> list[tuple[int, float]]:
    if not words:
        return []
    where, params = "", []
    if sources:
        where = f" AND c.source IN ({','.join('?' * len(sources))})"
        params = list(sources)
    if has_fts(conn):
        rows = conn.execute(
            "SELECT chunks_fts.rowid, bm25(chunks_fts, 2.0, 1.0) AS score FROM chunks_fts "
            "JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ?" + where +
            " ORDER BY score LIMIT ?", [_fts_query(words), *params, limit]).fetchall()
        return [(r[0], -float(r[1])) for r in rows]
    return _python_bm25(conn, words, sources, limit)


def _python_bm25(conn, words, sources, limit, k1: float = 1.2, b: float = 0.75):
    """BM25 in plain Python, for an SQLite built without FTS5."""
    sql = "SELECT id, title, text FROM chunks c"
    params: list = []
    if sources:
        sql += f" WHERE c.source IN ({','.join('?' * len(sources))})"
        params = list(sources)
    docs = [(r[0], tokens(r[1] + " " + r[2])) for r in conn.execute(sql, params)]
    if not docs:
        return []
    avg = sum(len(t) for _, t in docs) / len(docs)
    wanted = set(words)
    df = {w: 0 for w in wanted}
    tf_rows = []
    for doc_id, toks in docs:
        tf: dict[str, int] = {}
        for t in toks:
            if t in wanted:
                tf[t] = tf.get(t, 0) + 1
        for w in tf:
            df[w] += 1
        if tf:
            tf_rows.append((doc_id, tf, len(toks)))
    n = len(docs)
    scored = []
    for doc_id, tf, length in tf_rows:
        score = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * length / avg))
        scored.append((doc_id, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def _vectors(conn, model: str):
    generation = conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()
    key = (str(conn.execute("PRAGMA database_list").fetchone()[2]), model,
           generation[0] if generation else "0")
    if _VECTOR_CACHE["key"] == key:
        return _VECTOR_CACHE["ids"], _VECTOR_CACHE["matrix"], _VECTOR_CACHE["sources"]
    ids, sources, flat = [], [], array.array("f")
    dim = 0
    for chunk_id, source, blob, d in conn.execute(
            "SELECT c.id, c.source, v.vec, v.dim FROM chunks c JOIN vectors v "
            "ON v.sha = c.sha AND v.model = ?", (model,)):
        if dim and d != dim:
            continue
        dim = d
        ids.append(chunk_id)
        sources.append(source)
        flat.frombytes(blob)
    matrix: Any = (flat, dim)
    try:
        import numpy as np                                            # optional, never required
        matrix = np.frombuffer(flat.tobytes(), dtype=np.float32).reshape(len(ids), dim) if ids else None
    except Exception:                                                 # noqa: BLE001
        pass
    _VECTOR_CACHE.update({"key": key, "ids": ids, "matrix": matrix, "sources": sources})
    return ids, matrix, sources


def _semantic(conn, query_vec: array.array, model: str, sources, limit: int) -> list[tuple[int, float]]:
    ids, matrix, chunk_sources = _vectors(conn, model)
    if not ids or matrix is None:
        return []
    wanted = set(sources) if sources else None
    if isinstance(matrix, tuple):
        flat, dim = matrix
        q = list(query_vec)
        scores = []
        for n, chunk_id in enumerate(ids):
            if wanted and chunk_sources[n] not in wanted:
                continue
            row = flat[n * dim:(n + 1) * dim]
            scores.append((chunk_id, sum(a * b for a, b in zip(q, row))))
    else:
        import numpy as np
        sims = matrix @ np.frombuffer(query_vec.tobytes(), dtype=np.float32)
        scores = [(ids[n], float(sims[n])) for n in range(len(ids))
                  if not wanted or chunk_sources[n] in wanted]
    scores.sort(key=lambda x: -x[1])
    return scores[:limit]


def _snippet(text: str, words: list[str], limit: int = MAX_SNIPPET) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    low = flat.casefold()
    best = 0
    positions = [low.find(w) for w in words if low.find(w) >= 0]
    if positions:
        best = max(0, min(positions) - limit // 4)
    piece = flat[best:best + limit]
    return ("..." if best else "") + piece + ("..." if best + limit < len(flat) else "")


def recall(query: str, *, sources: Iterable[str] | None = None, k: int = DEFAULT_K,
           embedder: Any = None, path: Path | None = None, include_ledger: bool = True,
           probes: dict | None = None) -> dict:
    """Facts from the ledger, then passages from the index, with the basis."""
    query = " ".join(str(query or "").split())[:400]
    k = max(1, min(int(k or DEFAULT_K), MAX_K))
    wanted = [s for s in (list(sources) if sources else []) if s in SOURCES or s == "ledger"]
    index_sources = [s for s in wanted if s != "ledger"] or None
    out: dict[str, Any] = {"query": query, "facts": [], "snippets": [], "basis": GUESS}
    if not query:
        out["note"] = "no query was given"
        return out
    if include_ledger and (not wanted or "ledger" in wanted):
        facts, unreadable = ledger(query, probes=probes)
        out["facts"] = [{**f, "basis": KNOWN} for f in facts]
        if unreadable:
            out["unreadable_stores"] = unreadable
    words = significant(query)
    target = Path(path) if path is not None else db_path()
    engine = "none"
    if not target.exists():
        out["index"] = "not built yet: the index has never run on this machine"
    elif not wanted or index_sources:
        try:
            conn = connect(target)
        except IndexUnavailable as exc:
            out["index"] = str(exc)
            conn = None
        if conn is not None:
            try:
                embedder = embedder if embedder is not None else OllamaEmbedder(
                    timeout_s=QUERY_EMBED_TIMEOUT_S)
                total = counts(conn, getattr(embedder, "model", None))
                lexical = _lexical(conn, words, index_sources, 40)
                semantic: list[tuple[int, float]] = []
                why_lexical = ""
                if total["embedded_chunks"]:
                    if hasattr(embedder, "available") and not embedder.available():
                        why_lexical = getattr(embedder, "why", "") or "the embedder is unavailable"
                    else:
                        try:
                            qvec = _normalise(embedder.embed([query])[0])
                            semantic = _semantic(conn, qvec, getattr(embedder, "model", model_name()),
                                                 index_sources, 40)
                        except Exception as exc:                      # noqa: BLE001
                            why_lexical = f"the embedding model did not answer ({str(exc)[:80]})"
                else:
                    why_lexical = "no chunk has an embedding yet"
                fused: dict[int, float] = {}
                for rank, (cid, _s) in enumerate(lexical):
                    fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
                for rank, (cid, _s) in enumerate(semantic):
                    fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
                if semantic and lexical:
                    engine = "semantic+lexical"
                elif semantic:
                    engine = "semantic"
                elif lexical or words:
                    engine = "lexical"
                coverage = (total["embedded_chunks"] / total["chunks"]) if total["chunks"] else 0.0
                out["answered_by"] = engine
                out["embedded_fraction"] = round(coverage, 3)
                if engine == "lexical" and why_lexical:
                    out["lexical_because"] = why_lexical
                ranked = sorted(fused.items(), key=lambda x: -x[1])
                picked, per_doc = [], {}
                for cid, score in ranked:
                    row = conn.execute("SELECT source, ref, title, text, ts, locator FROM chunks WHERE id=?",
                                       (cid,)).fetchone()
                    if row is None or per_doc.get(row[1], 0) >= 2:
                        continue
                    per_doc[row[1]] = per_doc.get(row[1], 0) + 1
                    picked.append({"source": row[0], "where": row[5] or row[1], "title": row[2],
                                   "ts": row[4], "text": _snippet(row[3], words),
                                   "basis": FOUND, "score": round(score * 1000, 2)})
                    if len(picked) >= k:
                        break
                out["snippets"] = picked
            except sqlite3.Error as exc:
                out["index"] = f"the index could not be searched ({type(exc).__name__})"
            finally:
                conn.close()
    if out["facts"]:
        out["basis"] = KNOWN
    elif out["snippets"]:
        out["basis"] = FOUND
    if out["basis"] == GUESS:
        out["note"] = ("nothing in her stores or her history matches this. Anything said about "
                       "it now is a GUESS and must be said as one.")
    elif out["basis"] == FOUND:
        out["note"] = ("these are passages that LOOK related, found by search - history, not "
                       "fact. Say 'from my history' and check before stating them as true.")
    else:
        out["note"] = ("facts are exact rows from her own stores; snippets are related history "
                       "found by search and are not facts.")
    return out


# ---- running in the background ---------------------------------------------------

def read_stamp() -> dict:
    try:
        value = json.loads(stamp_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_stamp(value: dict) -> None:
    from aletheia import stateio
    stamp_path().parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(stamp_path(), value)


def _due(stamp: dict, now: float, interval_s: float) -> bool:
    last = stamp.get("finished_epoch") or stamp.get("started_epoch") or 0
    try:
        return now - float(last) >= interval_s
    except (TypeError, ValueError):
        return True


#: Windows priority and window flags for the background build.
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _spawn_build(budget_s: float) -> int:
    from aletheia import proc
    from aletheia.fleet import REPO_ROOT
    index_dir().mkdir(parents=True, exist_ok=True)
    log = open(index_dir() / "build.log", "a", encoding="utf-8")
    kwargs: dict = {"cwd": str(REPO_ROOT), "stdin": subprocess.DEVNULL, "stdout": log,
                    "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = proc.hidden_flags(BELOW_NORMAL_PRIORITY_CLASS | CREATE_NEW_PROCESS_GROUP)
    try:
        return subprocess.Popen([sys.executable, "-m", "aletheia.semantic_index", "build",
                                 "--budget-s", str(int(budget_s)), "--quiet"], **kwargs).pid
    finally:
        log.close()


def kick_if_due(*, interval_s: float = RUN_INTERVAL_S, budget_s: float = DEFAULT_BUDGET_S,
                spawner: Callable[[float], int] | None = None, now: float | None = None) -> dict:
    """Start one background build if one is due and none is running. Cheap:
    a JSON read and, at most, one process start. Never raises."""
    try:
        if os.environ.get("ALETHEIA_REHEARSAL") or os.environ.get("ALETHEIA_SEMANTIC_INDEX_OFF"):
            return {"started": False, "why": "off in this process"}
        from aletheia import policy, proc
        if policy.halted() is not None:
            return {"started": False, "why": "halted"}
        now = time.time() if now is None else now
        stamp = read_stamp()
        pid = stamp.get("pid")
        if pid and not stamp.get("finished_epoch") and \
                proc.pid_alive(pid, needle="aletheia.semantic_index") is not False and \
                now - float(stamp.get("started_epoch") or 0) < 6 * 3600:
            return {"started": False, "why": "a build is already running", "pid": pid}
        if not _due(stamp, now, interval_s):
            return {"started": False, "why": "not due"}
        pid = (spawner or _spawn_build)(budget_s)
        _write_stamp({"pid": pid, "started_epoch": now, "started_at": _now(), "by": "core"})
        return {"started": True, "pid": pid}
    except Exception as exc:                                          # noqa: BLE001
        return {"started": False, "why": f"{type(exc).__name__}: {str(exc)[:120]}"}


def background_loop(stop=None, *, first_wait_s: float = LOOP_FIRST_WAIT_S,
                    poll_s: float = LOOP_POLL_S) -> None:
    """The Core's daemon thread: wait, kick, wait. The thread itself does no
    indexing, so it cannot slow a beat or an answer."""
    import threading
    stop = stop or threading.Event()
    if stop.wait(first_wait_s):
        return
    while not stop.is_set():
        kick_if_due()
        if stop.wait(poll_s):
            return


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Her local semantic index over code, docs and history.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    b.add_argument("--no-embed", action="store_true")
    b.add_argument("--sources", default="")
    b.add_argument("--quiet", action="store_true")
    r = sub.add_parser("recall")
    r.add_argument("query")
    r.add_argument("--sources", default="")
    r.add_argument("-k", type=int, default=DEFAULT_K)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        stamp = read_stamp()
        started = time.time()
        _write_stamp({**stamp, "pid": os.getpid(), "started_epoch": started, "started_at": _now(),
                      "finished_epoch": None})
        try:
            report = build(budget_s=args.budget_s, embed=not args.no_embed,
                           sources=[s for s in args.sources.split(",") if s] or None)
        finally:
            done = read_stamp()
            done.update({"pid": os.getpid(), "finished_epoch": time.time(), "finished_at": _now()})
            _write_stamp(done)
        if not report.get("skipped"):
            stamp = read_stamp()
            stamp["last_report"] = {k: report.get(k) for k in
                                    ("seconds", "chunks", "embedded_chunks", "embedded", "embedder",
                                     "embed_skipped", "errors", "embed_rate_per_s")}
            _write_stamp(stamp)
        print(json.dumps(report if not args.quiet else
                         {k: report.get(k) for k in ("seconds", "chunks", "embedded_chunks", "embedded",
                                                      "embed_skipped")}, indent=1, default=str))
        return 0
    if args.cmd == "recall":
        print(json.dumps(recall(args.query, sources=[s for s in args.sources.split(",") if s] or None,
                                k=args.k), indent=1, ensure_ascii=False, default=str))
        return 0
    print(json.dumps(status(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
