// Metade da extensão que roda na aba do jogo, no mundo isolado (não enxerga o código do jogo).
// Leva as mensagens entre a página (pagina.js) e o fundo da extensão (fundo.js), que fala com o
// robô do PC. Mostra um pontinho no canto: verde = ligado ao robô, laranja = esperando.
(() => {
  'use strict';
  const CANAL = 'pokeidletracker-coletor';
  const VERSAO = chrome.runtime.getManifest().version;

  const estado = { jogo: false, nick: '?', ligada: false, motivo: 'esperando o jogo' };
  let porta = null;
  let ponto = null;

  const paraPagina = (o) => window.postMessage({ canal: CANAL, de: 'aba', ...o }, location.origin);

  function pintar() {
    if (!document.body) return;
    if (!ponto) {
      ponto = document.createElement('div');
      ponto.style.cssText = 'position:fixed;left:4px;bottom:4px;width:8px;height:8px;border-radius:50%;'
        + 'z-index:2147483647;pointer-events:auto;opacity:.8;box-shadow:0 0 0 1px rgba(0,0,0,.5)';
      document.body.appendChild(ponto);
    }
    ponto.style.background = estado.ligada ? '#4caf50' : '#ff9800';
    ponto.title = `PokeIdle Tracker – coletor v${VERSAO}\n`
      + (estado.ligada ? `ligado ao robô do PC (conta ${estado.nick})` : estado.motivo);
  }
  const mudar = (patch) => { Object.assign(estado, patch); pintar(); };
  document.addEventListener('DOMContentLoaded', pintar);

  function ligar() {
    if (porta || !estado.jogo) return;
    try {
      porta = chrome.runtime.connect({ name: 'coletor' });
    } catch (e) {
      mudar({ motivo: `extensão recarregada; recarregue a página (${e.message || e})` });
      return;
    }
    porta.onMessage.addListener((m) => {
      if (m.ev === 'ligada') {
        mudar({ ligada: !!m.ligada, motivo: m.motivo || estado.motivo });
        paraPagina({ ev: 'ext', ligada: !!m.ligada });
      } else if (m.ev === 'robo') {
        paraPagina({ ev: 'enviar', dados: m.dados });
      }
    });
    porta.onDisconnect.addListener(() => {
      porta = null;
      paraPagina({ ev: 'ext', ligada: false });
      mudar({ ligada: false, motivo: 'reconectando com o fundo da extensão' });
      setTimeout(ligar, 2_000);   // o fundo (service worker) pode ter sido encerrado: volta sozinho
    });
    porta.postMessage({ ev: 'oi', nick: estado.nick, versao: VERSAO });
  }

  function desligar() {
    if (porta) { const p = porta; porta = null; p.disconnect(); }
    paraPagina({ ev: 'ext', ligada: false });
  }

  window.addEventListener('message', (e) => {
    const m = e.data;
    if (e.source !== window || !m || m.canal !== CANAL || m.de !== 'pagina') return;
    if (m.ev === 'jogo') {
      if (m.aberto) {
        mudar({ jogo: true, nick: m.nick || estado.nick, motivo: 'procurando o robô no PC' });
        ligar();
      } else {
        mudar({ jogo: false, ligada: false, motivo: 'esperando o jogo' });
        desligar();
      }
    } else if (m.ev === 'msg' && porta && typeof m.dados === 'string') {
      porta.postMessage({ ev: 'jogo', dados: m.dados });
    }
  });

  // Mantém o fundo da extensão acordado enquanto a aba está ligada.
  setInterval(() => { if (porta) porta.postMessage({ ev: 'vivo' }); }, 20_000);
})();
