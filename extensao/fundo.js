// Fundo da extensão (service worker): abre a conexão com o robô do PC em ws://127.0.0.1:8772 e
// repassa as mensagens entre ele e a aba do jogo. Fica no fundo (e não na aba) porque uma página
// https não pode falar com endereços locais do PC sem esbarrar nas regras do navegador.
const ROBO = 'ws://127.0.0.1:8772';
const NOVA_TENTATIVA_MS = 10_000;
const OCUPADO_MS = 60_000;   // o robô já tem outra aba ligada (4002)

chrome.runtime.onConnect.addListener((porta) => {
  if (porta.name !== 'coletor') return;
  let ws = null;
  let oi = null;
  let fim = false;
  let timer = null;
  const avisar = (ligada, motivo) => { try { porta.postMessage({ ev: 'ligada', ligada, motivo }); } catch { /* aba fechou */ } };

  function abrir() {
    timer = null;
    if (fim) return;
    try {
      ws = new WebSocket(ROBO);
    } catch (e) {
      avisar(false, `não deu para abrir a conexão: ${e.message || e}`);
      timer = setTimeout(abrir, NOVA_TENTATIVA_MS);
      return;
    }
    ws.onopen = () => ws.send(JSON.stringify({ t: 'ext.oi', nick: oi.nick, versao: oi.versao }));
    ws.onmessage = (ev) => {
      const d = ev.data;
      if (typeof d !== 'string') return;
      if (d.startsWith('{"t": "ext.ok"') || d.startsWith('{"t":"ext.ok"')) return avisar(true);
      try { porta.postMessage({ ev: 'robo', dados: d }); } catch { /* aba fechou */ }
    };
    ws.onclose = (ev) => {
      ws = null;
      if (fim) return;
      const ocupado = ev.code === 4002;
      avisar(false, ocupado ? 'o robô já está ligado a outra aba' : 'robô do PC fora do ar; tentando de novo');
      timer = setTimeout(abrir, ocupado ? OCUPADO_MS : NOVA_TENTATIVA_MS);
    };
  }

  porta.onMessage.addListener((m) => {
    if (m.ev === 'oi' && !oi) {
      oi = m;
      abrir();
    } else if (m.ev === 'jogo' && ws && ws.readyState === 1) {
      ws.send(m.dados);
    }
  });
  porta.onDisconnect.addListener(() => {
    fim = true;
    if (timer) clearTimeout(timer);
    if (ws) ws.close(1000, 'aba fechada');
  });
});
