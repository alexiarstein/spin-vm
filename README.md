# spin-vm / LexVM

This repository now includes two launchers for QEMU VMs:

- `spin-vm.py`: original TUI (dialog-based) flow.
- `lexvm.py`: GUI version (GTK4/Libadwaita), named LexVM.

## Common dependencies

- python3
- qemu-system-x86_64
- qemu-img
- ovmf (for UEFI mode)

## Extra dependencies for TUI

- dialog

## Extra dependencies for GUI (LexVM)

- python3-gi
- gir1.2-gtk-4.0
- gir1.2-adw-1

## Run

```bash
python3 spin-vm.py   # TUI
python3 lexvm.py     # GUI (LexVM)
```
