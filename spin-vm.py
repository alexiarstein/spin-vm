#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil

# --- Constants ---
QEMU_BIN = "qemu-system-x86_64"
OVMF_CODE = "/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_TEMPLATE = "/usr/share/OVMF/OVMF_VARS_4M.fd"
BACKTITLE = "SIMPLE VM CREATOR by Alexia Michelle https://github.com/alexiarstein/spin-vm"

def run_command(cmd, capture_output=False, shell=False):
    try:
        if capture_output:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, shell=shell)
            return result.stdout.strip()
        else:
            subprocess.run(cmd, check=True, shell=shell)
            return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}\n{e}")
        return False

def check_dependencies():
    deps = ["qemu-system-x86_64", "qemu-img", "dialog"]
    missing = [d for d in deps if shutil.which(d) is None]
    
    # Check for UEFI firmware if needed later, but basic ones first
    if not os.path.exists(OVMF_CODE):
        missing.append("ovmf")

    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        choice = input("Do you want to install them using apt? (y/n): ")
        if choice.lower() == 'y':
            packages = []
            for m in missing:
                if m == "ovmf": packages.append("ovmf")
                elif m.startswith("qemu"): packages.append("qemu-system-x86")
                else: packages.append(m)
            
            # Remove duplicates
            packages = list(set(packages))
            print(f"Installing: {packages}")
            run_command(["sudo", "apt", "update"])
            run_command(["sudo", "apt", "install", "-y"] + packages)
        else:
            print("Cannot proceed without dependencies.")
            sys.exit(1)

def dialog_input(title, prompt, default=""):
    cmd = ["dialog", "--backtitle", BACKTITLE, "--title", title, "--inputbox", prompt, "10", "60", default]
    # Dialog outputs to stderr
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stderr.strip()
    return None

def dialog_fselect(title, path):
    cmd = ["dialog", "--title", title, "--fselect", path, "15", "70"]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stderr.strip()
    return None

def dialog_dselect(title, path):
    cmd = ["dialog", "--title", title, "--dselect", path, "15", "70"]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stderr.strip()
    return None

def dialog_menu(title, prompt, choices, height=15, width=60):
    # choices is list of (tag, item)
    flattened = []
    for tag, item in choices:
        flattened.extend([tag, item])
    
    cmd = ["dialog", "--backtitle", BACKTITLE, "--title", title, "--menu", prompt, str(height), str(width), str(len(choices))] + flattened
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stderr.strip()
    return None

def dialog_yesno(title, prompt, yes_label="Yes", no_label="No"):
    cmd = ["dialog", "--backtitle", BACKTITLE, "--title", title, "--yes-label", yes_label, "--no-label", no_label, "--yesno", prompt, "10", "60"]
    result = subprocess.run(cmd)
    return result.returncode == 0

def browse_path(start_path, select_dir=False, title="Browse"):
    current_path = os.path.abspath(start_path)
    if not os.path.isdir(current_path):
        current_path = os.path.expanduser("~")

    while True:
        try:
            items = os.listdir(current_path)
        except PermissionError:
            dialog_yesno("Error", f"Permission denied: {current_path}")
            current_path = os.path.dirname(current_path)
            continue

        choices = []
        # Add special option for directory selection
        if select_dir:
            choices.append((".", f"--> SELECT THIS DIRECTORY: {current_path} <--"))
        
        choices.append(("..", "../ (Go Up)"))
        
        # Sort directories first, then files
        dirs = sorted([d for d in items if os.path.isdir(os.path.join(current_path, d))])
        files = sorted([f for f in items if os.path.isfile(os.path.join(current_path, f))])

        for d in dirs:
            choices.append((d + "/", "(Dir)"))
        for f in files:
            choices.append((f, "(File)"))

        prompt = f"Current Path: {current_path}\nSelect a {'directory' if select_dir else 'file'}:"
        selection = dialog_menu(title, prompt, choices, height=20, width=75)

        if selection is None: # Cancel
            return None
        
        if selection == ".":
            return current_path
        elif selection == "..":
            current_path = os.path.dirname(current_path)
        elif selection.endswith("/"):
            current_path = os.path.join(current_path, selection[:-1])
        else:
            full_path = os.path.join(current_path, selection)
            if select_dir:
                # If they clicked a file while in dir seek mode, ignore or maybe prompt
                continue
            else:
                return full_path

def main():
    check_dependencies()

    # 1. Select ISO
    iso_path = browse_path("/home/alexia/", select_dir=False, title="SELECT ISO FILE")
    if not iso_path:
        sys.exit(0)
    if not os.path.isfile(iso_path):
        print(f"Invalid ISO path: {iso_path}")
        sys.exit(1)

    # 2. Select VM Directory
    vm_dir = browse_path("/home/alexia/", select_dir=True, title="SELECT DIR TO INSTALL VIRTUAL DISK")
    if not vm_dir:
        sys.exit(0)
    os.makedirs(vm_dir, exist_ok=True)

    # 3. BIOS or UEFI
    is_uefi = dialog_yesno("Boot Emulation Mode", "CHOOSE THE BOOT MODE FOR THE MACHINE:\n\nUEFI for a UEFI machine, BIOS for a BIOS machine", yes_label="UEFI", no_label="BIOS")

    # 4. Install or Run
    mode = dialog_menu("Action", "Select action:", [("install", "Install from ISO"), ("run", "Run installed machine from disk")])
    if not mode:
        sys.exit(1)

    # Setup Paths
    disk_name = os.path.basename(iso_path).replace(".iso", "") + (".uefi" if is_uefi else "") + ".qcow2"
    disk_path = os.path.join(vm_dir, disk_name)
    vars_path = os.path.join(vm_dir, "OVMF_VARS_" + os.path.basename(iso_path).replace(".iso", "") + ".fd")

    # QEMU Args
    qemu_args = [
        QEMU_BIN,
        "-enable-kvm",
        "-m", "2048",
        "-smp", "4",
        "-cpu", "host",
        "-drive", f"file={disk_path},format=qcow2,if=virtio",
        "-netdev", "user,id=net0",
        "-device", "virtio-net-pci,netdev=net0",
        "-display", "gtk"
    ]

    if is_uefi:
        qemu_args.extend([
            "-drive", f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}",
            "-drive", f"if=pflash,format=raw,file={vars_path}"
        ])

    if mode == "install":
        print(f"Starting INSTALL mode ({'UEFI' if is_uefi else 'BIOS'})")
        
        # Create Disk
        if os.path.exists(disk_path):
            if dialog_yesno("Disk Exists", f"Disk {disk_path} already exists. Overwrite?"):
                os.remove(disk_path)
            else:
                print("Aborting.")
                sys.exit(1)
        
        run_command(["qemu-img", "create", "-f", "qcow2", disk_path, "20G"])

        if is_uefi:
            if os.path.exists(vars_path):
                os.remove(vars_path)
            shutil.copy(OVMF_VARS_TEMPLATE, vars_path)

        qemu_args.extend(["-cdrom", iso_path, "-boot", "order=d"])
    
    else: # Run mode
        if not os.path.exists(disk_path):
            print(f"Disk not found: {disk_path}. Run install first.")
            sys.exit(1)
        
        print(f"Starting RUN mode ({'UEFI' if is_uefi else 'BIOS'})")
        qemu_args.extend(["-boot", "order=c"])
    

    # Launch
    print(f"Launching QEMU: {' '.join(qemu_args)}")
    subprocess.run(qemu_args)

    if mode == "install":
        if dialog_yesno("Install Complete", "Installation process finished. Do you want to run the VM now from the virtual drive?"):
            # Re-run in 'run' mode
            print("Restarting VM in RUN mode...")
            # Filter out install specific args
            new_args = [arg for arg in qemu_args if arg not in ["-cdrom", iso_path, "order=d", "-boot"]]
            new_args.extend(["-boot", "order=c"])
            subprocess.run(new_args)

if __name__ == "__main__":
    main()
