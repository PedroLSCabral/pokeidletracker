// Roda DENTRO da página do jogo (world MAIN), antes do código dele (document_start).
//
// Pega o socket que o próprio jogo abre, sem abrir conexão nova (uma segunda conexão derrubaria a
// conta com o código 4001), e serve de ponte para o robô do PC:
//   - o robô só pode mandar três pedidos de leitura: csv.pedir (export), market.itens (vitrine) e
//     market.listar (loja de Pokémon). Qualquer outra coisa é descartada aqui;
//   - só as RESPOSTAS a esses pedidos voltam para o robô, e elas não chegam ao jogo (senão o jogo
//     baixaria um .csv a cada hora e a tela do mercado pularia de página sozinha);
//   - o welcome vai para o robô sem o `estado` (a conta). O token nunca é lido.
// A conversa com a outra metade da extensão (aba.js) é por window.postMessage.
(() => {
  'use strict';
  if (window.__pokeidleTrackerColetor) return;
  window.__pokeidleTrackerColetor = true;

  const CANAL = 'pokeidletracker-coletor';
  const PRAZO_MS = 60_000;          // um pedido sem resposta nesse tempo não segura mais nada
  const Original = window.WebSocket;
  const envioOriginal = Original.prototype.send;

  let sock = null;                  // o socket do jogo
  let welcome = null;               // o último welcome, já sem o estado da conta
  let extLigada = false;            // o robô aceitou a ponte
  let enviandoNosso = false;
  const doRobo = {};                // chave → horários dos pedidos do robô ainda sem resposta
  const doJogo = {};                // chave → horários dos pedidos do próprio jogo

  const PERMITIDOS = { 'csv.pedir': 'csv', 'market.itens': 'market:itens', 'market.listar': 'market:vitrine' };
  const chaveResposta = (m) => (m.t === 'csv' ? 'csv' : m.t === 'market' ? `market:${m.aba}` : null);

  const postar = (o) => window.postMessage({ canal: CANAL, de: 'pagina', ...o }, location.origin);

  function marcar(fila, chave) {
    (fila[chave] = fila[chave] || []).push(Date.now());
  }
  function tirar(fila, chave) {
    const f = fila[chave];
    if (!f) return false;
    const t = Date.now();
    while (f.length && t - f[0] > PRAZO_MS) f.shift();
    return f.length ? (f.shift(), true) : false;
  }
  const algumPendente = () => Object.values(doRobo).some((f) => f.some((t) => Date.now() - t < PRAZO_MS));

  function nick() {
    try { return JSON.parse(localStorage.getItem('sessao') || '{}').nick || '?'; } catch { return '?'; }
  }

  function mandarWelcome() {
    postar({ ev: 'msg', dados: welcome || '{"t":"welcome","parcial":true}' });
  }

  // Ouvinte do socket do jogo. Registrado no construtor, ele roda antes dos ouvintes do jogo e
  // pode engolir a resposta (stopImmediatePropagation também barra o onmessage).
  function filtro(ev) {
    const d = ev.data;
    if (typeof d !== 'string' || d.length < 8) return;
    if (d.includes('"t":"welcome"')) {
      try {
        const m = JSON.parse(d);
        if (m.t !== 'welcome') return;
        delete m.estado;
        welcome = JSON.stringify(m);
        postar({ ev: 'jogo', aberto: true, nick: nick() });
        if (extLigada) mandarWelcome();
      } catch { /* nada */ }
      return;
    }
    if (d.includes('"t":"csv"') || d.includes('"t":"market"')) {
      let m;
      try { m = JSON.parse(d); } catch { return; }
      const k = chaveResposta(m);
      if (!k || !tirar(doRobo, k)) { if (k) tirar(doJogo, k); return; }
      if (extLigada) postar({ ev: 'msg', dados: d });
      // Se o jogo também pediu a mesma coisa nesse meio-tempo, a resposta segue para ele.
      if (!tirar(doJogo, k)) ev.stopImmediatePropagation();
      return;
    }
    if (d.includes('"t":"erro"') && extLigada && algumPendente()) postar({ ev: 'msg', dados: d });
  }

  function engatar(ws, cedo) {
    if (ws === sock) return;
    if (sock) postar({ ev: 'jogo', aberto: false });
    sock = ws;
    welcome = null;
    ws.addEventListener('message', filtro);
    ws.addEventListener('close', (e) => {
      if (sock !== ws) return;
      sock = null;
      postar({ ev: 'jogo', aberto: false, codigo: e.code });
    });
    if (!cedo) {
      // Pegamos o socket só no primeiro envio (o welcome pode já ter passado): segue sem ele.
      setTimeout(() => { if (sock === ws && !welcome && ws.readyState === 1) postar({ ev: 'jogo', aberto: true, nick: nick() }); }, 15_000);
    }
  }

  class WebSocketDoJogo extends Original {
    constructor(...args) {
      super(...args);
      try { if (String(args[0]).includes('pokeidle.io')) engatar(this, true); } catch { /* nada */ }
    }
  }
  window.WebSocket = WebSocketDoJogo;

  Original.prototype.send = function (dados) {
    try {
      if (this !== sock && String(this.url).includes('pokeidle.io')) engatar(this, false);
      if (this === sock && !enviandoNosso && typeof dados === 'string'
          && (dados.includes('"t":"csv.pedir"') || dados.includes('"t":"market.'))) {
        const k = PERMITIDOS[JSON.parse(dados).t];
        if (k) marcar(doJogo, k);
      }
    } catch { /* nada */ }
    return envioOriginal.apply(this, arguments);
  };

  window.addEventListener('message', (e) => {
    const m = e.data;
    if (e.source !== window || !m || m.canal !== CANAL || m.de !== 'aba') return;
    if (m.ev === 'ext') {
      extLigada = !!m.ligada;
      if (extLigada) mandarWelcome();
      return;
    }
    if (m.ev !== 'enviar' || typeof m.dados !== 'string') return;
    let pedido;
    try { pedido = JSON.parse(m.dados); } catch { return; }
    const k = PERMITIDOS[pedido && pedido.t];
    if (!k || !sock || sock.readyState !== 1) return;
    marcar(doRobo, k);
    enviandoNosso = true;
    try { envioOriginal.call(sock, JSON.stringify(pedido)); } finally { enviandoNosso = false; }
  });
})();
