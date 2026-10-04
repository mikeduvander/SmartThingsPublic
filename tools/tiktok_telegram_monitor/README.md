# TikTok → Telegram-monitor

Scriptet søger hvert minut efter TikTok-videoer under søgeordet **Vollsmose** og
sender nye resultater til en Telegram-chat. Første kørsel gemmer de eksisterende
resultater som udgangspunkt, så chatten ikke bliver fyldt med gamle videoer.

> TikTok har ikke et stabilt, offentligt søge-API til dette formål. Løsningen
> bruger derfor det uofficielle `TikTokApi` og kan kræve et nyt `msToken`, hvis
> TikTok ændrer sin hjemmeside eller udløber din cookie.

## Konfiguration

Telegram bot-tokenet og standard-chat-id'et er allerede indsat øverst i
`tiktok_monitor.py`. Chat-id'et kan om nødvendigt tilsidesættes med
miljøvariablen `KOE_TELEGRAM_CHAT_ID`. Alle parametre og den fastlåste
dependency findes nu i samme Python-fil; der bruges ingen `.env`- eller
`requirements.txt`-fil.

### Find TikToks `msToken`

1. Log ind på `https://www.tiktok.com` i en browser, og søg én gang efter
   `Vollsmose` (TikTok knytter søgeadgangen til sessionen).
2. Åbn udviklerværktøjer → **Application/Storage** → **Cookies**.
3. Kopiér værdien for cookien `msToken`, og indsæt den i konstanten
   `TIKTOK_MS_TOKEN` øverst i `tiktok_monitor.py`. Den kan alternativt angives
   som miljøvariablen `TIKTOK_MS_TOKEN`.

## Installation og start

Python 3.10 eller nyere anbefales.

```bash
cd tools/tiktok_telegram_monitor
python3 -m venv .venv
source .venv/bin/activate
python tiktok_monitor.py --install-dependencies
python tiktok_monitor.py
```

Installationskommandoen læser den fastlåste TikTokApi-version direkte fra
`REQUIRED_PACKAGES` i scriptet og installerer også Playwright Chromium.

Scriptet fortsætter selv efter en midlertidig TikTok-fejl. Stop det med
`Ctrl+C`. Brug `python tiktok_monitor.py --once` til én enkelt kontrol, f.eks.
hvis scriptet i stedet startes hvert minut via cron.

## Drift med systemd

Lad helst scriptet køre kontinuerligt frem for at starte en ny browser hvert
minut. Eksempel på `/etc/systemd/system/tiktok-monitor.service`:

```ini
[Unit]
Description=TikTok Vollsmose Telegram monitor
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/sti/til/SmartThingsPublic/tools/tiktok_telegram_monitor
ExecStart=/sti/til/SmartThingsPublic/tools/tiktok_telegram_monitor/.venv/bin/python tiktok_monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Aktivér den med:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tiktok-monitor
sudo journalctl -u tiktok-monitor -f
```

Allerede sete video-id'er gemmes i `seen_videos.json`. Slet filen for at danne
et nyt udgangspunkt. Søgeord, interval, antal resultater og state-fil kan
ændres via konstanterne øverst i `tiktok_monitor.py` eller de tilsvarende
miljøvariabler.
