from .repl import main as repl

try:
    from .telegram_bot import main as telegram_bot
except ImportError:

    def telegram_bot():
        print("telegram_bot is not available. ensure all dependencies are installed.")


__all__ = ["repl", "telegram_bot"]
