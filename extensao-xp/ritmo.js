// Extensão "Ritmo de XP": roda DENTRO da página do jogo (world MAIN, document_start).
//
// Só ESCUTA o socket que o próprio jogo abre: não abre conexão, não manda nada ao servidor e não lê o
// token. Do que o jogo já recebe, guarda o estado da conta (`welcome` e os `estado` parciais, mesclados
// como o cliente faz em shared/estado-delta.mjs) e, a cada mudança de XP, uma amostra (hora, XP
// acumulado, bônus que valia). Com isso mede o ritmo, tira os bônus (fica o XP/h "cru" da caça) e
// projeta o tempo até o nível escolhido com os bônus que o jogador deixar ligados (padrão: os que
// estão valendo na conta, lidos de `estado.bonusXp`). As contas estão em calculo.js.
// Tudo fica no navegador (localStorage, por conta).
(() => {
  'use strict';
  if (window.__pokeidleRitmoXp) return;
  window.__pokeidleRitmoXp = true;

  const C = globalThis.RitmoXpCalculo;
  if (!C) return;
  const GUARDAR_MS = 6 * C.HORA;          // amostras mais velhas que isso são descartadas
  const JUNTAR_MS = 15_000;               // amostras mais perto que isso viram uma só (mesmo bônus)
  const MAX_AMOSTRAS = 3000;
  const PINTAR_MS = 5_000;
  const FOLGA_NIVEL_POKEMON = 5;          // o jogo só deixa usar Pokémon até o Nv do treinador + 5
  const JANELAS = [
    { id: '10', rotulo: '10 min', ms: 10 * 60_000 },
    { id: '30', rotulo: '30 min', ms: 30 * 60_000 },
    { id: '60', rotulo: '1 h', ms: 60 * 60_000 },
    { id: '180', rotulo: '3 h', ms: 3 * 60 * 60_000 },
    { id: '360', rotulo: '6 h', ms: GUARDAR_MS },
  ];

  // ---------------------------------------------------------------- estado da conta (só leitura)
  let campos = null;                      // estado.* menos os Pokémon
  let pokemons = new Map();
  let tiposBoost = [];
  let desvioServidor = 0;                 // Date.now() − hora do servidor
  const agoraServidor = () => Date.now() - desvioServidor;

  function mesclar(parcial) {
    if (!parcial || typeof parcial !== 'object') return;
    const { cheio, pokemons: lista, pkMud, pkFora, dexMud, dexFora, ...resto } = parcial;
    delete resto.pokedex;                 // não serve aqui e é grande
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

  /** O bônus de XP valendo agora, como o jogo mostra (`bonusXpAgora`): partes sem as vencidas. */
  function bonusAgora() {
    const b = campos?.bonusXp;
    if (!b || !Array.isArray(b.partes)) return { tr: 1, pk: 1, partes: [] };
    const fator = (x, k) => Number(x?.[k]) || 1;
    const produto = (l, k) => l.reduce((m, x) => m * fator(x, k), 1);
    const resto = (k) => {
      const r = fator(b, k) / produto(b.partes, k);
      return Math.abs(r - 1) < 1e-4 ? 1 : r;
    };
    const agora = agoraServidor();
    const partes = b.partes.filter((x) => !(Number(x.ate) > 0) || x.ate > agora).map((x) => ({ ...x }));
    const outros = { id: 'outros', tr: resto('tr'), pk: resto('pk') };
    if (outros.tr !== 1 || outros.pk !== 1) partes.push(outros);
    return { tr: produto(partes, 'tr'), pk: produto(partes, 'pk'), partes };
  }

  // ---------------------------------------------------------------- amostras de XP
  // chave: 'tr' (treinador) ou 'pk:<id>' → [{ t, xp, mult }]
  let nick = null;
  let series = {};
  let aberturaEm = Date.now();

  const chaveConta = () => `pokeidle-ritmo-xp:${nick}`;
  function lerGuardado(sufixo, padrao) {
    try { return JSON.parse(localStorage.getItem(`${chaveConta()}:${sufixo}`) ?? 'null') ?? padrao; } catch { return padrao; }
  }
  function guardar(sufixo, valor) {
    try { localStorage.setItem(`${chaveConta()}:${sufixo}`, JSON.stringify(valor)); } catch { /* cheio ou bloqueado */ }
  }

  function anotar(chave, xp, mult) {
    if (!Number.isFinite(xp)) return;
    const s = (series[chave] ??= []);
    const t = Date.now();
    const ult = s[s.length - 1];
    if (ult && ult.xp === xp) return;
    // o mesmo bônus e bem perto da anterior: só atualiza a última (a penúltima segura o começo)
    const pen = s[s.length - 2];
    if (ult && pen && t - pen.t < JUNTAR_MS && Math.abs(ult.mult - mult) < 1e-9) { ult.t = t; ult.xp = xp; }
    else s.push({ t, xp, mult });
    const corte = t - GUARDAR_MS;
    while (s.length && (s[0].t < corte || s.length > MAX_AMOSTRAS)) s.shift();
    sujo = true;
  }

  function anotarTudo() {
    if (!campos) return;
    const b = bonusAgora();
    anotar('tr', Number(campos.xp), b.tr);
    for (const p of pokemons.values()) anotar(`pk:${p.id}`, Number(p.xp), b.pk);
  }

  let sujo = false;
  function guardarAmostras() {
    if (!sujo || !nick) return;
    sujo = false;
    // guarda só o treinador e os Pokémon que ganharam XP nas últimas horas
    const fica = {};
    for (const [k, s] of Object.entries(series)) if (s.length > 1) fica[k] = s;
    guardar('amostras', fica);
  }
  setInterval(guardarAmostras, 30_000);
  addEventListener('pagehide', guardarAmostras);

  function aoEntrar(m) {
    desvioServidor = m.estado?.servidorAgora ? Date.now() - m.estado.servidorAgora : 0;
    tiposBoost = Array.isArray(m.tiposBoost) ? m.tiposBoost : [];
    campos = null;
    mesclar({ ...m.estado, cheio: true });
    const novo = String(campos?.nick ?? '?');
    if (novo !== nick) {
      nick = novo;
      series = lerGuardado('amostras', {});
      const corte = Date.now() - GUARDAR_MS;
      for (const k of Object.keys(series)) {
        series[k] = (series[k] || []).filter((a) => a && a.t >= corte);
        if (!series[k].length) delete series[k];
      }
      const g = lerGuardado('opcoes', {});
      // alvo, manual e liga são objetos: cada conta com os seus (não os do padrão, compartilhados)
      opcoes = { ...OPCOES_PADRAO, ...g, alvo: { ...g.alvo }, manual: { ...g.manual }, liga: { ...g.liga } };
      aberturaEm = Date.now();
    }
    // reconectou: o XP de agora entra como amostra nova, sem contar o tempo fora como ritmo zero
    // (o tempo fora conta, sim: quem não caçou não ganhou XP).
    anotarTudo();
    pedirPintura();
  }

  function aoMensagem(ev) {
    const d = ev.data;
    if (typeof d !== 'string' || d.length < 12) return;
    const ini = d.slice(0, 40);
    if (!ini.includes('"t":"welcome"') && !ini.includes('"t":"estado"')) return;
    let m;
    try { m = JSON.parse(d); } catch { return; }
    if (m.t === 'welcome' && m.estado) aoEntrar(m);
    else if (m.t === 'estado' && m.estado) {
      if (m.estado.servidorAgora) desvioServidor = Date.now() - m.estado.servidorAgora;
      mesclar(m.estado);
      anotarTudo();
      pedirPintura();
    }
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

  // ---------------------------------------------------------------- os bônus que dá para ligar
  const tipoBoost = (chave) => tiposBoost.find((b) => b.chave === chave)?.mult;
  const pctLive = (live) => 1 + (Number(live?.pct) || 15) / 100;
  // A ordem e os nomes são os da tela "Bônus de XP" do jogo.
  const FONTES = [
    { id: 'vip', nome: 'VIP', oferta: () => ({ tr: 1.5, pk: 1.5 }) },
    { id: 'boostXp', nome: 'XP Boost', oferta: () => ({ tr: tipoBoost('xp') ?? 1.5, pk: 1 }) },
    { id: 'boostPokexp', nome: 'XP Boost Pokémon', oferta: () => ({ tr: 1, pk: tipoBoost('pokexp') ?? 1.5 }) },
    { id: 'guildBoost', nome: 'Boost da Guild', oferta: () => ({ tr: 1.1, pk: 1.1 }) },
    { id: 'twitch', nome: 'Bônus Twitch', oferta: (e) => ({ tr: pctLive(e?.twitch), pk: pctLive(e?.twitch) }) },
    { id: 'kick', nome: 'Bônus na Kick', oferta: (e) => ({ tr: pctLive(e?.kick), pk: pctLive(e?.kick) }) },
    {
      id: 'atrasados', nome: 'Boost dos Atrasados', oferta: () => ({ tr: 10, pk: 10 }),
      mostrar: (e) => (Number(e?.loja?.alvoAtrasados) || 0) > (Number(e?.level) || 0),
    },
    { id: 'sacrificio', nome: 'Boost do Sacrifício', oferta: () => ({ tr: 1.2, pk: 1.2 }) },
    {
      id: 'guild', nome: 'Guild no ranking',
      oferta: (e) => ({ tr: 1 + (Number(e?.guildBonusPct) || 0) / 100, pk: 1 + (Number(e?.guildBonusPct) || 0) / 100 }),
      mostrar: (e) => (Number(e?.guildBonusPct) || 0) > 0,
    },
    { id: 'evento', nome: 'Evento', oferta: () => null },
    { id: 'raid', nome: 'Raid Gigantamax', oferta: () => null },
    { id: 'outros', nome: 'Outro bônus', oferta: () => null },
  ];

  /** Cada bônus com o fator para o treinador e o Pokémon, se vale agora, até quando e o padrão. */
  function listaBonus() {
    const b = bonusAgora();
    const ativas = new Map(b.partes.map((x) => [x.id, x]));
    const lista = [];
    for (const f of FONTES) {
      const x = ativas.get(f.id);
      const of = x ? { tr: Number(x.tr) || 1, pk: Number(x.pk) || 1 } : f.oferta(campos);
      if (!x && (!of || (f.mostrar && !f.mostrar(campos)))) continue;
      const alvo = f.id === 'atrasados' ? (Number(x?.alvo) || Number(campos?.loja?.alvoAtrasados) || 0) : 0;
      lista.push({ id: f.id, nome: f.nome, tr: of.tr, pk: of.pk, ativo: !!x, ate: Number(x?.ate) || 0, alvo });
    }
    // partes que o jogo mandou e esta lista não conhece
    for (const x of b.partes) {
      if (FONTES.some((f) => f.id === x.id)) continue;
      lista.push({ id: x.id, nome: `Bônus "${x.id}"`, tr: Number(x.tr) || 1, pk: Number(x.pk) || 1, ativo: true, ate: Number(x.ate) || 0, alvo: 0 });
    }
    return { lista, atual: b };
  }

  // ---------------------------------------------------------------- opções do jogador (por conta)
  const OPCOES_PADRAO = { quem: 'tr', janela: '30', alvo: {}, manual: {}, liga: {}, prazos: true, aberto: false, pos: null };
  let opcoes = { ...OPCOES_PADRAO, alvo: {}, manual: {}, liga: {} };
  const salvarOpcoes = () => { if (nick) guardar('opcoes', opcoes); };
  const ligado = (bn) => (bn.id in opcoes.liga ? !!opcoes.liga[bn.id] : bn.ativo);

  // ---------------------------------------------------------------- a conta da estimativa
  function alvoDe(quem, nivel) {
    const v = Math.floor(Number(opcoes.alvo[quem]));
    return v > nivel ? v : (Math.floor(nivel / 100) + 1) * 100;
  }

  /** A projeção de um alvo ('tr' ou 'pk:<id>') com os bônus ligados. */
  function montarProjecao(quem, ent, cruH, bonus, atual) {
    const k = quem === 'tr' ? 'tr' : 'pk';
    const agora = agoraServidor();
    const ligados = bonus.filter(ligado);
    const comuns = ligados.filter((bn) => bn.id !== 'atrasados').map((bn) => ({
      f: bn[k],
      ateMs: opcoes.prazos && bn.ativo && bn.ate > 0 ? Math.max(0, bn.ate - agora) : Infinity,
    }));
    const atr = ligados.find((bn) => bn.id === 'atrasados');
    let atrasados = null;
    if (atr && atr.alvo > (Number(campos.level) || 0)) {
      const xpFim = C.xpTotal(atr.alvo);
      if (k === 'tr') atrasados = { f: atr.tr, xpFim };
      else {
        // vale até o TREINADOR chegar no alvo: o tempo vem da projeção do treinador
        const tr = ritmoDe('tr', atual);
        const projTr = tr ? montarProjecao('tr', null, tr.cruH, bonus, atual) : null;
        const ateMs = projTr ? projTr.tempoAte(xpFim) : Infinity;
        atrasados = { f: atr.pk, ateMs };
      }
    }
    return C.projecao({ xp: Number(ent?.xp ?? campos.xp), cruH, bonus: comuns, atrasados });
  }

  /** O ritmo de um alvo: medido na janela ou o digitado (que é com os bônus de agora). */
  function ritmoDe(quem, atual) {
    const k = quem === 'tr' ? 'tr' : 'pk';
    const manual = Number(opcoes.manual[quem]);
    if (manual > 0) return { cruH: manual / (atual[k] || 1), medidoH: manual, manual: true };
    const jan = JANELAS.find((j) => j.id === opcoes.janela) ?? JANELAS[1];
    const r = C.medirRitmo(series[quem] ?? [], Date.now(), jan.ms);
    return r && r.ganho > 0 ? r : null;
  }

  // ---------------------------------------------------------------- tela
  let host = null, raiz = null, painel = null, botao = null;
  let pinturaPedida = false;
  function pedirPintura() {
    if (pinturaPedida) return;
    pinturaPedida = true;
    requestAnimationFrame(() => { pinturaPedida = false; pintar(); });
  }

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (f) => `+${(Math.round((f - 1) * 1000) / 10).toLocaleString('pt-BR')}%`;
  const quando = (ms) => {
    if (!Number.isFinite(ms)) return '';
    const d = new Date(Date.now() + ms);
    const hoje = new Date();
    const dias = Math.round((new Date(d.toDateString()) - new Date(hoje.toDateString())) / 86_400_000);
    const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    if (dias === 0) return `hoje às ${hora}`;
    if (dias === 1) return `amanhã às ${hora}`;
    return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} às ${hora}`;
  };

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .bt { position: fixed; right: 12px; bottom: 12px; z-index: 2147483646; font: 600 12px system-ui, sans-serif;
      background: #1d2433; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 16px; padding: 6px 10px;
      cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.4); opacity: .85; }
    .bt:hover { opacity: 1; }
    .pn { position: fixed; z-index: 2147483647; width: 360px; max-height: 80vh; overflow: auto;
      background: #151b27; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 10px;
      box-shadow: 0 8px 24px rgba(0,0,0,.5); font: 13px/1.4 system-ui, sans-serif; }
    .cab { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: #1d2433; cursor: move;
      border-bottom: 1px solid #2a3348; position: sticky; top: 0; }
    .cab b { flex: 1; }
    .x { background: none; border: 0; color: #9aa6bd; font-size: 16px; cursor: pointer; }
    .cp { padding: 8px 10px; display: grid; gap: 8px; }
    label { color: #9aa6bd; font-size: 12px; }
    select, input[type=number] { background: #0f141e; color: #e8ecf3; border: 1px solid #3a4560; border-radius: 6px;
      padding: 3px 6px; font: inherit; }
    input[type=number] { width: 110px; }
    .lin { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .card { background: #1b2230; border: 1px solid #2a3348; border-radius: 8px; padding: 8px; }
    .grande { font-size: 18px; font-weight: 700; color: #ffd166; }
    .fraco { color: #9aa6bd; font-size: 12px; }
    .aviso { color: #ff9f43; font-size: 12px; }
    .bn { display: grid; grid-template-columns: auto 1fr auto; gap: 2px 6px; align-items: center; }
    .bn small { grid-column: 2 / 4; color: #9aa6bd; font-size: 11px; margin-top: -2px; }
    .on { color: #7bd88f; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { text-align: right; padding: 2px 4px; border-bottom: 1px solid #222b3c; }
    th:first-child, td:first-child { text-align: left; }
    summary { cursor: pointer; color: #9aa6bd; }
    a { color: #7fb2ff; cursor: pointer; }
  `;

  function montarTela() {
    if (host && !host.isConnected && document.body) document.body.appendChild(host);   // o jogo trocou o body
    if (host || !document.body) return;
    host = document.createElement('div');
    host.id = 'pokeidle-ritmo-xp';
    raiz = host.attachShadow({ mode: 'open' });
    raiz.innerHTML = `<style>${CSS}</style>
      <button class="bt" title="Ritmo de XP: quanto falta até o nível que você escolher">⏱ XP</button>
      <div class="pn" hidden>
        <div class="cab"><b>Ritmo de XP</b><span class="fraco" data-nick></span><button class="x" title="Fechar">×</button></div>
        <div class="cp">
          <div class="lin"><label>Quem</label><select data-quem></select></div>
          <div class="lin">
            <label>Nível alvo</label><input type="number" min="2" step="1" data-alvo>
            <label>Ritmo dos últimos</label><select data-janela>${JANELAS.map((j) => `<option value="${j.id}">${j.rotulo}</option>`).join('')}</select>
          </div>
          <div class="lin"><label title="XP/h com os bônus de agora, como a Sessão do jogo mostra. Vazio = medir.">XP/h digitado</label>
            <input type="number" min="0" step="1000" placeholder="medir" data-manual></div>
          <div class="card" data-resultado></div>
          <div class="card">
            <div class="lin" style="justify-content:space-between"><b>Bônus de XP</b><a data-padrao title="Volta para os bônus que estão valendo na conta">padrão da conta</a></div>
            <div data-bonus></div>
            <div class="lin" style="margin-top:6px"><input type="checkbox" data-prazos id="rx-prazos">
              <label for="rx-prazos">Bônus da conta acabam no prazo</label></div>
          </div>
          <details data-det><summary>Nível a nível</summary><div data-tabela></div></details>
          <div class="fraco">Só lê o que o jogo já recebe nesta aba. Não manda nada ao servidor.</div>
        </div>
      </div>`;
    document.body.appendChild(host);
    botao = raiz.querySelector('.bt');
    painel = raiz.querySelector('.pn');
    const $ = (s) => raiz.querySelector(s);

    botao.addEventListener('click', () => { opcoes.aberto = !opcoes.aberto; salvarOpcoes(); pintar(); });
    $('.x').addEventListener('click', () => { opcoes.aberto = false; salvarOpcoes(); pintar(); });
    $('[data-quem]').addEventListener('change', (e) => { opcoes.quem = e.target.value; salvarOpcoes(); pintar(true); });
    $('[data-janela]').addEventListener('change', (e) => { opcoes.janela = e.target.value; salvarOpcoes(); pintar(); });
    $('[data-alvo]').addEventListener('input', (e) => { opcoes.alvo[opcoes.quem] = Number(e.target.value) || null; salvarOpcoes(); pintar(); });
    $('[data-manual]').addEventListener('input', (e) => { opcoes.manual[opcoes.quem] = Number(e.target.value) || null; salvarOpcoes(); pintar(); });
    $('[data-prazos]').addEventListener('change', (e) => { opcoes.prazos = e.target.checked; salvarOpcoes(); pintar(); });
    $('[data-padrao]').addEventListener('click', () => { opcoes.liga = {}; salvarOpcoes(); pintar(); });
    $('[data-bonus]').addEventListener('change', (e) => {
      const id = e.target?.dataset?.bn;
      if (!id) return;
      opcoes.liga[id] = e.target.checked;
      salvarOpcoes();
      pintar();
    });

    // arrastar pelo cabeçalho
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
    $('[data-det]').addEventListener('toggle', () => pintar());
    pintar(true);
  }

  function posicionar() {
    const p = opcoes.pos;
    if (p) { painel.style.left = `${p.x}px`; painel.style.top = `${p.y}px`; painel.style.right = 'auto'; painel.style.bottom = 'auto'; }
    else { painel.style.right = '12px'; painel.style.bottom = '48px'; painel.style.left = 'auto'; painel.style.top = 'auto'; }
  }

  function nomePk(p) {
    return `${p.apelido || p.nome || `#${p.speciesId}`}${p.shiny ? ' ✦' : ''} (Nv ${p.level})`;
  }

  function pintar(trocouQuem = false) {
    if (!raiz) return;
    painel.hidden = !opcoes.aberto;
    if (!opcoes.aberto) return;
    posicionar();
    const $ = (s) => raiz.querySelector(s);
    const res = $('[data-resultado]');
    if (!campos) {
      res.innerHTML = '<span class="fraco">Esperando o jogo mandar os dados da conta (entre ou recarregue a página).</span>';
      return;
    }
    $('[data-nick]').textContent = nick ?? '';

    // quem: o treinador, o Pokémon ativo e os que ganharam XP (XP Share, casa)
    const ativo = pokemons.get(campos.activeId);
    const comXp = [...pokemons.values()].filter((p) => p.id !== campos.activeId && (series[`pk:${p.id}`]?.length ?? 0) > 1);
    if (opcoes.quem.startsWith('pk:') && !pokemons.has(Number(opcoes.quem.slice(3)))) opcoes.quem = 'tr';
    const opts = [`<option value="tr">Treinador (Nv ${campos.level})</option>`];
    if (ativo) opts.push(`<option value="pk:${ativo.id}">Ativo: ${esc(nomePk(ativo))}</option>`);
    for (const p of comXp) opts.push(`<option value="pk:${p.id}">${esc(nomePk(p))}</option>`);
    const sel = $('[data-quem]');
    const html = opts.join('');
    if (sel.dataset.html !== html) { sel.innerHTML = html; sel.dataset.html = html; }
    sel.value = opcoes.quem;
    $('[data-janela]').value = opcoes.janela;
    $('[data-prazos]').checked = !!opcoes.prazos;

    const quem = opcoes.quem;
    const ent = quem === 'tr' ? campos : pokemons.get(Number(quem.slice(3)));
    const nivel = Number(ent.level) || 1;
    const xp = Number(ent.xp) || 0;
    const alvo = alvoDe(quem, nivel);
    const ia = $('[data-alvo]');
    if (trocouQuem || raiz.activeElement !== ia) ia.value = alvo;
    const im = $('[data-manual]');
    if (trocouQuem || raiz.activeElement !== im) im.value = opcoes.manual[quem] || '';

    const { lista, atual } = listaBonus();
    const k = quem === 'tr' ? 'tr' : 'pk';
    const agora = agoraServidor();
    const relevantes = lista.filter((bn) => Math.abs(bn[k] - 1) > 1e-9);
    $('[data-bonus]').innerHTML = relevantes.length
      ? relevantes.map((bn) => {
        const prazo = bn.ativo
          ? (bn.id === 'atrasados' && bn.alvo ? `valendo até o treinador chegar no Nv ${bn.alvo}`
            : bn.ate > 0 ? `valendo · acaba em ${C.tempoCurto(bn.ate - agora)}` : 'valendo')
          : 'desligado na conta';
        return `<label class="bn"><input type="checkbox" data-bn="${esc(bn.id)}" ${ligado(bn) ? 'checked' : ''}>
          <span class="${bn.ativo ? 'on' : ''}">${esc(bn.nome)}</span><b>${pct(bn[k])}</b><small>${esc(prazo)}</small></label>`;
      }).join('')
      : '<span class="fraco">Nenhum bônus para este XP.</span>';
    const fLig = relevantes.filter(ligado).reduce((m, bn) => m * bn[k], 1);

    const r = ritmoDe(quem, atual);
    const avisos = [];
    if (k === 'pk' && alvo > (Number(campos.level) || 0) + FOLGA_NIVEL_POKEMON) {
      avisos.push(`O jogo só deixa usar Pokémon até o Nv do treinador + ${FOLGA_NIVEL_POKEMON} (agora, Nv ${(Number(campos.level) || 0) + FOLGA_NIVEL_POKEMON}).`);
    }
    if (!r) {
      const jan = JANELAS.find((j) => j.id === opcoes.janela) ?? JANELAS[1];
      res.innerHTML = `<div>Nv ${nivel} → <b>${alvo}</b>: faltam ${C.numCurto(Math.max(0, C.xpTotal(alvo) - xp))} XP.</div>
        <div class="fraco">Sem ganho de XP nos últimos ${jan.rotulo} nesta aba. Deixe caçando uns minutos, aumente a janela ou digite o XP/h.</div>
        ${avisos.map((a) => `<div class="aviso">${esc(a)}</div>`).join('')}`;
      $('[data-tabela]').innerHTML = '';
      return;
    }
    const proj = montarProjecao(quem, ent, r.cruH, lista, atual);
    const ms = proj.tempoAte(C.xpTotal(alvo));
    const em24 = C.nivelPeloXp(proj.xpEm(24 * C.HORA));
    const fonte = r.manual ? 'digitado' : `medido em ${C.tempoCurto(r.ms)}`;
    res.innerHTML = `
      <div>Nv ${nivel} → <b>${alvo}</b> em</div>
      <div class="grande">${C.tempoCurto(ms)}</div>
      <div class="fraco">${esc(quando(ms))} · faltam ${C.numCurto(Math.max(0, C.xpTotal(alvo) - xp))} XP</div>
      <div style="margin-top:6px">Ritmo: <b>${C.numCurto(r.medidoH)}</b> XP/h (${fonte}, com ${pct(atual[k])} de bônus)</div>
      <div class="fraco">Sem bônus: ${C.numCurto(r.cruH)} XP/h · com os marcados: ${C.numCurto(r.cruH * fLig)} XP/h (${pct(fLig)})</div>
      <div class="fraco">Em 24 h: Nv ${em24}</div>
      ${avisos.map((a) => `<div class="aviso">${esc(a)}</div>`).join('')}`;

    if ($('[data-det]').open) {
      const linhas = C.linhasAteAlvo(proj, xp, nivel, alvo, 40);
      $('[data-tabela]').innerHTML = `<table><tr><th>Nv</th><th>XP do nível</th><th>+ tempo</th><th>Total</th></tr>
        ${linhas.map((l) => `<tr><td>${l.nivel}</td><td>${C.numCurto(l.xpDoNivel)}</td><td>${C.tempoCurto(l.desdeAnterior)}</td><td>${C.tempoCurto(l.ms)}</td></tr>`).join('')}
        </table>${linhas.length && linhas[0].nivel + 1 < (linhas[1]?.nivel ?? 0) ? '<div class="fraco">Com muitos níveis, a tabela pula de alguns em alguns.</div>' : ''}`;
    }
  }

  document.addEventListener('DOMContentLoaded', montarTela);
  setInterval(() => {
    montarTela();
    if (opcoes.aberto) pintar();
  }, PINTAR_MS);
})();
