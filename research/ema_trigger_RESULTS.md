# Uji TRIGGER = EMA20/50 Cross H1 (T1) vs Trigger Donchian v1.2 — Hasil Backtest (2026-10-07)

**Pertanyaan user:** "ketika EMA-nya udah ngecross itu ngasih alert entry (buy/sell)" — karena di chart
07 Okt 2026 cross H1 (sekitar $4160) mendahului sinyal Donchian SELL @$4082 sekitar ~$80.
User approved "gas", dites fair.
**Prior jujur:** EMA-cross sebagai trigger standalone pernah KALAH di semua 6 simbol (riset awal
Okt 2026); F2 (fresh-cross sebagai filter) gagal (PF 0.82). Ekspektasi: kemungkinan besar gagal —
tapi tes tetap dijalankan fair.

**Metode:** harness `ema_trigger_backtest.py` (mesin runner, live_pos gate, resolusi
SL/TP1/48h-expiry, prioritas SL intrabar — persis `run_ema` di `ema_filter_backtest.py`).
Data Binance PAXGUSDT M5 Jan–Okt 2026 (proxy XAUUSD), download ulang dari Binance Vision
(monthly Jan–Sep + daily 01–06 Okt; file daily 07 Okt belum terbit saat tes).

**Definisi T1 yang presisi (tanpa lookahead):**
- Cross terdeteksi pada bar H1 completed `j`: `sign(EMA20−EMA50)` berubah (definisi persis F2;
  butuh `prev_sign != 0`, jadi cross pertama dari warmup tidak dihitung).
- Entry = close bar M5 PERTAMA dengan `ts >= h1t[j]+3600` (momen cross diketahui).
- Cross up → BUY, cross down → SELL. Satu cross = satu sinyal; cross saat posisi aktif = dibuang
  (sama seperti sinyal Donchian saat posisi aktif di v1.2).
- Risk management IDENTIK v1.2: SL 1.5×ATR(H1) (@bar cross), TP1 1R / TP2 1.5R / TP3 2R,
  TP1-touch → SL ke breakeven, 48h expiry, one-position-at-a-time.
- Varian utama T1+H4 (filter H4 SMA15 seperti v1.2, dihitung pada bar cross `jc`);
  varian diagnostik T1 tanpa filter H4. Filter EMA-state TIDAK dipakai (redundan dengan trigger).

**Validasi:** baseline v1.2 di script ini (n=238, PF=1.38, totR=+42.2, maxDD=15.3) match PERSIS
dengan `ema_filter_RESULTS.md` — angka antar-varian comparable.

## 1. Hasil utama

| Varian | Jan–Okt n | win% | PF | avgR | totR | maxDD | Sep–Okt n | PF | totR |
|---|---|---|---|---|---|---|---|---|---|
| v1.2 baseline (Donchian trigger) | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | 15.3 | 27 | 0.86 | -2.0 |
| **T1: EMA-cross trigger +H4** | 92 | 25.0 | **0.86** | -0.07 | **-6.4** | 12.1 | 17 | 0.93 | -0.6 |
| T1: EMA-cross trigger no-H4 | 92 | 21.7 | 0.68 | -0.17 | -15.4 | 19.7 | 17 | 0.60 | -3.6 |

- **T1 GAGAL DECISIF.** PF 0.86 (< 1.0 = rugi), totR −6.4R vs +42.2R milik v1.2. Tanpa filter H4
  lebih parah (PF 0.68). Di data terbaru Sep–Okt pun tidak lebih baik dari v1.2 secara bermakna
  (0.93 vs 0.86, n=17 — noise di sampel kecil).
- Frekuensi: 99 cross H1 dalam 9 bulan (98 event dalam periode Jan–Okt) → 92 trade diambil
  (6 dibuang one-position gate; filter H4 tidak memblokir satu pun — cross H1 praktis selalu
  selaras H4). v1.2 memberi 238 sinyal: T1 ~60% lebih jarang AND jauh lebih jelek.

## 2. Diagnostik: kenapa gagal

| Metrik (T1+H4, Jan–Okt) | Angka |
|---|---|
| % SL yang kena dalam ≤12 bar H1 setelah entry (whipsaw) | **87%** |
| Rata-rata bar H1 entry → SL | 6.1 jam |
| Rata-rata bar H1 entry → TP1 touch | 10.1 jam |

- **Mekanisme kegagalan = whipsaw.** 87% dari SL kena dalam 12 jam pertama. Cross EMA adalah
  indikator lagging: saat dia cross, harga sudah bergerak jauh — dan sering langsung berbalik.
- **Contoh konkret 02–03 Okt** (5 trade T1 terakhir di data): SELL −1R → BUY −1R (3 jam
  kemudian) → SELL −1R (2 jam kemudian!) → BUY −1R → SELL +0.1R. **4 SL beruntun dalam ~2 hari**
  karena cross flip-flop bolak-balik. Inilah yang tidak terlihat di satu chart cantik.
- Ironi yang wajib dicatat: chart 07 Okt yang memicu ide ini justru menunjukkan cross DOWN
  yang "sempurna" — tapi data 9 bulan menunjukkan cross semacam itu lebih sering jebakan
  daripada berkah. Satu chart = anekdot; 99 cross = data.

## 3. Kesimpulan jujur & rekomendasi

**JANGAN ganti trigger ke EMA cross.** Hasilnya bukan "netral tapi menarik" — melainkan rugi
sistematis (PF 0.86, −6.4R). Ini konfirmasi ketiga setelah (a) EMA-cross standalone kalah di
6 simbol dan (b) F2 gagal: **EMA cross tidak bisa dipakai sebagai trigger entry.**

**Rekomendasi: tetap di v1.2 (Donchian trigger + filter H4 + filter EMA-state H1) apa adanya.**
EMA20/50 tetap dipakai — tapi sebagai FILTER (terbukti +0.15 PF), bukan sebagai TRIGGER.
Posisi EMA dalam sistem sudah benar: Donchian yang cari momen breakout, EMA yang menilai
apakah breakout itu searah trend menengah.

**Skeptisisme yang wajib dicatat:**
- Tanpa spread/komisi/slippage — PF live akan lebih rendah dari semua angka di atas.
- Feed backtest (Binance) ≠ feed live (Twelve Data); 92 trade T1 = sampel kecil-sedang.
- Cross terakhir di data (BUY @ 07 Okt 01:00 WIB) belum ada di hasil — datanya mentok 06 Okt.

## File
- `~/workspace/trading-ea/research/ema_trigger_backtest.py` — script uji T1
- Laporan ini: `~/workspace/trading-ea/research/ema_trigger_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — download ulang dari Binance Vision bila perlu)
