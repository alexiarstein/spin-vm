#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import gettext
import locale

from gi.repository import Adw, Gdk, Gio, Gtk, Pango

QEMU_BIN = "qemu-system-x86_64"
QEMU_IMG_BIN = "qemu-img"
OVMF_CODE = "/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_TEMPLATE = "/usr/share/OVMF/OVMF_VARS_4M.fd"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATHS = [
    os.path.join(SCRIPT_DIR, "lexvm.svg"),
    "/usr/share/icons/hicolor/scalable/apps/lexvm.svg",
    "/usr/share/pixmaps/lexvm.svg",
]

# i18n: check installed system locale first, fall back to local repo locale/
_SYSTEM_LOCALE_DIR = "/usr/share/locale"
_LOCAL_LOCALE_DIR = os.path.join(SCRIPT_DIR, "locale")
_LOCALE_DIR = (
    _SYSTEM_LOCALE_DIR
    if os.path.exists(os.path.join(_SYSTEM_LOCALE_DIR, "es", "LC_MESSAGES", "lexvm.mo"))
    else _LOCAL_LOCALE_DIR
)
gettext.bindtextdomain("lexvm", _LOCALE_DIR)
gettext.textdomain("lexvm")
_ = gettext.gettext


class LexVMWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        window_title = _("LexVM - A Virtual Machine Creator")
        self.set_title(window_title)
        self.set_default_size(860, 460)

        self._set_window_icon()

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.toast_overlay.set_child(root)

        toolbar_view = Adw.ToolbarView()
        root.append(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(True)
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Gtk.Label(label=window_title))
        menubar = self._build_menubar()
        header.pack_start(menubar)
        toolbar_view.add_top_bar(header)

        self.launch_button = Gtk.Button(label="Launch")
        self.launch_button.add_css_class("pill")
        self.launch_button.add_css_class("suggested-action")
        self.launch_button.connect("clicked", self._launch_vm)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content.set_margin_top(6)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_hexpand(True)
        content.set_vexpand(True)
        toolbar_view.set_content(content)

        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_col.set_hexpand(True)
        content.append(left_col)

        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_col.set_hexpand(True)
        right_col.set_vexpand(True)
        content.append(right_col)

        mode_group = Adw.PreferencesGroup()
        mode_group.set_title(_("Action"))
        left_col.append(mode_group)

        self.mode_row = Adw.ActionRow()
        self.mode_row.set_title(_("Mode"))
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mode_box.set_valign(Gtk.Align.CENTER)

        self.install_radio = Gtk.CheckButton(label=_("Install"))
        self.install_radio.set_active(True)
        self.run_radio = Gtk.CheckButton(label=_("Run"))
        self.run_radio.set_group(self.install_radio)

        self.install_radio.connect("toggled", self._on_mode_changed)
        self.run_radio.connect("toggled", self._on_mode_changed)

        mode_box.append(self.install_radio)
        mode_box.append(self.run_radio)
        self.mode_row.add_suffix(mode_box)
        mode_group.add(self.mode_row)

        location_group = Adw.PreferencesGroup()
        location_group.set_title(_("Paths"))
        left_col.append(location_group)

        self.iso_path = ""
        self.vm_dir = os.path.expanduser("~/VMs")

        self.iso_row = Adw.ActionRow()
        self.iso_row.set_title(_("ISO image"))
        self.iso_row.set_subtitle(_("No image selected"))
        iso_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        iso_btn.add_css_class("circular")
        iso_btn.set_tooltip_text(_("Choose ISO image"))
        iso_btn.set_valign(Gtk.Align.CENTER)
        iso_btn.connect("clicked", self._select_iso)
        self.iso_value = Gtk.Label(label=_("Not selected"))
        self.iso_value.add_css_class("dim-label")
        self.iso_value.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.iso_value.set_max_width_chars(26)
        self.iso_row.add_suffix(self.iso_value)
        self.iso_row.add_suffix(iso_btn)
        location_group.add(self.iso_row)

        self.dir_row = Adw.ActionRow()
        self.dir_row.set_title(_("Virtual disk directory"))
        self.dir_row.set_subtitle(self.vm_dir)
        dir_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        dir_btn.add_css_class("circular")
        dir_btn.set_tooltip_text(_("Choose virtual disk directory"))
        dir_btn.set_valign(Gtk.Align.CENTER)
        dir_btn.connect("clicked", self._select_directory)
        self.dir_row.add_suffix(dir_btn)
        location_group.add(self.dir_row)

        vm_group = Adw.PreferencesGroup()
        vm_group.set_title(_("Virtual machine"))
        left_col.append(vm_group)

        self.name_row = Adw.EntryRow()
        self.name_row.set_title(_("VM name"))
        self.name_row.set_text("lexvm")
        vm_group.add(self.name_row)

        self.boot_row = Adw.ActionRow()
        self.boot_row.set_title(_("Boot mode"))
        boot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        boot_box.set_valign(Gtk.Align.CENTER)

        self.uefi_radio = Gtk.CheckButton(label=_("UEFI (Recommended)"))
        self.uefi_radio.set_active(True)
        self.bios_radio = Gtk.CheckButton(label="BIOS")
        self.bios_radio.set_group(self.uefi_radio)

        boot_box.append(self.uefi_radio)
        boot_box.append(self.bios_radio)
        self.boot_row.add_suffix(boot_box)
        vm_group.add(self.boot_row)

        resources_group = Adw.PreferencesGroup()
        resources_group.set_title(_("Resources"))
        right_col.append(resources_group)

        self.ram_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1024, 16384, 512)
        self.ram_scale.set_value(2048)
        self.ram_scale.set_draw_value(False)
        self.ram_scale.set_digits(0)
        self.ram_scale.set_size_request(280, -1)
        self.ram_value = Gtk.Label(label=self._format_ram(self.ram_scale.get_value()))
        self.ram_value.add_css_class("dim-label")
        self.ram_scale.connect("value-changed", self._on_ram_changed)
        self._add_slider_row(resources_group, _("RAM"), None, self.ram_scale, self.ram_value)

        self.cpu_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 16, 1)
        self.cpu_scale.set_value(4)
        self.cpu_scale.set_draw_value(False)
        self.cpu_scale.set_digits(0)
        self.cpu_scale.set_size_request(280, -1)
        self.cpu_value = Gtk.Label(label=self._format_cpus(self.cpu_scale.get_value()))
        self.cpu_value.add_css_class("dim-label")
        self.cpu_scale.connect("value-changed", self._on_cpu_changed)
        self._add_slider_row(resources_group, _("vCPUs"), None, self.cpu_scale, self.cpu_value)

        self.disk_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 512, 2)
        self.disk_scale.set_value(40)
        self.disk_scale.set_draw_value(False)
        self.disk_scale.set_digits(0)
        self.disk_scale.set_size_request(280, -1)
        self.disk_value = Gtk.Label(label=self._format_disk(self.disk_scale.get_value()))
        self.disk_value.add_css_class("dim-label")
        self.disk_scale.connect("value-changed", self._on_disk_changed)
        self._add_slider_row(resources_group, _("Disk"), None, self.disk_scale, self.disk_value)

        self.existing_frame = Gtk.Frame()
        self.existing_frame.add_css_class("vm-sheet-frame")
        self.existing_frame.set_hexpand(True)
        self.existing_frame.set_vexpand(True)
        right_col.append(self.existing_frame)

        existing_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        existing_box.add_css_class("vm-sheet")
        existing_box.set_margin_top(10)
        existing_box.set_margin_bottom(10)
        existing_box.set_margin_start(10)
        existing_box.set_margin_end(10)
        self.existing_frame.set_child(existing_box)

        existing_title = Gtk.Label(label=_("Existing disks / VMs"))
        existing_title.set_halign(Gtk.Align.START)
        existing_title.add_css_class("title-4")
        existing_box.append(existing_title)

        self.existing_hint = Gtk.Label(
            label=_("Select an existing disk to populate VM name and boot mode, then launch.")
        )
        self.existing_hint.set_wrap(True)
        self.existing_hint.set_halign(Gtk.Align.START)
        self.existing_hint.add_css_class("dim-label")
        existing_box.append(self.existing_hint)

        existing_scroll = Gtk.ScrolledWindow()
        existing_scroll.set_hexpand(True)
        existing_scroll.set_vexpand(True)
        existing_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        existing_box.append(existing_scroll)

        self.existing_list = Gtk.ListBox()
        self.existing_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.existing_list.connect("row-selected", self._on_existing_disk_selected)
        existing_scroll.set_child(self.existing_list)

        self.existing_context_model = Gio.Menu()
        self.existing_context_model.append(_("Delete VM"), "win.delete_vm")
        self.existing_context_menu = Gtk.PopoverMenu.new_from_model(self.existing_context_model)
        self.existing_context_menu.set_has_arrow(False)
        self.existing_context_menu.set_parent(self.existing_list)

        self.existing_right_click = Gtk.GestureClick()
        self.existing_right_click.set_button(3)
        self.existing_right_click.connect("pressed", self._on_existing_list_right_click)
        self.existing_list.add_controller(self.existing_right_click)

        # Push launch action to the lower-right area for a cleaner balance.
        right_spacer = Gtk.Box()
        right_spacer.set_vexpand(True)
        right_col.append(right_spacer)

        launch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        launch_row.set_halign(Gtk.Align.END)
        launch_row.append(self.launch_button)
        right_col.append(launch_row)

        self.launch_button.set_label(_("Launch VM"))
        self._on_mode_changed(None)
        self._refresh_existing_disks()

    def _build_menubar(self):
        self._setup_actions()

        menu_model = Gio.Menu()

        file_menu = Gio.Menu()
        file_menu.append(_("Exit"), "win.exit")
        menu_model.append_submenu(_("File"), file_menu)

        help_menu = Gio.Menu()
        help_menu.append(_("Help"), "win.help")
        help_menu.append(_("About"), "win.about")
        menu_model.append_submenu(_("Help"), help_menu)

        menubar = Gtk.PopoverMenuBar.new_from_model(menu_model)
        menubar.add_css_class("flat")
        return menubar

    def _setup_actions(self):
        exit_action = Gio.SimpleAction.new("exit", None)
        exit_action.connect("activate", self._on_exit)
        self.add_action(exit_action)

        help_action = Gio.SimpleAction.new("help", None)
        help_action.connect("activate", self._on_help)
        self.add_action(help_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        delete_vm_action = Gio.SimpleAction.new("delete_vm", None)
        delete_vm_action.connect("activate", self._on_delete_vm_action)
        self.add_action(delete_vm_action)

    def _set_window_icon(self):
        try:
            for icon_path in ICON_PATHS:
                if os.path.isfile(icon_path):
                    display = self.get_display()
                    icon_theme = Gtk.IconTheme.get_for_display(display)
                    icon_dir = os.path.dirname(icon_path)
                    icon_theme.add_search_path(icon_dir)
                    return
        except Exception as e:
            print(f"Warning: Could not register icon theme: {e}")

    def _on_exit(self, _action, _param):
        self.close()

    def _on_help(self, _action, _param):
        self._show_error_dialog(_("Help"), _("Help placeholder. We can add full documentation here later."))

    def _on_about(self, _action, _param):
        self._show_error_dialog(_("About LexVM"), _("About placeholder. Version and credits can be added later."))

    def _add_slider_row(self, group, title, subtitle, slider, value_label):
        row = Adw.ActionRow()
        row.set_title(title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.add_suffix(value_label)
        row.add_suffix(slider)
        row.set_activatable(False)
        group.add(row)

    def _select_iso(self, _button):
        chooser = Gtk.FileChooserNative.new(
            _("Select ISO image"),
            self,
            Gtk.FileChooserAction.OPEN,
            _("Select"),
            _("Cancel"),
        )

        iso_filter = Gtk.FileFilter()
        iso_filter.set_name(_("ISO images"))
        iso_filter.add_pattern("*.iso")
        chooser.add_filter(iso_filter)

        chooser.connect("response", self._on_iso_response)
        chooser.show()

    def _on_iso_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected_file = chooser.get_file()
            if selected_file:
                self.iso_path = selected_file.get_path() or ""
                self.iso_value.set_label(os.path.basename(self.iso_path) if self.iso_path else _("Not selected"))
                self.iso_row.set_subtitle(self.iso_path)
        chooser.destroy()

    def _select_directory(self, _button):
        chooser = Gtk.FileChooserNative.new(
            _("Select VM directory"),
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            _("Select"),
            _("Cancel"),
        )
        chooser.connect("response", self._on_dir_response)
        chooser.show()

    def _on_dir_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            if selected:
                path = selected.get_path()
                if path:
                    self.vm_dir = path
                    self.dir_row.set_subtitle(self.vm_dir)
                    self._refresh_existing_disks()
        chooser.destroy()

    def _on_mode_changed(self, _obj):
        mode = self._current_mode()
        install = mode == "install"
        self.iso_row.set_sensitive(install)
        if install and not self.iso_path:
            self.iso_row.set_subtitle(_("No image selected"))
        if not install:
            self.iso_row.set_subtitle(_("Not required in run mode"))

    def _current_mode(self):
        if self.install_radio.get_active():
            return "install"
        return "run"

    def _boot_mode(self):
        if self.uefi_radio.get_active():
            return "UEFI"
        return "BIOS"

    def _format_ram(self, value):
        return f"{int(value)} MB"

    def _format_cpus(self, value):
        return _("{} cores").format(int(value))

    def _format_disk(self, value):
        return f"{int(value)} GB"

    def _on_ram_changed(self, scale):
        self.ram_value.set_label(self._format_ram(scale.get_value()))

    def _on_cpu_changed(self, scale):
        self.cpu_value.set_label(self._format_cpus(scale.get_value()))

    def _on_disk_changed(self, scale):
        self.disk_value.set_label(self._format_disk(scale.get_value()))

    def _toast(self, message):
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _show_error_dialog(self, title, body):
        dialog = Adw.MessageDialog.new(self, title, body)
        dialog.add_response("close", _("Close"))
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()

    def _show_overwrite_dialog(self, disk_path, launch_ctx):
        dialog = Adw.MessageDialog.new(
            self,
            _("Disk already exists"),
            disk_path + "\n\n" + _("Overwrite existing virtual disk and continue install?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("overwrite", _("Overwrite"))
        dialog.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_overwrite_response, launch_ctx)
        dialog.present()

    def _on_overwrite_response(self, dialog, response, launch_ctx):
        dialog.destroy()
        if response != "overwrite":
            return
        self._launch_with_context(launch_ctx, overwrite_existing=True)

    def _show_delete_vm_dialog(self, disk_info):
        vars_path = os.path.join(self.vm_dir, f"OVMF_VARS_{disk_info['vm_name']}.fd")
        extra_note = ""
        if os.path.exists(vars_path):
            extra_note = _("\n\nAssociated firmware state will also be removed.")

        dialog = Adw.MessageDialog.new(
            self,
            _("Delete VM from disk"),
            _("The selected VM disk will be permanently deleted:\n\n") + disk_info["path"] + extra_note,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_vm_response, disk_info)
        dialog.present()

    def _on_delete_vm_response(self, dialog, response, disk_info):
        dialog.destroy()
        if response != "delete":
            return

        try:
            if os.path.exists(disk_info["path"]):
                os.remove(disk_info["path"])

            vars_path = os.path.join(self.vm_dir, f"OVMF_VARS_{disk_info['vm_name']}.fd")
            if os.path.exists(vars_path):
                os.remove(vars_path)

            self._refresh_existing_disks()
            self._toast(_("Deleted VM disk: {}").format(disk_info["file_name"]))
        except Exception as exc:
            self._show_error_dialog(_("Delete failed"), str(exc))

    def _on_delete_vm_action(self, _action, _param):
        row = self.existing_list.get_selected_row()
        if row is None or not hasattr(row, "disk_info"):
            return
        self._show_delete_vm_dialog(row.disk_info)

    def _on_existing_list_right_click(self, _gesture, _n_press, x, y):
        row = self.existing_list.get_row_at_y(int(y))
        if row is None or not hasattr(row, "disk_info"):
            return

        self.existing_list.select_row(row)

        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self.existing_context_menu.set_pointing_to(rect)
        self.existing_context_menu.popup()

    def _selected_vm_context(self):
        mode = self._current_mode()
        boot_mode = self._boot_mode()
        is_uefi = boot_mode == "UEFI"
        vm_name = self.name_row.get_text().strip()
        disk_name = vm_name + (".uefi" if is_uefi else "") + ".qcow2"
        disk_path = os.path.join(self.vm_dir, disk_name)
        vars_path = os.path.join(self.vm_dir, f"OVMF_VARS_{vm_name}.fd")
        return {
            "mode": mode,
            "is_uefi": is_uefi,
            "vm_name": vm_name,
            "disk_path": disk_path,
            "vars_path": vars_path,
        }

    def _build_qemu_args(self, disk_path, vars_path, is_uefi):
        qemu_args = [
            QEMU_BIN,
            "-enable-kvm",
            "-m",
            str(int(self.ram_scale.get_value())),
            "-smp",
            str(int(self.cpu_scale.get_value())),
            "-cpu",
            "host",
            "-drive",
            f"file={disk_path},format=qcow2,if=virtio",
            "-netdev",
            "user,id=net0",
            "-device",
            "virtio-net-pci,netdev=net0",
            "-display",
            "gtk",
        ]
        if is_uefi:
            qemu_args.extend(
                [
                    "-drive",
                    f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}",
                    "-drive",
                    f"if=pflash,format=raw,file={vars_path}",
                ]
            )
        return qemu_args

    def _launch_with_context(self, launch_ctx, overwrite_existing=False):
        try:
            mode = launch_ctx["mode"]
            is_uefi = launch_ctx["is_uefi"]
            disk_path = launch_ctx["disk_path"]
            vars_path = launch_ctx["vars_path"]

            os.makedirs(self.vm_dir, exist_ok=True)

            if mode == "install":
                if overwrite_existing and os.path.exists(disk_path):
                    os.remove(disk_path)

                disk_size = int(self.disk_scale.get_value())
                subprocess.run([QEMU_IMG_BIN, "create", "-f", "qcow2", disk_path, f"{disk_size}G"], check=True)

                if is_uefi:
                    if os.path.exists(vars_path):
                        os.remove(vars_path)
                    shutil.copy(OVMF_VARS_TEMPLATE, vars_path)
            else:
                if not os.path.exists(disk_path):
                    self._show_error_dialog(
                        _("Virtual disk not found"),
                        disk_path + "\n\n" + _("Install the VM first or adjust VM name/boot mode."),
                    )
                    return

                if is_uefi and not os.path.exists(vars_path):
                    shutil.copy(OVMF_VARS_TEMPLATE, vars_path)

            qemu_args = self._build_qemu_args(disk_path, vars_path, is_uefi)

            if mode == "install":
                qemu_args.extend(["-cdrom", self.iso_path, "-boot", "order=d"])
            else:
                qemu_args.extend(["-boot", "order=c"])

            subprocess.Popen(qemu_args)
            self._refresh_existing_disks()
            self._toast(_("VM launched"))
        except subprocess.CalledProcessError as exc:
            self._show_error_dialog(_("QEMU error"), str(exc))
        except Exception as exc:
            self._show_error_dialog(_("Unexpected error"), str(exc))

    def _scan_existing_disks(self):
        if not os.path.isdir(self.vm_dir):
            return []

        entries = []
        for name in os.listdir(self.vm_dir):
            if not name.endswith(".qcow2"):
                continue
            path = os.path.join(self.vm_dir, name)
            if not os.path.isfile(path):
                continue

            is_uefi = name.endswith(".uefi.qcow2")
            vm_name = name[:-11] if is_uefi else name[:-6]
            entries.append(
                {
                    "path": path,
                    "file_name": name,
                    "vm_name": vm_name,
                    "is_uefi": is_uefi,
                }
            )

        entries.sort(key=lambda item: item["file_name"].lower())
        return entries

    def _refresh_existing_disks(self):
        child = self.existing_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.existing_list.remove(child)
            child = next_child

        entries = self._scan_existing_disks()
        if not entries:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=_("No virtual disks found in selected directory."))
            label.set_halign(Gtk.Align.START)
            label.add_css_class("dim-label")
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.set_margin_start(4)
            label.set_margin_end(4)
            row.set_child(label)
            row.set_selectable(False)
            self.existing_list.append(row)
            return

        for entry in entries:
            row = Gtk.ListBoxRow()
            row.disk_info = entry

            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)
            row_box.set_margin_start(4)
            row_box.set_margin_end(4)

            name_label = Gtk.Label(label=entry["vm_name"])
            name_label.set_halign(Gtk.Align.START)

            mode_label = Gtk.Label(label=f"{'UEFI' if entry['is_uefi'] else 'BIOS'} - {entry['file_name']}")
            mode_label.set_halign(Gtk.Align.START)
            mode_label.add_css_class("dim-label")
            mode_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)

            row_box.append(name_label)
            row_box.append(mode_label)
            row.set_child(row_box)
            self.existing_list.append(row)

    def _on_existing_disk_selected(self, _listbox, row):
        if row is None or not hasattr(row, "disk_info"):
            return

        info = row.disk_info
        self.name_row.set_text(info["vm_name"])
        if info["is_uefi"]:
            self.uefi_radio.set_active(True)
        else:
            self.bios_radio.set_active(True)
        self.run_radio.set_active(True)
        self._toast(_("Selected existing disk: {}").format(info["file_name"]))

    def _launch_vm(self, _button):
        missing = self._validate_inputs()
        if missing:
            self._show_error_dialog(_("Cannot launch VM"), missing)
            return

        launch_ctx = self._selected_vm_context()
        if launch_ctx["mode"] == "install" and os.path.exists(launch_ctx["disk_path"]):
            self._show_overwrite_dialog(launch_ctx["disk_path"], launch_ctx)
            return

        self._launch_with_context(launch_ctx)

    def _validate_inputs(self):
        if shutil.which(QEMU_BIN) is None:
            return _("Dependency missing: {}").format("qemu-system-x86_64")
        if shutil.which(QEMU_IMG_BIN) is None:
            return _("Dependency missing: {}").format("qemu-img")
        if self._boot_mode() == "UEFI":
            if not os.path.exists(OVMF_CODE) or not os.path.exists(OVMF_VARS_TEMPLATE):
                return _("UEFI firmware missing: install package ovmf")

        mode = self._current_mode()
        if mode == "install":
            if not self.iso_path:
                return _("Select an ISO image for install mode")
            if not os.path.isfile(self.iso_path):
                return _("Selected ISO path is invalid")

        vm_name = self.name_row.get_text().strip()
        if not vm_name:
            return _("VM name is required")
        if "/" in vm_name:
            return _("VM name cannot include '/'")
        return None


class LexVMApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.lexvm.app", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = LexVMWindow(application=self)
            self._load_css(win)
        win.present()

    def _load_css(self, window):
        css = """
        .title-4 {
            font-weight: 700;
        }

        .vm-sheet-frame {
            border-radius: 18px;
            border: 1px solid alpha(@window_fg_color, 0.08);
            background-color: alpha(@view_bg_color, 0.85);
        }

        .vm-sheet {
            background: transparent;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            window.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def main():
    app = LexVMApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
