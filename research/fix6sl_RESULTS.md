# Investigasi 6 SL Beruntun XAUUSD — Hasil Riset (2026-10-06)

**Pertanyaan user:** "perbaiki signalnya" setelah 6 SL beruntun (-6R, ~-112 USC ≈ 19% modal).
**Metode:** rekonstruksi konteks 6 trade + re-backtest v1.1 di data terbaru + uji 3 kandidat perbaikan.
**Batasan:** tidak ada file live yang diubah. Semua angka dari backtest PAXGUSDT (Binance spot, proxy XAUUSD).

---

## 1. Pola 6 loss (jurnal 2026-10-05 s/d 2026-10-06)

| # | Sinyal | Waktu (WIB) | Sesi | H4 | Hasil |
|---|---|---|---|---|---|
| 1 | BUY @4162.15 | 05 Okt 14:50 | London | (v1.0, tanpa filter) | SL -1R |
| 2 | BUY @4168.28 | 05 Okt 15:10 | London | (v1.0) | SL -1R |
| 3 | BUY @4165.04 | 05 Okt 15:45 | London | (v1.0) | SL -1R |
| 4 | SELL @4126 | 06 Okt 00:10 | New York | BEARISH ✓ | SL -1R |
| 5 | SELL @4125 | 06 Okt 09:35 | Asia | BEARISH ✓ | SL -1R |
| 6 | BUY @4177 | 06 Okt 19:00 | London | BULLISH ✓ | SL -1R |

**Temuan pola:**
- **Keenamnya tidak pernah menyentuh TP1** (MFE maksimal 0.89R, dua di antaranya 0.00R — langsung balik arah). Ini mode loss yang "bersih": breakout palsu, bukan hampir-profit.
- **3 dari 6 adalah sinyal stacked v1.0** (trade 1–3, selisih 20–35 menit). Aturan one-position-at-a-time di v1.1 (sudah live) akan men-suppress trade 2 dan 3. Di bawah logika live saat ini, rangkaiannya hanya 4 SL (-4R), bukan 6.
- **Tidak ada pola sesi** (London 4×, NY 1×, Asia 1×). Filter H4 bekerja sesuai desain (semua sinyal searah trend) tapi tidak menyelamatkan — breakout searah trend pun bisa whipsaw.
- **Tidak ada rilis ekonomi FRED** (NFP/CPI/PPI/GDP) dalam ±1 hari dari keenam sinyal. FOMC memang tidak ter-cover kalender (blind spot struktural yang sudah diketahui).
- **Caveat feed:** data Binance PAXGUSDT memuat wick $4230 pada 2 Okt yang (dilihat dari sinyal live yang tetap fire) tidak ada di feed Twelve Data XAU/USD. Akibatnya boundary Donchian di backtest ≠ boundary live untuk sinyal yang mepet — rekonstruksi kondisi sinyal live per-trade di data Binance tidak 100% akurat. Backtest tetap valid sebagai uji *strategi*, tapi bukan replika 1:1 sinyal live.

**Apakah 6 SL beruntun anomali?** Tidak. Di backtest v1.1 Jan–Okt (265 trade), streak SL terpanjang = **tepat 6**, dan kejadian streak ≥6 SL muncul **3× dalam 9 bulan**. Yang dialami user = skenario terburuk yang sudah diketahui, bukan kerusakan strategi.

---

## 2. Re-backtest v1.1 di data terbaru (Sep–Okt 2026)

Replikasi setia logika live (Donchian(48) H1, trigger M5, SL 1.5×ATR H1, transition-only, H4 filter, one-position). Harness divalidasi: replika `m5_check2.py` menghasilkan n=529/PF=1.09 vs acuan riset n=520/PF=1.10 (match).

| Periode | n | Win% | PF | avgR | Total R | MaxDD |
|---|---|---|---|---|---|---|
| v1.1 Jan–Okt 2026 | 265 | 31.3 | **1.23** | +0.11 | +29.1 | 19.1 |
| v1.1 **Sep–Okt 2026** | 31 | 19.4 | **0.75** | -0.13 | -4.0 | 11.0 |

**Edge melemah di data terbaru** (PF 0.75, n=31). Tapi ini konsisten dengan temuan riset sebelumnya (Q3 2026 PF 0.94 — kuartal merah memang terjadi). Sampel Sep–Okt kecil (31 trade); belum cukup bukti untuk menyatakan edge hilang permanen.

Per bulan (v1.1): Jan PF 2.91 → Feb 1.17 → Mar 1.39 → Apr 1.08 → Mei 1.00 → Jun 1.68 → **Jul 0.48** → Agu 1.08 → **Sep 0.86** → Okt 0.00 (n=3). Sistem trend-following: panen saat trending (Jan, Jun), berdarah saat choppy (Jul, Sep).

---

## 3. Uji kandidat perbaikan (maksimal 3)

Semua diuji di data yang SAMA (Sep–Okt dan Jan–Okt). Yang sudah pernah ditolak (filter sesi, SL 2.0×, TP1 0.75R) tidak diuji ulang.

### C1: Syarat breakout minimal (depth ≥ 0.3×ATR) — ❌ DITOLAK TEGAS
Alasan awal: keenam loss tampak seperti breakout "tipis". Hasil:

| Periode | Baseline v1.1 | C1 |
|---|---|---|
| Sep–Okt | PF 0.75 (n=31) | PF **0.50** (n=14) |
| Jan–Okt | PF 1.23 (n=265) | PF **0.93** (n=117) |

Diagnostik tambahan: trade dengan depth < 0.3 ATR justru **PF 1.49** (n=171), sedangkan depth ≥ 0.3 ATR **PF 0.83** (n=94). Median depth trade WIN (0.14 ATR) < trade LOSS (0.21 ATR). **Edge strategi ini justru ada di breakout awal yang tipis** — menunggu konfirmasi lebih dalam malah masuk telat. Ini contoh textbook kenapa filter tidak boleh dirancang dari 6 trade.

### C2: Cooldown 12 jam setelah SL — ⚠️ MENARIK, tapi tipis
Alasan: loss berkerumun saat pasar choppy; jeda setelah SL menghindari whipsaw lanjutan.

| Periode | Baseline v1.1 | C2 (12h) |
|---|---|---|
| Sep–Okt | PF 0.75, totR -4.0 (n=31) | PF **0.86**, totR -2.0 (n=27) |
| Jan–Okt | PF 1.23, totR +29.1 (n=265) | PF **1.31**, totR +30.6 (n=213) |

Robustness parameter (dipilih arbitrer sebelum uji, lalu di-bracket): 6h → PF 1.24/0.80; 24h → PF 1.37/1.00. Arah perbaikan konsisten di semua parameter dan kedua periode — bukan hasil cherry-pick satu angka. Harga: frekuensi trade turun ~20%.

### C3: Skip saat ledakan volatilitas (ATR > 2× median 20) — ❌ TIDAK BERGUNA
Hampir tidak ada sinyal yang tersaring (n=264 vs 265). Kondisi yang dimaksud praktis tidak pernah terjadi di data 9 bulan. Ditolak.

---

## 4. Proposal (maksimal 2, angka jujur)

### Proposal A: Tambah cooldown 12 jam pasca-SL (butuh diskusi + approval)
- Ekspektasi dari backtest: PF 1.23 → ~1.31 (Jan–Okt), drawdown Sep–Okt -4.0R → -2.0R. Perbaikan **kecil** (+0.08 PF), bukan obat mujarab.
- Mekanisme masuk akal (hindari chop pasca-loss), konsisten di 6h/12h/24h — tapi tetap bisa jadi noise. Bukan janji profit.
- Biaya: ~20% lebih sedikit sinyal. Tidak mengubah definisi sinyal, hanya jeda antar-trade setelah rugi — overlay risk-management, bukan otak-atik logika entry.
- **Belum diimplementasikan.** Menunggu persetujuan eksplisit user sesuai aturan.

### Proposal B: Jangan ubah apa-apa (opsi valid)
- 6 SL = streak terburuk yang *diharapkan* muncul ~3×/tahun menurut backtest 9 bulan. Sistem berperilaku sesuai distribusinya.
- 2 dari 6 loss berasal dari stacking v1.0 yang sudah diperbaiki one-position-at-a-time di v1.1.
- Kelemahan Sep–Okt (PF 0.75) konsisten dengan Q3 merah yang sudah diketahui; n=31 terlalu kecil untuk vonis "edge hilang".
- Biarkan learning loop (review Minggu) yang menilai dengan data lebih banyak.

---

## 5. Peringatan overfitting & caveat
- **6 trade = sampel anekdot.** C1 adalah buktinya: pola yang "jelas" di 6 trade ternyata terbalik di 265 trade. Jangan pernah tuning dari streak.
- Gain C2 (+0.08 PF) tipis dan bisa noise; jangan oversell.
- Backtest feed (Binance PAXGUSDT) ≠ live feed (Twelve Data XAU/USD); sinyal boundary-touching bisa berbeda.
- Tanpa spread/komisi/slippage — PF live akan lebih rendah dari semua angka di atas.
- 265 trade masih sampel sedang; edge bisa hilang berbulan-bulan (terbukti Jul & Sep).

## File
- `~/workspace/trading-ea/research/fix6sl.py` — rekonstruksi konteks 6 trade (Part A)
- `~/workspace/trading-ea/research/fix6sl_backtest.py` — harness backtest v1.1 (tervalidasi vs m5_check2: n=529/PF=1.09 ≈ acuan 520/1.10)
- `~/workspace/trading-ea/research/fix6sl_candidates.py` — uji C1/C2/C3 + diagnostik
- Laporan ini: `~/workspace/trading-ea/research/fix6sl_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — download ulang dari Binance Vision bila perlu)
