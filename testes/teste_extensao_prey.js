// Teste da extensão Prey (extensao-prey/) numa aba falsa do jogo (Playwright), com o painel de verdade:
//   node testes/teste_extensao_prey.js
// Sobe um painel de teste numa porta qualquer (usa data/jogo/ para a conta), troca o WebSocket do jogo por um
// falso que só entrega mensagens montadas aqui, e no lugar da ponte.js/fundo.js um ouvinte que leva o
// pedido ao painel. Confere a recomendação, o aviso de cartela pendente e que nada é enviado ao jogo.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const RAIZ = path.join(__dirname, '..');
const PASTA = path.join(RAIZ, 'extensao-prey');
const PORTA = 18_700 + Math.floor(Math.random() * 1000);   // uma porta livre qualquer (a do teste anterior pode estar em TIME_WAIT)
const H = 3_600_000;

async function esperarPainel() {
  for (let i = 0; i < 60; i++) {
    try { await fetch(`http://127.0.0.1:${PORTA}/api/prey`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); return; } catch { /* ainda subindo */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('o painel de teste não subiu');
}

(async () => {
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const painel = spawn(py, [path.join(RAIZ, 'src', 'painel.py'), '--porta', String(PORTA)], { stdio: 'ignore' });
  let navegador;
  try {
    await esperarPainel();
    // os dados do jogo: uma espécie que tem hunt e um Pokémon forte
    const especie = await (await fetch(`http://127.0.0.1:${PORTA}/api/pk/especies`)).json();
    const { chromium } = require('playwright');
    navegador = await chromium.launch();
    const pagina = await navegador.newPage();
    const erros = [];
    pagina.on('pageerror', (e) => erros.push(String(e)));
    pagina.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
    await pagina.route('https://pokeidle.io/**', (r) => r.fulfill({ contentType: 'text/html', body: '<!doctype html><title>jogo</title><body><h1>jogo falso</h1></body>' }));
    await pagina.exposeFunction('__painel', async (corpo) => {
      const r = await fetch(`http://127.0.0.1:${PORTA}/api/prey`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
      const d = await r.json();
      return r.ok ? { dados: d } : { erro: d.erro };
    });
    await pagina.addInitScript(() => {
      class SocketFalso extends EventTarget {
        constructor(url) { super(); this.url = url; this.readyState = 1; (window.__sockets ??= []).push(this); }
        send() { (window.__enviados ??= []).push([...arguments]); }
        close() {}
      }
      window.WebSocket = SocketFalso;
      window.__entregar = (o) => { for (const s of window.__sockets) s.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(o) })); };
      // a ponte falsa: faz o papel de ponte.js + fundo.js
      window.__pedidos = 0;
      window.addEventListener('message', async (e) => {
        const m = e.data;
        if (!m || m.canal !== 'pokeidletracker-prey' || m.de !== 'pagina') return;
        window.__pedidos++;
        const r = await window.__painel(m.corpo);
        window.postMessage({ canal: 'pokeidletracker-prey', de: 'ponte', ev: 'resposta', id: m.id, ...r }, location.origin);
      });
    });
    await pagina.addInitScript({ content: fs.readFileSync(path.join(PASTA, 'prey.js'), 'utf8') });
    await pagina.goto('https://pokeidle.io/');
    await pagina.evaluate(() => new WebSocket('wss://pokeidle.io/ws'));

    const agora = Date.now();
    const dia = new Date(agora + 3 * H).toISOString().slice(0, 10);
    const pk = { id: 7, speciesId: 460, nome: 'Abomasnow', tipos: ['GRASS', 'ICE'], level: 1176, slot: 0,
      stats: { hp: 1500, atk: 1800, def: 1400, spAtk: 1800, spDef: 1500, speed: 1000 }, ivs: { hp: 20, atk: 20, def: 20, spAtk: 20, spDef: 20, speed: 20 } };
    const outro = { ...pk, id: 8, speciesId: 6, nome: 'Charizard', tipos: ['FIRE', 'FLYING'], level: 300, slot: 1 };
    const lista = [443, 10, 16, 19, 41, 69, 74, 92, 129];
    const estado = {
      cheio: true, nick: 'teste', level: 1300, servidorAgora: agora, activeId: 7, huntSlug: 'gible_sinnoh', pokemons: [pk, outro],
      automation: { prey: { dia, cartelas: [{ lista, pk: null, bonus: 'spawn', est: 3, n: [0, 0, 0] }, null] } },
    };
    await pagina.evaluate((m) => window.__entregar(m), { t: 'welcome', estado });
    const bt = pagina.locator('#pokeidle-prey .bt');
    await bt.waitFor();
    assert.match(await bt.innerText(), /Prey •/, 'cartela esperando a escolha');
    await bt.click();
    await pagina.locator('#pokeidle-prey .grande').waitFor({ timeout: 15_000 });
    let t = await pagina.locator('#pokeidle-prey .pn').innerText();
    console.log(t);
    assert.match(t, /(Escolha|A que menos perde)\s+Gible/, 'Gible com Spawn na melhor hunt dele');
    assert.match(t, /Spawn \+3/);
    assert.match(t, /Sem Prey, a melhor hunt dele/);
    assert.match(t, /Cartela 2[\s\S]*sem a roletada/);

    // escolheu outro: o aviso de troca; o botão perde o ponto
    await pagina.evaluate((m) => window.__entregar(m), { t: 'estado', estado: { servidorAgora: Date.now(), automation: { prey: { dia, cartelas: [{ lista, pk: 10, bonus: 'spawn', est: 3, n: [0, 0, 0] }, null] } } } });
    await pagina.waitForFunction(() => /Você escolheu/.test(document.querySelector('#pokeidle-prey').shadowRoot.querySelector('.pn').innerText), null, { timeout: 15_000 });
    t = await pagina.locator('#pokeidle-prey .pn').innerText();
    assert.match(t, /Você escolheu Caterpie[\s\S]*só roletando a lista/);
    assert.match(t, /(A melhor seria|A que menos perde)\s+Gible/);
    assert.doesNotMatch(await bt.innerText(), /•/);

    // outro Pokémon no seletor: pede de novo
    const antes = await pagina.evaluate(() => window.__pedidos);
    await pagina.locator('#pokeidle-prey [data-quem]').selectOption('8');
    await pagina.waitForFunction((n) => window.__pedidos > n, antes);
    await pagina.waitForTimeout(1500);

    // cartela de ontem: vale como vazia
    await pagina.evaluate((m) => window.__entregar(m), { t: 'estado', estado: { servidorAgora: Date.now(), automation: { prey: { dia: '2000-01-01', cartelas: [{ lista, pk: null, bonus: 'dano', est: 1 }] } } } });
    await pagina.waitForFunction(() => /Nenhuma cartela roletada hoje/.test(document.querySelector('#pokeidle-prey').shadowRoot.querySelector('.pn').innerText));
    assert.doesNotMatch(await bt.innerText(), /•/);
    await pagina.evaluate((m) => window.__entregar(m), { t: 'estado', estado: { servidorAgora: Date.now(), automation: { prey: { dia, cartelas: [{ lista, pk: null, bonus: 'spawn', est: 3 }, null] } } } });
    await pagina.locator('#pokeidle-prey [data-quem]').selectOption('ativo');
    await pagina.waitForFunction(() => /(Escolha|A que menos perde)\s+Gible/.test(document.querySelector('#pokeidle-prey').shadowRoot.querySelector('.pn').innerText), null, { timeout: 15_000 });
    await pagina.screenshot({ path: process.env.FOTO || path.join(require('os').tmpdir(), 'prey.png') });

    assert.ok(!(await pagina.evaluate(() => window.__enviados?.length)), 'a extensão não pode mandar nada pelo socket');
    assert.deepStrictEqual(erros, []);
    console.log('tela: ok');
  } finally {
    if (navegador) await navegador.close();
    painel.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
