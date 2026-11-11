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
    <div class="linha-wrap">
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
    </button>
    <button class="btn-vender" data-vender="${esc(i.nome)}" title="Vender: quanto pedir, em qual moeda e quando">vender</button>
    </div>`).join('') || '<div class="vazio">Nada encontrado.</div>';
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
  $('#det-vender').classList.remove('hidden');
  const desde = s.primeira ? fDiaHora.format(s.primeira) : '—';
  $('#detalhe').innerHTML = `
    <div class="tiles">
      <div class="tile"><div class="rot">Mediana</div><div class="val">${htmlPreco(s.mediana, moeda)}</div><div class="det">p10 ${fmtNum(s.p10, moeda)} · p90 ${fmtNum(s.p90, moeda)}</div></div>
      <div class="tile"><div class="rot">Média (por unidade)</div><div class="val">${htmlPreco(s.media, moeda)}</div><div class="det">${moeda === 'gems' && s.media ? usd(s.media) + ' bruto' : '&nbsp;'}</div></div>
      <div class="tile"><div class="rot">Mín · Máx</div><div class="val" style="font-size:16px">${fmtNum(s.min, moeda)} · ${fmtNum(s.max, moeda)}</div><div class="det">${s.suspeitas ? `${s.suspeitas} venda(s) suspeita(s) fora da conta` : 'nenhuma venda suspeita'}</div></div>
      <div class="tile"><div class="rot">Vendas · unidades</div><div class="val">${nf(0).format(s.vendas)} · ${nf(0).format(s.unidades)}</div><div class="det">desde ${desde}</div></div>
      <div class="tile"><div class="rot">Menor anúncio agora</div><div class="val">${htmlPreco(v.min, moeda)}</div><div class="det">${v.anuncios != null ? `${nf(0).format(v.anuncios)} anúncios · ${nf(0).format(v.unidades)} un.` : 'sem dado da vitrine'}</div></div>
      <div class="tile"><div class="rot">Média 7d (jogo)</div><div class="val">${htmlPreco(v.media7, moeda)}</div><div class="det">calculada pelo próprio jogo</div></div>
    </div>
    <div class="grafico-box" tabindex="0" aria-label="Gráfico de preço: setas andam de ponto em ponto, Esc solta ou volta o zoom">
      <div class="barra-grafico">
        <div class="legenda" id="g-legenda"></div>
        <div class="zoom" id="g-zoom"></div>
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
// Leitura do gráfico de preço (e do de volume, que divide o eixo do tempo com ele):
//  - arrastar faz zoom no trecho; o servidor manda baldes mais finos (até 5 min) e o resumo do trecho;
//  - clicar fixa o ponto (o tooltip fica parado nele); ← → andam de ponto em ponto; Esc solta;
//  - a legenda liga e desliga cada série, e a escala de preço se ajusta só ao que está visível.
const graf = {
  chave: '',      // item|moeda|janela: trocar qualquer um zera o zoom
  pilha: [],      // zooms empilhados: {de, ate, passo, serie, anuncios, resumo, carregando}
  fixo: null,     // t (início do balde) do ponto fixado
  ocultas: new Set(), // séries escondidas pela legenda (lembradas no localStorage)
  v: null,        // a vista desenhada agora (escalas e pontos), usada pelos eventos
};

function passoBonito(bruto) {
  const p = 10 ** Math.floor(Math.log10(bruto));
  const f = bruto / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

// Marcas do eixo do tempo em horas redondas de Brasília (00:00, 06:00…), nunca em horários quebrados.
const DESLOC_BRT = -3 * 3600_000;
function marcasTempo(x0, x1, maxMarcas) {
  const H = 3600_000, D = 24 * H;
  const passos = [15 * 60_000, 30 * 60_000, H, 2 * H, 3 * H, 6 * H, 12 * H, D, 2 * D, 7 * D, 14 * D, 30 * D];
  const passo = passos.find((p) => (x1 - x0) / p <= maxMarcas) || passos[passos.length - 1];
  const out = [];
  for (let t = Math.ceil((x0 + DESLOC_BRT) / passo) * passo - DESLOC_BRT; t <= x1; t += passo) {
    const meiaNoite = (t + DESLOC_BRT) % D === 0;
    out.push({ t, forte: meiaNoite, txt: passo >= D || meiaNoite ? fDia.format(t) : fHora.format(t) });
  }
  return out;
}

function vistaGrafico(d) {
  const z = graf.pilha[graf.pilha.length - 1];
  if (z) return { x0: z.de, x1: z.ate, serie: z.serie, anun: z.anuncios.filter((a) => a.min != null), passo: z.passo, zoom: z };
  return { x0: d.inicio, x1: d.agora, serie: d.serie, anun: d.anuncios.filter((a) => a.min != null), passo: d.passo, zoom: null };
}

function desenharGraficos(d) {
  const chave = `${d.nome}|${d.moeda}|${d.janela}`;
  if (graf.chave !== chave) { graf.chave = chave; graf.pilha = []; graf.fixo = null; }
  const gp = $('#g-preco'), gv = $('#g-vol');
  if (!gp) return;
  const W = Math.max(320, gp.clientWidth);
  const H = 270, HV = 70;
  const m = { l: 62, r: 84, t: 10, b: 24 };
  const { x0, x1, serie, anun, passo, zoom } = vistaGrafico(d);
  const moeda = d.moeda;
  const ver = (k) => !graf.ocultas.has(k);
  desenharBarraGrafico(d, zoom, passo);
  if (!serie.length && !anun.length) {
    gp.innerHTML = `<div class="vazio">${zoom ? 'Sem vendas neste trecho. Volte o zoom.' : 'Sem vendas nesta janela. Tente uma janela maior.'}</div>`;
    gv.innerHTML = ''; $('#g-aviso').textContent = '';
    graf.v = null;
    return;
  }
  const pw = W - m.l - m.r;
  const X = (t) => m.l + ((Math.min(Math.max(t, x0), x1) - x0) / (x1 - x0)) * pw;
  const centro = (s) => X((Math.max(s.t, x0) + Math.min(s.fim, x1)) / 2);

  // A escala só olha o que está ligado: esconder a faixa mín–máx "abre" a mediana.
  let vals = [];
  if (ver('faixa')) vals = vals.concat(serie.flatMap((s) => [s.min, s.max]));
  if (ver('mediana') || !ver('faixa')) vals = vals.concat(serie.map((s) => s.mediana));
  if (ver('anuncio')) vals = vals.concat(anun.map((a) => a.min));
  if (!vals.length) vals = serie.map((s) => s.mediana).concat(anun.map((a) => a.min));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo *= 0.9; hi = hi * 1.1 || 1; }
  const passoY = passoBonito((hi - lo) / 5);
  lo = Math.max(0, Math.floor(lo / passoY) * passoY);
  hi = Math.ceil(hi / passoY) * passoY;
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);

  // Grade: horizontais em valores redondos, verticais nas marcas do tempo (meia-noite mais forte).
  let svg = '';
  for (let v = lo; v <= hi + passoY / 2; v += passoY) {
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grade)" stroke-width="1"/>`;
    svg += `<text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${fmtNum(v, moeda)}</text>`;
  }
  const marcas = marcasTempo(x0, x1, Math.max(3, Math.floor(pw / 80)));
  let gradeV = '';
  for (const mk of marcas) {
    const x = X(mk.t);
    gradeV += `<line x1="${x}" x2="${x}" y1="${m.t}" y2="${H - m.b}" stroke="var(--grade)" stroke-width="1" ${mk.forte ? '' : 'stroke-dasharray="2 4"'}/>`;
    const anc = x - m.l < 20 ? 'start' : W - m.r - x < 20 ? 'end' : 'middle';
    svg += `<text x="${x}" y="${H - 6}" text-anchor="${anc}" ${mk.forte ? 'class="forte"' : ''}>${mk.txt}</text>`;
  }
  svg = gradeV + svg;

  // Trechos contínuos: mais de 3 h sem venda (ou um balde vazio, nos baldes grandes) quebra a linha
  // em vez de inventar o meio. Abaixo disso a linha liga os pontos e as barras de volume mostram o vazio.
  const trechos = [];
  const buraco = Math.max(passo * 1.5, 3 * 3600_000);
  serie.forEach((s, i) => {
    if (!i || s.t - serie[i - 1].t > buraco) trechos.push([]);
    trechos[trechos.length - 1].push(s);
  });
  for (const tr of trechos) {
    if (tr.length === 1) {
      const s = tr[0];
      if (ver('faixa')) svg += `<rect x="${centro(s) - 4}" y="${Y(s.max)}" width="8" height="${Math.max(2, Y(s.min) - Y(s.max))}" fill="var(--serie-1)" opacity=".3"/>`;
    } else {
      const topo = tr.map((s) => `${centro(s)},${Y(s.max)}`).join(' ');
      const base = [...tr].reverse().map((s) => `${centro(s)},${Y(s.min)}`).join(' ');
      if (ver('faixa')) svg += `<polygon points="${topo} ${base}" fill="var(--serie-1)" opacity=".18"/>`;
      if (ver('mediana')) svg += `<path d="M${tr.map((s) => `${centro(s)} ${Y(s.mediana)}`).join(' L')}" fill="none" stroke="var(--serie-1)" stroke-width="2" stroke-linejoin="round" shape-rendering="geometricPrecision"/>`;
    }
  }
  // Bolinhas só quando cabem (pelo menos ~10 px entre pontos) ou quando o ponto está sozinho.
  const cabem = serie.length <= pw / 10;
  if (ver('mediana')) {
    serie.forEach((s, i) => {
      const sozinho = trechos.some((tr) => tr.length === 1 && tr[0] === s);
      if (cabem || sozinho) svg += `<circle cx="${centro(s)}" cy="${Y(s.mediana)}" r="${cabem ? 3.5 : 3}" fill="var(--serie-1)" stroke="var(--linha)" stroke-width="2" shape-rendering="geometricPrecision"/>`;
    });
  }

  // Menor anúncio (fotos da vitrine; buraco > 2 h quebra a linha).
  if (ver('anuncio')) {
    const trA = [];
    anun.forEach((a, i) => {
      if (!i || a.t - anun[i - 1].t > 2 * 3600_000) trA.push([]);
      trA[trA.length - 1].push(a);
    });
    for (const tr of trA) {
      if (tr.length > 1) svg += `<path d="M${tr.map((a) => `${X(a.t)} ${Y(a.min)}`).join(' L')}" fill="none" stroke="var(--serie-2)" stroke-width="2" stroke-linejoin="round" shape-rendering="geometricPrecision"/>`;
      else svg += `<circle cx="${X(tr[0].t)}" cy="${Y(tr[0].min)}" r="3" fill="var(--serie-2)" stroke="var(--linha)" stroke-width="2" shape-rendering="geometricPrecision"/>`;
    }
    if (anun.length <= pw / 10) anun.forEach((a) => { svg += `<circle cx="${X(a.t)}" cy="${Y(a.min)}" r="3.5" fill="var(--serie-2)" stroke="var(--linha)" stroke-width="2" shape-rendering="geometricPrecision"/>`; });
  }

  // Rótulos diretos só no fim de cada série (o resto fica no tooltip).
  const rots = [];
  if (serie.length && ver('mediana')) rots.push({ y: Y(serie[serie.length - 1].mediana), cor: 'var(--serie-1)', txt: fmtNum(serie[serie.length - 1].mediana, moeda) });
  if (anun.length && ver('anuncio')) rots.push({ y: Y(anun[anun.length - 1].min), cor: 'var(--serie-2)', txt: fmtNum(anun[anun.length - 1].min, moeda) });
  if (rots.length === 2 && Math.abs(rots[0].y - rots[1].y) < 18) {
    const meio = (rots[0].y + rots[1].y) / 2, cima = rots[0].y <= rots[1].y ? 0 : 1;
    rots[cima].y = meio - 9; rots[1 - cima].y = meio + 9;
  }
  rots.forEach((r) => {
    svg += `<rect x="${W - m.r + 8}" y="${r.y - 4}" width="8" height="8" fill="${r.cor}"/>`;
    svg += `<text class="rotulo-dir" x="${W - m.r + 20}" y="${r.y + 5}">${r.txt}</text>`;
  });

  // Mira: linha vertical e horizontal, anéis nos dois pontos e as etiquetas nos eixos.
  svg += `<g id="mira-g" visibility="hidden">
    <line id="mira" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--tinta-3)" stroke-width="1"/>
    <line id="mira-h" x1="${m.l}" x2="${W - m.r}" y1="0" y2="0" stroke="var(--tinta-3)" stroke-width="1" stroke-dasharray="3 3"/>
    <circle id="mira-p" r="6" fill="none" stroke="var(--tinta)" stroke-width="2" shape-rendering="geometricPrecision"/>
    <circle id="mira-a" r="6" fill="none" stroke="var(--serie-2)" stroke-width="2" shape-rendering="geometricPrecision"/>
    <g id="mira-ey"><rect x="2" y="-9" width="${m.l - 6}" height="18" rx="3" fill="var(--tinta)"/><text class="etq" x="${m.l - 8}" y="4" text-anchor="end"></text></g>
    <g id="mira-ex"><rect x="-44" y="${H - m.b + 2}" width="88" height="18" rx="3" fill="var(--tinta)"/><text class="etq" x="0" y="${H - 7}" text-anchor="middle"></text></g>
  </g>`;
  svg += `<rect id="g-sel" y="${m.t}" height="${H - m.t - m.b}" fill="var(--tinta)" opacity=".12" visibility="hidden"/>`;
  svg += `<rect class="alvo" x="${m.l}" y="0" width="${pw}" height="${H}" fill="transparent"/>`;
  gp.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Preço de ${esc(d.nome)} ao longo do tempo">${svg}</svg>`;

  // Volume: gráfico separado (nunca dois eixos no mesmo gráfico).
  const maxU = Math.max(1, ...serie.map((s) => s.unidades));
  let sv = `<line x1="${m.l}" x2="${W - m.r}" y1="${HV - 2}" y2="${HV - 2}" stroke="var(--grade)"/>`;
  sv += `<text x="${m.l - 8}" y="14" text-anchor="end">${nf(0).format(maxU)}</text><text x="${m.l - 8}" y="${HV - 2}" text-anchor="end">0</text>`;
  for (const mk of marcas) sv += `<line x1="${X(mk.t)}" x2="${X(mk.t)}" y1="4" y2="${HV - 2}" stroke="var(--grade)" ${mk.forte ? '' : 'stroke-dasharray="2 4"'}/>`;
  serie.forEach((s, i) => {
    const xa = X(s.t) + 1, xb = X(Math.min(s.fim, x1)) - 1;
    const h = (s.unidades / maxU) * (HV - 8);
    sv += `<rect data-i="${i}" x="${xa}" y="${HV - 2 - h}" width="${Math.max(2, xb - xa)}" height="${Math.max(1, h)}" fill="var(--serie-1)"/>`;
  });
  sv += `<line id="mira-v" x1="0" x2="0" y1="0" y2="${HV}" stroke="var(--tinta-3)" visibility="hidden"/>`;
  sv += `<rect id="g-sel-v" y="0" height="${HV}" fill="var(--tinta)" opacity=".12" visibility="hidden"/>`;
  sv += `<rect class="alvo" x="${m.l}" y="0" width="${pw}" height="${HV}" fill="transparent"/>`;
  gv.innerHTML = `<svg viewBox="0 0 ${W} ${HV}" height="${HV}" role="img" aria-label="Unidades vendidas por período">${sv}</svg>`;

  const buracos = trechos.length - 1;
  $('#g-aviso').textContent = `Cada ponto = ${rotPasso(passo)}.` + (buracos > 0 ? ` A linha se interrompe onde ficou muito tempo sem venda (${buracos} intervalo(s)).` : '')
    + (zoom?.carregando ? ' Carregando o trecho em detalhe…' : '');

  graf.v = { d, W, H, m, pw, x0, x1, serie, anun, passo, X, Y, centro, moeda };
  ligarGrafico();
  if (graf.fixo != null) {
    const i = serie.findIndex((s) => s.t === graf.fixo);
    if (i >= 0) mostrarPonto(i, null); else graf.fixo = null;
  }
}

// Barra acima do gráfico: a legenda (que liga e desliga séries) e os botões de zoom.
function desenharBarraGrafico(d, zoom, passo) {
  const sw = [
    ['mediana', '<span class="sw" style="background:var(--serie-1)"></span>Mediana das vendas'],
    ['faixa', '<span class="sw band" style="background:var(--serie-1)"></span>Faixa mín–máx'],
    ['anuncio', '<span class="sw" style="background:var(--serie-2)"></span>Menor anúncio'],
  ];
  $('#g-legenda').innerHTML = sw.map(([k, h]) =>
    `<button class="leg ${graf.ocultas.has(k) ? 'off' : ''}" data-serie="${k}" aria-pressed="${!graf.ocultas.has(k)}" title="mostrar ou esconder">${h}</button>`).join('');
  const z = $('#g-zoom');
  if (!zoom) {
    z.innerHTML = '<span class="dica">arraste para dar zoom · clique fixa o ponto · ← → andam</span>';
    return;
  }
  const r = zoom.resumo;
  const quando = `${fDiaHora.format(zoom.de)} → ${fDiaHora.format(zoom.ate)}`;
  const res = r ? ` · mediana <b>${fmtNum(r.mediana, d.moeda)}</b> · ${nf(0).format(r.vendas)} vendas · ${nf(0).format(r.unidades)} un.` : '';
  z.innerHTML = `<span class="zoom-info">${quando}${res}</span>
    <button class="chip" data-zoom="voltar" title="voltar ao zoom anterior">− zoom</button>
    <button class="chip" data-zoom="tudo" title="ver a janela inteira">janela toda</button>`;
}

// Liga os eventos dos dois gráficos (o SVG é refeito a cada desenho, então religa sempre).
function ligarGrafico() {
  const v = graf.v;
  const tParaX = (ev) => {
    const r = ev.currentTarget.ownerSVGElement.getBoundingClientRect();
    return ((ev.clientX - r.left) / r.width) * v.W;
  };
  const xParaT = (x) => v.x0 + ((Math.min(Math.max(x, v.m.l), v.m.l + v.pw) - v.m.l) / v.pw) * (v.x1 - v.x0);
  let arrasto = null;
  const sel = (a, b) => {
    for (const id of ['#g-sel', '#g-sel-v']) {
      const el = $(id);
      if (a == null) { el.setAttribute('visibility', 'hidden'); continue; }
      const xa = Math.max(v.m.l, Math.min(a, b)), xb = Math.min(v.m.l + v.pw, Math.max(a, b));
      el.setAttribute('x', xa); el.setAttribute('width', Math.max(0, xb - xa)); el.setAttribute('visibility', 'visible');
    }
  };
  $$('.grafico .alvo').forEach((el) => {
    el.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      el.setPointerCapture(ev.pointerId);
      arrasto = { x: tParaX(ev), andou: false };
    });
    el.addEventListener('pointermove', (ev) => {
      const x = tParaX(ev);
      if (arrasto) {
        if (Math.abs(x - arrasto.x) > 5) arrasto.andou = true;
        if (arrasto.andou) { sel(arrasto.x, x); esconderMira(); return; }
      }
      if (graf.fixo == null) mostrarPonto(pontoMaisPerto(xParaT(x)), ev, xParaT(x));
    });
    el.addEventListener('pointerup', (ev) => {
      if (!arrasto) return;
      const x = tParaX(ev), a = arrasto;
      arrasto = null;
      sel(null);
      if (a.andou && Math.abs(x - a.x) > 8) { darZoom(xParaT(Math.min(a.x, x)), xParaT(Math.max(a.x, x))); return; }
      // Clique: fixa o ponto (ou solta, se for o mesmo).
      const i = pontoMaisPerto(xParaT(x));
      if (i == null) return;
      if (graf.fixo === v.serie[i].t) { graf.fixo = null; mostrarPonto(i, ev); } else { graf.fixo = v.serie[i].t; mostrarPonto(i, null); }
    });
    el.addEventListener('pointercancel', () => { arrasto = null; sel(null); });
    el.addEventListener('mouseleave', () => { if (graf.fixo == null && !arrasto) esconderMira(); });
  });
}

function pontoMaisPerto(t) {
  const v = graf.v;
  let i = null, dist = Infinity;
  v.serie.forEach((b, k) => { const dd = Math.abs((Math.max(b.t, v.x0) + Math.min(b.fim, v.x1)) / 2 - t); if (dd < dist) { dist = dd; i = k; } });
  return i != null && dist <= v.passo * 1.5 ? i : null;
}

function esconderMira() {
  $('#tooltip').classList.add('hidden');
  $('#mira-g')?.setAttribute('visibility', 'hidden');
  $('#mira-v')?.setAttribute('visibility', 'hidden');
  $$('#g-vol rect.ativo').forEach((r) => r.classList.remove('ativo'));
}

// Mostra o balde i (ou só o anúncio mais perto de t, se não há venda ali).
// ev = evento do mouse (o tooltip segue o cursor); null = ponto fixado (o tooltip fica no ponto).
function mostrarPonto(i, ev, t) {
  const v = graf.v, moeda = v.moeda;
  const s = i != null ? v.serie[i] : null;
  const tRef = s ? (s.t + s.fim) / 2 : t;
  if (tRef == null) return esconderMira();
  let a = null, da = Infinity;
  for (const x of v.anun) { const dd = Math.abs(x.t - tRef); if (dd < da) { da = dd; a = x; } }
  if (a && da > Math.max(90 * 60_000, v.passo)) a = null;
  if (!s && !a) {
    if (ev) { esconderMira(); }
    return;
  }
  const xm = s ? v.centro(s) : v.X(a.t);
  const ym = s ? v.Y(s.mediana) : v.Y(a.min);
  $('#mira-g').setAttribute('visibility', 'visible');
  for (const id of ['#mira', '#mira-v']) { const el = $(id); el.setAttribute('x1', xm); el.setAttribute('x2', xm); el.setAttribute('visibility', 'visible'); }
  const mh = $('#mira-h'); mh.setAttribute('y1', ym); mh.setAttribute('y2', ym);
  const p = $('#mira-p'), pa = $('#mira-a');
  p.setAttribute('visibility', s ? 'inherit' : 'hidden');
  if (s) { p.setAttribute('cx', xm); p.setAttribute('cy', ym); }
  pa.setAttribute('visibility', a && !graf.ocultas.has('anuncio') ? 'inherit' : 'hidden');
  if (a) { pa.setAttribute('cx', v.X(a.t)); pa.setAttribute('cy', v.Y(a.min)); }
  const ey = $('#mira-ey'); ey.setAttribute('transform', `translate(0 ${ym})`);
  ey.querySelector('text').textContent = fmtNum(s ? s.mediana : a.min, moeda);
  const ex = $('#mira-ex');
  const xe = Math.min(Math.max(xm, v.m.l + 44), v.W - v.m.r + 40);
  ex.setAttribute('transform', `translate(${xe} 0)`);
  ex.querySelector('text').textContent = fDiaHora.format(s ? s.t : a.t);
  $$('#g-vol rect.ativo').forEach((r) => r.classList.remove('ativo'));
  if (s) $(`#g-vol rect[data-i="${i}"]`)?.classList.add('ativo');

  let h = '';
  if (s) {
    const ant = i > 0 ? v.serie[i - 1] : null;
    const varr = ant && ant.mediana ? (s.mediana / ant.mediana - 1) * 100 : null;
    h += `<div class="t">${fDiaHora.format(s.t)} – ${fHora.format(Math.min(s.fim, v.x1))}${graf.fixo === s.t ? ' <span class="fixo">fixado</span>' : ''}</div>`;
    h += `<div><span class="sw" style="background:var(--serie-1)"></span>mediana <b>${fmtNum(s.mediana, moeda)}</b>`
      + (varr != null && Math.abs(varr) >= 0.05 ? ` <span class="var ${varr > 0 ? 'sobe' : 'desce'}">${varr > 0 ? '▲' : '▼'} ${nf(1).format(Math.abs(varr))}%</span>` : '') + '</div>';
    h += `<div>faixa <b>${fmtNum(s.min, moeda)} – ${fmtNum(s.max, moeda)}</b></div>`;
    h += `<div>${nf(0).format(s.vendas)} vendas · ${nf(0).format(s.unidades)} un.</div>`;
  } else h += `<div class="t">${fDiaHora.format(a.t)}</div><div>sem vendas aqui</div>`;
  if (a) {
    const dif = s && s.mediana ? (a.min / s.mediana - 1) * 100 : null;
    h += `<div><span class="sw" style="background:var(--serie-2)"></span>menor anúncio <b>${fmtNum(a.min, moeda)}</b>`
      + (dif != null ? ` (${dif >= 0 ? '+' : '−'}${nf(0).format(Math.abs(dif))}% da mediana)` : '') + '</div>';
    h += `<div class="sub">foto das ${fHora.format(a.t)}, ${nf(0).format(a.anuncios)} anúncios</div>`;
  }
  if (graf.fixo == null && s) h += '<div class="sub">clique para fixar</div>';
  const tip = $('#tooltip');
  tip.innerHTML = h;
  tip.classList.remove('hidden');
  let cx, cy;
  if (ev) { cx = ev.clientX; cy = ev.clientY; } else {
    const r = $('#g-preco svg').getBoundingClientRect();
    cx = r.left + (xm / v.W) * r.width; cy = r.top + (ym / v.H) * r.height;
  }
  // O tooltip vai para o lado com mais espaço, para não cobrir o ponto.
  // Ponto fixado: acima do ponto, quando cabe, para não cobrir o eixo do tempo.
  let tx = cx + 16;
  if (tx + tip.offsetWidth > innerWidth - 8) tx = cx - 16 - tip.offsetWidth;
  let ty = !ev && cy - tip.offsetHeight - 16 > 8 ? cy - tip.offsetHeight - 16 : cy + 16;
  ty = Math.min(Math.max(8, ty), innerHeight - tip.offsetHeight - 8);
  tip.style.left = Math.max(8, tx) + 'px'; tip.style.top = ty + 'px';
}

async function darZoom(de, ate) {
  const d = estado.ultimoItem;
  if (!d) return;
  const MIN = 3600_000;
  if (ate - de < MIN) { const c = (de + ate) / 2; de = c - MIN / 2; ate = c + MIN / 2; }
  ate = Math.min(ate, d.agora); de = Math.max(de, d.inicio);
  if (ate - de < MIN) de = ate - MIN;
  de = Math.round(de); ate = Math.round(ate);
  // Desenha já com os pontos que temos; o servidor manda os baldes finos logo em seguida.
  const atual = vistaGrafico(d);
  const z = {
    de, ate, passo: atual.passo, carregando: true, resumo: null,
    serie: atual.serie.filter((s) => s.fim > de && s.t < ate),
    anuncios: atual.anun.filter((a) => a.t >= de && a.t <= ate),
  };
  graf.pilha.push(z);
  graf.fixo = null;
  esconderMira();
  desenharGraficos(d);
  try {
    const r = await api('/api/item/serie', { nome: d.nome, moeda: d.moeda, janela: d.janela, de, ate });
    Object.assign(z, { passo: r.passo, serie: r.serie, anuncios: r.anuncios, resumo: r.resumo, carregando: false });
  } catch (e) {
    z.carregando = false;
  }
  if (estado.ultimoItem === d && graf.pilha[graf.pilha.length - 1] === z) desenharGraficos(d);
}

function voltarZoom(tudo) {
  if (!graf.pilha.length || !estado.ultimoItem) return;
  if (tudo) graf.pilha = []; else graf.pilha.pop();
  graf.fixo = null;
  esconderMira();
  desenharGraficos(estado.ultimoItem);
}

// Eventos que não dependem do SVG (ligados uma vez, por delegação no #detalhe).
function ligarControlesGrafico() {
  lerLocal('graf_ocultas').split(',').filter((k) => ['mediana', 'faixa', 'anuncio'].includes(k)).forEach((k) => graf.ocultas.add(k));
  if (graf.ocultas.size === 3) graf.ocultas.clear();
  $('#detalhe').addEventListener('click', (e) => {
    const leg = e.target.closest('[data-serie]');
    if (leg) {
      const k = leg.dataset.serie;
      if (graf.ocultas.has(k)) graf.ocultas.delete(k); else graf.ocultas.add(k);
      if (graf.ocultas.size === 3) graf.ocultas.delete(k); // pelo menos uma série fica
      gravarLocal('graf_ocultas', [...graf.ocultas].join(','));
      if (estado.ultimoItem) desenharGraficos(estado.ultimoItem);
      return;
    }
    const z = e.target.closest('[data-zoom]');
    if (z) voltarZoom(z.dataset.zoom === 'tudo');
  });
  $('#detalhe').addEventListener('dblclick', (e) => { if (e.target.closest('.grafico')) voltarZoom(false); });
  $('#detalhe').addEventListener('keydown', (e) => {
    if (!e.target.closest('.grafico-box') || !graf.v) return;
    const v = graf.v, n = v.serie.length;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (!n) return;
      e.preventDefault();
      let i = v.serie.findIndex((s) => s.t === graf.fixo);
      if (i < 0) i = e.key === 'ArrowLeft' ? n : -1;
      i = Math.min(n - 1, Math.max(0, i + (e.key === 'ArrowLeft' ? -1 : 1)));
      graf.fixo = v.serie[i].t;
      mostrarPonto(i, null);
    } else if (e.key === 'Escape') {
      if (graf.fixo != null) { graf.fixo = null; esconderMira(); } else voltarZoom(false);
    } else if (e.key === '-' || e.key === 'Backspace') {
      e.preventDefault(); voltarZoom(false);
    }
  });
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
              <td><span class="rar-tag ${classeRaridade(l.nome)}"><span class="ico">${img(l.icone)}</span>${l.raridade}</span></td>
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

// ------------------------------------------------------------------ vender (o que dropou)
const venda = { nome: null, qtd: 1, moeda: null, d: null };
const COR_ACAO = { agora: 'sobe', esperar: 'ouro', segurar: 'ouro', misto: 'neutro', tanto_faz: 'neutro', sem_dados: 'apagado' };
const LINHA_INDICADA = { agora: 'rapido', esperar: 'normal', segurar: 'paciente', misto: 'normal', tanto_faz: 'normal', sem_dados: 'normal' };
const NOME_OPCAO = { rapido: 'Rápido', normal: 'Normal', paciente: 'Paciente' };

function tempoEspera(min) {
  if (min == null) return '';
  if (min < 1) return 'menos de 1 min';
  if (min < 90) return `~${nf(0).format(min)} min`;
  if (min < 48 * 60) return `~${nf(0).format(min / 60)} h`;
  return `~${nf(0).format(min / 1440)} dias`;
}

async function abrirVenda(nome) {
  venda.nome = nome;
  venda.moeda = null;
  venda.d = null;
  const r = (estado.resumo?.itens || []).find((i) => i.nome === nome);
  $('#venda-ico').innerHTML = img(r?.icone);
  $('#venda-nome').textContent = nome;
  $('#venda-qtd').value = venda.qtd = 1;
  $('#venda-corpo').innerHTML = '<div class="vazio">Analisando as vendas…</div>';
  $('#venda-fundo').classList.remove('hidden');
  $('#venda-qtd').focus();
  $('#venda-qtd').select();
  try {
    const d = await api('/api/venda', { nome });
    if (venda.nome !== nome) return; // outro item já foi aberto
    venda.d = d;
    venda.moeda = d.escolha.moeda || 'gems';
    $('#venda-ico').innerHTML = img(d.icone);
    desenharVenda();
  } catch (e) {
    if (venda.nome === nome) $('#venda-corpo').innerHTML = `<div class="vazio">Não deu para analisar: ${esc(e.message)}</div>`;
  }
}

function fecharVenda() {
  $('#venda-fundo').classList.add('hidden');
  venda.nome = null;
}

function desenharVenda() {
  const d = venda.d;
  if (!d) return;
  const m = venda.moeda, a = d[m], q = venda.qtd, e = d.escolha;
  const nomeMoeda = (mo) => (mo === 'gems' ? 'gemas' : 'coins');
  const abas = ['gems', 'coins'].map((mo) => `<button class="chip ${mo === m ? 'ativa' : ''}" data-vmoeda="${mo}" ${d[mo].tem_mercado ? '' : 'disabled'}>
      <span class="ico">${img(mo === 'gems' ? IMG.gema : IMG.moeda)}</span>${nomeMoeda(mo)}${mo === e.moeda ? ' (indicada)' : ''}</button>`).join('');

  const veredito = `
    <div class="caixa venda-moeda">
      <h3>Em qual moeda</h3>
      <div class="venda-grande">${e.moeda ? `Venda em ${nomeMoeda(e.moeda)}` : 'Sem mercado'}</div>
      <p>${esc(e.motivo)}</p>
      ${e.coins_em_gemas != null && d.cambio.coins_por_gema ? `<p class="aviso">1 unidade vendida em coins vale ~${nf(2).format(e.coins_em_gemas)} gemas depois da troca. Câmbio: ${fmtNum(d.cambio.coins_por_gema, 'coins')} coins por gema, medido em ${d.cambio.itens} itens vendidos nas duas moedas.</p>` : ''}
      <div class="venda-abas">${abas}</div>
    </div>`;

  if (!a || !a.tem_mercado) {
    $('#venda-corpo').innerHTML = `<div class="venda-topo">${veredito}</div><div class="vazio">Sem vendas nem anúncios deste item em ${nomeMoeda(m)}.</div>`;
    return;
  }

  const qd = a.quando;
  const quando = `
    <div class="caixa venda-quando ${COR_ACAO[qd.acao] || 'neutro'}">
      <h3>Quando vender <span class="tag" title="Baixa: menos de 3 dias de coleta ou poucas vendas. Média: menos de 7 dias.">confiança ${esc(a.confianca)}</span></h3>
      <div class="venda-grande">${esc(qd.titulo)}</div>
      <ul>${qd.motivos.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
      ${qd.alvo ? `<button class="chip" id="venda-alerta" data-alvo="${Math.round(qd.alvo)}">me avise quando a mediana 24h chegar a ${fmtNum(qd.alvo, m)}</button> <span class="aviso" id="venda-alerta-res"></span>` : ''}
    </div>`;

  // Linhas de preço; preços iguais viram uma linha só ("Rápido / Normal").
  const linhas = [];
  for (const k of ['rapido', 'normal', 'paciente']) {
    const o = a.opcoes[k];
    if (!o) continue;
    const ult = linhas[linhas.length - 1];
    if (ult && ult.o.preco === o.preco) { ult.chaves.push(k); continue; }
    linhas.push({ chaves: [k], o });
  }
  const indicada = LINHA_INDICADA[qd.acao] || 'normal';
  const espera = a.unidades_dia > 0 ? tempoEspera(q / a.unidades_dia * 1440) : '';
  const descr = (ks) => {
    if (ks.includes('rapido')) return `1 abaixo do menor anúncio: você fica em 1º da fila${espera ? ` e sai em ${espera} pelo ritmo de compras` : ''}`;
    if (ks.includes('normal')) return a.fino ? 'pela média de 7 dias do jogo: quase não há vendas para comparar' : 'o preço das vendas das últimas horas';
    return 'acima da maioria das vendas: espera um comprador que pague mais';
  };
  const tabela = `
    <div class="caixa">
      <h3>Por quanto anunciar ${q > 1 ? `(${nf(0).format(q)} unidades)` : ''}</h3>
      <div class="tabela-wrap" style="max-height:none"><table class="tabela venda-precos">
        <tr><th></th><th class="num">Anunciar a</th><th class="num">Você recebe</th>${m === 'gems' ? '<th class="num">Em dólar</th>' : ''}<th class="num" title="Das vendas das últimas 48 h, quantas saíram a esse preço ou mais">Vendas 48h ≥</th></tr>
        ${linhas.map(({ chaves, o }) => `
          <tr class="${chaves.includes(indicada) ? 'indicada' : ''}">
            <td><b>${chaves.map((k) => NOME_OPCAO[k]).join(' / ')}</b>${chaves.includes(indicada) ? ' <span class="tag">indicado</span>' : ''}<div class="aviso" style="padding:0">${descr(chaves)}</div></td>
            <td class="num">${htmlPreco(o.preco, m)}</td>
            <td class="num">${htmlPreco(o.liquido_un * q, m)}</td>
            ${m === 'gems' ? `<td class="num">${usd(o.liquido_un * q)}</td>` : ''}
            <td class="num">${o.vendas_acima != null ? o.vendas_acima + '%' : '—'}</td>
          </tr>`).join('')}
      </table></div>
      <p class="aviso">Já com a taxa de ${Math.round(d.taxa * 100)}% do mercado${m === 'gems' ? ' (em gemas o jogo arredonda a taxa para cima)' : ''}.</p>
      ${a.anuncio_muito_baixo ? `<p class="aviso">O menor anúncio (${fmtNum(a.anuncio_min, m)}) está muito abaixo do preço de referência. Parece outro mercado, como lotes vendidos baratos por unidade. Ficar em 1º da fila seria dar o item, então o preço rápido ficou de fora. O normal só sai se aparecer um comprador disposto a pagar esse preço.</p>` : ''}
    </div>`;

  const mh = a.melhor_hora;
  const contexto = `
    <div class="tiles venda-tiles">
      <div class="tile"><div class="rot">Menor anúncio agora</div><div class="val">${htmlPreco(a.anuncio_min, m)}</div><div class="det">${d.anuncios != null ? nf(0).format(d.anuncios) + ' anúncios' : '&nbsp;'}</div></div>
      <div class="tile"><div class="rot">Média 7d do jogo</div><div class="val">${htmlPreco(a.media7_jogo, m)}</div><div class="det">${a.vs_media7_jogo != null ? `últimas vendas ${htmlVar(a.vs_media7_jogo)}` : '&nbsp;'}</div></div>
      <div class="tile"><div class="rot">Vendas por dia</div><div class="val">${nf(a.vendas_dia < 10 ? 1 : 0).format(a.vendas_dia)}</div><div class="det">${nf(0).format(a.unidades_dia)} unidades/dia</div></div>
      <div class="tile"><div class="rot">Estoque à venda</div><div class="val">${d.estoque_dias != null ? nf(1).format(d.estoque_dias) + ' d' : '—'}</div><div class="det">${d.estoque_unidades != null ? nf(0).format(d.estoque_unidades) + ' un. ÷ ritmo de compra' : '&nbsp;'}</div></div>
      <div class="tile"><div class="rot">Mais compras</div><div class="val">${mh ? `${mh.inicio}h–${mh.fim}h` : '—'}</div><div class="det">${mh ? `${mh.parte}% das unidades` : 'com 3+ dias de coleta'}</div></div>
    </div>`;

  const mt = d.montagem;
  const montagem = mt && m === 'gems' && mt.vantagem != null ? `
    <div class="caixa">
      <h3>Ou juntar 10 e montar</h3>
      <p>Montar ${mt.sufixo === 'House' ? 'uma casa' : 'uma bicicleta'} com 10 fragmentos ${mt.vantagem >= 0 ? 'rende' : 'perde'} <b>${nf(1).format(Math.abs(mt.vantagem))}%</b> em média, contra vender os 10 pelo preço normal (${htmlPreco(mt.dez_fragmentos, 'gems')} líquido).
        Sem contar Mítica e Lendária: ${htmlVar(mt.vantagem_sem_raras)}.${mt.vantagem > 0 && mt.vantagem_sem_raras < 0 ? ' A vantagem depende só das raridades altas.' : ''}</p>
      ${mt.sem_preco.length ? `<p class="aviso">Sem preço, contam como zero: ${esc(mt.sem_preco.join(', '))}.</p>` : ''}
      <button class="chip" id="venda-montagem">ver a aba Montagem</button>
    </div>` : '';

  $('#venda-corpo').innerHTML = `<div class="venda-topo">${veredito}${quando}</div>${tabela}${contexto}${montagem}`;
}

function ligarVenda() {
  $('#det-vender').addEventListener('click', () => estado.item && abrirVenda(estado.item));
  $('#venda-fechar').addEventListener('click', fecharVenda);
  $('#venda-fundo').addEventListener('click', (e) => { if (e.target.id === 'venda-fundo') fecharVenda(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && venda.nome) fecharVenda(); });
  $('#venda-qtd').addEventListener('input', (e) => {
    const v = Math.floor(Number(e.target.value));
    venda.qtd = Number.isFinite(v) && v >= 1 ? v : 1;
    desenharVenda();
  });
  $('#venda-corpo').addEventListener('click', async (e) => {
    const mo = e.target.closest('[data-vmoeda]');
    if (mo) { venda.moeda = mo.dataset.vmoeda; desenharVenda(); return; }
    if (e.target.closest('#venda-montagem')) { fecharVenda(); mostrarAba('montagem'); return; }
    const al = e.target.closest('#venda-alerta');
    if (al) {
      al.disabled = true;
      try {
        await postar('/api/regras', { tipo: 'acima', item: venda.nome, moeda: venda.moeda, valor: Number(al.dataset.alvo) });
        $('#venda-alerta-res').textContent = 'alerta criado (aba Sinais)';
      } catch (err) {
        al.disabled = false;
        $('#venda-alerta-res').textContent = 'não deu: ' + err.message;
      }
    }
  });
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
      || `<tr><td colspan="7" class="vazio" style="padding:20px">Nenhuma revenda com lucro agora: depois dos 15% de taxa, comprar no menor anúncio e revender pela mediana dá prejuízo em todos os itens. Marque "mostrar também as margens negativas" para ver o quanto falta.</td></tr>`}
    ${(() => {
      const fora = d.itens.filter((s) => s.anuncio_fora);
      return fora.length ? `<tr><td colspan="7" class="vazio" style="padding:6px 8px;text-align:left">Fora da conta, com o menor anúncio abaixo de ¼ da referência: ${fora.map((s) => `${esc(s.nome)} (${fmtNum(s.anuncio_min, m)} contra ${fmtNum(s.referencia, m)})`).join(', ')}. Parece outro mercado (lotes vendidos baratos por unidade), não uma pechincha.</td></tr>` : '';
    })()}`;
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

// ------------------------------------------------------------------ PvP (Tracker do jogo)
const NOME_FAIXA = { todas: 'todos os ranks', baixo: 'low elo', alto: 'high elo', bronze: 'Bronze', prata: 'Prata', ouro: 'Ouro',
  platina: 'Platina', diamante: 'Diamante', mestre: 'Mestre+' };
const NOME_TIER = { bronze: 'Bronze', prata: 'Prata', ouro: 'Ouro', platina: 'Platina', diamante: 'Diamante', mestre: 'Mestre',
  graomestre: 'Grão Mestre', challenger: 'Challenger' };
const pct = (v) => (v == null ? '—' : nf(1).format(v * 100) + '%');
const lerLocal = (k) => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
const gravarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento: só não lembra */ } };

async function analisarPvp(e, forcar = false) {
  e?.preventDefault();
  const nick = $('#pvp-nick').value.trim();
  if (!nick) { $('#pvp-nick').reportValidity(); return; }
  gravarLocal('pvp_nick', nick);
  const botoes = document.querySelectorAll('#pvp-form button');
  botoes.forEach((b) => { b.disabled = true; });
  $('#pvp-corpo').innerHTML = `<div class="vazio">${forcar ? 'Lendo de novo o seu perfil e o meta no Tracker…' : 'Lendo o Tracker do jogo… (a primeira vez leva uns 30 s)'}</div>`;
  let d;
  try {
    d = await api('/api/pvp', { nick, faixa: $('#pvp-faixa').value, orcamento: $('#pvp-orc').value, moeda: $('#pvp-moeda').value,
      forcar: forcar ? 1 : '' });
  } catch (err) {
    $('#pvp-corpo').innerHTML = `<div class="vazio">Não deu: ${esc(err.message)}</div>`;
    return;
  } finally {
    botoes.forEach((b) => { b.disabled = false; });
  }
  estado.pvp = d;
  desenharPvp();
}

// "agora", "há 3 min", "há 2 h" a partir de um instante em ms.
function haQuanto(ms) {
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  return min < 1 ? 'agora' : min < 60 ? `há ${min} min` : `há ${Math.round(min / 60)} h`;
}

function desenharPvp() {
  const d = estado.pvp;
  if (!d) return;
  const r = d.rank || {}, t = d.totais || {}, m = d.moeda;
  $('#pvp-sub').textContent = `${d.nick} · temporada ${d.temporada || '—'} · meta de ${NOME_FAIXA[d.faixa] || d.faixa}${d.lido_em ? ` · perfil lido ${haQuanto(d.lido_em)}` : ''}${d.meta_lido_em ? `, meta ${haQuanto(d.meta_lido_em)}` : ''}${d.velho ? ' · dados guardados (o Tracker não respondeu)' : ''}`;
  const tiles = `
    <div class="tiles">
      <div class="tile"><div class="rot">Rank</div><div class="val">${esc(NOME_TIER[r.tierId] || r.tierId || '—')}</div><div class="det">${r.pontos != null ? nf(0).format(r.pontos) + ' PR' : 'sem partidas ranqueadas'}${r.posicao ? ` · #${nf(0).format(r.posicao)}` : ''}</div></div>
      <div class="tile"><div class="rot">Temporada</div><div class="val">${nf(0).format(r.vitorias || 0)}V · ${nf(0).format(r.derrotas || 0)}D</div><div class="det">${pct(r.winrate)} de vitórias</div></div>
      <div class="tile"><div class="rot">Últimas partidas</div><div class="val">${d.vitorias_recentes} de ${d.partidas_recentes}</div><div class="det">vitórias</div></div>
      <div class="tile"><div class="rot">Desde sempre</div><div class="val">${pct(t.partidas ? t.vitorias / t.partidas : null)}</div><div class="det">${nf(0).format(t.partidas || 0)} partidas</div></div>
    </div>`;

  const timeHtml = `
    <div class="caixa"><h3>Seu time agora <span class="aviso">(das últimas 5 partidas)</span></h3>
      <div class="tabela-wrap" style="max-height:none"><table class="tabela">
        <tr><th>Pokémon</th><th class="num">Nível</th><th class="num">Sua taxa</th><th class="num">Partidas</th><th class="num" title="Taxa de vitória da espécie no meta, puxada para 50% quando há poucas partidas">Meta</th></tr>
        ${d.time.map((p) => `<tr><td style="white-space:normal">${esc(p.nome)} ${p.shiny ? '<span class="tag shiny">shiny</span>' : ''}<br>${tagsTipo(p.tipos)}</td>
          <td class="num">${p.nivel != null ? nf(0).format(p.nivel) : '—'}</td><td class="num">${pct(p.taxa)}</td>
          <td class="num">${p.partidas != null ? nf(0).format(p.partidas) : '—'}</td><td class="num">${pct(p.meta)}</td></tr>`).join('')
          || '<tr><td colspan="5" class="vazio">Sem partidas recentes.</td></tr>'}
      </table></div></div>`;

  const ameacas = `
    <div class="caixa"><h3>Para quem você mais perde</h3>
      <div class="tabela-wrap" style="max-height:none"><table class="tabela">
        <tr><th>Adversário</th><th class="num" title="Derrotas contra ele na temporada">Derrotas</th><th class="num">Sua taxa</th><th class="num" title="Derrotas recentes em que ele estava no time do outro">Recentes</th><th>Do seu time, sofre</th><th>Resiste</th></tr>
        ${d.ameacas.map((a) => `<tr><td style="white-space:normal">${esc(a.nome)}<br>${tagsTipo(a.tipos)}</td>
          <td class="num">${nf(0).format(a.derrotas)}${a.partidas ? ` <span class="tag">${nf(0).format(a.partidas)}</span>` : ''}</td>
          <td class="num">${pct(a.taxa)}</td><td class="num">${a.derrotas_recentes || '—'}</td>
          <td style="white-space:normal">${a.sofrem.length ? esc(a.sofrem.join(', ')) : '<span class="aviso">ninguém</span>'}</td>
          <td style="white-space:normal">${a.resistem.length ? esc(a.resistem.join(', ')) : '<span class="aviso">ninguém</span>'}</td></tr>`).join('')
          || '<tr><td colspan="6" class="vazio">Ainda sem derrotas suficientes para apontar um padrão.</td></tr>'}
      </table></div>
      <p class="aviso">Sofre / resiste: pelos golpes do mesmo tipo do adversário (tabela de tipos do jogo).</p></div>`;

  const tiposHtml = `
    <div class="caixa"><h3>Tipos que te castigam</h3>
      <p>${d.tipos_castigam.map((x) => `<span class="tipo-tag">${esc(x.nome)}</span> ${x.parte}%`).join(' &nbsp; ') || '—'}</p>
      <h3 style="margin-top:10px">Buracos do time</h3>
      <p>${d.buracos.filter((b) => b.fracos >= 2).map((b) => `<span class="tipo-tag">${esc(b.nome)}</span> ${b.fracos} sofrem, ${b.resistem} resistem`).join('<br>')
        || 'Nenhum tipo pega 2 ou mais do seu time.'}</p></div>`;

  const soLoja = $('#pvp-soloja')?.checked ?? !!d.orcamento;
  const sugs = d.sugestoes.filter((s) => !soLoja || !d.orcamento || s.mais_forte);
  const anuncio = (a) => (a ? `${htmlPreco(a.preco, m)} <span class="aviso">Nv ${nf(0).format(a.nivel)} · P${a.potencia ?? '?'} · ${nf(0).format(a.poder || 0)} de poder${a.ivs_nota ? ' · ' + htmlIvsChave(a.ivs_nota) : ''}${a.shiny ? ' · shiny' : ''}</span>` : '');
  const sugestoes = `
    <div class="caixa"><h3>Quem comprar para o seu time</h3>
      ${d.orcamento ? `<label class="check"><input type="checkbox" id="pvp-soloja" ${soLoja ? 'checked' : ''}> só o que tem anúncio até ${fmtNum(d.orcamento, m)} ${m === 'gems' ? 'gemas' : 'coins'}</label>` : '<p class="aviso">Ponha um orçamento para ver os anúncios da loja de cada sugestão.</p>'}
      <div class="tabela-wrap" style="max-height:none"><table class="tabela">
        <tr><th>#</th><th>Pokémon</th><th>Por quê</th><th class="num">Meta</th>${d.orcamento ? '<th title="Pelo ⚔ (40%) e pela nota dos IVs (60%): o IV do ataque da espécie e o de SPD pesam mais">Na loja: o melhor</th><th>O mais barato</th>' : ''}</tr>
        ${sugs.map((s, i) => {
          const porque = [];
          if (s.respostas.length) porque.push('ganha de ' + s.respostas.map((v) => `${esc(v.nome)} (${pct(v.taxa)} em ${nf(0).format(v.partidas)})`).join(', '));
          if (s.resiste_a.length) porque.push('resiste a ' + esc(s.resiste_a.join(', ')));
          if (s.tampa.length) porque.push('tapa o buraco de ' + esc(s.tampa.join(', ')));
          if (s.sofre_de.length) porque.push('<span class="desce">cuidado: sofre de ' + esc(s.sofre_de.join(', ')) + '</span>');
          const fora = d.orcamento && !s.mais_forte
            ? `<td colspan="2" class="aviso" style="white-space:normal">${s.anuncios_fora ? `nada até o orçamento (${nf(0).format(s.anuncios_fora)} anúncios, a partir de ${fmtNum(s.mais_barato_fora, m)})` : 'sem anúncio na loja'}</td>` : '';
          return `<tr><td>${i + 1}</td><td style="white-space:normal">${esc(s.nome)}<br>${tagsTipo(s.tipos)}</td>
            <td style="white-space:normal;min-width:260px">${porque.join('; ') || 'forte no meta do rank'}</td>
            <td class="num">${s.meta_taxa != null ? `${pct(s.meta_taxa)} <span class="tag">${nf(0).format(s.meta_partidas)}</span>` : '<span class="aviso">pouco usado</span>'}</td>
            ${d.orcamento ? (fora || `<td style="white-space:normal">${anuncio(s.mais_forte)}</td><td style="white-space:normal">${s.mais_barato && s.mais_barato.id !== s.mais_forte.id ? anuncio(s.mais_barato) : '<span class="aviso">o mesmo</span>'}${s.anuncios > 1 ? ` <span class="tag">${s.anuncios} anúncios</span>` : ''}</td>`) : ''}</tr>`;
        }).join('') || `<tr><td colspan="6" class="vazio">${d.orcamento ? 'Nenhuma sugestão tem anúncio até esse orçamento. Desmarque o filtro para ver todas.' : 'Sem sugestões.'}</td></tr>`}
      </table></div>
      <p class="aviso">A ordem soma três coisas: quanto a espécie ganha das suas ameaças no PvP inteiro (com pelo menos 20 confrontos), a taxa dela no meta do rank e o encaixe de tipos. A loja é lida a cada 3 h; confira o anúncio no jogo antes de comprar.</p></div>`;

  const mt = d.meta || {};
  const linhaMeta = (x) => `<tr><td style="white-space:normal">${esc(x.nome)}<br>${tagsTipo(x.tipos)}</td><td class="num">${nf(0).format(x.partidas)}</td><td class="num">${pct(x.taxa)}</td></tr>`;
  const meta = `
    <div class="duas-col">
      <div class="caixa"><h3>Meta: mais usados (${esc(NOME_FAIXA[mt.faixa] || mt.faixa || '')})</h3>
        <table class="tabela"><tr><th>Pokémon</th><th class="num">Partidas</th><th class="num">Vitórias</th></tr>${(mt.mais_usados || []).map(linhaMeta).join('')}</table></div>
      <div class="caixa"><h3>Meta: melhor taxa (500+ partidas)</h3>
        <table class="tabela"><tr><th>Pokémon</th><th class="num">Partidas</th><th class="num">Vitórias</th></tr>${(mt.melhor_taxa || []).map(linhaMeta).join('')}</table></div>
    </div>
    <div class="caixa" style="margin-top:10px"><h3>Times do topo do ranking</h3>
      ${(mt.repetidos_topo || []).length ? `<p>Mais repetidos: ${mt.repetidos_topo.map(([n, c]) => `${esc(n)} <span class="tag">${c}</span>`).join(' ')}</p>` : ''}
      <div class="tabela-wrap" style="max-height:none"><table class="tabela">
        <tr><th>#</th><th>Treinador</th><th class="num">PR</th><th class="num">Vitórias</th><th>Time (últimas 5 partidas)</th></tr>
        ${(mt.times_topo || []).map((j) => `<tr><td>${j.posicao}</td><td>${esc(j.nick)}</td><td class="num">${nf(0).format(j.pontos)}</td><td class="num">${pct(j.taxa)}</td>
          <td style="white-space:normal">${esc(j.time.map((x) => x.nome).join(', '))}</td></tr>`).join('') || '<tr><td colspan="5" class="vazio">Sem dados do topo agora.</td></tr>'}
      </table></div></div>`;

  $('#pvp-corpo').innerHTML = tiles + `<div class="duas-col">${timeHtml}${tiposHtml}</div>` + `<div style="margin-top:10px">${ameacas}</div>`
    + `<div style="margin-top:10px">${sugestoes}</div>` + `<div style="margin-top:10px">${meta}</div>`;
}

function ligarPvp() {
  $('#pvp-nick').value = lerLocal('pvp_nick');
  $('#pvp-form').addEventListener('submit', analisarPvp);
  $('#pvp-forcar').addEventListener('click', () => analisarPvp(null, true));
  $('#pvp-corpo').addEventListener('change', (e) => { if (e.target.id === 'pvp-soloja') desenharPvp(); });
}

// ------------------------------------------------------------------ pokémon (Fase 4)
const TIPOS_PK = { NORMAL: 'Normal', FIRE: 'Fogo', WATER: 'Água', GRASS: 'Planta', ELECTRIC: 'Elétrico', ICE: 'Gelo',
  FIGHTING: 'Lutador', POISON: 'Veneno', GROUND: 'Terra', FLYING: 'Voador', PSYCHIC: 'Psíquico', BUG: 'Inseto',
  ROCK: 'Pedra', GHOST: 'Fantasma', DRAGON: 'Dragão', DARK: 'Sombrio', STEEL: 'Aço', FAIRY: 'Fada' };
// 1.234.567 → "1,2 mi": o XP/h vai de milhares a bilhões.
const curto = (v) => (v >= 1e9 ? `${nf(2).format(v / 1e9)} bi` : v >= 1e6 ? `${nf(1).format(v / 1e6)} mi` : v >= 1e3 ? `${nf(0).format(v / 1e3)} mil` : nf(0).format(v));
const OBJETIVOS_PK = {
  equilibrado: 'equilibrado: bom de caça e com preço justo',
  xp: 'mais XP por hora caçando (simula a melhor hunt)',
  caca: 'melhor para caçar e upar (dano com o ataque da espécie e o SPD)',
  forte: 'o maior ⚔ do jogo (soma dos 6 atributos)',
  barganha: 'o maior desconto vs preço justo',
  custo: 'mais dano de caça por gema/coin',
  nota: 'a maior nota',
  pvp: 'melhor para PvP (meta do rank + contra quem você perde + IVs de ataque e SPD)',
  ponte: 'transferir gemas entre contas: o melhor Pokémon no piso de preço',
};
// O texto de baixo do formulário muda com o objetivo: a ponte pede o passo a passo.
const EXPLICA_PK = {
  ponte: '<b>Ponte de gemas:</b> 1) a conta que vai receber compra aqui um Pokémon de piso (em coins, o padrão); '
    + '2) anuncia esse Pokémon em gemas pelo valor a transferir (ex.: 310); 3) a outra conta compra logo em seguida (ninguém mais paga isso num Pokémon de piso); '
    + '4) a que anunciou recebe o valor menos a comissão. O Pokémon fica na conta que mandou as gemas e vai para o PvP dela, '
    + 'por isso a lista vem do mais decente para PvP (meta do rank, + ⚔; com o nick da aba PvP, também contra quem você perde).',
};
let explicaPadraoPk = '';

function trocarObjetivoPk() {
  const ponte = $('#pkb-obj').value === 'ponte';
  $('#pkb-transf-rot').classList.toggle('hidden', !ponte);
  // Na ponte o teto é o piso do mercado; o orçamento vira opcional.
  $('#pkb-orc').required = !ponte;
  $('#pkb-orc').placeholder = ponte ? 'opcional' : 'ex.: 300';
  if (ponte) $('#pkb-moeda').value = 'coins';
  $('#pkb-explica').innerHTML = EXPLICA_PK[$('#pkb-obj').value] || explicaPadraoPk;
  if (!ponte) $('#pkb-ponte').classList.add('hidden');
}

function resumoPonte(p, m) {
  if (!p) return 'Nenhum anúncio nessa moeda com esses filtros: sem piso para calcular.';
  let t = `Piso agora: <b>${fmtNum(p.piso, m)}</b>. Entram os anúncios até ${fmtNum(p.teto, m)} (até ${p.folga_pct}% acima do piso, ou o orçamento se for menor).`;
  if (!p.transferir) return t + ' Preencha "quanto vou transferir" para ver a conta.';
  t += `<br>Transferindo <b>${fmtNum(p.transferir, 'gems')} gemas</b>: comissão de ${fmtNum(p.comissao, 'gems')} (${nf(1).format(p.comissao / p.transferir * 100)}%), a conta que anunciou recebe <b>${fmtNum(p.recebe, 'gems')} gemas</b>.`;
  if (p.custo_total_gemas == null) return t;
  t += ` Custo total com o 1º da lista: <b>${nf(1).format(p.custo_total_gemas)} gemas</b> (${nf(1).format(p.custo_pct)}% do valor) = comissão`
    + (p.pokemon_gemas != null ? ` + Pokémon ${nf(1).format(p.pokemon_gemas)}` : '')
    + (p.diaria_gemas != null ? ` + diária de anúncio ${nf(1).format(p.diaria_gemas)}` : '');
  t += p.coins_por_gema
    ? ` (câmbio de ${fmtNum(p.coins_por_gema, 'coins')} coins por gema).`
    : `, mais ${fmtNum(p.custo_coins_sem_cambio, 'coins')} coins (sem câmbio do mercado ainda para converter).`;
  return t;
}
estado.pksub = 'buscar';
estado.pkdias = 7;

function mostrarSubPk(sub) {
  estado.pksub = sub;
  $$('[data-pksub]').forEach((b) => b.classList.toggle('ativa', b.dataset.pksub === sub));
  $$('.pk-painel').forEach((p) => p.classList.toggle('hidden', p.id !== 'pk-' + sub));
  if (sub === 'padroes') carregarPadroesPk();
  if (sub === 'vendas') carregarPokemon();
  if (sub === 'pvp' && !estado.pvp && $('#pvp-nick').value.trim()) analisarPvp();
}

const tagsTipo = (tipos) => (tipos || []).map((t) => `<span class="tipo-tag">${esc(TIPOS_PK[t] || t)}</span>`).join('');


// IVs individuais (pokemon.nota_ivs): o IV do ataque que a espécie usa e o de SPD, com os horríveis em vermelho.
const NOME_LADO_IV = { físico: 'ATQ', especial: 'SP.ATQ', misto: 'ATQ/SP.ATQ' };
function htmlIvsChave(n) {
  if (!n) return '';
  const v = (k, rot) => `<span class="${n.ruins.includes(k) ? 'margem-neg' : ''}">${rot} ${n[k]}</span>`;
  return `${v('ataque', NOME_LADO_IV[n.lado] || 'ATQ')} · ${v('speed', 'SPD')}`;
}
function tituloIvs(x) {
  const n = x.ivs_nota;
  const todos = Object.entries(x.ivs || {}).map(([k, v]) => k + ' ' + v).join(' · ');
  if (!n) return `IVs: ${todos}`;
  return `IVs: ${todos} | nota dos IVs ${nf(1).format(n.nota)}/10 (ataque ${n.lado}): pesa 40% o IV de ataque da espécie, 30% o de SPD e 10% cada HP, DEF e SP.DEF; um IV de ataque ou SPD abaixo de 11 castiga a nota${n.ruins.length ? ' (este tem ' + n.ruins.map((k) => (k === 'speed' ? 'SPD' : 'ataque')).join(' e ') + ' horrível)' : ''}`;
}
async function buscarPk(e) {
  e?.preventDefault();
  const moeda = $('#pkb-moeda').value;
  $('#pkb-tabela').innerHTML = '<tr><td class="vazio">procurando…</td></tr>';
  const d = await api('/api/pk/buscar', {
    orcamento: $('#pkb-orc').value, moeda, objetivo: $('#pkb-obj').value, especie: $('#pkb-esp').value.trim(),
    tipo: $('#pkb-tipo').value, pmin: $('#pkb-pmin').value, nivel: $('#pkb-nivel').value, nota: $('#pkb-nota').value,
    shiny: $('#pkb-shiny').checked ? 1 : '', treinador: $('#pkb-treinador').value,
    // Objetivo PvP: o meta do high elo e, se o nick já foi preenchido na aba PvP, as suas ameaças.
    pvp_nick: ['pvp', 'ponte'].includes($('#pkb-obj').value) ? lerLocal('pvp_nick') : '', pvp_faixa: 'alto',
    transferir: $('#pkb-obj').value === 'ponte' ? $('#pkb-transf').value : '',
  });
  if ($('#pkb-obj').value === 'ponte') gravarLocal('pk_transferir', $('#pkb-transf').value);
  gravarLocal('pk_treinador', $('#pkb-treinador').value);
  $('#pkb-sub').textContent = d.varredura_ms
    ? `loja lida às ${fDiaHora.format(d.varredura_ms)} · ${nf(0).format(d.anuncios_na_loja)} anúncios · ${nf(0).format(d.total)} cabem no orçamento`
      + (d.funil_xp ? ` · XP/h calculado nos ${d.funil_xp} que mais batem` : '')
    : 'a loja ainda não foi lida pelo robô';
  if (d.aviso_xp) $('#pkb-sub').textContent += ` · XP/h: ${d.aviso_xp}`;
  if (d.aviso_pvp) $('#pkb-sub').textContent += ` · PvP: ${d.aviso_pvp} (ordenado só pelo ⚔)`;
  const m = d.moeda;
  $('#pkb-ponte').classList.toggle('hidden', d.objetivo !== 'ponte');
  if (d.objetivo === 'ponte') $('#pkb-ponte').innerHTML = resumoPonte(d.ponte, m);
  $('#pkb-tabela').innerHTML = `
    <tr><th>#</th><th>Pokémon</th><th class="num">Nv</th><th class="num">P</th><th class="num" title="Soma dos IVs e, embaixo, o IV do ataque que a espécie usa e o de SPD (em vermelho, abaixo de 11). Passe o mouse na linha para ver todos e a nota dos IVs.">IV</th><th class="num">Qual.</th><th class="num">Nota</th>
      <th class="num" title="⚔ do jogo: a soma dos 6 atributos em escala de log (a régua do ranking)">Poder</th>
      <th class="num" title="Dano na caça: (2 × nível ÷ 5 + 2) × o ataque que a espécie usa (ATK nos golpes físicos, SP.ATK nos especiais), × a cadência do IV de SPD (1 no IV 16), ÷ 100. É o que decide quem mata mais rápido.">Caça</th>
      <th class="num" title="XP por hora na melhor hunt liberada para o seu nível de treinador, sem bônus, AoE, TM, bike ou casa. Passe o mouse no número para ver a hunt.">XP/h</th><th class="num">Preço</th><th class="num">Preço justo</th><th class="num">Desconto</th><th>Confiança</th>
      <th class="num">Lucro revendendo</th><th>Vendedor</th></tr>
    ${d.itens.map((x, i) => `<tr title="${esc(tituloIvs(x))}${x.faixa ? ` | vendas parecidas entre ${fmtNum(x.faixa[0], m)} e ${fmtNum(x.faixa[1], m)}` : ''}">
      <td>${i + 1}</td>
      <td style="white-space:normal">${esc(x.especie)} ${x.shiny ? '<span class="tag shiny">shiny</span>' : ''}${x.tm ? ' <span class="tag">TM</span>' : ''}${x.nota_pvp != null ? ` <span class="tag" title="Nota de PvP da espécie (0 a 1): meta do high elo e as suas ameaças">PvP ${nf(2).format(x.nota_pvp)}</span>` : ''}<br>${tagsTipo(x.tipos)}</td>
      <td class="num">${nf(0).format(x.nivel ?? 0)}</td><td class="num">${x.potencia ?? '—'}</td><td class="num" style="white-space:nowrap">${x.iv ?? '—'}${x.ivs_nota ? `<br><span class="aviso">${htmlIvsChave(x.ivs_nota)}</span>` : ''}</td>
      <td class="num">${x.qualidade != null ? nf(3).format(x.qualidade) : '—'}</td><td class="num">${x.nota != null ? nf(3).format(x.nota) : '—'}</td>
      <td class="num">${nf(0).format(x.poder ?? 0)}</td>
      <td class="num" title="${x.ataque ? 'ataque ' + x.ataque : ''}">${x.caca != null ? nf(0).format(x.caca) : '—'}</td>
      <td class="num" title="${x.xp_hunt ? esc(`${x.xp_hunt.nome} (Nv ${nf(0).format(x.xp_hunt.nivel)}) · ${nf(0).format(x.xp_hunt.abates_h)} abates/h · ${nf(1).format(x.xp_hunt.luta_s)} s de luta por abate${x.xp_hunt.morre ? ' · morre às vezes' : ''}`) : ''}">${x.xp_h != null ? curto(x.xp_h) : '—'}</td>
      <td class="num">${htmlPreco(x.preco, m)}</td>
      <td class="num">${x.justo != null ? fmtNum(x.justo, m) + ` <span class="tag">${x.comps}</span>` : '<span class="aviso">sem vendas parecidas</span>'}</td>
      <td class="num">${x.desconto != null ? htmlVar(x.desconto) : '—'}</td>
      <td>${x.confianca ? `<span class="conf ${x.confianca}">${x.confianca}</span>` : '—'}</td>
      <td class="num ${x.lucro_revenda > 0 ? 'margem-pos' : 'margem-neg'}">${x.lucro_revenda != null ? (x.lucro_revenda > 0 ? '+' : '') + fmtNum(x.lucro_revenda, m) : '—'}</td>
      <td>${esc(x.vendedor)}</td></tr>`).join('')
      || `<tr><td colspan="16" class="vazio" style="padding:20px">${d.varredura_ms ? 'Nenhum Pokémon da loja cabe nesse orçamento com esses filtros.' : 'O robô ainda não leu a loja de Pokémon (ele faz isso a cada 3 h).'}</td></tr>`}`;
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
  $('#pkb-treinador').value = lerLocal('pk_treinador');
  $('#pkb-transf').value = lerLocal('pk_transferir');
  explicaPadraoPk = $('#pkb-explica').innerHTML;
  $('#pkb-obj').addEventListener('change', trocarObjetivoPk);
  $('#pkb-tipo').innerHTML = '<option value="">qualquer</option>' + Object.entries(TIPOS_PK).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  $('#pkb-form').addEventListener('submit', buscarPk);
  ligarPvp();
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
  ligarControlesGrafico();
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
  $('#lista').addEventListener('click', (e) => {
    const v = e.target.closest('[data-vender]');
    if (v) return abrirVenda(v.dataset.vender);
    const b = e.target.closest('.linha-item');
    if (b) selecionar(b.dataset.nome);
  });
  ligarVenda();
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
