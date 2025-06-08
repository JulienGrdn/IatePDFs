#!/usr/bin/env python3

import gi
import os
import subprocess
import threading
import tempfile
import shutil
from pathlib import Path

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Gio, GLib, GObject, Adw

try:
    from pypdf import PdfWriter, PdfReader
    from pypdf.errors import PdfReadError
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError, PDFInfoNotInstalledError
except ImportError as e:
    print(f"Error: Missing required Python library '{e.name}'.")
    print(f"Please install it using: pip install {e.name} pypdf pdf2image")
    exit(1)


# --- Core Logic ---

def compress_pdf(input_path, output_path, quality="ebook"):
    try:
        command = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS=/{quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={output_path}", input_path
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True, "Compression successful."
    except FileNotFoundError:
        return False, "Error: Ghostscript (gs) is not installed or not in your PATH."
    except subprocess.CalledProcessError as e:
        return False, f"Ghostscript failed: {e.stderr}"

def merge_pdfs(pdf_paths, output_path):
    merger = PdfWriter()
    try:
        for path in pdf_paths:
            merger.append(path)
        merger.write(output_path)
        merger.close()
        return True, f"Successfully merged {len(pdf_paths)} files."
    except Exception as e:
        return False, f"Failed to merge PDFs: {e}"

def reorder_pdf_pages(input_path, output_path, new_order_indices):
    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for index in new_order_indices:
            writer.add_page(reader.pages[index])
        with open(output_path, "wb") as f:
            writer.write(f)
        return True, "Successfully reordered pages."
    except Exception as e:
        return False, f"Failed to reorder PDF: {e}"


# --- Drag-and-Drop Functionality ---

class DraggableMixin:
    """A mixin class to provide drag-and-drop functionality for reordering."""
    def setup_dnd(self, widget):
        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare)
        source.connect("drag-begin", self._on_drag_begin)
        source.connect("drag-end", self._on_drag_end)
        widget.add_controller(source)

        target = Gtk.DropTarget.new(type=GObject.TYPE_OBJECT, actions=Gdk.DragAction.MOVE)
        target.connect("drop", self._on_drop)
        widget.add_controller(target)

    def _on_drag_prepare(self, source, x, y):
        widget = source.get_widget()
        paintable = Gtk.WidgetPaintable(widget=widget)
        source.set_icon(paintable, x, y)
        value = GObject.Value(GObject.TYPE_OBJECT, widget)
        return Gdk.ContentProvider.new_for_value(value)

    def _on_drag_begin(self, source, drag):
        source.get_widget().set_opacity(0.5)

    def _on_drag_end(self, source, drag, delete_data):
        source.get_widget().set_opacity(1.0)
    
    def _on_drop(self, target, value, x, y):
        raise NotImplementedError


# --- Reorderable Widgets ---

class PdfFileRow(Gtk.ListBoxRow, DraggableMixin):
    """A row for the Merge tab, reorderable within a Gtk.ListBox."""
    def __init__(self, file_path, app_window):
        super().__init__()
        self.file_path = file_path
        self.app_window = app_window
        
        action_row = Adw.ActionRow(
            title=os.path.basename(file_path),
            subtitle=str(Path(file_path).parent)
        )
        self.set_child(action_row)

        preview_stack = Gtk.Stack()
        self.preview_image = Gtk.Picture(width_request=60, height_request=84)
        self.preview_spinner = Gtk.Spinner(spinning=True)
        preview_stack.add_named(self.preview_spinner, "loading")
        preview_stack.add_named(self.preview_image, "done")
        preview_stack.set_visible_child_name("loading")
        action_row.add_prefix(preview_stack)
        
        remove_button = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER)
        remove_button.connect("clicked", self._on_remove_clicked)
        action_row.add_suffix(remove_button)
        
        self.setup_dnd(self)
        threading.Thread(target=self._generate_preview, args=(preview_stack,)).start()

    def _on_drop(self, target, value, x, y):
        source_row = value
        target_row = self 
        list_box = target_row.get_parent()

        if source_row is target_row or not isinstance(list_box, Gtk.ListBox):
            return True

        target_index = target_row.get_index()
        list_box.remove(source_row)
        list_box.insert(source_row, target_index)
        return True

    def _generate_preview(self, stack):
        try:
            with tempfile.TemporaryDirectory() as temp_path:
                images = convert_from_path(self.file_path, dpi=72, first_page=1, last_page=1, output_folder=temp_path, fmt='png', size=(120, None))
                if images:
                    texture = Gdk.Texture.new_from_filename(images[0].filename)
                    GLib.idle_add(self._set_preview_image, texture, stack)
                    return
        except Exception as e:
            print(f"Could not generate preview for {self.file_path}: {e}")
        GLib.idle_add(self._set_preview_error, stack)

    def _set_preview_image(self, texture, stack):
        self.preview_image.set_paintable(texture)
        stack.set_visible_child_name("done")

    def _set_preview_error(self, stack):
        self.preview_image.set_icon_name("image-missing-symbolic")
        self.preview_image.set_pixel_size(48)
        stack.set_visible_child_name("done")

    def _on_remove_clicked(self, button):
        list_box = self.get_parent()
        if list_box:
            list_box.remove(self)
            self.app_window._update_merge_view_state()


class PdfPageWidget(Gtk.FlowBoxChild, DraggableMixin):
    """A widget representing a single, reorderable PDF page in a grid."""
    def __init__(self, pdf_path, page_index):
        super().__init__()
        self.original_page_index = page_index

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.add_css_class("card")
        self.set_child(content_box)
        
        preview_stack = Gtk.Stack()
        self.preview_image = Gtk.Picture(width_request=120, height_request=168)
        self.preview_spinner = Gtk.Spinner(spinning=True)
        preview_stack.add_named(self.preview_spinner, "loading")
        preview_stack.add_named(self.preview_image, "done")
        preview_stack.set_visible_child_name("loading")
        
        content_box.append(preview_stack)
        content_box.append(Gtk.Label(label=f"Page {page_index + 1}"))
        
        self.setup_dnd(self)
        threading.Thread(target=self._generate_page_preview, args=(pdf_path, preview_stack,)).start()

    def _on_drop(self, target, value, x, y):
        source_container = value
        target_container = self

        if source_container is target_container: return True

        flow_box = target_container.get_parent()
        if not isinstance(flow_box, Gtk.FlowBox): return False
        
        target_index = target_container.get_index()
        flow_box.remove(source_container)
        flow_box.insert(source_container, target_index)
        return True

    def _generate_page_preview(self, pdf_path, stack):
        try:
            with tempfile.TemporaryDirectory() as temp_path:
                images = convert_from_path(pdf_path, dpi=96, first_page=self.original_page_index + 1, last_page=self.original_page_index + 1, output_folder=temp_path, fmt='png', size=(120, None))
                if images:
                    texture = Gdk.Texture.new_from_filename(images[0].filename)
                    GLib.idle_add(self._set_preview_image, texture, stack)
                    return
        except (PDFPageCountError, PDFSyntaxError, Exception) as e:
            print(f"Error generating preview for page {self.original_page_index + 1}: {e}")
        GLib.idle_add(self._set_preview_error, stack)

    def _set_preview_image(self, texture, stack):
        self.preview_image.set_paintable(texture)
        stack.set_visible_child_name("done")

    def _set_preview_error(self, stack):
        self.preview_image.set_icon_name("image-missing-symbolic")
        self.preview_image.set_pixel_size(64)
        stack.set_visible_child_name("done")


# --- Main Application Window ---

class PdfToolWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("PDF Tools")
        self.set_default_size(550, 500)
        self.connect("close-request", self._on_close_request)
        
        self.is_processing = False
        self.reorder_source_path = None
        self.compression_quality = "ebook"
        
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b".card { border-radius: 8px; border: 1px solid silver; background-color: white; margin: 6px; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        
        self.view_stack = Adw.ViewStack()
        view_switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        
        toolbar_view = Adw.ToolbarView.new()
        header_bar = Adw.HeaderBar.new()
        header_bar.set_title_widget(view_switcher)
        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(self.view_stack)
        
        self.toast_overlay.set_child(toolbar_view)

        # --- Setup Views ---
        self.compress_page, self.compress_status_page, self.compress_spinner = self._create_compress_page()
        self.view_stack.add_titled_with_icon(self.compress_page, "compress", "Compress", "document-open-symbolic")

        self.merge_page, self.merge_list_box, self.merge_button, self.merge_view_stack = self._create_merge_page()
        self.view_stack.add_titled_with_icon(self.merge_page, "merge", "Merge", "object-merge-symbolic")

        self.reorder_page, self.reorder_flow_box, self.reorder_button, self.reorder_view_stack = self._create_reorder_page()
        self.view_stack.add_titled_with_icon(self.reorder_page, "reorder", "Reorder Pages", "document-page-setup-symbolic")
        
        drop_target_window = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target_window.connect("drop", self._on_drop)
        self.add_controller(drop_target_window)

    def _create_compress_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        
        qualities = ["screen", "ebook", "printer", "prepress"]
        quality_combo_row = Adw.ComboRow(title="Compression Quality", model=Gtk.StringList.new(qualities))
        quality_combo_row.set_selected(qualities.index(self.compression_quality))
        quality_combo_row.connect("notify::selected-item", self._on_quality_changed)
        
        prefs_group = Adw.PreferencesGroup()
        prefs_group.add(quality_combo_row)
        page.append(prefs_group)
        
        status_page = Adw.StatusPage(vexpand=True)
        spinner = Gtk.Spinner(spinning=False, visible=False, width_request=32, height_request=32)
        page.append(status_page)
        
        self._reset_compress_ui(status_page)
        return page, status_page, spinner

    def _create_merge_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        view_stack = Gtk.Stack(vexpand=True)
        placeholder = Adw.StatusPage(
            icon_name="document-new-symbolic",
            title="Drag PDFs Here to Merge",
            description="You can reorder the files before merging."
        )
        scrolled_window = Gtk.ScrolledWindow()
        view_stack.add_named(scrolled_window, "list")
        view_stack.add_named(placeholder, "placeholder")
        page.append(view_stack)

        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        scrolled_window.set_child(list_box)
        
        # THE FIX: Use Gtk.ActionBar, not Adw.ActionBar
        action_bar = Gtk.ActionBar()
        merge_button = Gtk.Button(label="Merge PDFs", sensitive=False)
        merge_button.add_css_class("suggested-action")
        merge_button.connect("clicked", self._on_merge_clicked)
        action_bar.set_center_widget(merge_button)
        page.append(action_bar)
        
        self._update_merge_view_state(view_stack, merge_button, list_box, False)
        return page, list_box, merge_button, view_stack

    def _create_reorder_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        view_stack = Gtk.Stack(vexpand=True)
        placeholder = Adw.StatusPage(
            icon_name="document-page-setup-symbolic",
            title="Drop a Single PDF Here to Reorder its Pages",
        )
        scrolled_window = Gtk.ScrolledWindow()
        view_stack.add_named(scrolled_window, "grid")
        view_stack.add_named(placeholder, "placeholder")
        page.append(view_stack)

        flow_box = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE)
        scrolled_window.set_child(flow_box)

        # THE FIX: Use Gtk.ActionBar, not Adw.ActionBar
        action_bar = Gtk.ActionBar()
        save_button = Gtk.Button(label="Save Reordered PDF", sensitive=False)
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_reorder_save_clicked)
        action_bar.set_center_widget(save_button)
        page.append(action_bar)

        self._update_reorder_view_state(view_stack, save_button, False)
        return page, flow_box, save_button, view_stack

    def _on_drop(self, drop_target, value, x, y):
        files = []
        if hasattr(value, 'get_files'): files = value.get_files()
        elif isinstance(value, Gio.File): files = [value]
        
        if not files: return True
        if self.is_processing:
            self.toast_overlay.add_toast(Adw.Toast(title="A task is already in progress."))
            return True
        
        current_view = self.view_stack.get_visible_child_name()
        if current_view == "compress":
            if files[0].get_path() and files[0].get_path().lower().endswith(".pdf"):
                self._start_compression(files[0].get_path())
        elif current_view == "merge":
            pdf_files = [f for f in files if f.get_path() and f.get_path().lower().endswith(".pdf")]
            for pdf_file in pdf_files: self._add_pdf_to_merge_list(pdf_file.get_path())
        elif current_view == "reorder":
            if files[0].get_path() and files[0].get_path().lower().endswith(".pdf"):
                self._load_pdf_for_reordering(files[0].get_path())
        return True

    def _start_compression(self, file_path):
        threading.Thread(target=self._run_compression, args=(file_path,)).start()
        
    def _run_compression(self, input_path):
        self._set_processing_state(True, "Compressing...")
        output_path = os.path.join(os.path.dirname(input_path), f"{Path(input_path).stem}_compressed.pdf")
        success, message = compress_pdf(input_path, output_path, self.compression_quality)
        GLib.idle_add(self._on_compression_finished, success, message, input_path, output_path)
    
    def _on_compression_finished(self, success, message, input_path, output_path):
        self._set_processing_state(False)
        if success:
            self.compress_status_page.set_icon_name("emblem-ok-symbolic")
            self.compress_status_page.set_title("Compression Successful")
            try:
                original_size = os.path.getsize(input_path); new_size = os.path.getsize(output_path)
                ratio = 1 - (new_size / original_size) if original_size > 0 else 0
                self.compress_status_page.set_description(f'Original: {original_size/1024:.1f} KB → New: {new_size/1024:.1f} KB (Reduced by {ratio:.1%})')
            except OSError:
                 self.compress_status_page.set_description("Could not calculate size reduction.")
        else:
            self.compress_status_page.set_icon_name("dialog-error-symbolic")
            self.compress_status_page.set_title("Compression Failed")
            self.compress_status_page.set_description(message)
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    def _add_pdf_to_merge_list(self, file_path):
        row = PdfFileRow(file_path, self)
        self.merge_list_box.append(row)
        self._update_merge_view_state()

    def _update_merge_view_state(self, view_stack=None, button=None, list_box=None, has_files=None):
        view_stack = view_stack or self.merge_view_stack
        button = button or self.merge_button
        list_box = list_box or self.merge_list_box
        
        num_children = len(self._get_all_children(list_box))
        if has_files is None: has_files = num_children > 0
        
        view_stack.set_visible_child_name("list" if has_files else "placeholder")
        button.set_sensitive(num_children >= 2 and not self.is_processing)

    def _on_merge_clicked(self, button):
        pdf_paths = [child.file_path for child in self._get_all_children(self.merge_list_box)]
        self._show_save_dialog("merged.pdf", lambda path: self._run_merge(pdf_paths, path))

    def _run_merge(self, pdf_paths, output_path):
        self._set_processing_state(True, "Merging PDFs...")
        success, message = merge_pdfs(pdf_paths, output_path)
        GLib.idle_add(self._on_merge_finished, success, message)

    def _on_merge_finished(self, success, message):
        self._set_processing_state(False)
        self.toast_overlay.add_toast(Adw.Toast(title=message))
        if success:
            for child in self._get_all_children(self.merge_list_box):
                self.merge_list_box.remove(child)
            self._update_merge_view_state()

    def _load_pdf_for_reordering(self, file_path):
        try:
            reader = PdfReader(file_path)
            if reader.is_encrypted:
                self.toast_overlay.add_toast(Adw.Toast(title="Could not load: The PDF is encrypted."))
                return

            num_pages = len(reader.pages)
            if num_pages == 0:
                self.toast_overlay.add_toast(Adw.Toast(title="PDF is empty or cannot be read."))
                return

            for child in self._get_all_children(self.reorder_flow_box):
                self.reorder_flow_box.remove(child)
            
            self.reorder_source_path = file_path
            for i in range(num_pages):
                page_widget = PdfPageWidget(file_path, i)
                self.reorder_flow_box.append(page_widget)
            
            self._update_reorder_view_state(has_file=True)
        except (PdfReadError, Exception) as e:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Error reading PDF: {e}"))
            self._update_reorder_view_state(has_file=False)

    def _update_reorder_view_state(self, view_stack=None, button=None, has_file=None):
        view_stack = view_stack or self.reorder_view_stack
        button = button or self.reorder_button
        
        if has_file is None: has_file = self.reorder_source_path is not None
        
        view_stack.set_visible_child_name("grid" if has_file else "placeholder")
        button.set_sensitive(has_file and not self.is_processing)
        if not has_file:
            self.reorder_source_path = None
    
    def _on_reorder_save_clicked(self, button):
        default_name = f"{Path(self.reorder_source_path).stem}_reordered.pdf"
        self._show_save_dialog(default_name, self._run_reorder_and_save)

    def _run_reorder_and_save(self, output_path):
        flow_box_children = self._get_all_children(self.reorder_flow_box)
        new_order_indices = [child.original_page_index for child in flow_box_children]
        threading.Thread(target=self._run_reorder_task, args=(self.reorder_source_path, output_path, new_order_indices)).start()
        
    def _run_reorder_task(self, input_path, output_path, new_order):
        self._set_processing_state(True, "Saving PDF...")
        success, message = reorder_pdf_pages(input_path, output_path, new_order)
        GLib.idle_add(self._on_reorder_finished, success, message)

    def _on_reorder_finished(self, success, message):
        self._set_processing_state(False)
        self.toast_overlay.add_toast(Adw.Toast(title=message))
        if success:
            for child in self._get_all_children(self.reorder_flow_box):
                self.reorder_flow_box.remove(child)
            self._update_reorder_view_state()

    def _show_save_dialog(self, default_name, callback_on_accept):
        file_chooser = Gtk.FileChooserDialog(title="Save As...", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        file_chooser.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.ACCEPT)
        pdf_filter = Gtk.FileFilter(); pdf_filter.set_name("PDF files"); pdf_filter.add_mime_type("application/pdf")
        file_chooser.add_filter(pdf_filter)
        file_chooser.set_current_name(default_name)
        
        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                callback_on_accept(dialog.get_file().get_path())
            dialog.destroy()
        
        file_chooser.connect("response", on_response)
        file_chooser.present()

    def _get_all_children(self, container):
        children = []
        child = container.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def _on_quality_changed(self, combo_row, _):
        self.compression_quality = combo_row.get_selected_item().get_string()

    def _reset_compress_ui(self, status_page=None):
        status_page = status_page or self.compress_status_page
        status_page.set_icon_name("document-open-symbolic")
        status_page.set_title("PDF Compressor")
        status_page.set_description("Drag and drop a PDF file to begin.")
        status_page.set_child(None)

    def _set_processing_state(self, is_processing, message=""):
        self.is_processing = is_processing
        # Update all views' sensitivity
        self._update_merge_view_state()
        self._update_reorder_view_state()
        
        if self.view_stack.get_visible_child_name() == 'compress':
            self.compress_spinner.set_spinning(is_processing)
            if is_processing:
                self.compress_status_page.set_child(self.compress_spinner)
                self.compress_status_page.set_title(message)
                self.compress_status_page.set_description("Please wait.")
            else:
                self._reset_compress_ui()

        if is_processing:
            self.toast_overlay.add_toast(Adw.Toast(title=message))

    def _on_close_request(self, window):
        if self.is_processing:
            self.toast_overlay.add_toast(Adw.Toast(title="Cannot close while a task is in progress."))
            return True
        return False

class PdfToolApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id="io.github.JulienGrdn.IatePDFs", **kwargs)
    
    def do_activate(self):
        # THE FIX: Use shutil.which() for a robust and correct dependency check.
        if not shutil.which("pdfinfo"):
             dialog = Adw.MessageDialog(transient_for=self.get_active_window(), modal=True, heading="Dependency Missing: Poppler", body="This application requires Poppler to generate page previews. Please install 'poppler-utils' (or equivalent for your OS) and ensure it is in your system's PATH.")
             dialog.add_response("ok", "OK"); dialog.connect("response", lambda d, r: d.close()); dialog.present()
             return

        win = self.props.active_window
        if not win:
            win = PdfToolWindow(application=self)
        win.present()

if __name__ == "__main__":
    import sys
    app = PdfToolApp()
    app.run(sys.argv)

