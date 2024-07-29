# rpi5-k8s-node-bootstrapper


<p align="center">
  <img src="logo.jpg" alt="drawing" width="200"/>
</p>


A collection of scripts to help bootstrap Raspberry Pi 5s as Kubernetes nodes.

## Motivation
When provisioning my Raspberry Pi 5s as Kubernetes nodes, I had to do a fair amount of back and forth when figuring out what to include or not.
This is what I came up with, hopefully it might be useful for someone.

### Why not use Raspberry Pi Imager?
Its main advantage is that it takes care of:
* flashing the image
* creating an additional partition for data storage (e.g. in case you want to install Longhorn or something like this in your cluster)
* adds cloud-init configuration, including things like static IPs
* bootstraps the nodes to be ready for k8s installation, by doing things like disabling swap and installing a few required packages
* you can run it from the command line, so hopefully it's faster if you're provisioning multiple nodes

Of course though it doesn't support everything Raspberry Pi Imager supports.

## Description

There's 2 scripts in this repository:
* `partition_manager.py`: Copies an image to an SD card or NVMe disk. Also, creates an additional partition to use as storage on the node, separate from the system partition
* `config_generator.py`: Generates `cloud-init` configuration, to help bootstrap the node on first execution. Also optionally copies this config in the boot partition.

These are python scripts. You can run them as such, or you can use the `run.sh` script which spins up a Docker container, mounts a disk (the one you want to provision) and passes all arguments to the scripts. That way you don't need to install any of the dependencies locally.

If, however, you want to do that, this is being developed with `poetry`. You can use it to create a virtualenv, install dependencies and run everything from there.

## OS support

**This has been tested primarily on Linux.**

It's also known to work in OSX, but you'll need to:
* create a Linux VM (e.g. using UTM)
* install Ubuntu (or something similar)
* pass the disk via USB passthrough to the VM
* mount it in the Linux VM as a virtio share
* run the scripts as normal

The command to mount it would look something like that (all shares with UTM are named `shared`).
```
sudo mount -t 9p -o trans=virtio,version=9p2000.L share /mnt/shared
```

Be warned, this mode of execution is not really stable. It's slower and less predictable. Sometimes copying the image or formatting the partitions will get stuck and you'll see a bunch of issues in `sudo dmesg`.
I don't think there's any way around it.

The `config_generator` script works much better in OSX too with this mode, since it doesn't use the disk that much.

## Execution examples

Commands are quite interactive and will issue warnings if things go wrong.
You can always run them with `--debug` and see the output of every operation (suggested in the beginning).

To run the scripts, you'll first need to copy `config.ini.sample` and add your own config there.

If you're running `partition_manager` you'll also need to copy your image in the same directory (or just pass a path to it).

Then, you can run things like the following:
```
# This will format /dev/sdb, flash the image & create an additional partition
./run.sh partition_manager /dev/sdb --image-path ./ubuntu-24.04-preinstalled-server-arm64+raspi.img --force --debug

# This will generate & copy cloud-init configuration. It'll generate static IP configuration for WiFi, but not for ethernet.
./run.sh config-generator /dev/sdb --no-setup-eth --setup-wifi --debug --hosts-number 1 --force

# This will do the same, but will generate ethernet configuration and think this is the 6th host, so it'll name it as rpi06-ubuntupi.local. You can change the name pattern in the config file.
./run.sh config_generator /dev/sdb --no-setup-wifi --setup-eth --debug --hosts-number 1 --force --offset 5
```
