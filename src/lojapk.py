"""Loja de Pokémon: guarda os anúncios abertos lidos pelo robô (market.listar, 24 por página).

Cada varredura completa atualiza `pk_anuncios`: anúncio novo entra, anúncio visto de novo tem o
preço e o horário atualizados, e anúncio que sumiu (vendido, cancelado ou vencido) vira inativo.
"""
from __future__ import annotations

import json

INTERVALO_MS = 3 * 3600_000       # uma varredura completa a cada 3 h
PAUSA_ENTRE_PAGINAS_S = 1.0       # ~270 páginas → ~5 min por varredura, leve para o servidor
ULTIMA_PAGINA = 200               # o servidor não passa da página 200 (pedir 240 devolve a 200 de novo)
# Por isso a varredura vai moeda por moeda e, se uma moeda passar de ~4.800 anúncios, lê também do
# mais caro para o mais barato até encontrar o que já viu.
PASSADAS = [("orb", "baratos"), ("orb", "caros"), ("gold", "baratos"), ("gold", "caros")]

# Os mesmos campos que a tela do jogo manda, todos "sem filtro".
FILTRO_TUDO = dict(
    tipo="pokemon", moeda="", busca="", ordem="recentes", criterios=[], elementos=[], categoria="",
    soShiny=False, soP5=False, soMega=False, soLendario=False, soTmElemental=False, soTmAoe=False,
    semOutland=False, nivelMin="", nivelMax="", potenciaMin="", potenciaMax="", ivMin="", ivMax="",
    qualidadeMin="", qualidadeMax="", notaMin="", notaMax="",
)

MOEDA = {"gold": "coins", "orb": "gems"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pk_anuncios (
    id          INTEGER PRIMARY KEY,   -- id do anúncio no jogo
    pokemon_id  INTEGER,
    especie     TEXT,                  -- nome da espécie (ficha.nome)
    species_id  INTEGER,
    nivel       INTEGER,
    shiny       INTEGER,
    nota        REAL,
    poder       INTEGER,               -- força de combate calculada pelo jogo
    iv_total    INTEGER,
    ivs         TEXT,                  -- JSON {hp, atk, def, spAtk, spDef, speed}
    stats       TEXT,                  -- JSON dos atributos finais
    qualidade   REAL,
    potencia    INTEGER,
    tipos       TEXT,                  -- JSON ["FIRE", ...]
    refino      INTEGER,
    tm_elemental TEXT,
    tm_aoe      INTEGER,
    preco       INTEGER,
    moeda       TEXT,                  -- gems | coins
    vendedor    TEXT,
    criado_ms   INTEGER,
    expira_ms   INTEGER,
    favoritos   INTEGER,
    primeiro_ms INTEGER,               -- primeira vez que o robô viu o anúncio
    visto_ms    INTEGER,               -- última varredura em que ele estava lá
    ativo       INTEGER NOT NULL DEFAULT 1,
    sumiu_ms    INTEGER                -- varredura em que ele não estava mais
);
CREATE INDEX IF NOT EXISTS pk_anuncios_ativos ON pk_anuncios(ativo, moeda, preco);
CREATE INDEX IF NOT EXISTS pk_anuncios_especie ON pk_anuncios(especie, shiny);
CREATE TABLE IF NOT EXISTS pk_varreduras (
    snap_ms  INTEGER PRIMARY KEY,
    anuncios INTEGER,
    completa INTEGER
);
"""


def preparar(con) -> None:
    con.executescript(SCHEMA)


def _linha(a: dict, t0: int) -> tuple | None:
    f = a.get("ficha") or {}
    if a.get("tipo") != "pokemon" or not f:
        return None
    return (
        int(a["id"]), a.get("pokemonId"), f.get("nome"), f.get("speciesId"), f.get("level"),
        1 if f.get("shiny") else 0, f.get("nota"), f.get("poder"), f.get("ivTotal"),
        json.dumps(f.get("ivs") or {}), json.dumps(f.get("stats") or {}), f.get("quality"), f.get("potencia"),
        json.dumps(f.get("tipos") or []), f.get("refinoTotal"),
        json.dumps(f["tmElemental"]) if f.get("tmElemental") else None, 1 if f.get("tmAoe") else 0,
        a.get("preco"), MOEDA.get(a.get("moeda"), a.get("moeda")), a.get("vendedor"),
        a.get("criadoEm"), a.get("expiraEm"), a.get("favoritos"), t0, t0,
    )


def gravar(con, anuncios: list[dict], t0: int, completa: bool = False) -> int:
    """Grava um lote de anúncios vistos na varredura `t0`. Só na última chamada (`completa=True`)
    os anúncios que não apareceram viram inativos."""
    preparar(con)
    linhas = [x for x in (_linha(a, t0) for a in anuncios) if x]
    with con:
        con.executemany("""
            INSERT INTO pk_anuncios (id, pokemon_id, especie, species_id, nivel, shiny, nota, poder, iv_total, ivs,
                stats, qualidade, potencia, tipos, refino, tm_elemental, tm_aoe, preco, moeda, vendedor, criado_ms,
                expira_ms, favoritos, primeiro_ms, visto_ms, ativo, sumiu_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,NULL)
            ON CONFLICT(id) DO UPDATE SET preco=excluded.preco, moeda=excluded.moeda, nivel=excluded.nivel,
                poder=excluded.poder, nota=excluded.nota, expira_ms=excluded.expira_ms, favoritos=excluded.favoritos,
                visto_ms=excluded.visto_ms, ativo=1, sumiu_ms=NULL""", linhas)
    return len(linhas)


def finalizar(con, t0: int, total_visto: int, completa: bool) -> None:
    preparar(con)
    with con:
        if completa:
            con.execute("UPDATE pk_anuncios SET ativo=0, sumiu_ms=? WHERE ativo=1 AND visto_ms < ?", (t0, t0))
        con.execute("INSERT OR REPLACE INTO pk_varreduras VALUES (?,?,?)", (t0, total_visto, int(completa)))
