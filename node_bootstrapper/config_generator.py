from configparser import ConfigParser
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import jinja2
import rich
import typer
from passlib.hash import sha512_crypt
from rich.prompt import Confirm, Prompt
from typing_extensions import Annotated

from node_bootstrapper.utils import (
    get_panel,
    refresh_device_state,
    run_command,
    success_style,
    warning_style,
)

console = rich.console.Console()

THIS_PATH = Path(__file__).resolve().parent

TEMPLATE_PATH = THIS_PATH / Path("./templates/")
OUTPUT_PATH = THIS_PATH / Path("../output/")

CLOUD_INIT_TEMPLATE_PATH = TEMPLATE_PATH / "cloud-init/"
CLOUD_INIT_OUTPUT_PATH = OUTPUT_PATH / "cloud-init/"

CONFIGURATION_FILE = THIS_PATH / Path("../config.ini")


app = typer.Typer(no_args_is_help=True)


def get_from_config(
    config: ConfigParser, key: str, section: str = "config_generator"
) -> str:
    try:
        return config[section][key]
    except KeyError:
        console.print(f"Missing required configuration value: {key}")
        raise typer.Abort()


@app.command()
def cloud_init_config(
    device: str,
    hosts_number: Annotated[
        int, typer.Option(help="The number of hosts to generate config for.")
    ] = 4,
    offset: Annotated[
        int,
        typer.Option(
            help="The offset to use (e.g. if you've already got config for 3 hosts and need for 1 more)."
        ),
    ] = 0,
    setup_eth: Annotated[
        bool,
        typer.Option(
            help="Whether to generate config for the ethernet network interface or not.",
        ),
    ] = True,
    setup_wifi: Annotated[
        bool,
        typer.Option(
            help="Whether to generate config for the WiFi network interface or not.",
        ),
    ] = False,
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Enable debug mode to show command outputs."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force generation of config even if it already exists.",
    ),
):

    config = ConfigParser()
    config.read(CONFIGURATION_FILE)

    def _get_from_config(key: str) -> str:
        return get_from_config(config, key)

    gateway = IPv4Address(_get_from_config("gateway"))
    if not setup_eth and not setup_wifi:
        raise typer.Abort("Need to setup either ethernet or WiFi network.")

    if setup_eth:
        eth_network = IPv4Network(_get_from_config("eth_network"))
    if setup_wifi:
        wifi_network = IPv4Network(_get_from_config("wifi_network"))

    jinja_environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(CLOUD_INIT_TEMPLATE_PATH)
    )

    for host_idx in range(1 + offset, hosts_number + 1 + offset):
        hostname = _get_from_config("hostname_string").format(
            num=str(host_idx).zfill(2)
        )
        console.print(f"Working on host: {hostname}", style="green bold")

        host_dir = CLOUD_INIT_OUTPUT_PATH / hostname
        host_dir.mkdir(exist_ok=True if force else False, parents=True)
        password_hash = sha512_crypt.using(rounds=5000, salt="s4ltsltsALLT").hash(
            _get_from_config("local_admin_acc_password")
        )

        user_data_template = jinja_environment.get_template("user-data.j2")
        user_data_content = user_data_template.render(
            hostname=hostname,
            remote_admin_acc_ssh_key=_get_from_config("remote_admin_acc_ssh_key"),
            remote_admin_acc_username=_get_from_config("remote_admin_acc_username"),
            local_admin_acc_username=_get_from_config("local_admin_acc_username"),
            local_admin_acc_password=password_hash,
        )

        user_data_file_path = host_dir / "user-data"
        with open(user_data_file_path, "w") as user_data_file:
            user_data_file.write(user_data_content)
            if debug:
                console.print(
                    get_panel(
                        text=user_data_content, title="user-data", border_style="white"
                    )
                )

        network_config_template = jinja_environment.get_template("network-config.j2")

        render_args = {
            "gateway": gateway,
        }
        if setup_wifi:
            wifi_address = wifi_network[host_idx - 1]
            render_args["setup_wifi"] = True
            render_args["wifi_address"] = str(wifi_address)
            render_args["wifi_ssid"] = _get_from_config("wifi_ssid")
            render_args["wifi_password"] = _get_from_config("wifi_password")
        if setup_eth:
            eth_address = eth_network[host_idx - 1]
            render_args["setup_eth"] = True
            render_args["eth_address"] = str(eth_address)
        network_config_content = network_config_template.render(**render_args)

        network_config_file_path = host_dir / "network-config"
        with open(network_config_file_path, "w") as network_config_file:
            network_config_file.write(network_config_content)
            if debug:
                console.print(
                    get_panel(
                        text=network_config_content,
                        title="network-config",
                        border_style="white",
                    )
                )

        console.print(
            "Finished generating cloud-init configuration.", style=success_style
        )

        if Confirm.ask(
            rich.text.Text(
                "Want to copy cloud-init configuration files on the boot partition?",
                style=warning_style,
            )
        ):
            while not Confirm.ask(
                rich.text.Text("Is the correct disk inserted?", style=warning_style)
            ):
                pass

            output = run_command(f"lsblk {device}", debug=debug)
            console.print(
                rich.panel.Panel(
                    output.stdout, title="Available Devices", box=rich.box.ROUNDED
                )
            )
            partition_to_use = Prompt.ask("Enter the partition to use")
            refresh_device_state(partition_to_use, debug=debug)
            # Mount the new partition
            run_command("mkdir -p /mnt/data", debug)
            # run_command(f"echo 'UUID={uuid} /mnt/data ext4 defaults 0 2' | tee -a /etc/fstab", debug)
            run_command(f"mount {partition_to_use} /mnt/data", debug)

            console.print("Copying user-data to /boot", style=success_style)
            run_command(f"cp {user_data_file_path} /mnt/data", debug)
            console.print("Copying network-config to /boot", style=success_style)
            run_command(f"cp {network_config_file_path} /mnt/data", debug)
            console.print("Copying cmdline.txt (enables cgroups).")
            run_command(
                f"cp {TEMPLATE_PATH / "cmdline.txt"} /mnt/data/cmdline.txt", debug
            )
            console.print("Copying config.txt.")
            run_command(
                f"cp {TEMPLATE_PATH / "config.txt"} /mnt/data/config.txt", debug
            )

            console.print(
                f"Unmounting partition {partition_to_use}", style=success_style
            )
            run_command("umount /mnt/data", debug)
            console.print(
                "Finished copying cloud-init configuration.", style=success_style
            )


if __name__ == "__main__":
    app()
