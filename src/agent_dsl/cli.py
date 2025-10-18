# src/agent_dsl/cli.py
import click

@click.group(help="Agent DSL command-line tool.")
def cli() -> None:
    pass

@cli.command("hello", help="Say hello.")
@click.option("--name", "-n", default="world", show_default=True, help="Name to greet")
def hello(name: str) -> None:
    click.echo(f"Hello, {name}!")

def main() -> None:
    cli()  # 注意：这里调用的是 click 的命令组

if __name__ == "__main__":
    main()
