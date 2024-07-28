import subprocess

import rich
import typer

# TODO: use https://rich.readthedocs.io/en/stable/logging.html#logging-handler
console = rich.console.Console()


def get_panel(text: str, title: str, border_style: str):
    return rich.panel.Panel(
        text,
        title=title,
        title_align="left",
        expand=False,
        box=rich.box.ROUNDED,
        border_style=border_style,
    )


def run_command(command: str, debug: bool = False):
    """
    Runs a shell command and prints the command in gray. If the command succeeds,
    prints a success message in green; if it fails, prints the error in red and exits.
    If debug is True, prints the output of the command.
    """
    console.print(f"Running: {command}", style="bold")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if debug or result.returncode != 0:
        if result.stdout:
            console.print(
                get_panel(
                    text=result.stdout,
                    title=rich.text.Text("stdout", style="green bold"),
                    border_style="green",
                )
            )
        if result.stderr:
            console.print(
                get_panel(
                    text=result.stderr,
                    title=rich.text.Text("stderr", style="red bold"),
                    border_style="red",
                )
            )

        if not result.stdout and not result.stderr:
            title = (
                "[green]Command succeeded[/green]"
                if result.returncode == 0
                else "[red]Command failed[/red]"
            )
            console.print(title)
    if result.returncode != 0:
        raise typer.Abort()

    return result


def refresh_device_state(device: str, debug: bool = False):
    console.print("[green]Refreshing the state of the device...[/green]")
    run_command(f"partprobe {device}", debug)


warning_style = rich.style.Style(color="yellow", bold=True)
error_style = rich.style.Style(color="red", bold=True)
success_style = rich.style.Style(color="green")
