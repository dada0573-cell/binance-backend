import express from 'express';
import http from 'http';
import { WebSocketServer, WebSocket } from 'ws';
import cors from 'cors';

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;
const server = http.createServer(app);

// WebSocket server mounted on Express
const wss = new WebSocketServer({ server });

// In-memory state
let balance = 1000; // Starting balance in EUR
let tradesHistory = [];
let totalTrades = 0;

// REST API Endpoints
app.get('/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime() });
});

app.get('/balance', (req, res) => {
  res.json({ balance, currency: 'EUR' });
});

app.get('/trades', (req, res) => {
  res.json({ total: totalTrades, trades: tradesHistory });
});

// Broadcast to all connected frontend clients
function broadcastToFrontend(data) {
  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(data));
    }
  });
}

// Frontend WS Connection
wss.on('connection', (ws) => {
  console.log('Frontend connected to WebSocket');
  
  // Send initial state if needed
  ws.on('close', () => console.log('Frontend disconnected'));
});

// Binance WebSocket Connection
let binanceWs;
let prices = {
  BTCEUR: { bid: 0, ask: 0 },
  ETHBTC: { bid: 0, ask: 0 },
  ETHEUR: { bid: 0, ask: 0 },
};

function connectBinance() {
  const streamUrl = 'wss://data-stream.binance.vision/stream?streams=btceur@bookTicker/ethbtc@bookTicker/etheur@bookTicker';
  binanceWs = new WebSocket(streamUrl);

  binanceWs.on('open', () => {
    console.log('Connected to Binance WebSocket');
  });

  binanceWs.on('message', (data) => {
    try {
      const msg = JSON.parse(data);
      const parsed = msg.data;
      if (parsed?.s) {
        prices[parsed.s] = {
          bid: parseFloat(parsed.b),
          ask: parseFloat(parsed.a)
        };
        calculateTriangularArbitrage();
      }
    } catch (err) {
      console.error('Error parsing Binance message:', err);
    }
  });

  binanceWs.on('close', () => {
    console.log('Binance WebSocket closed. Reconnecting in 3s...');
    setTimeout(connectBinance, 3000);
  });

  binanceWs.on('error', (err) => {
    console.error('Binance WebSocket error:', err.message);
    binanceWs.close();
  });
}

// Arbitrage Engine
let lastTradeTime = 0;
let lastBroadcast = 0;

function calculateTriangularArbitrage() {
  if (!prices.BTCEUR.ask || !prices.ETHBTC.ask || !prices.ETHEUR.bid) return;

  const now = Date.now();
  if (now - lastBroadcast < 1000) return;
  lastBroadcast = now;

  const initialCapital = 1000;
  const binanceFee = 0.001; // 0.1% fee

  // EUR -> BTC -> ETH -> EUR
  let btcBought = (initialCapital / prices.BTCEUR.ask) * (1 - binanceFee);
  let ethBought = (btcBought / prices.ETHBTC.ask) * (1 - binanceFee);
  let finalEur = (ethBought * prices.ETHEUR.bid) * (1 - binanceFee);

  const profit = finalEur - initialCapital;
  const spreadPercent = (profit / initialCapital) * 100;

  // Send Balance
  broadcastToFrontend({
    type: 'BALANCE',
    payload: { balance, currency: 'EUR' }
  });

  // Send Order Book data
  const orderBookData = [
    { price: (prices.BTCEUR.bid * 0.999).toFixed(2), bid: 25.5, ask: 0 },
    { price: prices.BTCEUR.bid.toFixed(2), bid: 15.5, ask: 0 },
    { price: prices.BTCEUR.ask.toFixed(2), bid: 0, ask: 12.2 },
    { price: (prices.BTCEUR.ask * 1.001).toFixed(2), bid: 0, ask: 18.4 },
  ];

  broadcastToFrontend({
    type: 'ORDER_BOOK',
    payload: orderBookData
  });

  // ALWAYS send opportunities so the frontend table is populated
  const opportunity = {
    id: "OPP-" + Date.now().toString().slice(-6),
    path: "EUR → BTC → ETH → EUR",
    spread: spreadPercent.toFixed(4) + "%",
    profit: (profit >= 0 ? "+" : "-") + "€" + Math.abs(profit).toFixed(2),
    risk: profit > 0 ? "Basso" : "Alto"
  };

  broadcastToFrontend({
    type: 'OPPORTUNITIES',
    payload: [opportunity]
  });

  // Execute simulated trade ONLY if profitable and cooldown passed
  if (profit > 0 && now - lastTradeTime > 5000) {
    lastTradeTime = now;
    balance += profit;
    totalTrades++;

    const trade = {
      id: "T-" + Math.floor(Math.random() * 10000),
      time: new Date().toLocaleTimeString(),
      path: "EUR → BTC → ETH → EUR",
      type: "Triangolare",
      profit: "+" + "€" + profit.toFixed(2),
      status: "Completato"
    };

    tradesHistory.unshift(trade);
    if (tradesHistory.length > 50) tradesHistory.pop();

    broadcastToFrontend({
      type: 'NEW_TRADE',
      payload: trade
    });
  }
}

// Start Binance connection
connectBinance();

server.listen(PORT, () => {
  console.log(`Production Server running on port ${PORT}`);
});