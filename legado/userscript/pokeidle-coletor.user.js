// ==UserScript==
// @name         PokeIdle Tracker – Coletor
// @namespace    pokeidletracker
// @version      0.2.0
// @description  A cada hora pede o export da Tabela de preços (1 por hora, o limite do jogo) e um retrato da vitrine, e manda para o coletor local (python src/coletor.py).
// @match        https://pokeidle.io/*
// @match        https://*.pokeidle.io/*
// @run-at       document-start
// @sandbox      JavaScript
// @inject-into  page
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// @updateURL    http://127.0.0.1:8765/pokeidle-coletor.user.js
// @downloadURL  http://127.0.0.1:8765/pokeidle-coletor.user.js
// ==/UserScript==

(function () {
  'use strict';

  const VERSAO = '0.2.0';
  const SERVIDOR = 'http://127.0.0.1:8765';
  const CHECAR_A_CADA_MS = 60_000;     // pergunta ao coletor se é a vez
  const ESPERA_RESPOSTA_MS = 20_000;
  const W = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
  const log = (...a) => console.log('%c[coletor]', 'color:#b07cff', ...a);

  // ------------------------------------------------------------ selo de diagnóstico
  // Um selinho no canto da tela diz em que pé está o coletor, sem precisar abrir o console.
  const estado = { gm: typeof GM_xmlhttpRequest === 'function', servidor: null, erro: '', sock: false, ultimo: '' };
  let selo = null;
  function pintar() {
    if (!document.body) return;
    if (!selo) {
      selo = document.createElement('div');
      selo.style.cssText = 'position:fixed;left:6px;bottom:44px;z-index:2147483647;font:11px/1.3 sans-serif;'
        + 'background:rgba(20,10,30,.85);color:#eee;padding:4px 7px;border-radius:6px;pointer-events:auto;cursor:pointer;max-width:260px';
      selo.title = 'PokeIdle Tracker – clique para esconder';
      selo.onclick = () => { selo.style.display = 'none'; };
      document.body.appendChild(selo);
    }
    const ok = estado.gm && estado.servidor === true && estado.sock;
    const linhas = [
      `${ok ? '🟢' : '🟠'} coletor v${VERSAO}`,
      `gerenciador GM: ${estado.gm ? 'ok' : 'SEM GM_xmlhttpRequest'}`,
      `servidor PC: ${estado.servidor === null ? 'testando…' : estado.servidor ? 'ok' : 'FORA DO AR'}${estado.erro ? ` (${estado.erro})` : ''}`,
      `socket do jogo: ${estado.sock ? 'ok' : 'aguardando…'}`,
    ];
    if (estado.ultimo) linhas.push(estado.ultimo);
    selo.innerHTML = linhas.map((l) => `<div>${l.replace(/</g, '&lt;')}</div>`).join('');
  }
  const atualizar = (patch) => { Object.assign(estado, patch); pintar(); };
  document.addEventListener('DOMContentLoaded', pintar);

  // ------------------------------------------------------------ conexão do jogo
  // Pegamos o socket do próprio jogo no primeiro envio dele (o `hello` ou o ping de 25 s),
  // sem abrir conexão nova: uma segunda conexão derrubaria a conta (código 4001).
  let sock = null;
  const pendente = { csv: 0 };

  function engatar(ws) {
    if (ws === sock) return;
    sock = ws;
    const original = ws.onmessage;
    ws.onmessage = function (ev) {
      try { if (interceptar(ev)) return; } catch (e) { log('erro', e); }
      return original && original.call(this, ev);
    };
    atualizar({ sock: true });
    log('conectado ao socket do jogo');
  }

  try {
    const envioOriginal = W.WebSocket.prototype.send;
    W.WebSocket.prototype.send = function (dados) {
      try { if (String(this.url).includes('pokeidle.io')) engatar(this); } catch (e) { /* nada */ }
      return envioOriginal.apply(this, arguments);
    };
  } catch (e) {
    atualizar({ ultimo: `não deu para ligar no WebSocket: ${e}` });
  }

  // Devolve true quando a mensagem é a resposta do NOSSO export: ela não chega ao jogo,
  // senão o jogo baixaria um .csv e mostraria um aviso a cada hora.
  function interceptar(ev) {
    if (typeof ev.data !== 'string') return false;
    if (pendente.csv && ev.data.includes('"t":"csv"')) {
      const m = JSON.parse(ev.data);
      if (m.t !== 'csv' || m.tipo !== 'mercado') return false;
      pendente.csv = 0;
      if (m.recusa) {
        postar('/recusa', { nick: nick(), chave: m.recusa.chave, restaMs: m.recusa.restaMs });
        atualizar({ ultimo: `export: jogo pediu espera de ${Math.round((m.recusa.restaMs || 0) / 60000)} min` });
      } else if (m.ok && m.mercado && Array.isArray(m.mercado.linhas)) {
        postar('/vendas', {
          nick: nick(), esperaMs: m.esperaMs, cortado: !!m.mercado.cortado,
          tipo: m.mercado.tipo, linhas: m.mercado.linhas,
        });
        atualizar({ ultimo: `export ${new Date().toLocaleTimeString().slice(0, 5)}: ${m.mercado.linhas.length} vendas` });
      }
      return true;
    }
    // A vitrine segue também para o jogo (é uma leitura comum, a tela só se atualiza).
    if (ev.data.includes('"aba":"itens"') && ev.data.includes('"resumo"')) {
      const m = JSON.parse(ev.data);
      if (m.t === 'market' && m.aba === 'itens') postar('/vitrine', { nick: nick(), resumo: m.resumo, medias: m.medias });
    }
    return false;
  }

  // ------------------------------------------------------------ coletor local
  function http(metodo, caminho, corpo) {
    return new Promise((ok, falha) => {
      if (!estado.gm) return falha(new Error('sem GM_xmlhttpRequest'));
      try {
        GM_xmlhttpRequest({
          method: metodo,
          url: SERVIDOR + caminho,
          headers: { 'Content-Type': 'application/json' },
          data: corpo ? JSON.stringify(corpo) : undefined,
          timeout: 15_000,
          onload: (r) => {
            if (r.status !== 200) return falha(new Error(`HTTP ${r.status}`));
            try { ok(JSON.parse(r.responseText)); } catch (e) { falha(e); }
          },
          onerror: (r) => falha(new Error(r && (r.error || r.statusText) || 'erro de rede')),
          ontimeout: () => falha(new Error('timeout')),
        });
      } catch (e) { falha(e); }
    });
  }
  const postar = (c, b) => http('POST', c, b).catch((e) => { log('coletor fora do ar?', c, e); atualizar({ servidor: false, erro: String(e.message || e) }); });

  // Só o NICK sai daqui. O token da sessão nunca é lido para fora da página.
  function nick() {
    try { return JSON.parse(W.localStorage.getItem('sessao') || '{}').nick || '?'; } catch { return '?'; }
  }

  const enviarAoJogo = (msg) => sock && sock.readyState === 1 && (sock.send(JSON.stringify(msg)), true);

  async function rodada() {
    const pronto = !!(sock && sock.readyState === 1);
    atualizar({ sock: pronto });
    // Pergunta SEMPRE (mesmo sem socket): assim o status do PC mostra a aba e o que falta nela.
    let vez;
    const q = `nick=${encodeURIComponent(nick())}&sock=${pronto ? 1 : 0}&v=${VERSAO}&pag=${encodeURIComponent(location.pathname)}`;
    try {
      vez = await http('GET', `/vez?${q}`);
      atualizar({ servidor: true, erro: '' });
    } catch (e) {
      atualizar({ servidor: false, erro: String(e.message || e) });
      return;
    }
    if (!pronto) return;
    if (vez.exportar && !pendente.csv) {
      if (enviarAoJogo({ t: 'csv.pedir', tipo: 'mercado', filtros: {} })) {
        pendente.csv = Date.now();
        setTimeout(() => {
          if (pendente.csv) { pendente.csv = 0; postar('/falha', { nick: nick(), motivo: 'sem resposta' }); }
        }, ESPERA_RESPOSTA_MS);
      }
    }
    if (vez.vitrine) enviarAoJogo({ t: 'market.itens' });
    if (vez.itens) {
      try {
        const j = await fetch('/assets/items.json', { cache: 'no-cache' }).then((r) => r.json());
        postar('/itens', { items: j.items || [] });
      } catch (e) { log('items.json falhou', e); }
    }
  }

  setTimeout(rodada, 5_000);
  setInterval(rodada, CHECAR_A_CADA_MS);
  log(`v${VERSAO} carregado em ${location.href}`);
})();
