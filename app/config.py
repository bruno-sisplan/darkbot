"""Configuração fixa do darkbot (sem .env). Tudo que é chave ou parâmetro padrão fica aqui."""

VERSION = "0.1.0"

# Chaves embutidas. A chave salva em Configurações (se houver) tem prioridade sobre esta.
YOUTUBE_API_KEY = ""
ANTHROPIC_API_KEY = ""

# Coleta
DEFAULT_SCROLLS = 15
MAX_SCROLLS = 80
SCROLL_WAIT_MS = 1600          # espera entre scrolls para o YouTube carregar mais vídeos
STALE_SCROLLS_TO_STOP = 3      # para de rolar após N scrolls sem vídeo novo

# Cache da API (economia de cota)
VIDEO_REFRESH_HOURS = 6
CHANNEL_REFRESH_HOURS = 24

# Métricas
NEW_CHANNEL_DAYS = 180         # canal "novo" = criado há até 6 meses
SHORT_MAX_SECONDS = 60
