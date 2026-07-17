"""
coffee.py
Arbor 主入口

用法:
    from coffee import CoffeeSystem   # backward compat
    system = CoffeeSystem()
    system.start()
"""

from coffee_system import CoffeeSystem  # noqa: F401 — backward compat


def main():
    """CLI 入口 — 委托给 cli.coffee_cli"""
    from cli.coffee_cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
