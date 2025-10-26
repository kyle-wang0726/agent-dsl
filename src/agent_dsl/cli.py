import json
from pathlib import Path
import click

from .parser import parse as parse_text
from .runtime import Engine

@click.group(help="Agent DSL command-line tool.")
def cli() -> None:
    pass

@cli.command("run", help="Run a DSL file from its first state.")
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--flow", default="main", show_default=True, help="Flow name to run")
@click.option("--var", multiple=True, help="预置变量，形如 name=Alice，可重复传入多次")
@click.option("--data", type=click.Path(dir_okay=False, path_type=Path),
              help="上下文 JSON 文件；启动时加载，结束时保存")
@click.option("--no-save", is_flag=True, help="与 --data 同用时，运行结束不回写上下文")
@click.option("--llm", type=click.Choice(["none", "deepseek"]), default="none",
              show_default=True, help="是否启用LLM意图识别")
def run_cmd(script: Path, flow: str, var: tuple[str, ...], data: Path | None,
            no_save: bool, llm: str) -> None:
    text = script.read_text(encoding="utf-8")
    prog = parse_text(text)

    ctx: dict[str, str] = {}
    for item in var:
        if "=" not in item:
            raise click.UsageError(f"--var 需要 name=value 形式，收到：{item}")
        k, v = item.split("=", 1)
        ctx[k] = v

    if data and data.exists():
        try:
            raw = json.loads(data.read_text(encoding="utf-8") or "{}")
            if isinstance(raw, dict):
                ctx.update({k: str(v) for k, v in raw.items()})
        except Exception:
            pass

    def ask_fn(k: str, prompt: str) -> str:
        return click.prompt(prompt, type=str)

    use_llm = (llm == "deepseek")
    eng = Engine(prog, flow_name=flow, context=ctx, ask_fn=ask_fn, use_llm=use_llm)

    for line in eng.run_iter():
        click.echo(line)

    if data and not no_save:
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(json.dumps(eng.ctx, ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> None:
    cli()

if __name__ == "__main__":
    main()
