#!/usr/bin/env python3

import gi
import os
import sys
import shutil
import threading
import tempfile
import subprocess
from pathlib import Path

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Gio, GLib, Adw, GdkPixbuf, GObject

# Import PDF manipulation libraries
try:
    from pypdf import PdfWriter, PdfReader
    from pdf2image import convert_from_path
except ImportError as e:
    print(f"Error: Missing required Python library '{e.name}'.")
    print(f"Please install it using: pip install {e.name} pypdf pdf2image")
    exit(1)

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

class PdfFileRow(Gtk.ListBoxRow, DraggableMixin):
    """A reorderable row for a PDF file in the merge list."""
    def __init__(self, file_path, app_window):
        super().__init__()
        self.file_path = file_path
        self.app_window = app_window

        action_row = Adw.ActionRow(title=os.path.basename(file_path), subtitle=str(Path(file_path).parent))
        self.set_child(action_row)

        # Preview stack
        preview_stack = Gtk.Stack()
        self.preview_image = Gtk.Picture(width_request=40, height_request=55)
        self.preview_spinner = Gtk.Spinner(spinning=True)
        preview_stack.add_named(self.preview_spinner, "loading")
        preview_stack.add_named(self.preview_image, "done")
        preview_stack.set_visible_child_name("loading")
        action_row.add_prefix(preview_stack)

        # Remove button
        remove_button = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER)
        remove_button.connect("clicked", self._on_remove_clicked)
        action_row.add_suffix(remove_button)

        self.setup_dnd(self)
        threading.Thread(target=self._generate_preview, args=(preview_stack,)).start()

    def _on_drop(self, target, value, x, y):
        source_row, target_row = value, self
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
                images = convert_from_path(self.file_path, dpi=72, first_page=1, last_page=1, 
                                         output_folder=temp_path, fmt='png', size=(60, None))
                if images:
                    texture = Gdk.Texture.new_from_filename(images[0].filename)
                    GLib.idle_add(self._set_preview_image, texture, stack)
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
        self.get_parent().remove(self)
        self.app_window.update_ui_state()

class PdfPageWidget(Gtk.FlowBoxChild, DraggableMixin):
    """A widget representing a single, reorderable PDF page with delete functionality."""
    def __init__(self, pdf_path, page_index):
        super().__init__()
        self.original_page_index = page_index
        self.is_deleted = False

        overlay = Gtk.Overlay()
        self.set_child(overlay)

        # Main content box
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.content_box.add_css_class("card")
        overlay.set_child(self.content_box)

        # Preview
        preview_stack = Gtk.Stack()
        self.preview_image = Gtk.Picture(width_request=60, height_request=84)
        self.preview_spinner = Gtk.Spinner(spinning=True)
        preview_stack.add_named(self.preview_spinner, "loading")
        preview_stack.add_named(self.preview_image, "done")
        preview_stack.set_visible_child_name("loading")

        self.content_box.append(preview_stack)
        self.content_box.append(Gtk.Label(label=f"Page {page_index + 1}"))

        # Delete toggle button
        delete_button = Gtk.ToggleButton(icon_name="edit-delete-symbolic",
                                       valign=Gtk.Align.START, halign=Gtk.Align.END,
                                       margin_top=4, margin_end=4)
        delete_button.set_tooltip_text("Mark page for deletion")
        delete_button.connect("toggled", self._on_delete_toggled)
        overlay.add_overlay(delete_button)

        self.setup_dnd(self)
        threading.Thread(target=self._generate_page_preview, args=(pdf_path, preview_stack)).start()

    def _on_delete_toggled(self, button):
        self.is_deleted = button.get_active()
        self.content_box.set_opacity(0.4 if self.is_deleted else 1.0)

    def _on_drop(self, target, value, x, y):
        source_container, target_container = value, self
        if source_container is target_container: 
            return True

        flow_box = target_container.get_parent()
        if not isinstance(flow_box, Gtk.FlowBox): 
            return False

        target_index = target_container.get_index()
        flow_box.remove(source_container)
        flow_box.insert(source_container, target_index)
        return True

    def _generate_page_preview(self, pdf_path, stack):
        try:
            with tempfile.TemporaryDirectory() as temp_path:
                images = convert_from_path(pdf_path, dpi=96, 
                                         first_page=self.original_page_index + 1, 
                                         last_page=self.original_page_index + 1, 
                                         output_folder=temp_path, fmt='png', size=(90, 125))
                if images:
                    texture = Gdk.Texture.new_from_filename(images[0].filename)
                    GLib.idle_add(self._set_preview_image, texture, stack)
        except Exception as e:
            print(f"Error generating preview for page {self.original_page_index + 1}: {e}")
            GLib.idle_add(self._set_preview_error, stack)

    def _set_preview_image(self, texture, stack):
        self.preview_image.set_paintable(texture)
        stack.set_visible_child_name("done")

    def _set_preview_error(self, stack):
        self.preview_image.set_icon_name("image-missing-symbolic")
        self.preview_image.set_pixel_size(48)
        stack.set_visible_child_name("done")

class PdfToolWindow(Adw.ApplicationWindow):
    """The main application window."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("I ate PDFs")
        self.set_default_size(900, 650)
        self.connect("close-request", self._on_close_request)

        self.is_processing = False
        self.loaded_pdfs = []  # For merge functionality
        self.selected_pdf = None  # Currently selected PDF for operations
        self.reorder_source_path = None  # For reorder functionality
        self.compression_quality = "ebook"

        # CSS styling
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(
            b".card { border-radius: 8px; border: 1px solid silver; "
            b"background-color: white; margin: 6px; }"
            b".selected-row { background-color: alpha(@accent_color, 0.1); }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Create main layout
        self._create_ui()

        # Setup drag and drop for the entire window
        drop_target_window = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target_window.connect("drop", self._on_drop)
        self.add_controller(drop_target_window)

    def _create_ui(self):
        """Create the main UI layout."""
        toolbar_view = Adw.ToolbarView.new()

        # Header bar with action buttons
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Clear button and Browse files button in header
        self.clear_button = Gtk.Button(label="Clear All", icon_name="edit-clear-symbolic")
        self.clear_button.set_sensitive(False)
        self.clear_button.connect("clicked", self._on_clear_clicked)

        browse_button = Gtk.Button(label="Browse Files", icon_name="document-open-symbolic")
        browse_button.connect("clicked", self._on_browse_clicked)

        # Add buttons to header
        header_bar.pack_start(browse_button)
        header_bar.pack_start(self.clear_button)

        # About menu
        primary_menu = Gio.Menu()
        primary_menu.append("About", "win.about")
        menu_button = Gtk.MenuButton(menu_model=primary_menu, icon_name="open-menu-symbolic")
        header_bar.pack_end(menu_button)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_activated)
        self.add_action(about_action)

        # Main content area
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=12, 
                          margin_bottom=12, margin_start=12, margin_end=12)

        # Left panel - narrower file list for merging
        left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left_panel.set_size_request(300, -1)  # Made narrower from 350 to 280
        left_panel.set_hexpand(False)  

        # File list section
        files_group = Adw.PreferencesGroup(title="PDF Files")
        left_panel.append(files_group)

        scrolled_merge = Gtk.ScrolledWindow()
        scrolled_merge.set_vexpand(True)
        scrolled_merge.set_min_content_height(200)
        self.merge_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.merge_list_box.add_css_class("boxed-list")
        self.merge_list_box.connect("row-selected", self._on_file_selected)
        scrolled_merge.set_child(self.merge_list_box)
        files_group.add(scrolled_merge)

        # Merge button at bottom of file list
        merge_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        merge_button_box.set_margin_top(6)
        self.merge_button = Gtk.Button(label="Merge All PDFs", hexpand=True)
        self.merge_button.add_css_class("suggested-action")
        self.merge_button.set_sensitive(False)
        self.merge_button.connect("clicked", self._on_merge_clicked)
        merge_button_box.append(self.merge_button)
        files_group.add(merge_button_box)

        # Right panel - page reordering and operations
        right_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right_panel.set_hexpand(True)

        # Operations section - moved to right panel
        operations_group = Adw.PreferencesGroup(title="Operations")
        right_panel.append(operations_group)

        # --- Compress row ---
        compress_row = Adw.PreferencesRow()
        compress_row.set_activatable(False)  # no hover highlight

        compress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        compress_box.set_margin_top(4)
        compress_box.set_margin_bottom(4)
        compress_box.set_margin_start(12)
        compress_box.set_margin_end(12)

        compress_label = Gtk.Label(label="Compress PDF")
        compress_label.set_xalign(0)
        compress_box.append(compress_label)

        # Spacer pushes following widgets to the right
        compress_box.append(Gtk.Box(hexpand=True))

        qualities = ["screen", "ebook", "printer", "prepress"]
        self.quality_combo = Gtk.ComboBoxText()
        for quality in qualities:
            self.quality_combo.append_text(quality)
        self.quality_combo.set_active(qualities.index(self.compression_quality))
        self.quality_combo.connect("changed", self._on_quality_changed)
        compress_box.append(self.quality_combo)

        self.compress_button = Gtk.Button(label="Compress")
        self.compress_button.add_css_class("suggested-action")
        self.compress_button.set_sensitive(False)
        self.compress_button.connect("clicked", self._on_compress_clicked)
        compress_box.append(self.compress_button)

        compress_row.set_child(compress_box)
        operations_group.add(compress_row)


        # --- Split row ---
        split_row = Adw.PreferencesRow()
        split_row.set_activatable(False)  # no hover highlight

        split_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        split_box.set_margin_top(4)
        split_box.set_margin_bottom(4)
        split_box.set_margin_start(12)
        split_box.set_margin_end(12)

        split_label = Gtk.Label(label="Extract individual pages")
        split_label.set_xalign(0)
        split_box.append(split_label)

        split_box.append(Gtk.Box(hexpand=True))  # spacer

        self.split_button = Gtk.Button(label="Split")
        self.split_button.add_css_class("suggested-action")
        self.split_button.set_sensitive(False)
        self.split_button.connect("clicked", self._on_split_clicked)
        split_box.append(self.split_button)

        split_row.set_child(split_box)
        operations_group.add(split_row)


        # --- Reorder row ---
        reorder_row = Adw.PreferencesRow()
        reorder_row.set_activatable(False)  # no hover highlight

        reorder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        reorder_box.set_margin_top(4)
        reorder_box.set_margin_bottom(4)
        reorder_box.set_margin_start(12)
        reorder_box.set_margin_end(12)

        reorder_label = Gtk.Label(label="Save the reordered PDF")
        reorder_label.set_xalign(0)
        reorder_box.append(reorder_label)

        reorder_box.append(Gtk.Box(hexpand=True))  # spacer

        self.reorder_button = Gtk.Button(label="Save Reordered")
        self.reorder_button.add_css_class("suggested-action")
        self.reorder_button.set_sensitive(False)
        self.reorder_button.connect("clicked", self._on_reorder_clicked)
        reorder_box.append(self.reorder_button)

        reorder_row.set_child(reorder_box)
        operations_group.add(reorder_row)


        # Page reordering section
        reorder_group = Adw.PreferencesGroup(title="Page Reordering")
        right_panel.append(reorder_group)

        self.reorder_subtitle = Gtk.Label(label="Select a PDF file to reorder its pages")
        self.reorder_subtitle.add_css_class("dim-label")
        self.reorder_subtitle.set_halign(Gtk.Align.START)
        self.reorder_subtitle.set_margin_start(12)
        self.reorder_subtitle.set_margin_end(12)
        self.reorder_subtitle.set_margin_top(6)
        reorder_group.add(self.reorder_subtitle)

        scrolled_reorder = Gtk.ScrolledWindow()
        scrolled_reorder.set_vexpand(True)
        scrolled_reorder.set_min_content_height(300)
        self.reorder_flow_box = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=99, 
                                          selection_mode=Gtk.SelectionMode.NONE)
        scrolled_reorder.set_child(self.reorder_flow_box)
        reorder_group.add(scrolled_reorder)

        # Add panels to main box
        main_box.append(left_panel)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        main_box.append(right_panel)

        # Main stack for content/placeholder
        self.main_stack = Gtk.Stack(vexpand=True)

        # Placeholder
        placeholder = Adw.StatusPage(
            icon_name="document-open-symbolic",
            title="Drop PDF files here or browse to open",
            description="• Drop multiple PDFs to merge them\n• Select a PDF from the list for compression, splitting, or page reordering"
        )

        self.main_stack.add_named(placeholder, "placeholder")
        self.main_stack.add_named(main_box, "content")
        self.main_stack.set_visible_child_name("placeholder")

        toolbar_view.set_content(self.main_stack)
        self.toast_overlay.set_child(toolbar_view)

    def _on_about_activated(self, action, param):
        """Shows the About Window."""
        dialog = Adw.AboutWindow(transient_for=self.get_root())
        dialog.set_application_name("I ate PDFs")
        dialog.set_version("1.0")
        dialog.set_developer_name("Julien Grondin")
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_comments("A simple utility for PDF manipulation.")
        dialog.set_website("https://github.com/juliengrdn/iatepdfs")
        dialog.set_copyright("© 2025 Julien Grondin")
        # Set icon if available
        try:
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_resource_path("/")
            dialog.set_icon_name("iatepdfs")
        except:
            pass  # Fallback to default icon
        dialog.show()

    def _on_clear_clicked(self, button):
        """Clear all files and reset to launch state."""
        # Clear merge list
        child = self.merge_list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.merge_list_box.remove(child)
            child = next_child

        # Clear reorder view
        self._clear_reorder_view()

        # Reset state
        self.selected_pdf = None
        self.reorder_source_path = None

        # Reset to placeholder
        self.main_stack.set_visible_child_name("placeholder")

        self.update_ui_state()

    def _on_browse_clicked(self, button):
        """Open file browser to select PDF files."""
        dialog = Gtk.FileChooserDialog(
            title="Select PDF Files",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Open", Gtk.ResponseType.ACCEPT
        )
        dialog.set_select_multiple(True)

        # Add PDF filter
        file_filter = Gtk.FileFilter()
        file_filter.set_name("PDF files")
        file_filter.add_mime_type("application/pdf")
        dialog.add_filter(file_filter)

        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                files = dialog.get_files()
                pdf_paths = [f.get_path() for f in files if f.get_path().lower().endswith(".pdf")]
                if pdf_paths:
                    self._handle_files(pdf_paths)
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_drop(self, drop_target, value, x, y):
        """Handle drag and drop of files."""
        files = value.get_files() if hasattr(value, 'get_files') else [value]
        if not files or self.is_processing:
            if self.is_processing:
                self.toast_overlay.add_toast(Adw.Toast(title="A task is already in progress."))
            return True

        pdf_files = [f.get_path() for f in files if f.get_path() and f.get_path().lower().endswith(".pdf")]
        if pdf_files:
            self._handle_files(pdf_files)
        return True

    def _handle_files(self, pdf_paths):
        """Handle opened/dropped PDF files."""
        self.main_stack.set_visible_child_name("content")

        # Add to merge list
        for path in pdf_paths:
            self._add_pdf_to_merge_list(path)

        # Auto-select the first file if none selected
        if not self.selected_pdf and pdf_paths:
            first_row = self.merge_list_box.get_row_at_index(0)
            if first_row:
                self.merge_list_box.select_row(first_row)

        self.update_ui_state()

    def _add_pdf_to_merge_list(self, file_path):
        """Add a PDF to the merge list."""
        row = PdfFileRow(file_path, self)
        self.merge_list_box.append(row)

    def _on_file_selected(self, listbox, row):
        """Handle file selection for operations."""
        if row is None:
            self.selected_pdf = None
            self._clear_reorder_view()
            self.reorder_source_path = None
        else:
            self.selected_pdf = row.file_path
            self._load_pdf_for_reordering(row.file_path)

        self.update_ui_state()

    def _load_pdf_for_reordering(self, file_path):
        """Load PDF pages for reordering."""
        try:
            reader = PdfReader(file_path)
            if reader.is_encrypted:
                self.toast_overlay.add_toast(Adw.Toast(title="Cannot load encrypted PDF."))
                return

            # Clear existing pages
            self._clear_reorder_view()

            self.reorder_source_path = file_path
            filename = os.path.basename(file_path)
            self.reorder_subtitle.set_text(f"Reordering pages for: {filename}")

            for i in range(len(reader.pages)):
                page_widget = PdfPageWidget(file_path, i)
                self.reorder_flow_box.append(page_widget)

        except Exception as e:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Error reading PDF: {e}"))

    def _clear_reorder_view(self):
        """Clear the reorder view."""
        child = self.reorder_flow_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.reorder_flow_box.remove(child)
            child = next_child

        self.reorder_subtitle.set_text("Select a PDF file to reorder its pages")

    def update_ui_state(self):
        """Update the UI state based on loaded content."""
        merge_count = len(self._get_all_children(self.merge_list_box))
        has_selected_file = self.selected_pdf is not None
        has_reorder_content = self.reorder_source_path is not None

        # Update button states
        self.merge_button.set_sensitive(merge_count >= 2 and not self.is_processing)
        self.compress_button.set_sensitive(has_selected_file and not self.is_processing)
        self.split_button.set_sensitive(has_selected_file and not self.is_processing)
        self.reorder_button.set_sensitive(has_reorder_content and not self.is_processing)
        self.clear_button.set_sensitive(merge_count > 0 and not self.is_processing)

        # Check if we should reset to placeholder
        if merge_count == 0:
            self.main_stack.set_visible_child_name("placeholder")
            self.selected_pdf = None
            self.reorder_source_path = None

    def _get_all_children(self, container):
        """Get all children of a container."""
        children = []
        child = container.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def _on_compress_clicked(self, button):
        """Handle compress button click."""
        if not self.selected_pdf:
            return

        source_path = Path(self.selected_pdf)
        default_name = f"{source_path.stem}_compressed.pdf"
        self._show_save_dialog(default_name, self._run_compress_task, source_path.parent)

    def _on_split_clicked(self, button):
        """Handle split button click."""
        if not self.selected_pdf:
            return

        source_path = Path(self.selected_pdf)
        self._show_folder_dialog(self._run_split_task, source_path.parent)

    def _on_merge_clicked(self, button):
        """Handle merge button click."""
        default_name = "merged.pdf"
        self._show_save_dialog(default_name, self._run_merge_task)

    def _on_reorder_clicked(self, button):
        """Handle reorder button click."""
        if not self.reorder_source_path:
            return

        source_path = Path(self.reorder_source_path)
        default_name = f"{source_path.stem}_reordered.pdf"
        self._show_save_dialog(default_name, self._run_reorder_task, source_path.parent)

    def _on_quality_changed(self, combo):
        """Handle quality selection change."""
        self.compression_quality = combo.get_active_text()

    def _show_save_dialog(self, default_name, callback_on_accept, initial_dir=None):
        """Show save file dialog."""
        file_chooser = Gtk.FileChooserDialog(
            title="Save As...", 
            transient_for=self, 
            action=Gtk.FileChooserAction.SAVE
        )
        file_chooser.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, 
            "_Save", Gtk.ResponseType.ACCEPT
        )

        file_filter = Gtk.FileFilter()
        file_filter.set_name("PDF files")
        file_filter.add_mime_type("application/pdf")
        file_chooser.add_filter(file_filter)
        file_chooser.set_current_name(default_name)

        if initial_dir:
            folder_file = Gio.File.new_for_path(str(initial_dir))
            file_chooser.set_current_folder(folder_file)

        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                callback_on_accept(dialog.get_file().get_path())
            dialog.destroy()

        file_chooser.connect("response", on_response)
        file_chooser.present()

    def _show_folder_dialog(self, callback_on_accept, initial_dir=None):
        """Show folder selection dialog."""
        folder_chooser = Gtk.FileChooserDialog(
            title="Select Output Folder", 
            transient_for=self, 
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        folder_chooser.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, 
            "_Select", Gtk.ResponseType.ACCEPT
        )

        if initial_dir:
            folder_file = Gio.File.new_for_path(str(initial_dir))
            folder_chooser.set_current_folder(folder_file)

        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                callback_on_accept(dialog.get_file().get_path())
            dialog.destroy()

        folder_chooser.connect("response", on_response)
        folder_chooser.present()

    # Task execution methods
    def _run_compress_task(self, output_path):
        """Run compression task in background."""
        if not self.selected_pdf:
            return

        input_path = self.selected_pdf
        self._set_processing_state(True, "Compressing PDF...")

        def task():
            success, message = self._compress_pdf(input_path, output_path, self.compression_quality)
            GLib.idle_add(self._on_task_finished, success, message)

        threading.Thread(target=task, daemon=True).start()

    def _run_split_task(self, output_dir):
        """Run split task in background."""
        if not self.selected_pdf:
            return

        input_path = self.selected_pdf
        self._set_processing_state(True, "Splitting PDF...")

        def task():
            success, message = self._split_pdf(input_path, output_dir)
            GLib.idle_add(self._on_task_finished, success, message)

        threading.Thread(target=task, daemon=True).start()

    def _run_merge_task(self, output_path):
        """Run merge task in background."""
        children = self._get_all_children(self.merge_list_box)
        pdf_paths = [child.file_path for child in children]

        self._set_processing_state(True, "Merging PDFs...")

        def task():
            success, message = self._merge_pdfs(pdf_paths, output_path)
            GLib.idle_add(self._on_task_finished, success, message, True)  # Clear merge list on success

        threading.Thread(target=task, daemon=True).start()

    def _run_reorder_task(self, output_path):
        """Run reorder task in background."""
        if not self.reorder_source_path:
            return

        flow_box_children = self._get_all_children(self.reorder_flow_box)
        new_order_indices = [child.original_page_index for child in flow_box_children if not child.is_deleted]

        self._set_processing_state(True, "Saving reordered PDF...")

        def task():
            success, message = self._reorder_pdf_pages(self.reorder_source_path, output_path, new_order_indices)
            GLib.idle_add(self._on_task_finished, success, message)

        threading.Thread(target=task, daemon=True).start()

    # PDF manipulation methods
    def _compress_pdf(self, input_path, output_path, quality="ebook"):
        """Compress PDF using Ghostscript."""
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

    def _split_pdf(self, input_path, output_dir):
        """Split PDF into individual pages."""
        try:
            reader = PdfReader(input_path)
            base_name = Path(input_path).stem
            os.makedirs(output_dir, exist_ok=True)

            for i, page in enumerate(reader.pages):
                writer = PdfWriter()
                writer.add_page(page)
                output_filename = os.path.join(output_dir, f"{base_name}_page_{i + 1}.pdf")
                with open(output_filename, "wb") as f:
                    writer.write(f)

            return True, f"Successfully split into {len(reader.pages)} pages."
        except Exception as e:
            return False, f"Failed to split PDF: {e}"

    def _merge_pdfs(self, pdf_paths, output_path):
        """Merge multiple PDF files."""
        try:
            merger = PdfWriter()
            for path in pdf_paths:
                merger.append(path)
            merger.write(output_path)
            merger.close()
            return True, f"Successfully merged {len(pdf_paths)} files."
        except Exception as e:
            return False, f"Failed to merge PDFs: {e}"

    def _reorder_pdf_pages(self, input_path, output_path, new_order_indices):
        """Reorder PDF pages."""
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

    def _set_processing_state(self, is_processing, message=""):
        """Set processing state."""
        self.is_processing = is_processing
        self.update_ui_state()
        if is_processing:
            self.toast_overlay.add_toast(Adw.Toast(title=message))

    def _on_task_finished(self, success, message, clear_merge=False):
        """Handle task completion."""
        self._set_processing_state(False)
        self.toast_overlay.add_toast(Adw.Toast(title=message))

        if success and clear_merge:
            # Clear merge list after successful merge
            child = self.merge_list_box.get_first_child()
            while child:
                next_child = child.get_next_sibling()
                self.merge_list_box.remove(child)
                child = next_child

            self.selected_pdf = None
            self._clear_reorder_view()
            self.reorder_source_path = None
            self.update_ui_state()

        return False  # Remove from idle

    def _on_close_request(self, window):
        """Handle window close request."""
        if self.is_processing:
            self.toast_overlay.add_toast(Adw.Toast(title="Cannot close while a task is in progress."))
            return True
        return False

class PdfToolApp(Adw.Application):
    """Main application class."""
    def __init__(self, **kwargs):
        super().__init__(application_id="com.github.juliengrdn.iatepdfs", **kwargs)

    def do_activate(self):
        """Activate the application."""
        if not shutil.which("gs"):
            dialog = Adw.MessageDialog(
                transient_for=self.get_active_window(), 
                modal=True,
                heading="Dependency Missing: Ghostscript",
                body="This application requires Ghostscript ('gs') for compression. Please install it and ensure it's in your PATH."
            )
            dialog.add_response("ok", "OK")
            dialog.connect("response", lambda d, r: d.close())
            dialog.present()
            return

        win = self.props.active_window
        if not win:
            win = PdfToolWindow(application=self)
        win.present()

if __name__ == "__main__":
    app = PdfToolApp()
    app.run(sys.argv)
