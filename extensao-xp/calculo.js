// Contas da extensão "Ritmo de XP", sem nada de tela nem de socket (dá para testar no Node:
// testes/teste_extensao_xp.js).
//
// - A curva de XP é a do jogo (shared/boost-atrasados.mjs, `xpTotalDoNivel`): o mesmo XP acumulado
//   vale para o treinador e para o Pokémon. O `xp` que o jogo manda é o acumulado desde o Nv 1.
// - Os bônus de XP MULTIPLICAM um ao outro (o servidor manda o total e as partes em `bonusXp`).
// - O ritmo medido é dividido pelo bônus que valia em cada momento: sobra o ritmo "cru" da caça, e a
//   projeção multiplica de novo só pelos bônus que o jogador deixou ligados.
// - Um bônus com prazo (`ate`) pode acabar no meio do caminho; o dos Atrasados vale até o treinador
//   chegar no nível-alvo dele (para os dois XPs).
const RitmoXpCalculo = (() => {
  'use strict';

  const HORA = 3_600_000;

  /** XP acumulado para estar no começo do nível L (o `xpTotalDoNivel` do jogo). */
  const xpTotal = (L) => (L <= 1 ? 0 : Math.round((50 / 3) * (L ** 3 - 6 * L ** 2 + 17 * L - 12)));

  /** O nível de quem tem `xp` acumulado: o maior L com xpTotal(L) ≤ xp. */
  function nivelPeloXp(xp) {
    let lo = 1, hi = 2;
    while (xpTotal(hi) <= xp) hi *= 2;
    while (hi - lo > 1) {
      const meio = Math.floor((lo + hi) / 2);
      if (xpTotal(meio) <= xp) lo = meio; else hi = meio;
    }
    return lo;
  }

  /**
   * Ritmo cru (XP/h sem bônus) e o medido (com os bônus de cada momento) numa janela.
   * `amostras` = [{ t, xp, mult }] em ordem de tempo; `mult` é o bônus que valia quando o XP entrou.
   * Uma queda de XP (morte com perda de XP) entra como ganho negativo, como no jogo.
   */
  function medirRitmo(amostras, agora, janelaMs) {
    const desde = agora - janelaMs;
    let i = amostras.length - 1;
    while (i > 0 && amostras[i - 1].t >= desde) i--;
    // a 1ª amostra da janela é o ponto de partida: conta o XP que entrou depois dela
    const usadas = amostras.slice(Math.max(0, i));
    if (usadas.length < 2) return null;
    let cru = 0, medido = 0;
    for (let k = 1; k < usadas.length; k++) {
      const d = usadas[k].xp - usadas[k - 1].xp;
      medido += d;
      cru += d / (usadas[k].mult || 1);
    }
    const inicio = usadas[0].t;
    const ms = Math.max(agora - inicio, 60_000);
    return {
      cruH: (cru / ms) * HORA,
      medidoH: (medido / ms) * HORA,
      ganho: medido,
      ms,
      inicio,
      pontos: usadas.length - 1,
    };
  }

  /**
   * Projeção do XP no tempo com os bônus escolhidos.
   * - `xp`: XP acumulado de agora; `cruH`: XP/h sem bônus;
   * - `bonus`: [{ f, ateMs }] (fator e quando acaba; ateMs = Infinity se não acaba ou se o
   *   jogador mandou ignorar os prazos);
   * - `atrasados`: { f, xpFim } (acaba quando ESTE XP chega em xpFim: projeção do treinador) ou
   *   { f, ateMs } (acaba num instante: projeção do Pokémon, pelo tempo do treinador), ou null.
   * Devolve `tempoAte(xpAlvo)` em ms (Infinity se nunca chega) e `xpEm(ms)`.
   */
  function projecao({ xp, cruH, bonus = [], atrasados = null }) {
    const porMs = Math.max(0, cruH) / HORA;

    // Os pedaços em que o bônus não muda: cada um começa num instante e tem um fator.
    function pedacos(limiteMs) {
      const marcos = new Set([0]);
      for (const b of bonus) if (b.ateMs > 0 && b.ateMs < limiteMs) marcos.add(b.ateMs);
      if (atrasados && Number.isFinite(atrasados.ateMs) && atrasados.ateMs > 0 && atrasados.ateMs < limiteMs) marcos.add(atrasados.ateMs);
      return [...marcos].sort((a, b) => a - b);
    }
    const fatorEm = (t, xpAgora) => {
      let f = 1;
      for (const b of bonus) if (t < b.ateMs) f *= b.f;
      if (atrasados) {
        const vale = 'xpFim' in atrasados ? xpAgora < atrasados.xpFim : t < atrasados.ateMs;
        if (vale) f *= atrasados.f;
      }
      return f;
    };

    function tempoAte(xpAlvo) {
      if (xpAlvo <= xp) return 0;
      if (!(porMs > 0)) return Infinity;
      const marcos = pedacos(Infinity);
      let t = 0, x = xp;
      for (let k = 0; ; k++) {
        const fim = k + 1 < marcos.length ? marcos[k + 1] : Infinity;
        const f = fatorEm(t, x);
        const vel = porMs * f;
        // o XP dos Atrasados também tem um marco, mas no XP e não no tempo
        let xpParada = xpAlvo;
        if (atrasados && 'xpFim' in atrasados && x < atrasados.xpFim && atrasados.xpFim < xpAlvo) xpParada = atrasados.xpFim;
        const dtXp = (xpParada - x) / vel;
        if (t + dtXp <= fim) {
          t += dtXp;
          x = xpParada;
          if (x >= xpAlvo) return t;
          k--; // mesmo pedaço de tempo, só mudou o fator
          continue;
        }
        x += vel * (fim - t);
        t = fim;
      }
    }

    function xpEm(ms) {
      if (!(porMs > 0) || ms <= 0) return xp;
      const marcos = pedacos(ms);
      let t = 0, x = xp;
      for (let k = 0; k < marcos.length && t < ms; k++) {
        const fim = Math.min(ms, k + 1 < marcos.length ? marcos[k + 1] : Infinity);
        const f = fatorEm(t, x);
        const vel = porMs * f;
        if (atrasados && 'xpFim' in atrasados && x < atrasados.xpFim) {
          const dt = (atrasados.xpFim - x) / vel;
          if (t + dt < fim) {
            x = atrasados.xpFim;
            t += dt;
            k--;
            continue;
          }
        }
        x += vel * (fim - t);
        t = fim;
      }
      return x;
    }

    return { tempoAte, xpEm };
  }

  /**
   * As linhas da tabela "nível a nível" do nível de agora até o alvo. Com muitos níveis, pula de
   * forma que fiquem no máximo `max` linhas (sempre com o alvo na última).
   */
  function linhasAteAlvo(proj, xp, nivel, alvo, max = 40) {
    const linhas = [];
    if (alvo <= nivel) return linhas;
    const total = alvo - nivel;
    const passo = Math.max(1, Math.ceil(total / max));
    let anterior = 0;
    for (let L = nivel + 1; L <= alvo; L += passo) {
      const n = L + passo > alvo ? alvo : L;
      const ms = proj.tempoAte(xpTotal(n));
      linhas.push({ nivel: n, xpFalta: Math.max(0, xpTotal(n) - xp), ms, desdeAnterior: ms - anterior, xpDoNivel: xpTotal(n) - xpTotal(n - 1) });
      anterior = ms;
      if (n === alvo) break;
    }
    if (linhas[linhas.length - 1]?.nivel !== alvo) {
      const ms = proj.tempoAte(xpTotal(alvo));
      linhas.push({ nivel: alvo, xpFalta: Math.max(0, xpTotal(alvo) - xp), ms, desdeAnterior: ms - anterior, xpDoNivel: xpTotal(alvo) - xpTotal(alvo - 1) });
    }
    return linhas;
  }

  /** "3 d 4 h", "5 h 12 min", "8 min". */
  function tempoCurto(ms) {
    if (!Number.isFinite(ms)) return '—';
    if (ms < 60_000) return '< 1 min';
    const min = Math.round(ms / 60_000);
    const d = Math.floor(min / 1440);
    const h = Math.floor((min % 1440) / 60);
    const m = min % 60;
    if (d >= 30) return `${Math.round(min / 1440)} d`;
    if (d) return h ? `${d} d ${h} h` : `${d} d`;
    if (h) return m ? `${h} h ${m} min` : `${h} h`;
    return `${m} min`;
  }

  /** 1.234.567 → "1,23 mi"; números menores com separador de milhar. */
  function numCurto(n) {
    const a = Math.abs(n);
    const fmt = (v, c) => v.toLocaleString('pt-BR', { maximumFractionDigits: c });
    if (a >= 1e9) return `${fmt(n / 1e9, 2)} bi`;
    if (a >= 1e6) return `${fmt(n / 1e6, 2)} mi`;
    if (a >= 1e4) return `${fmt(n / 1e3, 1)} mil`;
    return fmt(Math.round(n), 0);
  }

  return { HORA, xpTotal, nivelPeloXp, medirRitmo, projecao, linhasAteAlvo, tempoCurto, numCurto };
})();

// No Chrome, cada arquivo do manifest roda como um script à parte: a página (ritmo.js) acha as
// contas pelo globalThis. No Node, pelo module.exports.
if (typeof module !== 'undefined') module.exports = RitmoXpCalculo;
else globalThis.RitmoXpCalculo = RitmoXpCalculo;
