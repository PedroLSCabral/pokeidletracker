"""Importa exportações do mercado do PokeIdle (CSV) para um banco SQLite.

Uso:
    python src/importer.py                # importa tudo que estiver em data/inbox/
    python src/importer.py arquivo.csv    # importa arquivos específicos

Deduplicação: o CSV não tem ID de transação e a data só vai até o minuto, e
linhas idênticas podem ser vendas diferentes de verdade. Por isso, a cada
importação:
  - todo minuto do arquivo, exceto o mais antigo, está completo nele. As linhas
    desses minutos no banco são substituídas pelas linhas do arquivo;
  - o minuto mais antigo pode estar cortado pelo limite de 5.000 linhas. Para
    ele, mantém-se a maior contagem de cada linha idêntica entre o banco e o arquivo.
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Horário de Brasília fixo (sem horário de verão desde 2019). O CSV do jogo vem nesse fuso, e o
# sistema pode estar em outro fuso: sem isto, os minutos não bateriam na deduplicação.
BRT = timezone(timedelta(hours=-3))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
PROCESSED = DATA / "processed"
DB_PATH = DATA / "market.db"

CURRENCY = {"Gemas": "gems", "Coins": "coins"}

# Colunas que identificam uma venda (linhas iguais nelas são "idênticas").
KEY_COLS = (
    "ts", "kind", "name", "qty", "currency", "total", "unit_price", "seller",
    "buyer", "level", "shiny", "nota", "iv_total", "potencia", "qualidade",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,      -- 'YYYY-MM-DD HH:MM', horário do export
    kind        TEXT NOT NULL,      -- 'item' | 'pokemon'
    name        TEXT NOT NULL,      -- nome como veio ('Common House #001706', 'Numel Nv 40')
    base_name   TEXT NOT NULL,      -- agrupável ('Common House', 'Numel')
    serial      TEXT,               -- '#001706' para itens únicos
    qty         INTEGER NOT NULL,
    currency    TEXT NOT NULL,      -- 'gems' | 'coins'
    total       INTEGER NOT NULL,
    unit_price  REAL NOT NULL,
    seller      TEXT,
    buyer       TEXT,
    level       INTEGER,
    shiny       INTEGER,
    nota        REAL,
    iv_total    INTEGER,
    potencia    INTEGER,
    qualidade   REAL,
    source_file TEXT
);
CREATE INDEX IF NOT EXISTS trades_ts   ON trades(ts);
CREATE INDEX IF NOT EXISTS trades_item ON trades(kind, base_name, currency, ts);

CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    file        TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    oldest_ts   TEXT,
    newest_ts   TEXT,
    rows_in_file INTEGER,
    rows_added  INTEGER,
    gap_before  INTEGER NOT NULL DEFAULT 0  -- 1 = pode ter faltado venda entre o export anterior e este
);

-- Snapshot da vitrine (anúncios abertos) de todos os itens, vindo do coletor.
CREATE TABLE IF NOT EXISTS vitrine (
    snap_ms     INTEGER NOT NULL,
    snap_ts     TEXT NOT NULL,
    item_id     INTEGER NOT NULL,
    anuncios    INTEGER,
    unidades    INTEGER,
    min_coins   INTEGER,
    min_gems    INTEGER,
    media7_coins REAL, un7_coins INTEGER,   -- média de 7 dias calculada pelo jogo
    media7_gems  REAL, un7_gems  INTEGER,
    PRIMARY KEY (snap_ms, item_id)
);

-- Nomes dos itens por ID (items.json do jogo + IDs especiais).
CREATE TABLE IF NOT EXISTS itens (
    id       INTEGER PRIMARY KEY,
    nome     TEXT NOT NULL,
    categoria TEXT
);

-- Estado do agendamento do coletor (chave/valor).
CREATE TABLE IF NOT EXISTS coleta (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""

# IDs que não estão no items.json (definidos no código do jogo).
ITENS_ESPECIAIS = {
    70000: "Bronze Boss Token",
    70011: "Key Fragment",
    70012: "Shiny Stone Fragment",
    70013: "Bicycle Fragment",
    70014: "Mega Stone Fragment",        # inferido pelo preço (≈ vendas do export)
    70015: "Mega Shiny Stone Fragment",  # inferido pelo preço (425 = venda do export)
    70040: "Common House", 70041: "Uncommon House", 70042: "Rare House",
    70043: "Mythic House", 70044: "Legendary House",
    70080: "Common Bicycle", 70081: "Uncommon Bicycle", 70082: "Rare Bicycle",
    70083: "Mythic Bicycle", 70084: "Legendary Bicycle",
    59194: "TM Disk Piece",              # nome usado nas vendas para a peça de TM Elemental
    40530: "AoE TM Disk Piece",
    70095: "Safari Ticket",              # inferido pelo preço (vitrine 95 / vendas ~75 gemas)
    70017: "Shiny Egg Fragment",         # inferido pelo preço (vitrine 1.500 / vendas ~1.000 gemas)
    70090: "Mystic Ticket",              # inferido: raríssimo, 11.800 gemas, aba Tickets do jogo
}

SERIAL_RE = re.compile(r"\s*(#\d+)$")
LEVEL_RE = re.compile(r"\s+Nv\s+\d+$")


def _int(v: str) -> int | None:
    v = v.strip()
    return int(v) if v else None


def _float(v: str) -> float | None:
    v = v.strip()
    return float(v.replace(",", ".")) if v else None


def parse_row(r: dict[str, str]) -> dict:
    kind = r["Tipo"].strip().lower()
    name = r["Item"].strip()
    serial = None
    if kind == "pokemon":
        base = LEVEL_RE.sub("", name)
    else:
        m = SERIAL_RE.search(name)
        serial = m.group(1) if m else None
        base = SERIAL_RE.sub("", name)
    shiny = r.get("Shiny", "").strip().lower()
    return {
        "ts": r["Data"].strip(),
        "kind": kind,
        "name": name,
        "base_name": base,
        "serial": serial,
        "qty": int(r["Quantidade"]),
        "currency": CURRENCY.get(r["Moeda"].strip(), r["Moeda"].strip().lower()),
        "total": int(r["Valor total"]),
        "unit_price": _float(r["Valor unitário"]),
        "seller": r["Vendedor"].strip() or None,
        "buyer": r["Comprador"].strip() or None,
        "level": _int(r.get("Nível", "")),
        "shiny": (1 if shiny == "sim" else 0) if kind == "pokemon" else None,
        "nota": _float(r.get("Nota", "")),
        "iv_total": _int(r.get("IV total", "")),
        "potencia": _int(r.get("Potência", "")),
        "qualidade": _float(r.get("Qualidade", "")),
    }


MOEDA_JSON = {"gold": "coins", "orb": "gems"}
QTD_PREFIXO = re.compile(r"^\d+×\s*")


def parse_json_row(row: list) -> dict:
    """Linha do export que vem pelo WebSocket (`csv` → `mercado.linhas`):
    [em_ms, tipo, descricao, qtd, moeda, bruto, vendedor, comprador, [nivel, shiny, nota, iv, potencia, qualidade]]
    Os arredondamentos imitam o CSV do jogo, para casar com linhas importadas de arquivo."""
    em, tipo, desc, qtd, moeda, bruto, vendedor, comprador, *resto = row
    pk = (resto[0] if resto else None) or []
    pk = list(pk) + [None] * (6 - len(pk))
    nivel, shiny, nota, iv, potencia, qualidade = pk[:6]
    kind = str(tipo).lower()
    q = int(qtd or 1)
    name = str(desc or "")
    serial = None
    if kind == "pokemon":
        base = LEVEL_RE.sub("", name)
    else:
        name = QTD_PREFIXO.sub("", name)
        m = SERIAL_RE.search(name)
        serial = m.group(1) if m else None
        base = SERIAL_RE.sub("", name)
    return {
        "ts": datetime.fromtimestamp(em / 1000, BRT).strftime("%Y-%m-%d %H:%M"),
        "ts_ms": int(em),
        "kind": kind,
        "name": name,
        "base_name": base,
        "serial": serial,
        "qty": q,
        "currency": MOEDA_JSON.get(moeda, str(moeda)),
        "total": int(bruto),
        "unit_price": round(int(bruto) / q, 2),
        "seller": vendedor or None,
        "buyer": comprador or None,
        "level": int(nivel) if nivel is not None else None,
        "shiny": (1 if shiny else 0) if kind == "pokemon" else None,
        "nota": round(float(nota), 3) if nota is not None else None,
        "iv_total": int(iv) if iv is not None else None,
        "potencia": int(potencia) if potencia is not None else None,
        "qualidade": round(float(qualidade), 3) if qualidade is not None else None,
    }


def read_export(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [parse_row(r) for r in csv.DictReader(f, delimiter=";")]


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Migração: horário exato (ms), só existe nas linhas vindas do coletor.
    if "ts_ms" not in {r[1] for r in con.execute("PRAGMA table_info(trades)")}:
        con.execute("ALTER TABLE trades ADD COLUMN ts_ms INTEGER")
    if "icone" not in {r[1] for r in con.execute("PRAGMA table_info(itens)")}:
        con.execute("ALTER TABLE itens ADD COLUMN icone TEXT")  # campo `icon` do items.json
    con.executemany("INSERT INTO itens (id, nome, categoria) VALUES (?, ?, 'especial') "
                    "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, categoria = 'especial'",
                    ITENS_ESPECIAIS.items())
    con.commit()
    return con


def _key(row) -> tuple:
    return tuple(row[c] for c in KEY_COLS)


def import_rows(con: sqlite3.Connection, rows: list[dict], source: str) -> dict:
    if not rows:
        return {"file": source, "rows_in_file": 0, "rows_added": 0, "gap_before": False}
    oldest = min(r["ts"] for r in rows)
    newest = max(r["ts"] for r in rows)
    db_newest = con.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    gap = db_newest is not None and oldest > db_newest

    before = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    cols = ["ts", "ts_ms", "kind", "name", "base_name", "serial", *KEY_COLS[3:], "source_file"]
    insert = f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"

    def ins(r):
        con.execute(insert, [source if c == "source_file" else r.get(c) for c in cols])

    with con:
        # Minutos completos no arquivo: substitui o que houver no banco.
        con.execute("DELETE FROM trades WHERE ts > ? AND ts <= ?", (oldest, newest))
        for r in rows:
            if r["ts"] > oldest:
                ins(r)
        # Minuto mais antigo (talvez cortado): completa só o que faltar no banco.
        existing = Counter(
            _key(r) for r in con.execute(
                f"SELECT {','.join(KEY_COLS)} FROM trades WHERE ts = ?", (oldest,)
            )
        )
        incoming = [r for r in rows if r["ts"] == oldest]
        seen = Counter()
        for r in incoming:
            k = _key(r)
            seen[k] += 1
            if seen[k] > existing[k]:
                ins(r)
        after = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        con.execute(
            "INSERT INTO imports (file, imported_at, oldest_ts, newest_ts, rows_in_file, rows_added, gap_before)"
            " VALUES (?,?,?,?,?,?,?)",
            (source, datetime.now().isoformat(timespec="seconds"), oldest, newest,
             len(rows), after - before, int(gap)),
        )
    return {"file": source, "oldest": oldest, "newest": newest,
            "rows_in_file": len(rows), "rows_added": after - before, "gap_before": gap}


def import_file(con: sqlite3.Connection, path: Path) -> dict:
    return import_rows(con, read_export(path), path.name)


def main(argv: list[str]) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    paths = [Path(a) for a in argv] or sorted(INBOX.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not paths:
        print(f"Nada para importar em {INBOX}")
        return
    con = connect()
    for p in paths:
        res = import_file(con, p)
        msg = (f"{p.name}: {res['rows_in_file']} linhas ({res.get('oldest')} → {res.get('newest')}), "
               f"{res['rows_added']:+d} no banco")
        if res["gap_before"]:
            msg += "  ⚠ intervalo sem dados antes deste export (vendas podem ter sido perdidas)"
        print(msg)
        if p.parent.resolve() == INBOX.resolve():
            shutil.move(str(p), PROCESSED / p.name)
    total = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"Total no banco: {total} vendas")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
