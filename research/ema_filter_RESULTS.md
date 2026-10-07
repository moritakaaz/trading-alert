# Uji EMA 20/50 sebagai Filter — Hasil Backtest (2026-10-07)

**Pertanyaan user:** "apa perlu kita tambahin indikator jika cross EMA 20 dan 50?" (setelah melihat chart dengan cross yang "menarik").
**Yang diuji:** EMA20/50 sebagai FILTER arah tambahan pada strategi live v1.1 — BUKAN strategi standalone (itu sudah pernah dites Okt 2026 dan kalah di semua simbol).
**Metode:** harness `fix6sl_backtest.py` (tervalidasi: replika n=529/PF=1.09 ≈ acuan 520/1.10). Data Binance PAXGUSDT M5 Jan–Okt 2026 (proxy XAUUSD). Semua varian diuji di data yang SAMA. Sinyal ter-suppress dijalankan sebagai "phantom trade" untuk mengukur PF-nya.
**Batasan:** tidak ada file live yang diubah. Script: `ema_filter_backtest.py`.

---

## 1. Hasil utama

| Varian | Jan–Okt n | win% | PF | avgR | totR | maxDD | Sep–Okt n | PF | totR | Suppress n | PF suppress |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v1.1 baseline | 265 | 31.3 | **1.23** | +0.11 | +29.1 | 19.1 | 31 | 0.75 | -4.0 | 0 | — |
| **F1: EMA20/50 state @H1** | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | **15.3** | 27 | **0.86** | **-2.0** | 52 | **0.20** |
| F2: EMA fresh-cross @H1 | 100 | 24.0 | 0.82 | -0.10 | -10.0 | 12.0 | 14 | 0.40 | -6.0 | 378 | 1.37 |
| F3: EMA20/50 state @M5 | 265 | 31.3 | 1.23 | +0.11 | +29.1 | 19.1 | 31 | 0.75 | -4.0 | 1 | — |

- **F1 MENANG JELAS.** PF 1.23→1.38, total R +29.1→+42.2, maxDD 19.1→15.3. Sinyal yang dibuang memang jelek (PF 0.20) — filter membuang yang busuk, bukan yang bagus. Konsisten juga di data terbaru Sep–Okt (0.75→0.86, rugi -4.0R→-2.0R). Biaya: ~10% lebih sedikit sinyal.
- **F2 DITOLAK TEGAS.** Cross "segar" malah membuang trade bagus (PF suppress 1.37!) dan menyisakan yang jelek (PF 0.82). Over-constraint klasik.
- **F3 TIDAK BERGUNA.** EMA M5 hampir selalu searah dengan breakout M5 — cuma 1 sinyal tersaring. Timeframe terlalu cepat untuk jadi filter.

## 2. Robustness F1 (apakah cuma kebetulan di 20/50?)

| Pasangan EMA | Jan–Okt PF | totR | Suppress n | PF suppress | Sep–Okt PF |
|---|---|---|---|---|---|
| 10/30 | 1.27 | +33.1 | 12 | 0.28 | 0.80 |
| 12/26 | 1.27 | +33.1 | 12 | 0.28 | 0.80 |
| **20/50 (usulan user)** | **1.38** | **+42.2** | 52 | 0.20 | **0.86** |
| 20/100 | 1.49 | +48.7 | 98 | 0.45 | 0.91 |
| 50/200 | 1.61 | +47.3 | 194 | 0.86 | 1.00 |

Arah perbaikan KONSISTEN di semua pasangan — mekanismenya (breakout searah trend menengah = lebih berkualitas) valid secara umum, bukan artefak satu angka. Catatan jujur: pasangan lebih lambat memberi PF lebih tinggi TAPI membunuh porsi trade lebih besar (50/200 membuang 40% sinyal). 20/50 adalah pilihan a priori user, bukan hasil optimasi — jadi tidak cherry-pick. Jangan tergoda ganti ke 50/200 hanya karena angkanya paling bagus di backtest.

F1(20/50) per bulan vs baseline: membaik/sama di 8 dari 10 bulan (Feb 1.30, Mar 1.61, Apr 1.56, Mei 1.40, Jun 1.59, Agu 1.03, Sep 1.00; Jan 2.73 vs 2.91 sedikit turun; Jul 0.61 vs 0.48 tetap merah tapi lebih baik; Okt n=2 terlalu kecil).

## 3. Diagnostik: 6 loss live kemarin vs F1

| Sinyal live | EMA20/50 H1 saat sinyal | F1 |
|---|---|---|
| BUY @4162.15, 4168.28, 4165.04 (05 Okt) | -9.00 / -8.19 (bearish) | TERSUPPRESS ×3 |
| SELL @4126 (05 Okt), @4125 (06 Okt) | -8.18 / -8.72 (bearish) | LOLOS (tetap loss) |
| BUY @4177 (06 Okt) | -8.72 (bearish) | TERSUPPRESS |

4 dari 6 loss akan tersuppress — rangkaian -6R menjadi -2R. Breakout melawan trend menengah memang sumber whipsaw utama.

## 4. Kesimpulan jujur & rekomendasi

**F1 (EMA20/50 state filter di H1) menambah edge secara nyata dan konsisten.** Ini filter trend menengah yang melengkapi (bukan menduplikasi) filter H4 yang sudah ada: H4 = trend besar, EMA20/50 = trend menengah. Mekanisme masuk akal, hasil konsisten lintas periode dan lintas parameter.

**Skeptisisme yang wajib dicatat:**
- Ide ini lahir dari 1 chart cantik — tapi validasinya 9 bulan data + robustness bracket, bukan 6 trade. Itu yang membedakannya dari overfitting.
- Tanpa spread/komisi/slippage — PF live akan lebih rendah dari semua angka di atas.
- Feed backtest (Binance) ≠ feed live (Twelve Data); 265 trade = sampel sedang.
- F1 tidak menyelamatkan 2 SELL yang loss — filter mengurangi whipsaw, bukan menghilangkannya.

**Rekomendasi: PASANG F1** — dengan persetujuan eksplisit user (ini perubahan logika sinyal). Implementasi ringan: 1 kondisi tambahan di fungsi filter sinyal (`diff = ema20-ema50 > 0` untuk BUY). Estimasi biaya: ~10% sinyal lebih sedikit. F2 dan F3 jangan dipasang.
