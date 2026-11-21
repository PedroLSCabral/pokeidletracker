// Fundo da extensão Prey (service worker): leva o pedido da aba ao painel do PC e devolve a resposta.
// Fica no fundo porque uma página https não fala com 127.0.0.1 sem esbarrar nas regras do navegador.
const PAINEL = 'http://127.0.0.1:8770/api/prey';
const PRAZO_MS = 20_000;

chrome.runtime.onMessage.addListener((m, _de, responder) => {
  if (!m || m.ev !== 'prey' || typeof m.corpo !== 'object') return false;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), PRAZO_MS);
  fetch(PAINEL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(m.corpo),
    signal: ctl.signal,
  })
    .then(async (r) => {
      let d = null;
      try { d = await r.json(); } catch { /* corpo vazio */ }
      if (!r.ok) responder({ erro: d?.erro || `o painel respondeu ${r.status}` });
      else responder({ dados: d });
    })
    .catch((e) => responder({ erro: e.name === 'AbortError' ? 'o painel demorou demais para responder' : 'painel do PC fora do ar (http://127.0.0.1:8770)', fora: true }))
    .finally(() => clearTimeout(timer));
  return true;   // responde depois (assíncrono)
});
