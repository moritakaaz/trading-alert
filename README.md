# XAUUSD Telegram Manual-Alert System

> ⚠️ **Bukan saran finansial.** Proyek eksperimen — dana yang dipakai adalah "uang belajar"
> (akun cent kecil). Jangan pakai untuk live trading tanpa paham risikonya.

Sistem alert entry **XAUUSD (M5)** yang mengirim sinyal ke Telegram: breakout
Donchian dengan filter trend, lengkap dengan jurnal otomatis, chart entry,
monitoring posisi (TP1/TP2/TP3 + breakeven), dan review performa mingguan.

## Strategi (v1.3, live)

| Komponen | Detail |
|---|---|
| Trigger | Breakout Donchian(48) di bar H1 completed, dievaluasi tiap close bar M5 |
| Stop loss | 1.5 × ATR(14) H1 |
| Take profit | TP1 1R → SL ke breakeven, TP2 1.5R, TP3 2R (runner) |
| Filter trend H4 | Hard filter — sinyal harus searah trend H4 (SMA15) |
| Filter EMA 20/50 | Hard filter — BUY hanya jika EMA20 > EMA50 di H1 (dan sebaliknya) |
| Manajemen | Satu posisi dalam satu waktu; tidak ada stacking sinyal |

**Hasil backtest jujur** (9 bulan, Jan–Okt 2026, 265 trade, data PAXGUSDT M5):

| Metrik | Angka |
|---|---|
| Profit Factor | **1.38** |
| Win rate | 33.6% |
| Rata-rata / trade | +0.18R |
| Max drawdown | 15.3R |

Catatan jujur: Q3 2026 strateginya merah. Belum termasuk spread/komisi/slippage —
hasil live **akan lebih rendah**. 265 trade = sampel sedang. Angka ini bukan janji.

## Arsitektur

```
scripts/
├── xauusd_entry_m5.sh    # Mesin utama: polling 5 menit, deteksi sinyal, kirim alert
├── xauusd_tg_cmd.sh      # Command handler Telegram (/cek, /chart, /riwayat, /trend, ...)
├── make_chart.py         # Render chart entry (matplotlib): Donchian + level SL/TP
├── entry_scoreboard.py   # Learning loop: nilai hasil tiap sinyal, review mingguan
├── xauusd_watchdog.py    # Dead man's switch: pastikan sistem tetap hidup
└── send_tg.py            # Pengirim Telegram (Bot API langsung)

data/
├── xauusd_ohlc.py        # Feed harga XAU/USD (Twelve Data, fallback Kraken PAXGUSD)
├── forex_news.py         # Headline berita forex (Finnhub) — warning keyword
└── release_calendar.py   # Kalender ekonomi: NFP/CPI/PPI/GDP (FRED)

research/                 # Backtest + laporan hasil (yang gagal juga didokumentasikan)
```

**Yang sudah dites dan DITOLAK** (biar nggak diulang): EMA-cross sebagai trigger,
filter sesi, SL 2.0×ATR, TP1 0.75R, filter breakout-depth, filter volatilitas,
EMA di M5/M15 sebagai filter, cooldown pasca-SL. Lihat `research/*_RESULTS.md`.

## Instalasi

```bash
git clone <repo-url>
cd xauusd-telegram-alert
cp .env.example .env
# isi TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVE_DATA_API_KEY di .env
```

1. Buat bot via [@BotFather](https://t.me/BotFather), catat token dan chat ID.
2. Daftar API key gratis di [Twelve Data](https://twelvedata.com) (feed utama).
   Opsional: [Finnhub](https://finnhub.io) (berita), [FRED](https://fred.stlouisfed.org) (kalender).
3. Sesuaikan path state/log di script dengan environment kamu
   (default mengacu ke `~/hooks/state/` dan `~/hooks/logs/`).
4. Jalankan `scripts/xauusd_entry_m5.sh` tiap 5 menit via cron/systemd.

> Catatan: script aslinya jalan di sebuah VM dengan pola kredensial khusus
> (`dynamic_credentials` surrogate). Untuk environment lain, ganti pemanggilan
> API di `data/*.py` dengan API key dari `.env` kamu secara langsung.

## Perintah Telegram

`/alert_on` `/alert_off` `/cek` `/chart` `/trend` `/riwayat` `/set_modal`
`/skip_trade` `/close_trade` `/cancel_trade` `/reset_trade`

## Lisensi

MIT — pakai, modifikasi, dan share dengan bebas. Risiko tetap milik masing-masing.
