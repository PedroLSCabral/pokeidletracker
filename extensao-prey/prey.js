// Extensão "Prey": roda DENTRO da página do jogo (world MAIN, document_start).
//
// Só ESCUTA o socket que o próprio jogo abre: não abre conexão, não manda nada ao servidor e não lê o
// token. Do que o jogo já recebe (o `welcome` e os `estado` parciais, mesclados como o cliente faz em
// shared/estado-delta.mjs), tira as cartelas do Prey de hoje (`automation.prey`), o Pokémon que está
// ganhando XP (`activeId`), o nível do treinador e a hunt de agora. Manda isso ao painel do PC
// (POST /api/prey, pela ponte.js e o fundo.js) e mostra qual dos 9 rende mais XP/h para esse Pokémon
// com o bônus e as estrelas que saíram. A conta está no painel (src/analise/prey.py).
(() => {
  'use strict';
  if (window.__pokeidlePrey) return;
  window.__pokeidlePrey = true;

  const CANAL = 'pokeidletracker-prey';
  const PINTAR_MS = 5_000;
  const SO_NIVEL_MS = 60_000;      // só o nível mudou: pede de novo no máximo a cada 1 min
  const HORA = 3_600_000;

  // ---------------------------------------------------------------- estado da conta (só leitura)
  let campos = null;               // estado.* menos os Pokémon
  let pokemons = new Map();
  let desvioServidor = 0;          // Date.now() − hora do servidor
  const agoraServidor = () => Date.now() - desvioServidor;

  function mesclar(parcial) {
    if (!parcial || typeof parcial !== 'object') return;
    const { cheio, pokemons: lista, pkMud, pkFora, dexMud, dexFora, ...resto } = parcial;
    delete resto.pokedex;
    if (cheio || !campos) {
      campos = resto;
      pokemons = new Map((lista ?? []).map((k) => [k.id, k]));
      return;
    }
    Object.assign(campos, resto);
    if (lista) pokemons = new Map(lista.map((k) => [k.id, k]));
    for (const k of pkMud ?? []) pokemons.set(k.id, k);
    for (const id of pkFora ?? []) pokemons.delete(id);
  }

  /** A chave do dia do Prey (shared/dia-sazonal.mjs): vira às 18:00 de Brasília (21:00 UTC). */
  const diaDoPrey = (t) => new Date(Number(t) + 3 * HORA).toISOString().slice(0, 10);

  /** As cartelas de hoje (`preyDoMomento`): as de outro dia valem como vazias. */
  function cartelasDeHoje() {
    const p = campos?.automation?.prey;
    if (!p || p.dia !== diaDoPrey(agoraServidor())) return [null, null];
    const cs = Array.isArray(p.cartelas) ? p.cartelas : [];
    return [0, 1].map((i) => {
      const c = cs[i];
      return c && Array.isArray(c.lista) && c.lista.length
        ? { lista: c.lista, pk: c.pk ?? null, bonus: c.bonus ?? null, est: c.est ?? null, n: c.n ?? null } : null;
    });
  }

  function aoMensagem(ev) {
    const d = ev.data;
    if (typeof d !== 'string' || d.length < 12) return;
    const ini = d.slice(0, 40);
    if (!ini.includes('"t":"welcome"') && !ini.includes('"t":"estado"')) return;
    let m;
    try { m = JSON.parse(d); } catch { return; }
    if (!m.estado) return;
    if (m.estado.servidorAgora) desvioServidor = Date.now() - m.estado.servidorAgora;
    if (m.t === 'welcome') { campos = null; mesclar({ ...m.estado, cheio: true }); lerOpcoes(); }
    else if (m.t === 'estado') mesclar(m.estado);
    else return;
    pedirPintura();
  }

  // ---------------------------------------------------------------- o socket do jogo (só ouvir)
  const vistos = new WeakSet();
  function escutar(ws) {
    if (vistos.has(ws)) return;
    vistos.add(ws);
    ws.addEventListener('message', aoMensagem);
  }
  const Original = window.WebSocket;
  class WebSocketOuvido extends Original {
    constructor(...args) {
      super(...args);
      try { if (String(args[0]).includes('pokeidle.io')) escutar(this); } catch { /* nada */ }
    }
  }
  window.WebSocket = WebSocketOuvido;
  const envioOriginal = Original.prototype.send;
  Original.prototype.send = function (...args) {
    // socket criado antes desta extensão: passa a ouvir no primeiro envio do jogo (não muda o envio)
    try { if (String(this.url).includes('pokeidle.io')) escutar(this); } catch { /* nada */ }
    return envioOriginal.apply(this, args);
  };

  // ---------------------------------------------------------------- opções (por conta)
  const OPCOES_PADRAO = { aberto: false, quem: 'ativo', pos: null };
  let opcoes = { ...OPCOES_PADRAO };
  let nick = null;
  const chave = () => `pokeidle-prey:${nick}:opcoes`;
  function lerOpcoes() {
    const novo = String(campos?.nick ?? '?');
    if (novo === nick) return;
    nick = novo;
    try { opcoes = { ...OPCOES_PADRAO, ...JSON.parse(localStorage.getItem(chave()) ?? 'null') }; } catch { opcoes = { ...OPCOES_PADRAO }; }
    ultimo = { assinatura: null, semNivel: null, em: 0 };
  }
  const salvarOpcoes = () => { try { if (nick) localStorage.setItem(chave(), JSON.stringify(opcoes)); } catch { /* cheio */ } };

  // ---------------------------------------------------------------- pedido ao painel
  let resposta = null;             // { dados } ou { erro }
  let pedindo = false;
  let ultimo = { assinatura: null, semNivel: null, em: 0 };
  let seq = 0;
  const pendentes = new Map();

  window.addEventListener('message', (e) => {
    const m = e.data;
    if (e.source !== window || !m || m.canal !== CANAL || m.de !== 'ponte' || m.ev !== 'resposta') return;
    const fim = pendentes.get(m.id);
    if (fim) { pendentes.delete(m.id); fim(m); }
  });

  function pedirAoPainel(corpo) {
    return new Promise((ok) => {
      const id = ++seq;
      const prazo = setTimeout(() => { pendentes.delete(id); ok({ erro: 'a extensão não respondeu (recarregue a página)' }); }, 25_000);
      pendentes.set(id, (r) => { clearTimeout(prazo); ok(r); });
      window.postMessage({ canal: CANAL, de: 'pagina', ev: 'pedir', id, corpo }, location.origin);
    });
  }

  function pokemonEscolhido() {
    if (!campos) return null;
    if (opcoes.quem !== 'ativo') {
      const p = pokemons.get(Number(opcoes.quem));
      if (p) return p;
    }
    return pokemons.get(campos.activeId) ?? null;
  }

  function montarCorpo() {
    const p = pokemonEscolhido();
    if (!p) return null;
    return {
      pokemon: { id: p.id, speciesId: p.speciesId, nome: p.nome, level: p.level, stats: p.stats, ivs: p.ivs, tipos: p.tipos },
      treinador: Number(campos.level) || null,
      huntSlug: campos.huntSlug ?? null,
      cartelas: cartelasDeHoje().map((c) => c && { lista: c.lista, pk: c.pk, bonus: c.bonus, est: c.est }),
    };
  }

  /** O pedido em texto, inteiro e sem os níveis (que sobem o tempo todo). */
  function assinaturas(corpo) {
    if (!corpo) return { assinatura: null, semNivel: null };
    return {
      assinatura: JSON.stringify(corpo),
      semNivel: JSON.stringify({ ...corpo, treinador: null, pokemon: { ...corpo.pokemon, level: null, stats: null } }),
    };
  }

  async function atualizar() {
    if (pedindo || !opcoes.aberto) return;
    const corpo = montarCorpo();
    if (!corpo || !corpo.cartelas.some(Boolean)) return;
    const { assinatura, semNivel } = assinaturas(corpo);
    if (assinatura === ultimo.assinatura) return;
    // só os níveis mudaram: a resposta que está na tela ainda serve; pede de novo no máximo a cada 1 min
    if (semNivel === ultimo.semNivel && resposta?.dados && Date.now() - ultimo.em < SO_NIVEL_MS) return;
    pedindo = true;
    ultimo = { assinatura, semNivel, em: Date.now() };
    pintar();
    const r = await pedirAoPainel(corpo);
    pedindo = false;
    resposta = { ...r, semNivel };
    if (r.erro) ultimo.assinatura = null;   // tenta de novo na próxima volta
    pintar();
  }

  // ---------------------------------------------------------------- tela
  let host = null, raiz = null, painel = null, botao = null;
  let pinturaPedida = false;
  function pedirPintura() {
    if (pinturaPedida) return;
    pinturaPedida = true;
    requestAnimationFrame(() => { pinturaPedida = false; pintar(); atualizar(); });
  }

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function numCurto(n) {
    if (!Number.isFinite(n)) return '—';
    const a = Math.abs(n);
    const f = (v, s) => `${v.toLocaleString('pt-BR', { maximumFractionDigits: v < 10 ? 2 : v < 100 ? 1 : 0 })}${s}`;
    if (a >= 1e12) return f(n / 1e12, ' tri');
    if (a >= 1e9) return f(n / 1e9, ' bi');
    if (a >= 1e6) return f(n / 1e6, ' mi');
    if (a >= 1e3) return f(n / 1e3, ' mil');
    return Math.round(n).toLocaleString('pt-BR');
  }
  const pct = (x) => (x == null ? '—' : `${x >= 0 ? '+' : '−'}${Math.abs(Math.round(x * 1000) / 10).toLocaleString('pt-BR')}%`);
  const BONUS = { dano: 'Dano', defesa: 'Defensivo', captura: 'Capture Boost', spawn: 'Spawn' };

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .bt { position: fixed; right: 76px; bottom: 12px; z-index: 2147483646; font: 600 12px system-ui, sans-serif;
      background: #1d2433; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 16px; padding: 6px 10px;
      cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.4); opacity: .85; }
    .bt:hover { opacity: 1; }
    .bt.pend { border-color: #ffd166; color: #ffd166; opacity: 1; }
    .pn { position: fixed; z-index: 2147483647; width: 420px; max-height: 80vh; overflow: auto;
      background: #151b27; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 10px;
      box-shadow: 0 8px 24px rgba(0,0,0,.5); font: 13px/1.4 system-ui, sans-serif; }
    .cab { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: #1d2433; cursor: move;
      border-bottom: 1px solid #2a3348; position: sticky; top: 0; }
    .cab b { flex: 1; }
    .x { background: none; border: 0; color: #9aa6bd; font-size: 16px; cursor: pointer; }
    .cp { padding: 8px 10px; display: grid; gap: 8px; }
    label { color: #9aa6bd; font-size: 12px; }
    select { background: #0f141e; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 6px; padding: 3px 6px; font: inherit; max-width: 300px; }
    .lin { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .card { background: #1b2230; border: 1px solid #2a3348; border-radius: 8px; padding: 8px; display: grid; gap: 4px; }
    .grande { font-size: 17px; font-weight: 700; color: #ffd166; }
    .fraco { color: #9aa6bd; font-size: 12px; }
    .aviso { color: #ff9f43; font-size: 12px; }
    .bom { color: #7bd88f; }
    .ruim { color: #ff7b7b; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 4px; }
    th, td { text-align: right; padding: 2px 4px; border-bottom: 1px solid #222b3c; white-space: nowrap; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
    td:nth-child(2) { white-space: normal; }
    tr.rec td { background: #24301f; }
    tr.esc td:first-child::after { content: ' ✔'; color: #7fb2ff; }
    tr.fora td { color: #6b7590; }
  `;

  function montarTela() {
    if (host && !host.isConnected && document.body) document.body.appendChild(host);
    if (host || !document.body) return;
    host = document.createElement('div');
    host.id = 'pokeidle-prey';
    raiz = host.attachShadow({ mode: 'open' });
    raiz.innerHTML = `<style>${CSS}</style>
      <button class="bt" title="Prey: qual dos 9 Pokémon da cartela rende mais XP para quem você está upando">🎯 Prey</button>
      <div class="pn" hidden>
        <div class="cab"><b>Prey: melhor escolha</b><span class="fraco" data-nick></span><button class="x" title="Fechar">×</button></div>
        <div class="cp">
          <div class="lin"><label>Upando</label><select data-quem></select></div>
          <div data-base class="fraco"></div>
          <div data-cartelas style="display:grid;gap:8px"></div>
          <div class="fraco">Conta do painel do PC (motor de XP/h da caça, sem AoE, TM, bike, casa e bônus de XP).
            Só lê o que o jogo já recebe nesta aba. Não manda nada ao jogo.</div>
        </div>
      </div>`;
    document.body.appendChild(host);
    botao = raiz.querySelector('.bt');
    painel = raiz.querySelector('.pn');
    const $ = (s) => raiz.querySelector(s);
    botao.addEventListener('click', () => { opcoes.aberto = !opcoes.aberto; salvarOpcoes(); pintar(); atualizar(); });
    $('.x').addEventListener('click', () => { opcoes.aberto = false; salvarOpcoes(); pintar(); });
    $('[data-quem]').addEventListener('change', (e) => { opcoes.quem = e.target.value; salvarOpcoes(); pintar(); atualizar(); });
    const cab = $('.cab');
    cab.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button')) return;
      const r = painel.getBoundingClientRect();
      const dx = e.clientX - r.left, dy = e.clientY - r.top;
      const mover = (ev) => {
        opcoes.pos = { x: Math.max(0, Math.min(innerWidth - 60, ev.clientX - dx)), y: Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy)) };
        posicionar();
      };
      const soltar = () => { removeEventListener('pointermove', mover); removeEventListener('pointerup', soltar); salvarOpcoes(); };
      addEventListener('pointermove', mover);
      addEventListener('pointerup', soltar);
    });
    pintar();
  }

  function posicionar() {
    const p = opcoes.pos;
    if (p) { painel.style.left = `${p.x}px`; painel.style.top = `${p.y}px`; painel.style.right = 'auto'; painel.style.bottom = 'auto'; }
    else { painel.style.right = '12px'; painel.style.bottom = '48px'; painel.style.left = 'auto'; painel.style.top = 'auto'; }
  }

  const nomePk = (p) => `${p.apelido || p.nome || `#${p.speciesId}`}${p.shiny ? ' ✦' : ''} (Nv ${p.level})`;
  const nv = (n) => Number(n).toLocaleString('pt-BR');
  const huntTxt = (o) => (o?.hunt ? `${o.hunt} (Nv ${nv(o.nivel_hunt)})` : '—');

  function htmlCartela(c, cru, i, calculando) {
    const tit = `<b>Cartela ${i + 1}</b>`;
    if (!cru) return `<div class="card">${tit}<span class="fraco">Ainda sem a roletada grátis de hoje (ou bloqueada).</span></div>`;
    if (!c || c.vazia) return `<div class="card">${tit}<span class="fraco">${calculando ? 'Calculando…' : 'Sem a conta do painel ainda.'}</span></div>`;
    const cab = `${tit} <span>${esc(c.texto ?? 'sem bônus ainda')}</span>`;
    const ops = c.opcoes ?? [];
    const rec = ops.find((o) => o.pk === c.recomendado);
    let topo = '';
    if (rec && c.bonus !== 'captura') {
      const ganho = rec.ganho;
      const rot = !c.vale ? 'A que menos perde' : c.escolhido != null ? 'A melhor seria' : 'Escolha';
      topo = `<div>${rot}</div>
        <div class="grande">${esc(rec.nome)}</div>
        <div>caçando em ${esc(huntTxt(rec))}: <b>${numCurto(rec.xp_h)}</b> XP/h
          <span class="${ganho > 0.001 ? 'bom' : 'ruim'}">(${pct(ganho)} sobre ${esc(c.referencia?.hunt ?? 'a melhor hunt')})</span></div>
        <div class="fraco">O bônus nessa hunt: ${pct(rec.ganho_bonus)} (${numCurto(rec.xp_h_sem)} → ${numCurto(rec.xp_h)} XP/h)${rec.atual ? ' · é a hunt de agora' : ''}</div>`;
    }
    let escolha = '';
    if (c.escolhido != null) {
      const e = ops.find((o) => o.pk === c.escolhido);
      escolha = e?.pk === c.recomendado
        ? `<div class="bom">Você escolheu ${esc(e?.nome)}: é a melhor das 9.</div>`
        : `<div class="aviso">Você escolheu ${esc(e?.nome ?? `#${c.escolhido}`)}${e?.xp_h ? ` (${numCurto(e.xp_h)} XP/h em ${esc(huntTxt(e))})` : ''}. Para trocar, só roletando a lista.</div>`;
    }
    const linhas = ops.map((o) => {
      const cls = [o.pk === c.recomendado && c.bonus !== 'captura' ? 'rec' : '', o.pk === c.escolhido ? 'esc' : '', o.xp_h ? '' : 'fora'].join(' ');
      const hunt = o.xp_h ? huntTxt(o) : o.liberada ? 'não mata' : o.nivel_min ? `liberada no Nv ${nv(o.nivel_min)}` : 'sem hunt no Mapa';
      return `<tr class="${cls}"><td>${esc(o.nome)}</td><td>${esc(hunt)}</td><td>${o.xp_h ? numCurto(o.xp_h) : ''}</td>
        <td class="${(o.ganho ?? -1) > 0.001 ? 'bom' : ''}">${o.xp_h ? pct(o.ganho) : ''}</td><td>${o.xp_h && c.bonus ? pct(o.ganho_bonus) : ''}</td></tr>`;
    }).join('');
    return `<div class="card"><div>${cab}</div>${topo}${escolha}
      ${c.nota ? `<div class="fraco">${esc(c.nota)}</div>` : ''}
      <table><tr><th>Pokémon</th><th>Melhor hunt dele</th><th>XP/h</th><th title="Sobre a melhor hunt sem esta cartela">vs melhor</th><th title="O quanto o bônus soma nessa hunt">bônus</th></tr>${linhas}</table></div>`;
  }

  function pintar() {
    if (!raiz) return;
    const cartelas = cartelasDeHoje();
    const pend = cartelas.some((c) => c && c.bonus && c.pk == null);
    botao.classList.toggle('pend', pend);
    botao.textContent = pend ? '🎯 Prey •' : '🎯 Prey';
    botao.title = pend ? 'Prey: tem cartela esperando a escolha do Pokémon' : 'Prey: qual dos 9 Pokémon da cartela rende mais XP para quem você está upando';
    painel.hidden = !opcoes.aberto;
    if (!opcoes.aberto) return;
    posicionar();
    const $ = (s) => raiz.querySelector(s);
    const base = $('[data-base]'), lista = $('[data-cartelas]');
    if (!campos) {
      base.textContent = 'Esperando o jogo mandar os dados da conta (entre ou recarregue a página).';
      lista.innerHTML = '';
      return;
    }
    $('[data-nick]').textContent = nick ?? '';
    const ativo = pokemons.get(campos.activeId);
    const equipe = [...pokemons.values()].filter((p) => p.slot != null && p.id !== campos.activeId).sort((a, b) => a.slot - b.slot);
    if (opcoes.quem !== 'ativo' && !pokemons.has(Number(opcoes.quem))) opcoes.quem = 'ativo';
    const opts = [`<option value="ativo">Ativo${ativo ? `: ${esc(nomePk(ativo))}` : ''}</option>`]
      .concat(equipe.map((p) => `<option value="${p.id}">${esc(nomePk(p))}</option>`)).join('');
    const sel = $('[data-quem]');
    if (sel.dataset.html !== opts) { sel.innerHTML = opts; sel.dataset.html = opts; }
    sel.value = String(opcoes.quem);

    if (!cartelas.some(Boolean)) {
      base.textContent = '';
      lista.innerHTML = '<div class="card"><span class="fraco">Nenhuma cartela roletada hoje. Faça a roletada grátis no Prey (Mochila); o bônus e as estrelas saem junto com os 9 Pokémon.</span></div>';
      return;
    }
    // resposta de outro pedido (outro Pokémon, cartela mudou): não mostra os números velhos
    const d = resposta?.semNivel === assinaturas(montarCorpo()).semNivel ? resposta.dados : null;
    if (resposta?.erro) base.innerHTML = `<span class="aviso">${esc(resposta.erro)}</span>`;
    else if (d) {
      const b = [];
      if (d.melhor) b.push(`Sem Prey, a melhor hunt dele: <b>${esc(huntTxt(d.melhor))}</b>, ${numCurto(d.melhor.xp_h)} XP/h.`);
      if (d.atual) b.push(`Agora em ${esc(huntTxt(d.atual))}${d.atual.xp_h ? `: ${numCurto(d.atual.xp_h)} XP/h` : ': ele não mata aqui, pela conta'}.`);
      base.innerHTML = b.join('<br>') + (pedindo ? ' <i>atualizando…</i>' : '');
    } else base.textContent = pedindo ? 'Calculando no painel…' : '';
    lista.innerHTML = cartelas.map((cru, i) => htmlCartela(d?.cartelas?.[i], cru, i, !d && pedindo)).join('');
  }

  document.addEventListener('DOMContentLoaded', montarTela);
  setInterval(() => {
    montarTela();
    pintar();
    atualizar();
  }, PINTAR_MS);
})();
