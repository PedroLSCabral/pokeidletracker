'use strict';
/* PokeIdle Tracker — painel. Sem dependências: gráficos em SVG desenhados aqui. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const estado = { aba: 'mercado', moeda: 'gems', janela: '7d', item: null, ordem: 'vendas', busca: '', resumo: null, fonte: 'auto', ultimoItem: null, categoria: 'todas' };

// ------------------------------------------------------------------ ícones (os do próprio jogo, carregados de pokeidle.io)
const SITE = 'https://pokeidle.io';
const IMG = {
  gema: `${SITE}/img/moeda-gema.png`,
  moeda: `${SITE}/assets/site/assets/ui/moeda-ouro.png`,
  bolsa: `${SITE}/assets/site/assets/ui/menu-bolsa.png`,
  pokedex: `${SITE}/midia/menu-pokedex.png`,
};
const CATEGORIAS = [
  { id: 'todas', nome: 'Todas', ico: IMG.bolsa },
  { id: 'casas', nome: 'Casas', ico: `${SITE}/img/itens/cat-casa.png` },
  { id: 'bicicletas', nome: 'Bicicletas', ico: `${SITE}/img/itens/cat-bicicleta.png` },
  { id: 'fragmentos', nome: 'Fragmentos', ico: `${SITE}/img/itens/cat-fragmento.png` },
  { id: 'pedras', nome: 'Pedras', ico: `${SITE}/assets/site/assets/items/fire_stone.gif` },
  { id: 'boss-tokens', nome: 'Boss Tokens', ico: `${SITE}/assets/site/assets/items/bronze_boss_token.png` },
  { id: 'tickets', nome: 'Tickets', ico: `${SITE}/img/itens/mystic-ticket.png` },
  { id: 'tms', nome: 'TMs', ico: `${SITE}/img/itens/zmove/aoe-disco.png` },
  { id: 'outros', nome: 'Outros', ico: IMG.bolsa },
];
/** <img> de um ícone do jogo; se o arquivo sumir do site, cai na bolsa (como o jogo faz). */
const img = (url) => `<img src="${esc(url || IMG.bolsa)}" alt="" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${IMG.bolsa}'">`;
const pintarIcones = (raiz = document) => $$('[data-ico]', raiz).forEach((el) => { el.innerHTML = img(IMG[el.dataset.ico]); });

// ------------------------------------------------------------------ formatação
const FUSO = 'America/Sao_Paulo';
const fHora = new Intl.DateTimeFormat('pt-BR', { timeZone: FUSO, hour: '2-digit', minute: '2-digit' });
const fDia = new Intl.DateTimeFormat('pt-BR', { timeZone: FUSO, day: '2-digit', month: '2-digit' });
const fDiaHora = new Intl.DateTimeFormat('pt-BR', { timeZone: FUSO, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const nf = (d) => new Intl.NumberFormat('pt-BR', { maximumFractionDigits: d });

function fmtNum(v, moeda = estado.moeda) {
  if (v == null || Number.isNaN(v)) return '—';
  if (moeda === 'coins') {
    const a = Math.abs(v);
    if (a >= 1e9) return nf(2).format(v / 1e9) + ' bi';
    if (a >= 1e6) return nf(1).format(v / 1e6) + ' mi';
    if (a >= 1e4) return nf(0).format(v / 1e3) + ' mil';
    return nf(0).format(v);
  }
  return nf(Math.abs(v) < 100 ? 1 : 0).format(v);
}
const htmlPreco = (v, moeda = estado.moeda) =>
  v == null ? '<span class="preco">—</span>'
    : `<span class="preco ${moeda}"><span class="ico">${img(moeda === 'gems' ? IMG.gema : IMG.moeda)}</span>${fmtNum(v, moeda)}</span>`;
function htmlVar(v, rot = '') {
  if (v == null) return `<span class="var zero">${rot} —</span>`;
  const c = v > 0.05 ? 'sobe' : v < -0.05 ? 'desce' : 'zero';
  const seta = c === 'sobe' ? '▲' : c === 'desce' ? '▼' : '■';
  return `<span class="var ${c}">${rot} ${seta} ${nf(1).format(Math.abs(v))}%</span>`;
}
const usd = (gemas) => '$' + nf(2).format(gemas * 0.009);

function classeRaridade(nome) {
  const m = /^(Common|Uncommon|Rare|Mythic|Legendary) (House|Bicycle)/.exec(nome);
  if (m) return { Common: 'r-comum', Uncommon: 'r-incomum', Rare: 'r-rara', Mythic: 'r-mitica', Legendary: 'r-lendaria' }[m[1]];
  return /Fragment/.test(nome) ? 'r-frag' : '';
}

async function api(caminho, params = {}) {
  const u = new URL(caminho, location.origin);
  Object.entries(params).forEach(([k, v]) => v != null && v !== '' && u.searchParams.set(k, v));
  let r;
  try {
    r = await fetch(u);
  } catch {
    throw Object.assign(new Error('o servidor do painel não responde'), { desligado: true });
  }
  const j = await r.json();
  if (!r.ok) throw new Error(j.erro || r.statusText);
  return j;
}

// ------------------------------------------------------------------ estado na URL (#)
function lerHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get('aba')) estado.aba = h.get('aba');
  if (h.get('moeda')) estado.moeda = h.get('moeda');
  if (h.get('janela')) estado.janela = h.get('janela');
  if (h.get('item')) estado.item = h.get('item');
  if (h.get('cat')) estado.categoria = h.get('cat');
}
function gravarHash() {
  const h = new URLSearchParams({ aba: estado.aba, moeda: estado.moeda, janela: estado.janela, cat: estado.categoria });
  if (estado.item) h.set('item', estado.item);
  history.replaceState(null, '', '#' + h.toString());
}

// ------------------------------------------------------------------ lista
async function carregarResumo() {
  estado.resumo = await api('/api/resumo', { moeda: estado.moeda });
  desenharLista();
  if (!estado.item && estado.resumo.itens.length) await selecionar(estado.resumo.itens[0].nome);
}

function spark(valores) {
  const pts = valores.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return '';
  const vs = pts.map(([, v]) => v);
  const lo = Math.min(...vs), hi = Math.max(...vs) || 1;
  const n = valores.length - 1;
  let d = '', antes = -2;
  for (const [i, v] of pts) {
    const x = (i / n) * 100, y = 16 - ((v - lo) / ((hi - lo) || 1)) * 14;
    d += (i - antes > 1 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
    antes = i;
  }
  return `<svg class="spark" viewBox="0 0 100 18" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="var(--serie-1)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}

function desenharCategorias() {
  const r = estado.resumo;
  if (!r) return;
  const conta = { todas: r.itens.length };
  r.itens.forEach((i) => { conta[i.categoria] = (conta[i.categoria] || 0) + 1; });
  if (!conta[estado.categoria]) estado.categoria = 'todas'; // categoria sem itens nesta moeda
  $('#categorias').innerHTML = CATEGORIAS.filter((c) => conta[c.id]).map((c) => `
    <button class="menu-item ${c.id === estado.categoria ? 'ativa' : ''}" data-cat="${c.id}">
      <span class="ico">${img(c.ico)}</span>${c.nome}<span class="qtd">${conta[c.id]}</span>
    </button>`).join('');
}

function desenharLista() {
  const r = estado.resumo;
  if (!r) return;
  desenharCategorias();
  const b = estado.busca.toLowerCase();
  let itens = r.itens.filter((i) => (estado.categoria === 'todas' || i.categoria === estado.categoria)
    && (!b || i.nome.toLowerCase().includes(b)));
  const ord = {
    vendas: (a, z) => z.vendas24h - a.vendas24h || a.nome.localeCompare(z.nome),
    var: (a, z) => Math.abs(z.var24h ?? 0) - Math.abs(a.var24h ?? 0),
    preco: (a, z) => (z.atual ?? z.anuncio_min ?? 0) - (a.atual ?? a.anuncio_min ?? 0),
    nome: (a, z) => a.nome.localeCompare(z.nome),
  }[estado.ordem];
  itens = [...itens].sort(ord);
  const cat = CATEGORIAS.find((c) => c.id === estado.categoria);
  $('#lista-sub').textContent = `${cat && cat.id !== 'todas' ? cat.nome.toLowerCase() + ' · ' : ''}${itens.length} itens · ${estado.moeda === 'gems' ? 'gemas' : 'coins'}`;
  $('#lista').innerHTML = itens.map((i) => `
    <button class="linha-item ${classeRaridade(i.nome)} ${i.nome === estado.item ? 'sel' : ''}" data-nome="${esc(i.nome)}">
      <span class="ico">${img(i.icone)}</span>
      <span style="min-width:0">
        <div class="nome">${esc(i.nome)}</div>
        <div class="meta">${i.vendas24h ? `${nf(0).format(i.vendas24h)} vendas 24h` : 'sem vendas 24h'}${i.anuncios ? ` · ${nf(0).format(i.anuncios)} anúncios` : ''}</div>
        ${spark(i.spark)}
      </span>
      <span class="direita">
        <div>${htmlPreco(i.atual ?? i.anuncio_min)}</div>
        <div>${i.atual == null && i.anuncio_min != null ? '<span class="var zero">anúncio</span>' : htmlVar(i.var24h, '24h')}</div>
      </span>
    </button>`).join('') || '<div class="vazio">Nada encontrado.</div>';
}

// ------------------------------------------------------------------ detalhe
async function selecionar(nome) {
  estado.item = nome;
  gravarHash();
  $$('.linha-item').forEach((el) => el.classList.toggle('sel', el.dataset.nome === nome));
  const d = await api('/api/item', { nome, moeda: estado.moeda, janela: estado.janela });
  if (d.nome !== estado.item) return; // outro clique já trocou
  estado.ultimoItem = d;
  desenharDetalhe(d);
}

function desenharDetalhe(d) {
  const s = d.stats, v = d.vitrine, moeda = d.moeda;
  $('#det-ico').innerHTML = img(d.icone);
  $('#det-nome').textContent = d.nome;
  const desde = s.primeira ? fDiaHora.format(s.primeira) : '—';
  $('#detalhe').innerHTML = `
    <div class="tiles">
      <div class="tile"><div class="rot">Mediana</div><div class="val">${htmlPreco(s.mediana, moeda)}</div><div class="det">p10 ${fmtNum(s.p10, moeda)} · p90 ${fmtNum(s.p90, moeda)}</div></div>
      <div class="tile"><div class="rot">Média (por unidade)</div><div class="val">${htmlPreco(s.media, moeda)}</div><div class="det">${moeda === 'gems' && s.media ? usd(s.media) + ' bruto' : '&nbsp;'}</div></div>
      <div class="tile"><div class="rot">Mín · Máx</div><div class="val" style="font-size:22px">${fmtNum(s.min, moeda)} · ${fmtNum(s.max, moeda)}</div><div class="det">${s.suspeitas ? `${s.suspeitas} venda(s) suspeita(s) fora da conta` : 'nenhuma venda suspeita'}</div></div>
      <div class="tile"><div class="rot">Vendas · unidades</div><div class="val">${nf(0).format(s.vendas)} · ${nf(0).format(s.unidades)}</div><div class="det">desde ${desde}</div></div>
      <div class="tile"><div class="rot">Menor anúncio agora</div><div class="val">${htmlPreco(v.min, moeda)}</div><div class="det">${v.anuncios != null ? `${nf(0).format(v.anuncios)} anúncios · ${nf(0).format(v.unidades)} un.` : 'sem dado da vitrine'}</div></div>
      <div class="tile"><div class="rot">Média 7d (jogo)</div><div class="val">${htmlPreco(v.media7, moeda)}</div><div class="det">calculada pelo próprio jogo</div></div>
    </div>
    <div class="grafico-box">
      <div class="legenda">
        <span><span class="sw" style="background:var(--serie-1)"></span>Mediana das vendas</span>
        <span><span class="sw band" style="background:var(--serie-1)"></span>Faixa mín–máx</span>
        <span><span class="sw" style="background:var(--serie-2)"></span>Menor anúncio</span>
      </div>
      <div class="grafico" id="g-preco"></div>
      <div class="titulo-mini">Unidades vendidas</div>
      <div class="grafico" id="g-vol"></div>
      <div class="aviso" id="g-aviso"></div>
    </div>
    <div class="duas-col">
      <div class="caixa">
        <h3>Calculadora de taxa</h3>
        <div class="calc-linha"><span>Vender por</span><input class="campo" id="c-venda" type="number" min="0" step="any" value="${s.mediana ?? v.min ?? ''}"></div>
        <div class="calc-linha"><span>Taxa do mercado (${Math.round(d.taxa * 100)}%)</span><b id="c-taxa">—</b></div>
        <div class="calc-linha"><span>Você recebe</span><b id="c-liq">—</b></div>
        ${moeda === 'gems' ? '<div class="calc-linha"><span>Em dólar (saque a $0,009)</span><b id="c-usd">—</b></div>' : ''}
        <div class="calc-linha" style="margin-top:8px"><span>Paguei (para revender)</span><input class="campo" id="c-pago" type="number" min="0" step="any" placeholder="opcional"></div>
        <div class="calc-linha"><span>Empata vendendo a</span><b id="c-empate">—</b></div>
        <div class="calc-linha"><span>Lucro vendendo pela mediana</span><b id="c-lucro">—</b></div>
      </div>
      <div class="caixa">
        <h3>Últimas vendas</h3>
        <div class="tabela-wrap" style="max-height:230px">
          <table class="tabela">
            <tr><th>Quando</th><th class="num">Qtd</th><th class="num">Unit.</th><th>Vendedor → comprador</th></tr>
            ${d.recentes.map((r) => `<tr class="${r.suspeita ? 'suspeita' : ''}" title="${r.suspeita ? 'fora da faixa normal: não entra nas estatísticas' : ''}">
              <td>${r.exato ? fDiaHora.format(r.t) : fDiaHora.format(r.t) + '*'}</td><td class="num">${nf(0).format(r.qtd)}</td>
              <td class="num">${fmtNum(r.unit, moeda)}</td><td>${esc(r.vendedor)} → ${esc(r.comprador)}</td></tr>`).join('')}
          </table>
        </div>
        <div class="aviso">* horário do CSV (só até o minuto). Riscadas = vendas suspeitas.</div>
      </div>
    </div>`;
  ligarCalculadora(d);
  desenharGraficos(d);
}

function ligarCalculadora(d) {
  const moeda = d.moeda;
  const calc = () => {
    const venda = parseFloat($('#c-venda').value);
    const pago = parseFloat($('#c-pago').value);
    const taxa = Number.isFinite(venda) ? (moeda === 'gems' ? Math.ceil(venda * d.taxa) : venda * d.taxa) : null;
    const liq = taxa != null ? venda - taxa : null;
    $('#c-taxa').innerHTML = taxa != null ? '− ' + fmtNum(taxa, moeda) : '—';
    $('#c-liq').innerHTML = liq != null ? htmlPreco(liq, moeda) : '—';
    if ($('#c-usd')) $('#c-usd').textContent = liq != null ? usd(liq) : '—';
    $('#c-empate').innerHTML = Number.isFinite(pago) ? htmlPreco(pago / (1 - d.taxa), moeda) : '—';
    const med = d.stats.mediana;
    $('#c-lucro').innerHTML = Number.isFinite(pago) && med != null
      ? `${htmlPreco(med * (1 - d.taxa) - pago, moeda)}${moeda === 'gems' ? ' (' + usd(med * (1 - d.taxa) - pago) + ')' : ''}` : '—';
  };
  $('#c-venda').addEventListener('input', calc);
  $('#c-pago').addEventListener('input', calc);
  calc();
}

// ------------------------------------------------------------------ gráfico
function passoBonito(bruto) {
  const p = 10 ** Math.floor(Math.log10(bruto));
  const f = bruto / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

function desenharGraficos(d) {
  const gp = $('#g-preco'), gv = $('#g-vol');
  const W = Math.max(320, gp.clientWidth);
  const H = 260, HV = 70;
  const m = { l: 62, r: 84, t: 10, b: 22 };
  const serie = d.serie;
  const anun = d.anuncios.filter((a) => a.min != null);
  const moeda = d.moeda;
  if (!serie.length && !anun.length) {
    gp.innerHTML = '<div class="vazio">Sem vendas nesta janela. Tente uma janela maior.</div>';
    gv.innerHTML = ''; $('#g-aviso').textContent = '';
    return;
  }
  const x0 = d.inicio, x1 = d.agora;
  const pw = W - m.l - m.r;
  const X = (t) => m.l + ((Math.min(Math.max(t, x0), x1) - x0) / (x1 - x0)) * pw;
  const centro = (s) => X((s.t + Math.min(s.fim, x1)) / 2);

  const vals = serie.flatMap((s) => [s.min, s.max]).concat(anun.map((a) => a.min));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo *= 0.9; hi = hi * 1.1 || 1; }
  const passo = passoBonito((hi - lo) / 4);
  lo = Math.max(0, Math.floor(lo / passo) * passo);
  hi = Math.ceil(hi / passo) * passo;
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);

  // Grade e eixos (linhas finas e sólidas).
  let svg = '';
  for (let v = lo; v <= hi + passo / 2; v += passo) {
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grade)" stroke-width="1"/>`;
    svg += `<text x="${m.l - 8}" y="${Y(v) + 5}" text-anchor="end">${fmtNum(v, moeda)}</text>`;
  }
  const dias = (x1 - x0) > 36 * 3600_000;
  for (let i = 0; i <= 4; i++) {
    const t = x0 + (i / 4) * (x1 - x0);
    const anc = i === 0 ? 'start' : i === 4 ? 'end' : 'middle';
    svg += `<text x="${X(t)}" y="${H - 4}" text-anchor="${anc}">${dias ? fDia.format(t) : fHora.format(t)}</text>`;
  }

  // Trechos contínuos (um buraco de coleta quebra a linha em vez de inventar o meio).
  const trechos = [];
  serie.forEach((s, i) => {
    if (!i || s.t - serie[i - 1].t > d.passo * 1.5) trechos.push([]);
    trechos[trechos.length - 1].push(s);
  });
  const poucos = serie.length <= 40;
  for (const tr of trechos) {
    if (tr.length === 1) {
      const s = tr[0];
      svg += `<rect x="${centro(s) - 4}" y="${Y(s.max)}" width="8" height="${Math.max(2, Y(s.min) - Y(s.max))}" fill="var(--serie-1)" opacity=".3"/>`;
    } else {
      const topo = tr.map((s) => `${centro(s)},${Y(s.max)}`).join(' ');
      const base = [...tr].reverse().map((s) => `${centro(s)},${Y(s.min)}`).join(' ');
      svg += `<polygon points="${topo} ${base}" fill="var(--serie-1)" opacity=".18"/>`;
      svg += `<path d="M${tr.map((s) => `${centro(s)} ${Y(s.mediana)}`).join(' L')}" fill="none" stroke="var(--serie-1)" stroke-width="2" shape-rendering="geometricPrecision"/>`;
    }
  }
  if (poucos || trechos.some((t) => t.length === 1)) {
    serie.forEach((s) => { svg += `<circle cx="${centro(s)}" cy="${Y(s.mediana)}" r="4" fill="var(--serie-1)" stroke="var(--linha)" stroke-width="2" shape-rendering="geometricPrecision"/>`; });
  }

  // Menor anúncio (snapshots da vitrine; buraco > 2 h quebra a linha).
  const trA = [];
  anun.forEach((a, i) => {
    if (!i || a.t - anun[i - 1].t > 2 * 3600_000) trA.push([]);
    trA[trA.length - 1].push(a);
  });
  for (const tr of trA) {
    if (tr.length > 1) svg += `<path d="M${tr.map((a) => `${X(a.t)} ${Y(a.min)}`).join(' L')}" fill="none" stroke="var(--serie-2)" stroke-width="2" shape-rendering="geometricPrecision"/>`;
  }
  if (anun.length <= 40) anun.forEach((a) => { svg += `<circle cx="${X(a.t)}" cy="${Y(a.min)}" r="4" fill="var(--serie-2)" stroke="var(--linha)" stroke-width="2" shape-rendering="geometricPrecision"/>`; });

  // Rótulos diretos só no fim de cada série (o resto fica no tooltip).
  const rots = [];
  if (serie.length) rots.push({ y: Y(serie[serie.length - 1].mediana), cor: 'var(--serie-1)', txt: fmtNum(serie[serie.length - 1].mediana, moeda) });
  if (anun.length) rots.push({ y: Y(anun[anun.length - 1].min), cor: 'var(--serie-2)', txt: fmtNum(anun[anun.length - 1].min, moeda) });
  if (rots.length === 2 && Math.abs(rots[0].y - rots[1].y) < 18) {
    const meio = (rots[0].y + rots[1].y) / 2, cima = rots[0].y <= rots[1].y ? 0 : 1;
    rots[cima].y = meio - 9; rots[1 - cima].y = meio + 9;
  }
  rots.forEach((r) => {
    svg += `<rect x="${W - m.r + 8}" y="${r.y - 4}" width="8" height="8" fill="${r.cor}"/>`;
    svg += `<text class="rotulo-dir" x="${W - m.r + 20}" y="${r.y + 5}">${r.txt}</text>`;
  });

  svg += `<line id="mira" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--tinta-3)" stroke-width="1" visibility="hidden"/>`;
  svg += `<circle id="mira-p" r="6" fill="none" stroke="var(--tinta)" stroke-width="2" visibility="hidden" shape-rendering="geometricPrecision"/>`;
  svg += `<rect class="alvo" x="${m.l}" y="0" width="${pw}" height="${H}" fill="transparent"/>`;
  gp.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Preço de ${esc(d.nome)} ao longo do tempo">${svg}</svg>`;

  // Volume: gráfico separado (nunca dois eixos no mesmo gráfico).
  const maxU = Math.max(1, ...serie.map((s) => s.unidades));
  let sv = `<line x1="${m.l}" x2="${W - m.r}" y1="${HV - 2}" y2="${HV - 2}" stroke="var(--grade)"/>`;
  sv += `<text x="${m.l - 8}" y="14" text-anchor="end">${nf(0).format(maxU)}</text><text x="${m.l - 8}" y="${HV - 2}" text-anchor="end">0</text>`;
  for (const s of serie) {
    const xa = X(s.t) + 1, xb = X(Math.min(s.fim, x1)) - 1;
    const h = (s.unidades / maxU) * (HV - 8);
    sv += `<rect x="${xa}" y="${HV - 2 - h}" width="${Math.max(2, xb - xa)}" height="${Math.max(1, h)}" fill="var(--serie-1)"/>`;
  }
  sv += `<line id="mira-v" x1="0" x2="0" y1="0" y2="${HV}" stroke="var(--tinta-3)" visibility="hidden"/>`;
  sv += `<rect class="alvo" x="${m.l}" y="0" width="${pw}" height="${HV}" fill="transparent"/>`;
  gv.innerHTML = `<svg viewBox="0 0 ${W} ${HV}" height="${HV}" role="img" aria-label="Unidades vendidas por período">${sv}</svg>`;

  const buracos = trechos.length - 1;
  $('#g-aviso').textContent = `Cada ponto = ${rotPasso(d.passo)}.` + (buracos > 0 ? ` A linha se interrompe onde não há coleta (${buracos} intervalo(s) sem dados).` : '');

  // Hover: mira compartilhada pelos dois gráficos + tooltip.
  const tip = $('#tooltip');
  const mover = (ev) => {
    const svgEl = ev.currentTarget.ownerSVGElement;
    const r = svgEl.getBoundingClientRect();
    const mx = ((ev.clientX - r.left) / r.width) * W;
    const t = x0 + ((mx - m.l) / pw) * (x1 - x0);
    let s = null, dist = Infinity;
    for (const b of serie) { const dd = Math.abs((b.t + b.fim) / 2 - t); if (dd < dist) { dist = dd; s = b; } }
    let a = null, da = Infinity;
    for (const x of anun) { const dd = Math.abs(x.t - t); if (dd < da) { da = dd; a = x; } }
    if (a && da > 90 * 60_000) a = null;
    if (s && dist > d.passo * 1.5) s = null;
    const xm = s ? centro(s) : a ? X(a.t) : mx;
    for (const [id, vis] of [['#mira', 1], ['#mira-v', 1]]) {
      const el = $(id); el.setAttribute('x1', xm); el.setAttribute('x2', xm); el.setAttribute('visibility', vis ? 'visible' : 'hidden');
    }
    const p = $('#mira-p');
    if (s) { p.setAttribute('cx', xm); p.setAttribute('cy', Y(s.mediana)); p.setAttribute('visibility', 'visible'); } else p.setAttribute('visibility', 'hidden');
    let h = '';
    if (s) {
      h += `<div class="t">${fDiaHora.format(s.t)} – ${fHora.format(Math.min(s.fim, x1))}</div>`;
      h += `<div><span class="sw" style="background:var(--serie-1)"></span>mediana <b>${fmtNum(s.mediana, moeda)}</b></div>`;
      h += `<div>faixa <b>${fmtNum(s.min, moeda)} – ${fmtNum(s.max, moeda)}</b></div>`;
      h += `<div>${nf(0).format(s.vendas)} vendas · ${nf(0).format(s.unidades)} un.</div>`;
    } else h += `<div class="t">${fDiaHora.format(t)}</div><div>sem vendas aqui</div>`;
    if (a) h += `<div><span class="sw" style="background:var(--serie-2)"></span>menor anúncio <b>${fmtNum(a.min, moeda)}</b> (${fHora.format(a.t)}, ${nf(0).format(a.anuncios)} anúncios)</div>`;
    tip.innerHTML = h;
    tip.classList.remove('hidden');
    const tx = Math.min(ev.clientX + 16, innerWidth - tip.offsetWidth - 8);
    const ty = Math.min(ev.clientY + 16, innerHeight - tip.offsetHeight - 8);
    tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
  };
  const sair = () => {
    tip.classList.add('hidden');
    ['#mira', '#mira-v', '#mira-p'].forEach((id) => $(id)?.setAttribute('visibility', 'hidden'));
  };
  $$('.alvo').forEach((el) => { el.addEventListener('mousemove', mover); el.addEventListener('mouseleave', sair); });
}

const rotPasso = (ms) => {
  const min = ms / 60000;
  if (min < 60) return `${min} min`;
  if (min < 1440) return `${min / 60} h`;
  return `${min / 1440} dia(s)`;
};

// ------------------------------------------------------------------ montagem
async function carregarMontagem() {
  const d = await api('/api/montagem');
  const fonte = estado.fonte;
  const escolher = (l) => {
    if (fonte === 'jogo') return l.media7_jogo != null ? [l.media7_jogo, 'jogo'] : [null, ''];
    if (fonte === 'anuncio') return l.anuncio != null ? [l.anuncio, 'anúncio'] : [null, ''];
    if (l.mediana != null && l.vendas >= 3) return [l.mediana, 'vendas'];
    if (l.media7_jogo != null) return [l.media7_jogo, 'jogo'];
    if (l.anuncio != null) return [l.anuncio, 'anúncio'];
    return [null, ''];
  };
  const html = Object.entries(d.montagens).map(([chave, mt]) => {
    const [fp, ff] = escolher({ mediana: mt.frag_mediana, vendas: mt.frag_vendas, media7_jogo: mt.frag_media7_jogo, anuncio: mt.frag_anuncio });
    const precos = mt.linhas.map(escolher);
    let ev = 0, semPreco = [], evMitica = 0;
    mt.linhas.forEach((l, i) => {
      const p = precos[i][0];
      if (p == null) { semPreco.push(l.raridade); return; }
      ev += l.chance * p;
      if (l.raridade === 'Mítica' || l.raridade === 'Lendária') evMitica += l.chance * p;
    });
    const custo = fp != null ? fp * 10 : null;
    const vant = custo ? (ev / custo - 1) * 100 : null;
    const vantSem = custo ? ((ev - evMitica) / custo - 1) * 100 : null;
    const titulo = chave === 'casa' ? 'Casa (10 Key Fragment)' : 'Bicicleta (10 Bicycle Fragment)';
    const ico = chave === 'casa' ? 'casa' : 'bike';
    const ups = [0, 1].map((i) => {
      const a = precos[i][0], b = precos[i + 1][0];
      if (a == null || b == null) return '';
      const compensa = 5 * a < b;
      return `<p>• Upgrade 5× ${mt.linhas[i].raridade} → 1 ${mt.linhas[i + 1].raridade}: custa ${fmtNum(5 * a, 'gems')}, vale ${fmtNum(b, 'gems')} — <b>${compensa ? 'compensa' : 'não compensa'}</b>.</p>`;
    }).join('');
    const leitura = vant == null ? '<p>Falta preço do fragmento.</p>' : `
      <p>• Montar ${vant >= 0 ? 'rende' : 'perde'} <b>${nf(1).format(Math.abs(vant))}%</b> em média contra vender os 10 fragmentos.</p>
      <p>• Sem contar Mítica e Lendária: <b>${vantSem >= 0 ? '+' : '−'}${nf(1).format(Math.abs(vantSem))}%</b>. ${vant > 0 && vantSem < 0 ? 'A vantagem depende só das raridades altas (1 em 200).' : ''}</p>
      ${semPreco.length ? `<p>• Sem preço (contam como zero): ${semPreco.join(', ')}.</p>` : ''}
      ${ups}`;
    return `
      <div class="janela">
        <div class="janela-titulo"><span class="ico ico-grande">${img(mt.icone)}</span>${titulo}</div>
        <div class="janela-corpo">
          <div class="tabela-wrap"><table class="tabela">
            <tr><th>Raridade</th><th class="num">Chance</th><th class="num">Vendas 7d</th><th class="num">Média 7d jogo</th><th class="num">Menor anúncio</th><th class="num">Usado</th></tr>
            ${mt.linhas.map((l, i) => `<tr>
              <td><span class="linha-item ${classeRaridade(l.nome)}" style="display:inline;padding:0 6px;border-top:0;border-right:0;border-bottom:0;box-shadow:none;background:none"><span class="ico" style="margin-right:6px">${img(l.icone)}</span>${l.raridade}</span></td>
              <td class="num">${nf(3).format(l.chance * 100)}%</td>
              <td class="num">${l.mediana != null ? `${fmtNum(l.mediana, 'gems')} <span class="tag">${l.vendas}</span>` : '—'}</td>
              <td class="num">${fmtNum(l.media7_jogo, 'gems')}</td>
              <td class="num">${fmtNum(l.anuncio, 'gems')}${l.anuncios ? ` <span class="tag">${l.anuncios}</span>` : ''}</td>
              <td class="num">${precos[i][0] != null ? `${htmlPreco(precos[i][0], 'gems')} <span class="tag">${precos[i][1]}</span>` : '—'}</td></tr>`).join('')}
          </table></div>
          <div class="ev-tiles">
            <div class="tile"><div class="rot">10 fragmentos</div><div class="val">${htmlPreco(custo, 'gems')}</div><div class="det">${ff ? 'preço: ' + ff : ''}</div></div>
            <div class="tile"><div class="rot">Valor esperado</div><div class="val">${htmlPreco(ev || null, 'gems')}</div><div class="det">Σ chance × preço</div></div>
            <div class="tile"><div class="rot">Vantagem de montar</div><div class="val">${htmlVar(vant)}</div><div class="det">vs vender fragmentos</div></div>
            <div class="tile"><div class="rot">Sem a Mítica</div><div class="val">${htmlVar(vantSem)}</div><div class="det">sem Mítica e Lendária</div></div>
          </div>
          <div class="leitura">${leitura}</div>
        </div>
      </div>`;
  }).join('');
  $('#montagens').innerHTML = html;
}

// ------------------------------------------------------------------ sinais (Fase 3)
async function postar(caminho, corpo) {
  const r = await fetch(caminho, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.erro || r.statusText);
  return j;
}

const htmlLiq = (s) => `<span class="liq ${s.liquidez}" title="${nf(1).format(s.vendas_dia)} vendas/dia">${s.liquidez}</span>`;
const DESCR_REGRA = (r, moeda) => {
  const v = r.tipo === 'oportunidade' || r.tipo === 'variacao' ? nf(1).format(r.valor) + '%' : fmtNum(r.valor, r.moeda);
  return { oportunidade: `margem de revenda ≥ ${v}`, abaixo: `menor anúncio ≤ ${v}`, acima: `mediana 24h ≥ ${v}`, variacao: `variação 7d ≥ ${v}` }[r.tipo];
};

async function carregarSinais() {
  const d = await api('/api/sinais', { moeda: estado.moeda });
  estado.sinais = d;
  desenharSinais();
}

function irParaItem(nome) {
  estado.item = nome;
  estado.categoria = 'todas';
  mostrarAba('mercado');
  desenharLista();
  selecionar(nome);
}

function desenharSinais() {
  const d = estado.sinais;
  if (!d) return;
  const m = d.moeda;
  // Oportunidades
  const todas = $('#op-todas').checked, semBaixa = $('#op-liquidez').checked;
  let ops = d.itens.filter((s) => s.margem != null && (todas || s.margem > 0) && (!semBaixa || s.liquidez !== 'baixa'));
  ops.sort((a, z) => z.margem - a.margem);
  const positivas = d.itens.filter((s) => s.margem > 0 && s.liquidez !== 'baixa').length;
  $('#op-sub').textContent = d.itens[0]?.snap_ms ? `vitrine de ${fHora.format(d.itens[0].snap_ms)} · ${positivas} com margem positiva` : '';
  $('#op-tabela').innerHTML = `
    <tr><th>Item</th><th class="num">Menor anúncio</th><th class="num">Referência</th><th class="num">Revende (líquido)</th><th class="num">Lucro/un.</th><th class="num">Margem</th><th>Liquidez</th></tr>
    ${ops.map((s) => `<tr class="clicavel" data-item="${esc(s.nome)}" title="${s.anuncios ?? '?'} anúncios · ${s.vendas7d} vendas em 7d">
      <td><span class="ico">${img(s.icone)}</span>${esc(s.nome)}</td>
      <td class="num">${htmlPreco(s.anuncio_min, m)}</td><td class="num">${fmtNum(s.referencia, m)}</td>
      <td class="num">${fmtNum(s.liquido_revenda, m)}</td>
      <td class="num ${s.lucro > 0 ? 'margem-pos' : 'margem-neg'}">${s.lucro > 0 ? '+' : ''}${fmtNum(s.lucro, m)}${m === 'gems' && s.lucro > 0 ? ` <span class="aviso">${usd(s.lucro)}</span>` : ''}</td>
      <td class="num">${htmlVar(s.margem)}</td><td>${htmlLiq(s)}</td></tr>`).join('')
      || `<tr><td colspan="7" class="vazio" style="padding:20px">Nenhuma revenda com lucro agora: depois dos 15% de taxa, comprar no menor anúncio e revender pela mediana dá prejuízo em todos os itens. Marque "mostrar também as margens negativas" para ver o quanto falta.</td></tr>`}`;
  // Barato / caro
  const bc = d.itens.filter((s) => s.desvio != null).sort((a, z) => a.desvio - z.desvio);
  $('#bc-tabela').innerHTML = `
    <tr><th>Item</th><th class="num">Mediana 24h</th><th class="num">Mediana 7d</th><th class="num">24h vs 7d</th><th class="num">Var. 7d</th><th>Liquidez</th></tr>
    ${bc.map((s) => `<tr class="clicavel" data-item="${esc(s.nome)}">
      <td><span class="ico">${img(s.icone)}</span>${esc(s.nome)}</td>
      <td class="num">${htmlPreco(s.mediana24h, m)}</td><td class="num">${fmtNum(s.mediana7d, m)}</td>
      <td class="num">${htmlVar(s.desvio)}</td><td class="num">${htmlVar(s.var7d)}</td><td>${htmlLiq(s)}</td></tr>`).join('')
      || '<tr><td colspan="6" class="vazio" style="padding:20px">Ainda sem histórico suficiente: a comparação entre 24h e 7 dias aparece depois de 36h de coleta.</td></tr>'}`;
  // Regras
  const nomesCanal = { windows: 'notificação do Windows', discord: 'Discord', telegram: 'Telegram' };
  $('#canais').innerHTML = 'Avisos por: ' + (d.canais.length
    ? d.canais.map((c) => `<span class="tag" style="color:var(--sobe)">${nomesCanal[c]}</span>`).join(' ')
    : '<span class="tag">só no painel</span>') + ' <span class="aviso">(Discord/Telegram: veja o PLANO.md)</span>';
  $('#regras-tabela').innerHTML = `
    <tr><th>Ativa</th><th>Item</th><th>Condição</th><th>Moeda</th><th></th></tr>
    ${d.regras.map((r) => `<tr class="${r.ativo ? '' : 'regra-off'}">
      <td><input type="checkbox" data-alternar="${r.id}" ${r.ativo ? 'checked' : ''} aria-label="ativar regra"></td>
      <td>${r.item ? esc(r.item) : '<i>qualquer item</i>'}</td><td>${esc(DESCR_REGRA(r))}</td>
      <td>${r.moeda === 'gems' ? 'gemas' : 'coins'}</td>
      <td><button class="chip" data-apagar="${r.id}">apagar</button></td></tr>`).join('')
      || '<tr><td colspan="5">Nenhuma regra.</td></tr>'}`;
  if (!$('#r-tipo').options.length) {
    $('#r-tipo').innerHTML = Object.entries(d.tipos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  }
  const selItem = $('#r-item').value;
  $('#r-item').innerHTML = '<option value="">qualquer item</option>' + d.nomes.map((n) => `<option ${n === selItem ? 'selected' : ''}>${esc(n)}</option>`).join('');
  // Log
  $('#log-tabela').innerHTML = `
    <tr><th>Quando</th><th>Alerta</th><th>Enviado por</th></tr>
    ${d.log.map((a) => `<tr><td>${fDiaHora.format(a.ms)}</td><td style="white-space:normal">${esc(a.msg)}</td><td>${esc(a.canais || 'só log')}</td></tr>`).join('')
      || '<tr><td colspan="3">Nenhum alerta ainda.</td></tr>'}`;
}

function ligarSinais() {
  $('#op-todas').addEventListener('change', desenharSinais);
  $('#op-liquidez').addEventListener('change', desenharSinais);
  $('#aba-sinais').addEventListener('click', async (e) => {
    const linha = e.target.closest('tr.clicavel');
    const apagar = e.target.closest('[data-apagar]');
    const alternar = e.target.closest('[data-alternar]');
    if (apagar) { await postar('/api/regras/apagar', { id: +apagar.dataset.apagar }); return carregarSinais(); }
    if (alternar) { await postar('/api/regras/alternar', { id: +alternar.dataset.alternar }); return carregarSinais(); }
    if (linha) irParaItem(linha.dataset.item);
  });
  $('#form-regra').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await postar('/api/regras', { tipo: $('#r-tipo').value, item: $('#r-item').value, moeda: $('#r-moeda').value, valor: $('#r-valor').value });
      $('#r-valor').value = '';
      carregarSinais();
    } catch (err) { alert(err.message); }
  });
  $('#btn-testar').addEventListener('click', async () => {
    $('#teste-res').textContent = 'enviando…';
    await destravarAudio();
    tocar('oportunidade');
    mostrarAviso({ msg: 'Teste de alerta: se você ouviu o som e está vendo este aviso, a página está avisando.', ms: Date.now() });
    const r = await postar('/api/alertas/testar', {});
    $('#teste-res').textContent = r.canais.length ? `enviado por: ${r.canais.join(', ')}${r.erros.length ? ' · falhas: ' + r.erros.join('; ') : ''}`
      : (r.erros.length ? 'falhou: ' + r.erros.join('; ') : 'nenhum canal configurado');
  });
}

// ------------------------------------------------------------------ aviso sonoro na página
// Som 8-bit gerado na hora (onda quadrada), sem arquivo. O navegador só libera áudio depois de um
// clique na página, por isso o botão "♪" pisca até o primeiro clique.
const som = { ligado: true, ctx: null };
try { som.ligado = localStorage.getItem('som') !== '0'; } catch { /* sem storage: fica ligado */ }
let ultimoAlerta = -1, naoVistos = 0;
const TITULO = document.title;

const audioPronto = () => !!som.ctx && som.ctx.state === 'running';
async function destravarAudio() {
  try {
    som.ctx = som.ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (som.ctx.state !== 'running') await som.ctx.resume();
  } catch { /* sem áudio neste navegador */ }
  pintarSom();
}
function pintarSom() {
  const b = $('#som');
  b.classList.toggle('ligado', som.ligado && audioPronto());
  b.classList.toggle('bloqueado', som.ligado && !audioPronto());
  $('#som-txt').textContent = !som.ligado ? 'som desligado' : audioPronto() ? 'som ligado' : 'clique para ativar o som';
}
function tocar(tipo = 'alerta') {
  if (!som.ligado || !audioPronto()) return;
  // Oportunidade: arpejo subindo (moeda); outros alertas: dois toques.
  const notas = tipo === 'oportunidade' ? [659, 784, 1047, 1319] : [880, 659, 880, 659];
  const t0 = som.ctx.currentTime + 0.02;
  notas.forEach((f, i) => {
    const o = som.ctx.createOscillator(), g = som.ctx.createGain();
    o.type = 'square';
    o.frequency.value = f;
    const ti = t0 + i * 0.11;
    g.gain.setValueAtTime(0.0001, ti);
    g.gain.exponentialRampToValueAtTime(0.07, ti + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, ti + 0.1);
    o.connect(g).connect(som.ctx.destination);
    o.start(ti);
    o.stop(ti + 0.12);
  });
}
function mostrarAviso(a) {
  const el = document.createElement('div');
  el.className = 'janela aviso-alerta';
  el.innerHTML = `<div class="janela-titulo">Alerta</div><div class="janela-corpo">${esc(a.msg)}
    <div class="quando">${fDiaHora.format(a.ms)}${a.item ? ' · clique para abrir o item' : ' · clique para fechar'}</div></div>`;
  el.addEventListener('click', () => { el.remove(); if (a.item) irParaItem(a.item); });
  $('#avisos').prepend(el);
  setTimeout(() => el.remove(), 90_000);
  while ($('#avisos').children.length > 4) $('#avisos').lastChild.remove();
}
const atualizarTitulo = () => { document.title = naoVistos ? `(${naoVistos}) ${TITULO}` : TITULO; };

async function checarAlertasNovos() {
  try {
    const d = await api('/api/alertas/novos', { desde: ultimoAlerta });  // `ultimoAlerta` = horário (ms) do último visto
    if (ultimoAlerta >= 0 && d.novos.length) {
      d.novos.forEach(mostrarAviso);
      tocar(d.novos.some((a) => a.msg.startsWith('💰')) ? 'oportunidade' : 'alerta');
      if (document.hidden) { naoVistos += d.novos.length; atualizarTitulo(); }
      if (estado.aba === 'sinais') carregarSinais();
    }
    ultimoAlerta = d.ultimo;  // na primeira vez só marca onde está: alertas antigos não tocam
  } catch { /* painel sem banco: tenta de novo na próxima */ }
}

function ligarSom() {
  pintarSom();
  $('#som').addEventListener('click', async () => {
    if (som.ligado && audioPronto()) {
      som.ligado = false;
    } else {
      som.ligado = true;
      await destravarAudio();
      tocar('oportunidade');
    }
    try { localStorage.setItem('som', som.ligado ? '1' : '0'); } catch { /* ok */ }
    pintarSom();
  });
  // Qualquer primeiro clique na página já libera o áudio.
  // (O clique no próprio botão fica com ele, senão destravaria e desligaria no mesmo clique.)
  document.addEventListener('pointerdown', (e) => {
    if (!audioPronto() && !e.target.closest('#som')) destravarAudio();
  }, { capture: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { naoVistos = 0; atualizarTitulo(); } });
  checarAlertasNovos();
  setInterval(checarAlertasNovos, 30_000);
}

// ------------------------------------------------------------------ pokémon (Fase 4)
const TIPOS_PK = { NORMAL: 'Normal', FIRE: 'Fogo', WATER: 'Água', GRASS: 'Planta', ELECTRIC: 'Elétrico', ICE: 'Gelo',
  FIGHTING: 'Lutador', POISON: 'Veneno', GROUND: 'Terra', FLYING: 'Voador', PSYCHIC: 'Psíquico', BUG: 'Inseto',
  ROCK: 'Pedra', GHOST: 'Fantasma', DRAGON: 'Dragão', DARK: 'Sombrio', STEEL: 'Aço', FAIRY: 'Fada' };
const OBJETIVOS_PK = {
  equilibrado: 'equilibrado: forte e com preço justo',
  forte: 'o mais forte (maior poder)',
  barganha: 'o maior desconto vs preço justo',
  custo: 'mais poder por gema/coin',
  nota: 'a maior nota',
};
estado.pksub = 'buscar';
estado.pkdias = 7;

function mostrarSubPk(sub) {
  estado.pksub = sub;
  $$('[data-pksub]').forEach((b) => b.classList.toggle('ativa', b.dataset.pksub === sub));
  $$('.pk-painel').forEach((p) => p.classList.toggle('hidden', p.id !== 'pk-' + sub));
  if (sub === 'padroes') carregarPadroesPk();
  if (sub === 'vendas') carregarPokemon();
}

const tagsTipo = (tipos) => (tipos || []).map((t) => `<span class="tipo-tag">${esc(TIPOS_PK[t] || t)}</span>`).join('');

async function buscarPk(e) {
  e?.preventDefault();
  const moeda = $('#pkb-moeda').value;
  $('#pkb-tabela').innerHTML = '<tr><td class="vazio">procurando…</td></tr>';
  const d = await api('/api/pk/buscar', {
    orcamento: $('#pkb-orc').value, moeda, objetivo: $('#pkb-obj').value, especie: $('#pkb-esp').value.trim(),
    tipo: $('#pkb-tipo').value, pmin: $('#pkb-pmin').value, nivel: $('#pkb-nivel').value, nota: $('#pkb-nota').value,
    shiny: $('#pkb-shiny').checked ? 1 : '',
  });
  $('#pkb-sub').textContent = d.varredura_ms
    ? `loja lida às ${fDiaHora.format(d.varredura_ms)} · ${nf(0).format(d.anuncios_na_loja)} anúncios · ${nf(0).format(d.total)} cabem no orçamento`
    : 'a loja ainda não foi lida pelo robô';
  const m = d.moeda;
  $('#pkb-tabela').innerHTML = `
    <tr><th>#</th><th>Pokémon</th><th class="num">Nv</th><th class="num">P</th><th class="num">IV</th><th class="num">Qual.</th><th class="num">Nota</th>
      <th class="num">Poder</th><th class="num">Preço</th><th class="num">Preço justo</th><th class="num">Desconto</th><th>Confiança</th>
      <th class="num">Lucro revendendo</th><th>Vendedor</th></tr>
    ${d.itens.map((x, i) => `<tr title="IVs: ${Object.entries(x.ivs).map(([k, v]) => k + ' ' + v).join(' · ')}${x.faixa ? ` | vendas parecidas entre ${fmtNum(x.faixa[0], m)} e ${fmtNum(x.faixa[1], m)}` : ''}">
      <td>${i + 1}</td>
      <td style="white-space:normal">${esc(x.especie)} ${x.shiny ? '<span class="tag shiny">shiny</span>' : ''}${x.tm ? ' <span class="tag">TM</span>' : ''}<br>${tagsTipo(x.tipos)}</td>
      <td class="num">${nf(0).format(x.nivel ?? 0)}</td><td class="num">${x.potencia ?? '—'}</td><td class="num">${x.iv ?? '—'}</td>
      <td class="num">${x.qualidade != null ? nf(3).format(x.qualidade) : '—'}</td><td class="num">${x.nota != null ? nf(3).format(x.nota) : '—'}</td>
      <td class="num">${nf(0).format(x.poder ?? 0)}</td>
      <td class="num">${htmlPreco(x.preco, m)}</td>
      <td class="num">${x.justo != null ? fmtNum(x.justo, m) + ` <span class="tag">${x.comps}</span>` : '<span class="aviso">sem vendas parecidas</span>'}</td>
      <td class="num">${x.desconto != null ? htmlVar(x.desconto) : '—'}</td>
      <td>${x.confianca ? `<span class="conf ${x.confianca}">${x.confianca}</span>` : '—'}</td>
      <td class="num ${x.lucro_revenda > 0 ? 'margem-pos' : 'margem-neg'}">${x.lucro_revenda != null ? (x.lucro_revenda > 0 ? '+' : '') + fmtNum(x.lucro_revenda, m) : '—'}</td>
      <td>${esc(x.vendedor)}</td></tr>`).join('')
      || `<tr><td colspan="14" class="vazio" style="padding:20px">${d.varredura_ms ? 'Nenhum Pokémon da loja cabe nesse orçamento com esses filtros.' : 'O robô ainda não leu a loja de Pokémon (ele faz isso a cada 3 h).'}</td></tr>`}`;
}

async function carregarPadroesPk() {
  const moeda = estado.moeda;
  const d = await api('/api/pk/padroes', { moeda, dias: estado.pkdias });
  const r = d.resumo;
  $('#pkp-sub').textContent = `em ${moeda === 'gems' ? 'gemas' : 'coins'} · dados de ${nf(1).format(Math.min(d.dias_cobertos, d.dias))} dia(s)`;
  $('#pkp-tiles').innerHTML = `
    <div class="tile"><div class="rot">Vendas</div><div class="val">${nf(0).format(r.vendas)}</div><div class="det">+${nf(0).format(r.vendas_outra_moeda)} na outra moeda</div></div>
    <div class="tile"><div class="rot">Volume</div><div class="val">${htmlPreco(r.volume, moeda)}</div><div class="det">${moeda === 'gems' ? usd(r.volume) : '&nbsp;'}</div></div>
    <div class="tile"><div class="rot">Preço mediano</div><div class="val">${htmlPreco(r.mediana, moeda)}</div><div class="det">${r.especies} espécies vendidas</div></div>
    <div class="tile"><div class="rot">Shiny</div><div class="val">${r.shiny_pct != null ? nf(1).format(r.shiny_pct) + '%' : '—'}</div><div class="det">das vendas</div></div>
    <div class="tile"><div class="rot">Na loja agora</div><div class="val">${nf(0).format(r.anuncios_loja)}</div><div class="det">${r.especies_loja} espécies${r.varredura_ms ? ' · lida ' + fHora.format(r.varredura_ms) : ''}</div></div>
    <div class="tile"><div class="rot">Saíram da loja (24h)</div><div class="val">${nf(0).format(r.sumiram_24h)}</div><div class="det">vendidos, cancelados ou vencidos</div></div>`;
  // Multiplicadores (escala logarítmica de 0,25× a o maior valor; a marca é 1×).
  const nomes = { potencia: 'Potência', nota: 'Nota', nivel: 'Nível', iv: 'IV total', qualidade: 'Qualidade', shiny: 'Shiny' };
  const todos = Object.values(d.premios).flat().map((x) => x.mult).filter((x) => x != null);
  const lo = Math.log(0.25), hi = Math.log(Math.max(4, ...todos));
  const pos = (v) => Math.max(0, Math.min(1, (Math.log(v) - lo) / (hi - lo))) * 100;
  $('#pkp-premios').innerHTML = Object.entries(d.premios).map(([dim, linhas]) => `
    <div class="premio-bloco"><h4>${nomes[dim]}</h4>
      ${linhas.map((l) => `<div class="premio-linha" title="${l.vendas} vendas">
        <span>${esc(l.faixa)}</span>
        <span class="premio-barra">${l.mult != null ? `<i style="width:${pos(l.mult)}%"></i>` : ''}<b style="left:${pos(1)}%"></b></span>
        <span class="v">${l.mult != null ? nf(2).format(l.mult) + '×' : `<span class="aviso">${l.vendas} vendas</span>`}</span></div>`).join('')}
    </div>`).join('');
  // Espécies
  $('#pkp-especies').innerHTML = `
    <tr><th>Espécie</th><th class="num">Vendas</th><th class="num">/dia</th><th class="num">Mediana</th><th class="num">p25–p75</th><th class="num">Na loja</th><th class="num">Menor anúncio</th><th class="num">Dias de estoque</th></tr>
    ${d.especies.map((e) => `<tr class="clicavel" data-pkesp="${esc(e.especie)}" title="clique para procurar essa espécie na loja">
      <td>${esc(e.especie)}</td><td class="num">${e.vendas}</td><td class="num">${nf(1).format(e.vendas_dia)}</td>
      <td class="num">${htmlPreco(e.mediana, moeda)}</td><td class="num">${fmtNum(e.p25, moeda)}–${fmtNum(e.p75, moeda)}</td>
      <td class="num">${e.anuncios}</td><td class="num">${fmtNum(e.menor_anuncio, moeda)}</td><td class="num">${e.dias_estoque ?? '—'}</td></tr>`).join('')}`;
  // Horas (barras; o hover de cada barra diz o número)
  const max = Math.max(1, ...d.horas.map((h) => h.vendas));
  const W = Math.max(300, $('#pkp-horas').clientWidth), H = 120, bw = (W - 40) / 24;
  $('#pkp-horas').innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Vendas por hora">
    <line x1="30" x2="${W - 6}" y1="${H - 18}" y2="${H - 18}" stroke="var(--grade)"/>
    <text x="24" y="14" text-anchor="end">${max}</text>
    ${d.horas.map((h, i) => { const hh = (h.vendas / max) * (H - 34); return `<rect x="${32 + i * bw}" y="${H - 18 - hh}" width="${Math.max(2, bw - 2)}" height="${Math.max(1, hh)}" fill="var(--serie-1)"><title>${h.hora}h: ${h.vendas} vendas</title></rect>`
      + (i % 3 === 0 ? `<text x="${32 + i * bw + bw / 2}" y="${H - 3}" text-anchor="middle">${h.hora}h</text>` : ''); }).join('')}
  </svg>`;
  const tabTop = (lista, titulo) => `<tr><th>${titulo}</th><th class="num">Qtd</th><th class="num">Mediana</th></tr>`
    + lista.map((x) => `<tr><td>${esc(x.nome)}</td><td class="num">${x.qtd}</td><td class="num">${fmtNum(x.mediana, moeda)}</td></tr>`).join('');
  $('#pkp-compradores').innerHTML = tabTop(d.compradores, 'Compradores');
  $('#pkp-vendedores').innerHTML = tabTop(d.vendedores, 'Vendedores');
  const piso = d.compradores.filter((c) => c.qtd >= 10 && c.mediana <= (r.mediana || 0) * 0.6);
  $('#pkp-piso').textContent = piso.length
    ? `Padrão: ${piso.map((c) => c.nome).join(', ')} compram em volume perto do piso (${fmtNum(piso[0].mediana, moeda)}). Esse é o preço mínimo prático de um Pokémon comum. Hipótese: viram matéria-prima (ex.: Oferenda, 5 Pokémon = 1 pedra garantida).`
    : '';
  $('#pkp-taxa').innerHTML = '<tr><th class="num">Vendendo por</th><th class="num">Taxa</th><th class="num">%</th><th class="num">Você recebe</th></tr>'
    + d.taxa_exemplos.map((x) => `<tr><td class="num">${htmlPreco(x.preco, moeda)}</td><td class="num">${fmtNum(x.taxa, moeda)}</td><td class="num">${nf(1).format(x.taxa / x.preco * 100)}%</td><td class="num">${fmtNum(x.preco - x.taxa, moeda)}</td></tr>`).join('');
}

function ligarPokemon() {
  $('#pkb-obj').innerHTML = Object.entries(OBJETIVOS_PK).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  $('#pkb-tipo').innerHTML = '<option value="">qualquer</option>' + Object.entries(TIPOS_PK).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  $('#pkb-form').addEventListener('submit', buscarPk);
  $$('[data-pksub]').forEach((b) => b.addEventListener('click', () => mostrarSubPk(b.dataset.pksub)));
  $$('[data-pkdias]').forEach((b) => b.addEventListener('click', () => {
    estado.pkdias = +b.dataset.pkdias;
    $$('[data-pkdias]').forEach((x) => x.classList.toggle('ativa', x === b));
    carregarPadroesPk();
  }));
  $('#pkp-especies').addEventListener('click', (e) => {
    const l = e.target.closest('[data-pkesp]');
    if (!l) return;
    $('#pkb-esp').value = l.dataset.pkesp;
    $('#pkb-moeda').value = estado.moeda;
    mostrarSubPk('buscar');
    buscarPk();
  });
}

let tPk = null;
async function carregarPokemon() {
  const d = await api('/api/pokemon', { busca: $('#pk-busca').value.trim(), moeda: $('#pk-moeda').value, shiny: $('#pk-shiny').checked ? 1 : '', limite: 300 });
  $('#pk-tabela').innerHTML = `
    <tr><th>Quando</th><th>Pokémon</th><th class="num">Nv</th><th>Shiny</th><th class="num">IV</th><th class="num">P</th><th class="num">Qual.</th><th class="num">Nota</th><th class="num">Preço</th><th>Vendedor → comprador</th></tr>
    ${d.vendas.map((v) => `<tr>
      <td>${fDiaHora.format(v.t)}</td><td>${esc(v.especie)}</td><td class="num">${v.nivel ?? '—'}</td>
      <td>${v.shiny ? '<span class="tag shiny">shiny</span>' : ''}</td><td class="num">${v.iv ?? '—'}</td><td class="num">${v.potencia ?? '—'}</td>
      <td class="num">${v.qualidade != null ? nf(3).format(v.qualidade) : '—'}</td><td class="num">${v.nota != null ? nf(3).format(v.nota) : '—'}</td>
      <td class="num">${htmlPreco(v.preco, v.moeda)}</td><td>${esc(v.vendedor)} → ${esc(v.comprador)}</td></tr>`).join('') || '<tr><td colspan="10">Nenhuma venda.</td></tr>'}`;
}

// ------------------------------------------------------------------ status do coletor
async function carregarStatus() {
  try {
    const s = await api('/api/status');
    const led = $('#status .led');
    const ult = s.ultimo_export ? s.ultimo_export.split(' ')[1] : null;
    $('#status-txt').textContent = ult ? `export ${ult} · próximo ${s.proximo_export === 'agora' ? 'agora' : s.proximo_export.split(' ')[1]}` : 'sem export ainda';
    // Atraso: comparar a venda mais recente com agora.
    const recente = s.venda_mais_recente ? Date.parse(s.venda_mais_recente.replace(' ', 'T') + ':00-03:00') : 0;
    const atraso = (Date.now() - recente) / 60000;
    led.className = 'led ' + (atraso < 90 ? 'ok' : atraso < 240 ? 'alerta' : 'ruim');
    $('#status').title = `Venda mais recente: ${s.venda_mais_recente} (${Math.round(atraso)} min atrás)`;
    $('#status-corpo').innerHTML = `
      <div class="calc-linha"><span>Vendas no banco</span><b>${nf(0).format(s.vendas_no_banco)} (${nf(0).format(s.vendas_com_ms)} com horário exato)</b></div>
      <div class="calc-linha"><span>Venda mais recente</span><b>${esc(s.venda_mais_recente)}</b></div>
      <div class="calc-linha"><span>Último export · próximo</span><b>${esc(s.ultimo_export)} · ${esc(s.proximo_export)}</b></div>
      <div class="calc-linha"><span>Vitrine (snapshots)</span><b>${esc(s.ultima_vitrine)} (${s.snapshots_vitrine})</b></div>
      <div class="calc-linha"><span>Buracos na coleta</span><b>${s.buracos}</b></div>
      ${s.buracos_lista.map((b) => `<div class="aviso">• faltam vendas antes de ${esc(b.antes_de)}</div>`).join('')}
      <pre>${esc(s.robo_log.join('\n'))}</pre>`;
  } catch (e) {
    $('#status .led').className = 'led ruim';
    $('#status-txt').textContent = e.desligado ? 'painel desligado: abra o iniciar.bat' : 'erro no painel: ' + e.message;
    $('#status').title = e.desligado
      ? 'O servidor do painel (python src/painel.py) não está rodando. Os números na tela são da última vez que ele respondeu.'
      : e.message;
  }
}

// ------------------------------------------------------------------ navegação
function mostrarAba(aba) {
  if (!['mercado', 'sinais', 'montagem', 'pokemon'].includes(aba)) aba = 'mercado';
  estado.aba = aba;
  $$('.abas .aba').forEach((b) => b.classList.toggle('ativa', b.dataset.aba === aba));
  $$('.aba-corpo').forEach((s) => s.classList.toggle('hidden', s.id !== 'aba-' + aba));
  $('.moeda-toggle').classList.toggle('hidden', !['mercado', 'sinais', 'pokemon'].includes(aba));
  gravarHash();
  if (aba === 'sinais') carregarSinais();
  if (aba === 'montagem') carregarMontagem();
  if (aba === 'pokemon') mostrarSubPk(estado.pksub);
  if (aba === 'mercado' && estado.ultimoItem) desenharGraficos(estado.ultimoItem);
}

function ligar() {
  pintarIcones();
  ligarSinais();
  ligarSom();
  ligarPokemon();
  $$('.abas .aba').forEach((b) => b.addEventListener('click', () => mostrarAba(b.dataset.aba)));
  $$('.btn-moeda').forEach((b) => b.addEventListener('click', async () => {
    estado.moeda = b.dataset.moeda;
    $$('.btn-moeda').forEach((x) => x.classList.toggle('ativa', x === b));
    if (estado.aba === 'sinais') carregarSinais();
    if (estado.aba === 'pokemon' && estado.pksub === 'padroes') carregarPadroesPk();
    await carregarResumo();
    if (estado.item) selecionar(estado.item);
  }));
  $$('[data-janela]').forEach((b) => b.addEventListener('click', () => {
    estado.janela = b.dataset.janela;
    $$('[data-janela]').forEach((x) => x.classList.toggle('ativa', x === b));
    if (estado.item) selecionar(estado.item);
  }));
  $$('[data-ordem]').forEach((b) => b.addEventListener('click', () => {
    estado.ordem = b.dataset.ordem;
    $$('[data-ordem]').forEach((x) => x.classList.toggle('ativa', x === b));
    desenharLista();
  }));
  $$('[data-fonte]').forEach((b) => b.addEventListener('click', () => {
    estado.fonte = b.dataset.fonte;
    $$('[data-fonte]').forEach((x) => x.classList.toggle('ativa', x === b));
    carregarMontagem();
  }));
  $('#busca').addEventListener('input', (e) => { estado.busca = e.target.value; desenharLista(); });
  $('#categorias').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cat]');
    if (!b) return;
    estado.categoria = b.dataset.cat;
    gravarHash();
    desenharLista();
  });
  $$('[data-tipo]').forEach((b) => b.addEventListener('click', () => { if (b.dataset.tipo === 'pokemon') mostrarAba('pokemon'); }));
  $('#lista').addEventListener('click', (e) => { const b = e.target.closest('.linha-item'); if (b) selecionar(b.dataset.nome); });
  const pk = () => { clearTimeout(tPk); tPk = setTimeout(carregarPokemon, 250); };
  $('#pk-busca').addEventListener('input', pk);
  $('#pk-moeda').addEventListener('change', pk);
  $('#pk-shiny').addEventListener('change', pk);
  $('#status').addEventListener('click', () => $('#status-pop').classList.toggle('hidden'));
  let tr = null;
  addEventListener('resize', () => { clearTimeout(tr); tr = setTimeout(() => estado.ultimoItem && estado.aba === 'mercado' && desenharGraficos(estado.ultimoItem), 150); });
}

async function iniciar() {
  lerHash();
  ligar();
  $$('.btn-moeda').forEach((x) => x.classList.toggle('ativa', x.dataset.moeda === estado.moeda));
  $$('[data-janela]').forEach((x) => x.classList.toggle('ativa', x.dataset.janela === estado.janela));
  carregarStatus();
  await carregarResumo();
  if (estado.item && estado.ultimoItem?.nome !== estado.item) selecionar(estado.item);
  mostrarAba(estado.aba);
  setInterval(carregarStatus, 60_000); // o selo de status (e o aviso de painel desligado) a cada minuto
  setInterval(async () => { // a cada 5 min, acompanha o coletor
    carregarStatus();
    await carregarResumo();
    if (estado.item && estado.aba === 'mercado') selecionar(estado.item);
    if (estado.aba === 'sinais') carregarSinais();
  }, 5 * 60_000);
}
iniciar();
