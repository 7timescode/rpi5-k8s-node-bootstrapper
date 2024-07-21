import os
import subprocess
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.text import Text

app = typer.Typer()
# TODO: use https://rich.readthedocs.io/en/stable/logging.html#logging-handler
console = Console()

MIN_SYSTEM_SIZE = 20  # Minimum recommended system partition size in GB


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
                Panel(
                    result.stdout,
                    title_align="left",
                    title=Text("stdout", style="green"),
                    expand=False,
                    box=box.ROUNDED,
                )
            )
        if result.stderr:
            console.print(
                Panel(
                    result.stderr,
                    title_align="left",
                    title=Text("stderr", style="red"),
                    expand=False,
                    box=box.ROUNDED,
                )
            )
        if not result.stdout and not result.stderr:
            title = (
                "[green]Command succeeded[/green]"
                if result.returncode == 0
                else "[red]Command failed[/red]"
            )
            console.print(title)

    return result


def check_device_empty(device: str, debug: bool = False) -> bool:
    """
    Checks if the given device is empty. Returns True if the device is empty,
    otherwise returns False.
    """
    refresh_device_state(device, debug)
    result = run_command(f"lsblk {device}", debug=debug)
    return len(result.stdout.splitlines()) <= 2


def get_disk_capacity(device: str, debug: bool = False) -> int:
    """
    Gets the capacity of the specified disk in GB.
    """
    result = run_command(f"lsblk -b -d -o SIZE -n {device}", debug=debug)
    size_bytes = int(result.stdout.strip())
    size_gb = size_bytes / (1024**3)
    return size_gb


def erase_device(device: str, debug: bool):
    """
    Prompts the user for confirmation and erases all partitions on the given device.
    """
    if Confirm.ask(
        f"[yellow]Are you sure you want to erase all partitions on {device}?[/yellow]"
    ):
        console.print(f"[yellow]Erasing all partitions on {device}...[/yellow]")
        run_command(f"parted {device} --script mklabel msdos", debug)
        refresh_device_state(device, debug)
    else:
        raise typer.Abort("Operation cancelled.")


def copy_image_with_progress(image_path: str, device: str, debug: bool):
    """
    Copies the image to the device using dd and shows a progress percentage.
    """
    # Get the size of the image file
    image_size = os.path.getsize(image_path)

    command = f"dd if={image_path} of={device} bs=4M status=progress"

    with subprocess.Popen(
        command, shell=True, stderr=subprocess.PIPE, bufsize=1, text=True
    ) as proc, Progress(console=console) as progress:
        task = progress.add_task("Copying image...", total=image_size)
        for line in proc.stderr:
            # Extract the amount of data copied so far
            if "bytes" in line:
                parts = line.split()
                if len(parts) > 0 and parts[0].isdigit():
                    bytes_copied = int(parts[0])
                    progress.update(task, completed=bytes_copied)
        proc.wait()
    refresh_device_state(device, debug)


def refresh_device_state(device: str, debug: bool = False):
    console.print("[green]Refreshing the state of the device...[/green]")
    run_command(f"partprobe {device}", debug)


def get_partition_info(device: str, debug: bool = False):

    result = run_command(f"parted {device} -ms unit s print", debug)
    lines = result.stdout.splitlines()

    # Find the start and end sectors of the second partition
    partition_info = {}
    total_sectors = None
    for line in lines:
        if "BYT" in line:
            continue
        if f"{device}" in line:
            total_sectors = int(line.split(":")[1].replace("s", ""))
            continue

        index, start, end, length, filesystem = line.split(":")[:5]
        partition_info[index] = {
            "start": int(start.replace("s", "")),
            "end": int(end.replace("s", "")),
            "length": int(length.replace("s", "")),
            "filesystem": filesystem,
        }

    return total_sectors, partition_info


def align_sector(sector, alignment=2048):
    """
    Aligns the given sector to the nearest alignment boundary.
    """
    return ((sector + alignment - 1) // alignment) * alignment


@app.command()
def manage_disk(
    device: str,
    system_size: str = typer.Option(
        None, help="Size for the system partition (e.g., 128G)."
    ),
    image_path: str = typer.Option(None, help="The path of the image."),
    force: bool = typer.Option(
        False, "--force", "-f", help="Bypass empty device check."
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Enable debug mode to show command outputs."
    ),
):
    """
    Manages the disk by partitioning it, writing a preinstalled image, and setting up
    additional partitions. Prompts for input if not provided via command-line options.
    """
    refresh_device_state(device, debug)

    disk_capacity_gb = get_disk_capacity(device, debug)
    suggested_system_capacity = int(max(disk_capacity_gb / 3, 100))

    console.print(f"[green bold]Using device: {device}[/green bold]")
    if system_size is None:
        system_size = IntPrompt.ask(
            "Enter the size for the system partition (in GB)",
            default=suggested_system_capacity,
        )

    if image_path is None:
        image_path = Prompt.ask("Enter the image path")

    # Check if the image path exists and is a `.img` image
    path = Path(image_path)
    if path.exists() and path.is_file():
        if not path.suffix == ".img":
            if not Confirm.ask(
                f"[yellow]File {str(path)} does not appear to be an .img file. Are you sure?[/yellow]"
            ):
                raise typer.Abort()
    else:
        console.print(
            f"[red]Path {str(path)} does not exist. Please enter a valid .img file path.[/red]"
        )
        raise typer.Abort()

    # Check if the system partition size is within recommended limits
    if system_size < MIN_SYSTEM_SIZE:
        console.print(
            f"[red]The system partition size should be at least {MIN_SYSTEM_SIZE}GB.[/red]"
        )
        raise typer.Abort()

    # Check if the total size exceeds the disk capacity
    if system_size > disk_capacity_gb:
        console.print(
            f"[red]The system size ({system_size}GB) exceeds the disk capacity ({disk_capacity_gb}GB).[/red]"
        )
        raise typer.Abort()

    if system_size > disk_capacity_gb / 2:
        if not Confirm.ask(  # TODO: This doesn't work
            f"[yellow]The system size might be too large ({system_size}GB / {disk_capacity_gb}GB total). Are you sure?[/yellow]"
        ):
            raise typer.Abort()

    # Check if the device is empty, unless force flag is set
    if not check_device_empty(device, debug):
        if force:
            erase_device(device, debug)
        else:
            raise typer.Abort(
                f"The device {device} is not empty. Use --force to erase all partitions."
            )

    # Copy the image to the device with a progress bar
    copy_image_with_progress(image_path, device, debug)

    # Wait for the device to be recognized
    console.print("[green]Waiting for the device to be recognized...[/green]")
    subprocess.run("sleep 5", shell=True)

    # Check the partition table type
    result = run_command(f"fdisk -l {device}", debug)
    if "Disklabel type: dos" in result.stdout:
        console.print("[green]Detected DOS partition table.[/green]")
        # boot_partition = f"{device}1"
        system_partition = f"{device}2"
        additional_partition = f"{device}3"
    else:
        # TODO: what to do here?
        typer.Abort("Partition table is not DOS. Will not continue.")

    # Verify that the copied partition is valid and fix it if necessary
    console.print("[green]Checking and resizing the system partition...[/green]")

    # TODO: This fails (non existent device)
    run_command(f"e2fsck -f -y {system_partition} || true", debug)

    total_sectors, partition_info = get_partition_info(device, debug)
    if not partition_info.get("2"):
        console.print("[red]Could not get 2nd partition info[/red]")
        raise typer.Abort()

    # Align the end sector for the system partition
    system_size_sectors = (
        system_size * 1024 * 1024 * 1024 // 512
    )  # Convert GB to sectors
    system_partition_new_end = align_sector(
        partition_info["2"]["start"] + system_size_sectors
    )

    # # Calculate the end sector for the resized second partition
    # system_partition_new_end = partition_info['2']['start'] + system_size_sectors - 1  # Correctly calculate the end sector

    # Align the end sector to the nearest multiple of 2048
    # if system_partition_new_end % 2048 != 0:
    #     system_partition_new_end += 2048 - (system_partition_new_end % 2048)

    # Resize the partition
    run_command(
        f"parted {device} --script resizepart 2 {system_partition_new_end}s", debug
    )
    console.print("[green]Checking filesystem on resized partition...[/green]")

    # TODO: This might not be empty first time around (or even the second one)
    run_command(f"e2fsck -f -y {system_partition} || true", debug)

    # Create the additional partition
    console.print(
        "[green]Creating additional partition in the remaining space...[/green]"
    )

    # Create the additional partition using the end sector of the second partition
    console.print(
        "[green]Creating additional partition in the remaining space...[/green]"
    )

    # Calculate the end sector for the additional partition
    # additional_partition_start = system_partition_new_end + 1
    additional_partition_end = total_sectors - 1  # Use all remaining sectors
    if additional_partition_end % 2048 != 0:
        additional_partition_end -= additional_partition_end % 2048
    additional_partition_start = align_sector(system_partition_new_end + 1)
    # additional_partition_end = align_sector(total_sectors - 1)

    # additional_partition_start = int(partition_info["2"]) + 1
    run_command(
        f"parted {device} --script mkpart primary {additional_partition_start}s {additional_partition_end}s",
        debug,
    )

    # Format the new partition
    console.print("[green]Formatting the new partition...[/green]")
    run_command(f"mkfs.ext4 {additional_partition}", debug)

    console.print("[green]Checking filesystem on additional partition...[/green]")
    run_command(f"e2fsck -f -y {additional_partition} || true", debug)

    # Mount the new partition
    # uuid = (
    #     subprocess.check_output(
    #         f"blkid -s UUID -o value {additional_partition}", shell=True
    #     )
    #     .decode()
    #     .strip()
    # )
    # run_command("mkdir -p /mnt/data", debug)
    # run_command(
    #     f"echo 'UUID={uuid} /mnt/data ext4 defaults 0 2' | tee -a /etc/fstab", debug
    # )
    # run_command(f"mount {additional_partition} /mnt/data", debug)

    console.print("[green]Disk management complete.[/green]")

    # # TODO: configure cloud-init
    # # We'll need to mount the partitions probably to do that (maybe not the 3rd one, but still).


if __name__ == "__main__":
    typer.run(app())
