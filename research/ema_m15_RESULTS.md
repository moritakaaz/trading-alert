# Uji EMA 20/50 di M15 sebagai Filter — Hasil Backtest (2026-10-07)

**Pertanyaan user:** stack multi-timeframe — M5 untuk entry scalping, M15 untuk lihat trend, H1 untuk konfirmasi. "Alangkah baiknya di TF M5 juga dipasang dan di testing." (M5 sudah dites di F3: tidak berguna.)
**Yang diuji:** filter EMA20/50 STATE di M15 di atas baseline v1.2 (= v1.1 + filter EMA20/50 state @H1, live sejak 2026-10-07).
**Metode:** harness `ema_m15_backtest.py` (pola `run_ema` dari `ema_filter_backtest.py`, basis `fix6sl_backtest.py` yang tervalidasi). M15 diresample dari bar M5 (pola sama seperti pembentukan H1). Tanpa lookahead: untuk sinyal di bar M5 (open ts), dipakai bar M15 terakhir yang sudah close: `k = bisect_left(m15t, ts - ts%900) - 1`. Data Binance PAXGUSDT M5 Jan–Okt 2026 (proxy XAUUSD). Sinyal ter-suppress dijalankan sebagai phantom trade per filter penyebabnya.
**Batasan:** tidak ada file live yang diubah. Script: `ema_m15_backtest.py`.

---

## 1. Hasil utama

| Varian | Jan–Okt n | win% | PF | avgR | totR | maxDD | Sep–Okt n | PF | totR |
|---|---|---|---|---|---|---|---|---|---|
| v1.2 baseline (H4 + EMA-H1) | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | 15.3 | 27 | 0.86 | -2.0 |
| **G1: v1.2 + EMA-M15** | 235 | 33.6 | 1.39 | +0.18 | +42.2 | 15.3 | 27 | 0.86 | -2.0 |
| **G2': v1.1 + EMA-M15 (ganti H1)** | 261 | 31.4 | 1.24 | +0.12 | +30.1 | 19.1 | 31 | 0.75 | -4.0 |

Sinyal ter-suppress (phantom, Jan–Okt):

| Varian | supH1 n | PF supH1 | supM15 n | PF supM15 |
|---|---|---|---|---|
| v1.2 baseline | 52 | 0.20 | — | — |
| G1 | 52 | 0.20 | **4** | 0.67 |
| G2' | — | — | **4** | 0.67 |

- **G1: tidak menambah apa-apa.** PF 1.38→1.39 (noise), totR identik +42.2, maxDD identik. Filter M15 cuma membuang 3 sinyal tambahan dari 238 — praktis tidak bekerja.
- **G2': M15 sendirian ≈ tanpa filter.** PF 1.24 ≈ v1.1 (1.23), totR +30.1 ≈ +29.1. Filter H1-lah yang mengerjakan semuanya; M15 tidak bisa menggantikannya.
- Di data terbaru Sep–Okt, G1 identik persis dengan v1.2 (M15 tidak membuang satu pun sinyal).

Validasi harness: baseline v1.2 di script ini (n=238, PF=1.38, totR=+42.2, maxDD=15.3) **match persis** dengan `ema_filter_RESULTS.md` — angka antar-varian comparable.

## 2. Diagnostik redundansi (sinyal kandidat pasca-H4, Jan–Okt, n=290)

| | H1 lolos | M15 membuang di antaranya | M15 lolos | H1 membuang di antaranya | Keduanya buang |
|---|---|---|---|---|---|
| v1.2 / G1 | 238 | **3 (1.3%)** | 286 | 51 (17.8%) | 1 |

Asimetris total: M15 hampir tidak pernah memblokir sinyal yang lolos H1 (1.3%), sedangkan H1 memblokir 17.8% dari yang lolos M15. **M15 bukan filter yang redundan-dua-arah — dia filter yang hampir tidak pernah aktif.** Dari 290 sinyal kandidat, M15 cuma membuang 4.

## 3. Kenapa M15 tidak berguna (penjelasan mekanis)

Saat breakout Donchian terjadi di M5 close **dan** trend H1 (20–50 jam) sudah selaras, trend M15 (5–12,5 jam) secara mekanis hampir selalu sudah selaras juga — MA cepat tidak mungkin tertinggal jauh tepat di momen breakout kuat searah trend menengah. Filter M15 hanya akan aktif di momen-momen whipsaw mikro di mana M15 berbalik sesaat — dan data menunjukkan momen itu hampir tidak pernah bertepatan dengan sinyal (4 dari 290). Ini pola yang sama dengan F3 (EMA @M5): **semakin cepat timeframe EMA, semakin dia "selalu setuju" dengan breakout di timeframe trigger** — sehingga sebagai filter dia tidak menyaring apa-apa.

Stack lengkap M5→M15→H1 sekarang sudah dites semua: M5 tidak berguna (F3, 1/265 tersaring), M15 tidak berguna (G1, 4/290), H1 yang bekerja (F1, PF 1.23→1.38).

## 4. Kesimpulan jujur & rekomendasi

**Jangan tambah filter EMA-M15.** Hasilnya netral (bukan negatif, bukan positif) — menambahkannya hanya menambah kompleksitas tanpa edge. Rekomendasi: tetap di v1.2 (H4 + EMA-H1) apa adanya.

**Skeptisisme yang wajib dicatat:**
- User pede "pasti bener lagi" setelah F1 menang — tapi justru di sinilah disiplin backtest penting: ide yang terasa benar pun harus dites, dan kali ini jawabannya "tidak".
- PF 1.39 vs 1.38 pada G1 adalah noise (3 trade beda dari 238), bukan perbaikan.
- Tanpa spread/komisi/slippage; feed backtest (Binance) ≠ feed live (Twelve Data); 265 trade = sampel sedang.

## File
- `~/workspace/trading-ea/research/ema_m15_backtest.py` — script uji G1/G2'
- Laporan ini: `~/workspace/trading-ea/research/ema_m15_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — download ulang dari Binance Vision bila perlu)
