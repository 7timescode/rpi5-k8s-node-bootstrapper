import os
import subprocess
from pathlib import Path

import rich
import typer
from rich.progress import Progress
from rich.prompt import Confirm, IntPrompt, Prompt

from node_bootstrapper.utils import (
    error_style,
    refresh_device_state,
    run_command,
    success_style,
    warning_style,
)

app = typer.Typer(no_args_is_help=True)
console = rich.console.Console()

MIN_SYSTEM_SIZE = 20  # Minimum recommended system partition size in GB


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
        rich.text.Text(
            f"Are you sure you want to erase all partitions on {device}?",
            style=warning_style,
        ),
    ):
        console.print(f"Erasing all partitions on {device}...", style=warning_style)
        run_command(f"parted {device} --script mklabel msdos", debug)
        refresh_device_state(device, debug)
    else:
        console.print("Operation cancelled.", style=error_style)
        raise typer.Abort()


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
def manage_partitions(
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

    console.print(f"Using device: {device} ({disk_capacity_gb}GB)", style=success_style)
    if system_size is None:
        system_size = IntPrompt.ask(
            "Enter the size for the system partition in GB",
            default=suggested_system_capacity,
        )

    if image_path is None:
        image_path = Prompt.ask("Enter the image path")

    # Check if the image path exists and is a `.img` image
    path = Path(image_path)
    if path.exists() and path.is_file():
        if not path.suffix == ".img":
            if not Confirm.ask(
                rich.text.Text(
                    f"File {str(path)} does not appear to be an .img file. Are you sure?",
                    style=warning_style,
                )
            ):
                raise typer.Abort()
    else:
        console.print(
            f"Path {str(path)} does not exist. Please enter a valid .img file path.",
            style=error_style,
        )
        raise typer.Abort()

    # Check if the system partition size is within recommended limits
    if system_size < MIN_SYSTEM_SIZE:
        console.print(
            f"The system partition size should be at least {MIN_SYSTEM_SIZE}GB.",
            style=error_style,
        )
        raise typer.Abort()

    # Check if the total size exceeds the disk capacity
    if system_size > disk_capacity_gb:
        console.print(
            f"The system size ({system_size}GB) exceeds the disk capacity ({disk_capacity_gb}GB).",
            style=error_style,
        )
        raise typer.Abort()

    if system_size > disk_capacity_gb / 2:
        if not Confirm.ask(  # TODO: This doesn't work
            rich.text.Text(
                f"The system size might be too large ({system_size}GB / {disk_capacity_gb}GB total). Are you sure?",
                style=warning_style,
            )
        ):
            raise typer.Abort()

    # Check if the device is empty, unless force flag is set
    if not check_device_empty(device, debug):
        if force:
            erase_device(device, debug)
        else:
            console.print(
                f"The device {device} is not empty. Use --force to erase all partitions.",
                style=error_style,
            )
            raise typer.Abort()

    # Copy the image to the device with a progress bar
    copy_image_with_progress(image_path, device, debug)

    # Wait for the device to be recognized
    console.print("Waiting for the device to be recognized...", style=success_style)
    subprocess.run("sleep 5", shell=True)

    # Check the partition table type
    result = run_command(f"fdisk -l {device}", debug)
    if "Disklabel type: dos" in result.stdout:
        console.print("Detected DOS partition table.", style=success_style)
        # boot_partition = f"{device}1"
        system_partition = f"{device}2"
        additional_partition = f"{device}3"
    else:
        console.print(
            "Partition table is not DOS. Will not continue.", style=error_style
        )
        raise typer.Abort()

    # Verify that the copied partition is valid and fix it if necessary
    console.print("Checking and resizing the system partition...", style=success_style)

    run_command(f"e2fsck -f -y {system_partition} || true", debug)

    total_sectors, partition_info = get_partition_info(device, debug)
    if not partition_info.get("2"):
        console.print("Could not get 2nd partition info.", style=error_style)
        raise typer.Abort()

    # Align the end sector for the system partition
    system_size_sectors = system_size * 1024 * 1024 * 1024 // 512
    # Convert GB to sectors
    system_partition_new_end = align_sector(
        partition_info["2"]["start"] + system_size_sectors
    )

    # Resize the partition
    run_command(
        f"parted {device} --script resizepart 2 {system_partition_new_end}s", debug
    )
    console.print("Checking filesystem on resized partition...", style=success_style)

    run_command(f"e2fsck -f -y {system_partition} || true", debug)

    # Create the additional partition
    console.print(
        "Creating additional partition in the remaining space...", style=success_style
    )

    # Create the additional partition using the end sector of the second partition
    console.print(
        "Creating additional partition in the remaining space...", style=success_style
    )

    # Calculate the end sector for the additional partition
    additional_partition_end = total_sectors - 1  # Use all remaining sectors
    if additional_partition_end % 2048 != 0:
        additional_partition_end -= additional_partition_end % 2048
    additional_partition_start = align_sector(system_partition_new_end + 1)

    run_command(
        f"parted {device} --script mkpart primary {additional_partition_start}s {additional_partition_end}s",
        debug,
    )

    # Format the new partition
    console.print("Formatting the new partition...", style=success_style)
    run_command(f"mkfs.ext4 {additional_partition}", debug)

    console.print("Checking filesystem on additional partition...", style=success_style)
    run_command(f"e2fsck -f -y {additional_partition} || true", debug)

    console.print("Disk management complete.", style=success_style)


if __name__ == "__main__":
    typer.run(app())
