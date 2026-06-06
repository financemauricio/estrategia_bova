"""Database access layer — Supabase PostgreSQL via psycopg2.

All public functions are thin wrappers that open a connection, execute a
single logical operation and close cleanly, so Streamlit's multi-user
re-run model does not leak connections.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Generator

import psycopg2
import psycopg2.extras
import streamlit as st


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    """Return DATABASE_URL from Streamlit secrets or .env fallback.

    Special characters in the password are percent-encoded automatically so
    psycopg2 can parse the URI correctly (e.g. ``&``, ``}``, ``)`` etc.).
    """
    from urllib.parse import urlparse, quote, urlunparse

    try:
        raw = st.secrets["DATABASE_URL"]
    except Exception:
        from dotenv import load_dotenv
        load_dotenv()
        raw = os.getenv("DATABASE_URL")
        if not raw:
            raise RuntimeError(
                "DATABASE_URL não configurado. Copie .env.example para .env e preencha."
            )

    parsed = urlparse(raw)
    if parsed.password:
        encoded_pw = quote(parsed.password, safe="")
        netloc = f"{parsed.username}:{encoded_pw}@{parsed.hostname}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))
    return raw


@contextlib.contextmanager
def _conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context manager that yields a committed (or rolled-back) connection."""
    con = psycopg2.connect(_get_db_url())
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS posicoes (
    id          SERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL UNIQUE,
    quantidade  REAL NOT NULL DEFAULT 0,
    preco_medio REAL NOT NULL DEFAULT 0,
    atualizado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS opcoes (
    id               SERIAL PRIMARY KEY,
    data_abertura    DATE NOT NULL,
    tipo             TEXT NOT NULL CHECK (tipo IN ('PUT', 'CALL')),
    ativo            TEXT NOT NULL DEFAULT 'BOVA11',
    codigo_opcao     TEXT,
    strike           REAL NOT NULL,
    vencimento       DATE NOT NULL,
    quantidade       INTEGER NOT NULL,
    premio_unitario  REAL NOT NULL,
    premio_total     REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ABERTA'
                         CHECK (status IN ('ABERTA', 'EXERCIDA', 'EXPIRADA', 'ROLADA')),
    data_fechamento  DATE,
    premio_recompra  REAL DEFAULT 0,
    origem_id        INTEGER REFERENCES opcoes(id),
    observacao       TEXT,
    criado_em        TIMESTAMPTZ DEFAULT NOW()
);

-- Migrations: add new columns to existing tables (idempotent)
ALTER TABLE opcoes ADD COLUMN IF NOT EXISTS premio_recompra REAL DEFAULT 0;
ALTER TABLE opcoes ADD COLUMN IF NOT EXISTS origem_id INTEGER REFERENCES opcoes(id);

CREATE TABLE IF NOT EXISTS aportes (
    id            SERIAL PRIMARY KEY,
    data          DATE NOT NULL,
    valor_total   REAL NOT NULL,
    bova11_qtd    REAL DEFAULT 0,
    bova11_valor  REAL DEFAULT 0,
    ivvb11_qtd    REAL DEFAULT 0,
    ivvb11_valor  REAL DEFAULT 0,
    hash11_qtd    REAL DEFAULT 0,
    hash11_valor  REAL DEFAULT 0,
    observacao    TEXT,
    criado_em     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS caixa (
    id         SERIAL PRIMARY KEY,
    data       DATE NOT NULL,
    tipo       TEXT NOT NULL CHECK (tipo IN ('ENTRADA', 'SAIDA')),
    valor      REAL NOT NULL,
    descricao  TEXT,
    criado_em  TIMESTAMPTZ DEFAULT NOW()
);
"""


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(_DDL)


# ---------------------------------------------------------------------------
# Posicoes
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def listar_posicoes() -> list[dict[str, Any]]:
    """Return all ticker positions.

    Returns
    -------
    list[dict]
        Each dict has keys: id, ticker, quantidade, preco_medio, atualizado_em.
    """
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM posicoes ORDER BY ticker")
            return [dict(r) for r in cur.fetchall()]


def upsert_posicao(ticker: str, quantidade: float, preco_medio: float) -> None:
    """Insert or update a position row.

    Parameters
    ----------
    ticker : str
        e.g. 'BOVA11'
    quantidade : float
        Total shares held.
    preco_medio : float
        Average purchase price per share.
    """
    sql = """
        INSERT INTO posicoes (ticker, quantidade, preco_medio, atualizado_em)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (ticker) DO UPDATE
            SET quantidade    = EXCLUDED.quantidade,
                preco_medio   = EXCLUDED.preco_medio,
                atualizado_em = NOW()
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(sql, (ticker, quantidade, preco_medio))
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# Opcoes
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def listar_opcoes(status: str | None = None) -> list[dict[str, Any]]:
    """Return options records, optionally filtered by status.

    Parameters
    ----------
    status : str or None
        One of 'ABERTA', 'EXERCIDA', 'EXPIRADA', 'ROLADA', or None for all.

    Returns
    -------
    list[dict]
    """
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute(
                    "SELECT * FROM opcoes WHERE status = %s ORDER BY vencimento",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM opcoes ORDER BY vencimento DESC")
            return [dict(r) for r in cur.fetchall()]


def inserir_opcao(
    data_abertura: str,
    tipo: str,
    ativo: str,
    codigo_opcao: str,
    strike: float,
    vencimento: str,
    quantidade: int,
    premio_unitario: float,
    observacao: str = "",
) -> None:
    """Record a new option sale.

    Parameters
    ----------
    data_abertura : str
        ISO date string 'YYYY-MM-DD'.
    tipo : str
        'PUT' or 'CALL'.
    ativo : str
        Underlying asset, e.g. 'BOVA11'.
    codigo_opcao : str
        Option ticker code.
    strike : float
        Strike price.
    vencimento : str
        Expiration ISO date.
    quantidade : int
        Number of contracts.
    premio_unitario : float
        Premium received per share.
    observacao : str
        Free-text note.
    """
    premio_total = premio_unitario * quantidade
    sql_op = """
        INSERT INTO opcoes
            (data_abertura, tipo, ativo, codigo_opcao, strike, vencimento,
             quantidade, premio_unitario, premio_total, status, observacao)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ABERTA', %s)
    """
    sql_cx = """
        INSERT INTO caixa (data, tipo, valor, descricao)
        VALUES (%s, 'ENTRADA', %s, %s)
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                sql_op,
                (
                    data_abertura, tipo, ativo, codigo_opcao, strike, vencimento,
                    quantidade, premio_unitario, premio_total, observacao,
                ),
            )
            cur.execute(sql_cx, (
                data_abertura,
                premio_total,
                f"Prêmio recebido — {codigo_opcao.upper()} {tipo}",
            ))
    st.cache_data.clear()


def editar_opcao(
    opcao_id: int,
    strike: float,
    vencimento: str,
    quantidade: int,
    premio_unitario: float,
    observacao: str,
) -> None:
    """Update editable fields of an existing option record.

    Parameters
    ----------
    opcao_id : int
    strike : float
    vencimento : str
        ISO date string.
    quantidade : int
    premio_unitario : float
    observacao : str
    """
    sql = """
        UPDATE opcoes
           SET strike          = %s,
               vencimento      = %s,
               quantidade      = %s,
               premio_unitario = %s,
               premio_total    = %s,
               observacao      = %s
         WHERE id = %s
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(sql, (
                strike, vencimento, quantidade,
                premio_unitario, premio_unitario * quantidade,
                observacao, opcao_id,
            ))
    st.cache_data.clear()


def fechar_opcao(
    opcao_id: int,
    status: str,
    data_fechamento: str,
    premio_recompra: float = 0.0,
) -> None:
    """Close an open option position.

    Parameters
    ----------
    opcao_id : int
    status : str
        'EXERCIDA', 'EXPIRADA', or 'ROLADA'.
    data_fechamento : str
        ISO date string.
    premio_recompra : float
        Unit premium paid to buy back the option (0 if expired worthless).
    """
    sql_up = """
        UPDATE opcoes
           SET status = %s, data_fechamento = %s, premio_recompra = %s
         WHERE id = %s
        RETURNING codigo_opcao, tipo, quantidade
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(sql_up, (status, data_fechamento, premio_recompra, opcao_id))
            row = cur.fetchone()
            # Register buyback cost as cash outflow when premium > 0
            if premio_recompra > 0 and row:
                codigo, tipo_op, qtd = row
                custo = premio_recompra * qtd
                cur.execute(
                    "INSERT INTO caixa (data, tipo, valor, descricao) VALUES (%s, 'SAIDA', %s, %s)",
                    (
                        data_fechamento,
                        custo,
                        f"Recompra — {(codigo or '').upper()} {tipo_op} ({status})",
                    ),
                )
    st.cache_data.clear()


def rolar_opcao(
    opcao_id: int,
    data_fechamento: str,
    premio_recompra: float,
    # nova opção
    tipo: str,
    ativo: str,
    codigo_opcao: str,
    strike: float,
    vencimento: str,
    quantidade: int,
    premio_unitario: float,
    observacao: str = "",
) -> int:
    """Close the current option and open a new one in a single transaction.

    The new option receives ``origem_id`` pointing to the rolled option,
    enabling full roll-chain tracking.

    Parameters
    ----------
    opcao_id : int
        ID of the open option to roll.
    data_fechamento : str
        ISO date of the roll (closing date).
    premio_recompra : float
        Unit premium paid to buy back the current option.
    tipo, ativo, codigo_opcao, strike, vencimento, quantidade, premio_unitario : ...
        Fields for the new option being sold.
    observacao : str
        Free-text note for the new option.

    Returns
    -------
    int
        ID of the newly created option record.
    """
    premio_novo_total = premio_unitario * quantidade
    close_sql = """
        UPDATE opcoes
           SET status = 'ROLADA', data_fechamento = %s, premio_recompra = %s
         WHERE id = %s
        RETURNING codigo_opcao, tipo AS tipo_orig, quantidade AS qtd_orig
    """
    open_sql = """
        INSERT INTO opcoes
            (data_abertura, tipo, ativo, codigo_opcao, strike, vencimento,
             quantidade, premio_unitario, premio_total, status, origem_id, observacao)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ABERTA', %s, %s)
        RETURNING id
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(close_sql, (data_fechamento, premio_recompra, opcao_id))
            row_orig = cur.fetchone()

            # Cash outflow: buyback of the old option
            if premio_recompra > 0 and row_orig:
                cod_orig, tipo_orig, qtd_orig = row_orig
                cur.execute(
                    "INSERT INTO caixa (data, tipo, valor, descricao) VALUES (%s, 'SAIDA', %s, %s)",
                    (
                        data_fechamento,
                        premio_recompra * qtd_orig,
                        f"Recompra (roll) — {(cod_orig or '').upper()} {tipo_orig}",
                    ),
                )

            cur.execute(
                open_sql,
                (
                    data_fechamento, tipo, ativo, codigo_opcao, strike, vencimento,
                    quantidade, premio_unitario, premio_novo_total,
                    opcao_id, observacao,
                ),
            )
            new_id = cur.fetchone()[0]

            # Cash inflow: premium received for the new option
            cur.execute(
                "INSERT INTO caixa (data, tipo, valor, descricao) VALUES (%s, 'ENTRADA', %s, %s)",
                (
                    data_fechamento,
                    premio_novo_total,
                    f"Prêmio recebido (roll) — {codigo_opcao.upper()} {tipo}",
                ),
            )

    st.cache_data.clear()
    return new_id


# ---------------------------------------------------------------------------
# Aportes
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def listar_aportes() -> list[dict[str, Any]]:
    """Return all contribution records ordered by date descending."""
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM aportes ORDER BY data DESC")
            return [dict(r) for r in cur.fetchall()]


def inserir_aporte(
    data: str,
    valor_total: float,
    bova11_qtd: float,
    bova11_valor: float,
    ivvb11_qtd: float,
    ivvb11_valor: float,
    hash11_qtd: float,
    hash11_valor: float,
    observacao: str = "",
) -> None:
    """Record a monthly contribution.

    Parameters
    ----------
    data : str
        ISO date 'YYYY-MM-DD'.
    valor_total : float
        Total amount contributed (usually 5000.0).
    bova11_qtd, bova11_valor : float
        Shares bought and BRL invested in BOVA11.
    ivvb11_qtd, ivvb11_valor : float
        Shares and BRL for IVVB11.
    hash11_qtd, hash11_valor : float
        Shares and BRL for HASH11.
    observacao : str
        Free-text note.
    """
    sql = """
        INSERT INTO aportes
            (data, valor_total,
             bova11_qtd, bova11_valor,
             ivvb11_qtd, ivvb11_valor,
             hash11_qtd, hash11_valor,
             observacao)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                sql,
                (
                    data, valor_total,
                    bova11_qtd, bova11_valor,
                    ivvb11_qtd, ivvb11_valor,
                    hash11_qtd, hash11_valor,
                    observacao,
                ),
            )
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# Caixa
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def saldo_caixa() -> float:
    """Compute current cash balance from all ledger entries.

    Returns
    -------
    float
        Net cash balance (entries minus exits).
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN tipo='ENTRADA' THEN valor ELSE -valor END), 0)
                FROM caixa
                """
            )
            return float(cur.fetchone()[0])


def registrar_caixa(data: str, tipo: str, valor: float, descricao: str = "") -> None:
    """Add a cash ledger entry.

    Parameters
    ----------
    data : str
        ISO date.
    tipo : str
        'ENTRADA' or 'SAIDA'.
    valor : float
        Positive amount.
    descricao : str
        Free-text description.
    """
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO caixa (data, tipo, valor, descricao) VALUES (%s, %s, %s, %s)",
                (data, tipo, valor, descricao),
            )
    st.cache_data.clear()


@st.cache_data(ttl=60, show_spinner=False)
def listar_caixa(limit: int = 30) -> list[dict[str, Any]]:
    """Return the most recent cash entries.

    Parameters
    ----------
    limit : int
        Max rows to return.
    """
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM caixa ORDER BY data DESC, criado_em DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Aggregations used across pages
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def total_premios_recebidos() -> float:
    """Sum of all option premiums collected (open + closed)."""
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(premio_total), 0) FROM opcoes")
            return float(cur.fetchone()[0])


@st.cache_data(ttl=60, show_spinner=False)
def total_aportado() -> float:
    """Sum of all contribution amounts."""
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(valor_total), 0) FROM aportes")
            return float(cur.fetchone()[0])
