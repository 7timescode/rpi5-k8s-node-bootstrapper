import os
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress
from rich.prompt import Confirm, IntPrompt, Prompt

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
    if debug:
        console.print(f"Running: {command}", style="bold")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if debug:
        if result.returncode == 0:
            console.print(" -- [green]Command succeeded![/green]")
        if result.stdout:
            console.print(f" -- [yellow]Output:[/yellow] {result.stdout}")
        if result.stderr:
            console.print(f" -- [red]Error:[/red] {result.stderr}")
    else:
        if result.returncode != 0:
            console.print(f"[red]Command failed with error:[/red] {result.stderr}")
            console.print(f"[yellow]Output:[/yellow] {result.stdout}")
            raise typer.Abort()
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
    if typer.confirm(f"Are you sure you want to erase all partitions on {device}?"):
        console.print(f"[yellow]Erasing all partitions on {device}...[/yellow]")
        run_command(f"parted {device} --script mklabel msdos", debug)
        refresh_device_state(device, debug)
    else:
        console.print("[red]Operation cancelled.[/red]")
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


def refresh_device_state(device: str, debug: bool = False):
    console.print("[green]Refreshing the state of the device...[/green]")
    run_command(f"partprobe {device}", debug)


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
    import ipdb

    ipdb.set_trace()
    # additional_size_gb = None
    refresh_device_state(device, debug)

    disk_capacity_gb = get_disk_capacity(device)
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
            if not Confirm(
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
        if not Confirm(
            f"[yellow]The system size might be too large (({system_size}GB) / {disk_capacity_gb}GB total). Are you sure?[/yellow]"
        ):
            raise typer.Abort()

    # Check if the device is empty, unless force flag is set
    if not check_device_empty(device, debug):
        if force:
            erase_device(device, debug)
        else:
            console.print(
                f"[red]The device {device} is not empty. Use --force to erase all partitions.[/red]"
            )
            raise typer.Abort()

    # Copy the image to the device with a progress bar
    copy_image_with_progress(image_path, device, debug)

    # Wait for the device to be recognized
    console.print("[green]Waiting for the device to be recognized...[/green]")
    subprocess.run("sleep 5", shell=True)

    # Check the partition table type
    result = run_command(f"fdisk -l {device}", debug)
    if "Disklabel type: dos" in result.stdout:
        console.print("[green]Detected DOS partition table.[/green]")
        system_partition = f"{device}1"
        additional_partition = f"{device}2"
    else:
        console.print("[green]Detected GPT partition table.[/green]")
        system_partition = f"{device}p1"
        additional_partition = f"{device}p2"

    # Verify that the copied partition is valid and fix it if necessary
    console.print("[green]Checking and resizing the system partition...[/green]")
    run_command(f"partprobe {device}", debug)
    run_command(f"e2fsck -f -y {system_partition} || true", debug)
    # run_command(f"resize2fs {system_partition} {system_size}", debug)

    # Resize the partition
    run_command(f"parted {device} --script resizepart 2 {system_size}GB", debug)
    console.print("[green]Checking resized partition...[/green]")
    run_command(f"e2fsck -f -y {system_partition} || true", debug)

    # Create the additional partition
    console.print(
        "[green]Creating additional partition in the remaining space...[/green]"
    )
    run_command(f"parted {device} --script mkpart primary {system_size}GB 100%", debug)

    # Format the new partition
    console.print("[green]Formatting the new partition...[/green]")
    run_command(f"mkfs.ext4 {additional_partition}", debug)

    # Mount the new partition
    uuid = (
        subprocess.check_output(
            f"blkid -s UUID -o value {additional_partition}", shell=True
        )
        .decode()
        .strip()
    )
    run_command("mkdir -p /mnt/data", debug)
    run_command(
        f"echo 'UUID={uuid} /mnt/data ext4 defaults 0 2' | tee -a /etc/fstab", debug
    )
    run_command(f"mount {additional_partition} /mnt/data", debug)

    console.print("[green]Disk management complete.[/green]")

    # # List of commands to run
    # commands_to_run = [
    #     # Update package lists
    #     # "apt-get update",
    #     # Install parted and e2fsprogs tools
    #     # "apt-get install -y parted e2fsprogs",
    #     # Write the image to the device
    #     f"dd if={image_path} of={device} bs=4M status=progress",
    #     # Ensure all data is written to the device
    #     "sync",
    #     # Check and repair the filesystem on the second partition
    #     f"e2fsck -f {device}",
    #     # Resize the filesystem on the second partition
    #     f"resize2fs {device}p2 {system_size}",
    #     # Resize the second partition
    #     f"parted {device} --script resizepart 2 {system_size}",
    #     # Create a new partition in the remaining space
    #     f"parted {device} --script mkpart primary {system_size} 100%",
    #     # Inform the OS of partition table changes
    #     f"partprobe {device}",
    #     # Format the new partition with ext4 filesystem
    #     f"mkfs.ext4 {device}p3",
    #     # # Get the UUID of the new partition
    #     # "UUID=$(blkid -s UUID -o value /dev/mmcblk0p3)",
    #     # Create a mount point for the new partition
    #     # "mkdir -p /mnt/data",
    #     # # Add the new partition to /etc/fstab
    #     # "echo 'UUID=$UUID /mnt/data ext4 defaults 0 2' >> /etc/fstab",
    #     # # Mount the new partition
    #     # "mount /dev/{device}p3 /mnt/data"
    # ]
    # # TODO: configure cloud-init
    # # We'll need to mount the partitions probably to do that (maybe not the 3rd one, but still).
    # import ipdb; ipdb.set_trace()

    # # Execute each command inside the Docker container
    # for cmd in commands_to_run:
    #     # docker_exec_command = f"docker exec -it node-bootstrapper bash -c \"{cmd}\""
    #     run_command(cmd, debug)


if __name__ == "__main__":
    typer.run(app())
