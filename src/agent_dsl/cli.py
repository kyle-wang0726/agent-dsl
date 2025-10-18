# src/agent_dsl/cli.py
import click
from pathlib import Path
from .parser import parse as parse_text
from .runtime import Engine

@click.group(help="Agent DSL command-line tool.")
def cli() -> None:
    pass

@cli.command("hello", help="Say hello.")
@click.option("--name", "-n", default="world", show_default=True, help="Name to greet")
def hello(name: str) -> None:
    click.echo(f"Hello, {name}!")

@cli.command("parse", help="Parse a DSL file and show the structure.")
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def parse_cmd(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    prog = parse_text(text)
    for flow_name, flow in prog.flows.items():
        click.echo(f"[flow] {flow_name}")
        for st_name, st in flow.states.items():
            click.echo(f"  [state] {st_name}")
            for a in st.actions:
                click.echo(f"    - {a.kind}: {a.args}")

@cli.command("run", help="Run a DSL file from its first state.")
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--flow", default="main", show_default=True, help="Flow name to run")
@click.option("--var", multiple=True, help="预置变量，形如 name=Alice，可重复传入多次")
def run_cmd(script: Path, flow: str, var: tuple[str, ...]) -> None:
    text = script.read_text(encoding="utf-8")
    prog = parse_text(text)
    ctx: dict[str, str] = {}
    for item in var:
        if "=" not in item:
            raise click.UsageError(f"--var 需要 name=value 形式，收到：{item}")
        k, v = item.split("=", 1)
        ctx[k] = v

    def ask_fn(k: str, prompt: str) -> str:
        # 让提示更友好
        return click.prompt(prompt, type=str)

    eng = Engine(prog, flow_name=flow, context=ctx, ask_fn=ask_fn)

    for line in eng.run_iter():
        click.echo(line)

def main() -> None:
    cli()

if __name__ == "__main__":
    main()
