"""Parâmetros fixos do darkbot. As CHAVES não ficam aqui: ficam na aba Configurações do app (banco local)."""

VERSION = "0.1.0"


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
SHORT_MAX_SECONDS = 180       # shorts vão até 3 min; são ignorados em tudo

# IA (Claude). Haiku para tarefas objetivas e em massa; Sonnet para análise e síntese.
AI_MODEL_FAST = "claude-haiku-4-5"
AI_MODEL_SMART = "claude-sonnet-5-5"
# Equivalentes da OpenAI (padrão; dá para trocar em Configurações pela lista de modelos da conta).
# Testado em 30/09/2026 com a conta do usuário: gpt-5.4-mini foi o que mais concordou com o Haiku no juiz de
# relevância (e tem preço parecido); gpt-6.1-sol tem o mesmo preço do Sonnet 5.5.
OPENAI_MODEL_FAST = "gpt-5.4-mini"   # no lugar do Haiku: rápido e barato
OPENAI_MODEL_SMART = "gpt-6.1-sol"   # no lugar do Sonnet: análises e relatórios
# US$ por 1 milhão de tokens: (entrada, saída). Só para mostrar o gasto no app.
# US$ por 1 milhão de tokens: (entrada, entrada em cache, saída). Preços oficiais em 30/09/2026
# (OpenAI: developers.openai.com/api/docs/pricing; Anthropic: tabela de modelos da Anthropic).
# Modelos com data no nome (ex.: gpt-5.4-mini-2026-03-17) usam o preço do nome base.
AI_PRICES = {
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
    "claude-sonnet-5-5": (2.00, 0.20, 10.00),
    "claude-sonnet-5": (2.00, 0.20, 10.00),
    "claude-sonnet-4-6": (3.00, 0.30, 15.00),
    "claude-opus-5-5": (4.00, 0.20, 20.00),
    "claude-opus-5": (5.00, 0.50, 25.00),
    "claude-opus-4-8": (5.00, 0.50, 25.00),
    "claude-fable-5-1": (10.00, 0.25, 50.00),
    "gpt-6-astra": (10.00, 1.00, 50.00),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6-sol": (2.00, 0.20, 10.00),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-5.6-sol": (4.00, 0.40, 20.00),
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.2": (1.75, 0.175, 14.00),
    "gpt-5.1": (1.25, 0.125, 10.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "o3": (2.00, 0.50, 8.00),
    "o4-mini": (1.10, 0.275, 4.40),
}
# Tokens medidos por tarefa (entrada, saída), por nível de modelo. Só para a estimativa de custo da tela.
TASK_TOKENS = {
    "pesquisa": ("Uma pesquisa (sem relatório)", {"fast": (48000, 5000)}),
    "relatorio": ("Relatório da pesquisa", {"smart": (12000, 6000)}),
    "analise": ("Análise de um vídeo", {"smart": (3500, 2500)}),
    "variacoes": ("Ideias de variações", {"smart": (3000, 2200)}),
    "malandro": ("Método Malandro", {"fast": (6500, 1800)}),
    "proximos": ("Próximos vídeos: vídeos para modelar e mapa", {"fast": (11500, 2700), "smart": (5500, 2800)}),
    "dna": ("Próximos vídeos: DNA do canal", {"smart": (900, 450)}),
}
# "Potencial": o vídeo furou a própria base OU está ganhando tração. O resto é ruído na pesquisa.
POTENTIAL_MIN_MULT = 1.0
POTENTIAL_MIN_VIEWS_DAY = 1000
AI_NICHE_TITLES = 80           # quantos títulos a IA vê para detectar o nicho
AI_NICHE_MIN_TITLES = 15       # abaixo disso não vale a pena perguntar
