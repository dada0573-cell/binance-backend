const express = require("express");
const cors = require("cors");
const WebSocket = require("ws");

const app = express();

const prices = {};

let balance = 1000;

let lastUpdate = 0;

const trades = [];

app.use(cors());

app.get("/", (req, res) => {
  res.send("Backend funcionando");
});

app.get("/health", (req, res) => {
  res.json({
    status: "ok"
  });
});

app.get("/balance", (req, res) => {
  res.json({
    balance: balance,
    totalTrades: trades.length
  });
});

app.get("/trades", (req, res) => {
  res.json(trades);
});

const ws = new WebSocket(
  "wss://data-stream.binance.vision/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker/ethbtc@bookTicker"
);

ws.on("open", () => {
  console.log("Conectado a Binance");
});

ws.on("message", (data) => {

  const json = JSON.parse(data);

  const parsed = json.data;

  if (!parsed) return;

  const symbol = parsed.s;

  prices[symbol] = {
    bid: parseFloat(parsed.b),
    ask: parseFloat(parsed.a),
  };

  const btcusdt = prices["BTCUSDT"];
  const ethbtc = prices["ETHBTC"];
  const ethusdt = prices["ETHUSDT"];

  if (btcusdt && ethbtc && ethusdt) {

    const now = Date.now();

    if (now - lastUpdate < 1000) return;

    lastUpdate = now;

    const usdtStart = 1000;

    const btc = usdtStart / btcusdt.ask;

    const eth = btc / ethbtc.ask;

    const usdtFinal = eth * ethusdt.bid;

    const profit = usdtFinal - usdtStart;

    console.clear();

    console.log("===============");
    console.log("ARBITRAJE TRIANGULAR");
    console.log("===============");

    console.log("USDT Inicial:", usdtStart.toFixed(2));

    console.log("USDT Final:", usdtFinal.toFixed(2));

    console.log("PROFIT:", profit.toFixed(4));

    if (profit > 0) {

      console.log("OPORTUNIDAD DETECTADA");

      balance += profit;

      const trade = {
        timestamp: new Date().toISOString(),
        initial: usdtStart,
        final: usdtFinal,
        profit: profit,
        balance: balance,
      };

      trades.push(trade);

      console.log("BALANCE:", balance.toFixed(2));

      console.log("TRADES:", trades.length);

    } else {

      console.log("Sin oportunidad");

    }

  }

});

ws.on("error", (error) => {
  console.log("WebSocket Error:", error.message);
});

ws.on("close", () => {
  console.log("Binance desconectó");
});

const PORT = process.env.PORT || 3000;

const server = app.listen(PORT, () => {
  console.log(`Servidor corriendo en puerto ${PORT}`);
});

const WebSocketServer = require("ws").Server;

const wss = new WebSocketServer({ server });

wss.on("connection", (client) => {

  console.log("Frontend conectado vía WebSocket");

  setInterval(() => {

    const lastTrade = trades[trades.length - 1] || null;

    client.send(JSON.stringify({
      type: "BALANCE",
      payload: {
        balance,
        totalTrades: trades.length,
        lastTrade
      }
    }));

  }, 2000);

});