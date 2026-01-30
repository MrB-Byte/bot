# 🛸 Koyeb Deployment Guide

## 100% Kostenlose 24/7 Bot-Hosting - KEIN Sleep-Modus!

### ✅ Warum Koyeb?
- **100% Kostenlos**: Dauerhaft kostenlos
- **Kein Sleep**: Läuft 24/7 ohne Unterbrechung
- **Docker Support**: Perfekt für Python Bots
- **Einfaches Setup**: Direkt von GitHub

### 🚀 Schritt-für-Schritt Setup

#### 1. GitHub Repository vorbereiten
- Alle Dateien sind bereits vorbereitet
- `Dockerfile` ist erstellt
- Bot erkennt Koyeb automatisch

#### 2. Koyeb Account erstellen
1. Gehe zu https://www.koyeb.com
2. Registriere dich mit GitHub (kostenlos)
3. Bestätige deine E-Mail

#### 3. App erstellen
1. Klicke "Create App"
2. Wähle "GitHub" als Source
3. Verbinde dein Repository
4. Name: `mib-bot`

#### 4. Konfiguration
- **Build Method**: Docker
- **Dockerfile Path**: `Dockerfile` (automatisch erkannt)
- **Port**: 8000 (automatisch)
- **Health Check**: `/health`

#### 5. Environment Variables setzen
```
TELEGRAM_TOKEN=8584873682:AAFNSd3dJ-kCj_uP-vUT0Iy7R5XS4tSQiok
GROUP_CHAT_ID=-1002027888526
SUPABASE_URL=https://hocqzefbbnowautoldvw.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhvY3F6ZWZiYm5vd2F1dG9sZHZ3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTY4NDU2NiwiZXhwIjoyMDg1MjYwNTY2fQ.fixKmVmcUNeqebl0IRpJO3ENUcbVQ1fqEJ3Ycv3vfQg
GEMINI_API_KEY=AIzaSyD6LTSd0Si8IfqD407ub4ZLhGAZazOCcxQ
KOYEB_ENVIRONMENT=true
```

#### 6. Deploy
1. Klicke "Deploy"
2. Warte auf Build (ca. 3-5 Minuten)
3. Bot startet automatisch!

### 🎯 Vorteile von Koyeb
- ✅ **Echtes 24/7**: Kein Sleep-Modus wie bei Render
- ✅ **Schnell**: Bessere Performance als andere kostenlose Anbieter
- ✅ **Zuverlässig**: Weniger Ausfälle
- ✅ **Auto-Deploy**: Bei jedem Git Push
- ✅ **Health Monitoring**: Integriert

### 📊 Nach dem Deployment
1. **Bot Status prüfen**: `/stats` in Telegram
2. **Health Check**: `https://your-app.koyeb.app/health`
3. **Logs**: Im Koyeb Dashboard
4. **Website**: Bleibt auf Vercel (nur Frontend)

### 🔧 Features
- **Sync**: Alle 30 Sekunden
- **Daily Jobs**: Geburtstage (8 AM), Grüße (7 AM)
- **Polling**: Echtes 24/7 ohne Webhook-Probleme
- **Health Server**: Läuft parallel auf Port 8000

### 💡 Monitoring
- Koyeb Dashboard zeigt Live-Status
- Health-Endpoint für externe Monitoring
- Telegram `/stats` für Bot-Status

## 🚀 Ready to Deploy!
Alle Dateien sind vorbereitet. Einfach zu Koyeb gehen und deployen!