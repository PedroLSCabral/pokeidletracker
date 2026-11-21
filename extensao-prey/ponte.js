// Metade da extensão Prey no mundo isolado da aba: leva os pedidos da página (prey.js) ao fundo
// (fundo.js), que fala com o painel do PC, e devolve as respostas. Não enxerga o código do jogo.
(() => {
  'use strict';
  const CANAL = 'pokeidletracker-prey';
  window.addEventListener('message', (e) => {
    const m = e.data;
    if (e.source !== window || !m || m.canal !== CANAL || m.de !== 'pagina' || m.ev !== 'pedir') return;
    const devolver = (r) => window.postMessage({ canal: CANAL, de: 'ponte', ev: 'resposta', id: m.id, ...r }, location.origin);
    try {
      chrome.runtime.sendMessage({ ev: 'prey', corpo: m.corpo }, (r) => {
        if (chrome.runtime.lastError) devolver({ erro: `extensão: ${chrome.runtime.lastError.message}` });
        else devolver(r || { erro: 'sem resposta do fundo da extensão' });
      });
    } catch (err) {
      devolver({ erro: `extensão recarregada; recarregue a página (${err.message || err})` });
    }
  });
})();
