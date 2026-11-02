import copy
import json
import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw
import pystray

from storage import NotesStore, atomic_write
from ui import FONT, THEME, NotesUI
from windowing import show_child_window

try:
	import winreg
except ImportError:
	winreg = None

APP_NAME = "DesktopStickyNotes"


class StickyNotesApp(NotesUI):
	def __init__(self, root: tk.Tk, data_dir=None, start_tray=True):
		self.root = root
		root.title("桌面便签")
		root.minsize(900, 600)
		root.configure(bg=THEME["bg"])
		root.protocol("WM_DELETE_WINDOW", self.on_close_main)
		self.current_category_id = None
		self.current_tag_id = None
		self.last_selected_tags = {}
		self.deleted_item = None
		self.loading_editor = False
		self.save_after_id = None
		self.dirty = False
		self.last_save_error = None
		self.drag = None
		self.tray_icon = None
		self.settings_window = None
		self.help_window = None
		self.startup_var = tk.BooleanVar(value=self.is_startup_enabled())
		self.data_file = os.path.join(data_dir or self.get_data_dir(), "notes.json")
		self.store = NotesStore(self.data_file)
		self.store.acquire()
		try:
			self.document = self.store.load()
		except Exception:
			self.store.close()
			raise
		self.categories = self.document["categories"]
		self.next_category_id = self.document["next_category_id"]
		self.next_tag_id = self.document["next_tag_id"]
		self.settings = self.document["settings"]
		if not self.categories:
			self.categories = [{"id": 1, "name": "默认分类", "tags": [{"id": 1, "title": "标签 1", "content": ""}]}]
			self.next_category_id = max(self.next_category_id, 2)
			self.next_tag_id = max(self.next_tag_id, 2)
		alpha = self.settings.get("main_alpha", 1.0)
		alpha = max(0.65, min(1.0, alpha)) if isinstance(alpha, (int, float)) else 1.0
		self.main_alpha_var = tk.DoubleVar(value=alpha)
		root.attributes("-alpha", alpha)
		self.initial_geometry = "1180x740"
		try:
			width, height = self.settings.get("geometry", "").split("+", 1)[0].split("x")
			self.initial_geometry = f"{max(900, min(int(width), root.winfo_screenwidth()))}x{max(600, min(int(height), root.winfo_screenheight()))}"
		except (ValueError, AttributeError):
			pass
		root.geometry(self.initial_geometry)
		self.setup_style()
		self.build_ui()
		self.current_category_id = self.categories[0]["id"]
		self.select_first_tag()
		self.bind_shortcuts()
		if start_tray:
			self.create_tray_icon()
		if start_tray and "--background" in sys.argv:
			self.hide_to_tray()

	@staticmethod
	def get_data_dir():
		app_data = os.getenv("APPDATA")
		path = os.path.join(app_data, APP_NAME) if app_data else os.path.join(os.path.expanduser("~"), f".{APP_NAME}")
		os.makedirs(path, exist_ok=True)
		return path

	def get_current_category(self):
		return next((c for c in self.categories if c["id"] == self.current_category_id), None)

	def get_current_tags(self):
		category = self.get_current_category()
		return category["tags"] if category else []

	def get_current_tag(self):
		return next((t for t in self.get_current_tags() if t["id"] == self.current_tag_id), None)

	def get_visible_tags(self):
		query = self.search_var.get().strip().casefold()
		return [t for t in self.get_current_tags() if not query or query in t["title"].casefold() or query in t["content"].casefold()]

	@staticmethod
	def abbreviated(text, length):
		text = " ".join(text.split())
		return text[:length] + "…" if len(text) > length else text

	def fit_list_text(self, widget, text):
		text = " ".join(text.split())
		width = max(40, int(widget.column("#0", "width")) - 26)
		if self.list_font.measure(text) <= width:
			return text
		left, right = 0, min(len(text), 160)
		while left < right:
			middle = (left + right + 1) // 2
			if self.list_font.measure(text[:middle] + "…") <= width:
				left = middle
			else:
				right = middle - 1
		return text[:left] + "…"

	def refresh_categories_list(self):
		self.refresh_list(self.categories_list, self.categories, self.current_category_id,
			lambda c: self.fit_list_text(self.categories_list, c["name"]))
		for category in self.categories:
			self.categories_list.item(str(category["id"]), values=(len(category["tags"]),))

	def refresh_tags_list(self):
		visible = self.get_visible_tags()
		self.refresh_list(self.tags_list, visible, self.current_tag_id, lambda t:
			f"{self.fit_list_text(self.tags_list, t['title']) or '未命名便签'}\n{self.fit_list_text(self.tags_list, t['content']) or '暂无正文'}")
		category = self.get_current_category()
		self.list_title_var.set(self.abbreviated(category["name"], 16) if category else "便签")
		query = bool(self.search_var.get().strip())
		self.list_count_var.set(f"找到 {len(visible)} / {len(self.get_current_tags())} 条便签" if query else f"{len(visible)} 条便签")
		self.clear_search_button.configure(state="normal" if query else "disabled")
		self.list_empty_var.set("没有匹配的便签" if query else "这里还没有便签")
		(self.list_holder if visible else self.list_empty).tkraise()
		self.update_editor_context()
		self.update_action_states()
		self.update_counts()

	@staticmethod
	def refresh_list(widget, items, selected_id, label):
		# Stable IDs preserve focus, scroll and keyboard selection during autosave.
		scroll = widget.yview()[0]
		wanted = {str(item["id"]) for item in items}
		for iid in widget.get_children():
			if iid not in wanted:
				widget.delete(iid)
		for index, item in enumerate(items):
			iid, text = str(item["id"]), label(item)
			if not widget.exists(iid):
				widget.insert("", index, iid=iid, text=text)
			else:
				widget.move(iid, "", index)
				if widget.item(iid, "text") != text:
					widget.item(iid, text=text)
		selected = str(selected_id)
		if selected in wanted and widget.selection() != (selected,):
			widget.selection_set(selected)
			widget.focus(selected)
		widget.yview_moveto(scroll)

	def update_editor_context(self):
		tag = self.get_current_tag()
		hidden = tag and self.search_var.get().strip() and tag not in self.get_visible_tags()
		self.editor_context_var.set("当前便签不在搜索结果中，清空搜索即可重新定位。" if hidden else "")
		if hidden:
			self.editor_context_label.pack(anchor="w", pady=(0, 12), before=self.editor_stack)
		else:
			self.editor_context_label.pack_forget()

	def update_action_states(self):
		for kind, menu, items, current_id in (
			("category", self.category_menu, self.categories, self.current_category_id),
			("tag", self.note_menu, self.get_current_tags(), self.current_tag_id),
		):
			index = next((i for i, item in enumerate(items) if item["id"] == current_id), -1)
			offset = 2 if kind == "category" else 0
			filtered = kind == "tag" and bool(self.search_var.get().strip())
			menu.entryconfigure(offset, state="normal" if index > 0 and not filtered else "disabled")
			menu.entryconfigure(offset + 1, state="normal" if 0 <= index < len(items) - 1 and not filtered else "disabled")
			menu.entryconfigure(offset + 3, state="normal" if index >= 0 and (kind != "category" or len(items) > 1) else "disabled")
		self.note_menu_button.configure(state="normal" if self.get_current_tag() else "disabled")

	def update_counts(self):
		tag = self.get_current_tag()
		chars = len(tag["content"]) if tag else 0
		total = sum(len(c["tags"]) for c in self.categories)
		self.count_var.set(f"共 {total} 条便签  ·  当前 {chars} 字符")

	def select_first_tag(self, preferred=None):
		tags = self.get_current_tags()
		self.current_tag_id = next((t["id"] for t in tags if t["id"] == preferred), tags[0]["id"] if tags else None)
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()

	def on_category_select(self, _event=None):
		selected = self.categories_list.selection()
		if not selected:
			return
		category = next((c for c in self.categories if str(c["id"]) == selected[0]), None)
		if not category or category["id"] == self.current_category_id:
			return
		if not self.flush_pending():
			self.refresh_categories_list()
			return
		self.last_selected_tags[self.current_category_id] = self.current_tag_id
		self.current_category_id = category["id"]
		self.search_var.set("")
		self.select_first_tag(self.last_selected_tags.get(self.current_category_id))

	def on_tag_select(self, _event=None):
		selected = self.tags_list.selection()
		if not selected:
			return
		tag = next((t for t in self.get_visible_tags() if str(t["id"]) == selected[0]), None)
		if not tag or tag["id"] == self.current_tag_id:
			return
		if not self.flush_pending():
			self.refresh_tags_list()
			return
		self.current_tag_id = tag["id"]
		self.load_current_tag_to_editor()

	def load_current_tag_to_editor(self):
		tag = self.get_current_tag()
		self.loading_editor = True
		self.note_title_entry.configure(state="normal")
		self.note_text.configure(state="normal")
		self.note_title_var.set(tag["title"] if tag else "")
		self.note_text.delete("1.0", tk.END)
		self.note_text.insert("1.0", tag["content"] if tag else "")
		self.note_text.edit_reset()
		self.note_text.edit_modified(False)
		if not tag:
			self.note_title_entry.configure(state="disabled")
			self.note_text.configure(state="disabled")
		(self.editor_content if tag else self.editor_empty).tkraise()
		category = self.get_current_category()
		self.breadcrumb_var.set(f"{self.abbreviated(category['name'], 14)} / 便签" if category else "便签")
		self.loading_editor = False
		self.update_editor_context()
		self.update_action_states()
		self.update_counts()

	def on_text_modified(self, _event=None):
		if self.note_text.edit_modified():
			self.schedule_save_current()
			self.note_text.edit_modified(False)

	def schedule_save_current(self):
		if self.loading_editor:
			return
		tag = self.get_current_tag()
		if not tag:
			return
		tag["title"] = self.note_title_var.get()
		tag["content"] = self.note_text.get("1.0", "end-1c")
		self.update_counts()
		self.schedule_persist()

	def schedule_persist(self):
		self.dirty = True
		self.status_var.set("有更改 · 即将自动保存")
		self.status_label.configure(fg=THEME["muted"])
		if self.save_after_id:
			self.root.after_cancel(self.save_after_id)
		self.save_after_id = self.root.after(400, self.save_current_note)

	def save_current_note(self):
		self.save_after_id = None
		self.refresh_tags_list()
		return self.save_data()

	def flush_pending(self):
		if self.note_text.edit_modified():
			self.schedule_save_current()
			self.note_text.edit_modified(False)
		if self.save_after_id:
			self.root.after_cancel(self.save_after_id)
			self.save_after_id = None
		return self.save_current_note() if self.dirty else True

	def make_document(self):
		data = dict(self.document)
		settings = dict(self.settings)
		geometry = self.root.winfo_geometry() if self.root.winfo_width() > 1 else self.initial_geometry
		settings.update(main_alpha=round(self.main_alpha_var.get(), 2), geometry=geometry)
		data.update(categories=self.categories, next_category_id=self.next_category_id, next_tag_id=self.next_tag_id, settings=settings)
		return data

	def save_data(self):
		try:
			self.store.save(self.make_document())
		except (OSError, ValueError) as exc:
			self.dirty = True
			self.status_var.set("保存失败 · 请重试或导出备份")
			self.status_label.configure(fg=THEME["danger"])
			if self.last_save_error != str(exc):
				self.last_save_error = str(exc)
				messagebox.showerror("保存失败", f"未能保存，当前内容仍保留在窗口中，请勿退出。\n请检查磁盘空间和文件权限，或使用「导出备份」。\n\n{exc}", parent=self.root)
			return False
		self.dirty = False
		self.last_save_error = None
		self.status_var.set(f"已保存到本机 · {datetime.now():%H:%M:%S}")
		self.status_label.configure(fg=THEME["accent"])
		return True

	def add_category(self):
		if not self.flush_pending():
			return
		name = simpledialog.askstring("新建分类", "给分类起个名字：", parent=self.root)
		if not name or not name.strip():
			return
		category = {"id": self.next_category_id, "name": name.strip(), "tags": []}
		self.next_category_id += 1
		self.categories.append(category)
		self.last_selected_tags[self.current_category_id] = self.current_tag_id
		self.current_category_id = category["id"]
		self.search_var.set("")
		self.select_first_tag()
		self.categories_list.see(str(category["id"]))
		self.save_data()

	def rename_selected_category(self, _event=None):
		category = self.get_current_category()
		if not category or not self.flush_pending():
			return
		name = simpledialog.askstring("重命名分类", "请输入新的分类名称：", initialvalue=category["name"], parent=self.root)
		if name and name.strip():
			category["name"] = name.strip()
			self.refresh_categories_list()
			self.refresh_tags_list()
			self.breadcrumb_var.set(f"{self.abbreviated(name.strip(), 14)} / 便签")
			self.save_data()

	def remember_deletion(self, kind, item, index, category_id=None):
		self.deleted_item = (kind, copy.deepcopy(item), index, category_id)
		name = item["name"] if kind == "category" else item["title"]
		self.undo_var.set(f"已删除{'分类' if kind == 'category' else '便签'}「{self.abbreviated(name, 24)}」")
		self.undo_bar.grid()

	def delete_selected_category(self):
		category = self.get_current_category()
		if not category or not self.flush_pending():
			return
		if len(self.categories) <= 1:
			messagebox.showwarning("提示", "至少保留一个分类。", parent=self.root)
			return
		if not messagebox.askyesno("删除分类", f"确定删除「{category['name']}」及其中的 {len(category['tags'])} 条便签？\n删除后可点击「撤销删除」，历史备份中也会保留删除前的文件。", parent=self.root):
			return
		if not self.save_data():
			return
		index = self.categories.index(category)
		self.last_selected_tags[category["id"]] = self.current_tag_id
		self.remember_deletion("category", category, index)
		self.categories.remove(category)
		self.current_category_id = self.categories[min(index, len(self.categories) - 1)]["id"]
		self.search_var.set("")
		self.select_first_tag(self.last_selected_tags.get(self.current_category_id))
		self.save_data()

	def add_tag(self):
		if not self.flush_pending():
			return
		category = self.get_current_category()
		if not category:
			return
		tag = {"id": self.next_tag_id, "title": f"便签 {self.next_tag_id}", "content": ""}
		self.next_tag_id += 1
		category["tags"].append(tag)
		self.current_tag_id = tag["id"]
		self.search_var.set("")
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()
		self.tags_list.see(str(tag["id"]))
		self.note_title_entry.focus_set()
		self.note_title_entry.selection_range(0, tk.END)
		self.save_data()

	def delete_selected_tag(self):
		tag = self.get_current_tag()
		if not tag or not self.flush_pending():
			return
		if not messagebox.askyesno("删除便签", f"确定删除「{tag['title']}」？\n删除后可点击「撤销删除」，历史备份中也会保留删除前的文件。", parent=self.root):
			return
		if not self.save_data():
			return
		tags = self.get_current_tags()
		index = tags.index(tag)
		self.remember_deletion("tag", tag, index, self.current_category_id)
		tags.remove(tag)
		preferred = tags[min(index, len(tags) - 1)]["id"] if tags else None
		self.select_first_tag(preferred)
		self.save_data()

	def undo_delete(self):
		if not self.deleted_item or not self.flush_pending():
			return
		kind, item, index, category_id = self.deleted_item
		if kind == "category":
			self.categories.insert(min(index, len(self.categories)), item)
			self.current_category_id = item["id"]
			preferred = self.last_selected_tags.get(item["id"])
		else:
			category = next((c for c in self.categories if c["id"] == category_id), None)
			if not category:
				return
			category["tags"].insert(min(index, len(category["tags"])), item)
			self.current_category_id, preferred = category_id, item["id"]
		self.deleted_item = None
		self.undo_bar.grid_remove()
		self.search_var.set("")
		self.select_first_tag(preferred)
		self.save_data()

	def move_selected(self, kind, offset):
		if kind == "tag" and self.search_var.get().strip():
			return
		if not self.flush_pending():
			return
		items = self.categories if kind == "category" else self.get_current_tags()
		current_id = self.current_category_id if kind == "category" else self.current_tag_id
		index = next((i for i, item in enumerate(items) if item["id"] == current_id), -1)
		target = index + offset
		if index < 0 or not 0 <= target < len(items):
			return
		items.insert(target, items.pop(index))
		self.refresh_categories_list()
		self.refresh_tags_list()
		(self.categories_list if kind == "category" else self.tags_list).see(str(current_id))
		self.save_data()

	def bind_drag(self, widget, kind):
		widget.bind("<ButtonPress-1>", lambda event: self.drag_start(event, kind))
		widget.bind("<B1-Motion>", self.drag_motion)
		widget.bind("<ButtonRelease-1>", self.drag_end)

	def drag_start(self, event, kind):
		self.drag = None
		if kind == "tag" and self.search_var.get().strip():
			return
		row = event.widget.identify_row(event.y)
		if row and self.flush_pending():
			self.drag = (kind, row, False)

	def drag_motion(self, event):
		if not self.drag:
			return
		kind, iid, moved = self.drag
		row = event.widget.identify_row(event.y)
		items = self.categories if kind == "category" else self.get_current_tags()
		index = next((i for i, item in enumerate(items) if str(item["id"]) == iid), -1)
		target = next((i for i, item in enumerate(items) if str(item["id"]) == row), -1)
		if index < 0 or target < 0 or index == target:
			return
		# Do not reorder an unselected item if the preceding save blocked selection.
		current_id = self.current_category_id if kind == "category" else self.current_tag_id
		if str(current_id) != iid:
			return
		items.insert(target, items.pop(index))
		self.drag = (kind, iid, True)
		self.root.configure(cursor="fleur")
		self.refresh_categories_list()
		self.refresh_tags_list()

	def drag_end(self, _event=None):
		if self.drag and self.drag[2]:
			self.save_data()
		self.drag = None
		self.root.configure(cursor="")

	def bind_item_context(self, widget, kind):
		def popup(event, keyboard=False):
			row = widget.focus() if keyboard else widget.identify_row(event.y)
			if not row or not self.flush_pending():
				return "break"
			widget.selection_set(row)
			widget.focus(row)
			widget.focus_set()
			(self.on_category_select if kind == "category" else self.on_tag_select)()
			menu = self.category_menu if kind == "category" else self.note_menu
			x, y = (widget.winfo_rootx() + 24, widget.winfo_rooty() + 30) if keyboard else (event.x_root, event.y_root)
			try:
				menu.tk_popup(x, y)
			finally:
				menu.grab_release()
			return "break"
		widget.bind("<Button-3>", popup)
		widget.bind("<Shift-F10>", lambda event: popup(event, True))

	def bind_shortcuts(self):
		def run(action):
			def callback(_event):
				action()
				return "break"
			return callback
		for key, action in (("<Control-n>", self.add_tag), ("<Control-s>", self.manual_save),
			("<Control-f>", self.focus_search), ("<Control-e>", self.export_data), ("<F1>", self.show_help),
			("<F6>", lambda: self.cycle_focus(1)), ("<Shift-F6>", lambda: self.cycle_focus(-1))):
			self.root.bind(key, run(action))
		self.categories_list.bind("<F2>", run(self.rename_selected_category))
		self.tags_list.bind("<Return>", run(self.note_text.focus_set))
		self.note_text.bind("<Control-z>", run(lambda: self.edit_history(False)))
		self.note_text.bind("<Control-y>", run(lambda: self.edit_history(True)))
		self.note_text.bind("<Control-Shift-Z>", run(lambda: self.edit_history(True)))
		self.search_entry.bind("<Escape>", run(lambda: self.search_var.set("")))

	def cycle_focus(self, direction):
		widgets = [self.categories_list, self.tags_list if self.get_visible_tags() else self.search_entry]
		if self.get_current_tag():
			widgets += [self.note_title_entry, self.note_text]
		current = self.root.focus_get()
		index = widgets.index(current) if current in widgets else (-1 if direction > 0 else 0)
		widgets[(index + direction) % len(widgets)].focus_set()

	def edit_history(self, redo):
		try:
			self.note_text.edit_redo() if redo else self.note_text.edit_undo()
		except tk.TclError:
			pass

	def focus_search(self):
		self.search_entry.focus_set()
		self.search_entry.selection_range(0, tk.END)

	def manual_save(self):
		if self.flush_pending():
			self.save_data()

	def export_data(self):
		# Export remains available even when local persistence is failing.
		self.flush_pending()
		path = filedialog.asksaveasfilename(parent=self.root, title="导出全部便签", defaultextension=".json",
			initialfile=f"桌面便签备份-{datetime.now():%Y%m%d-%H%M%S}.json", filetypes=[("JSON 备份", "*.json")])
		if not path:
			return
		if os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(self.data_file)):
			messagebox.showwarning("请选择其他位置", "导出文件不能覆盖正在使用的数据文件。", parent=self.root)
			return
		try:
			atomic_write(path, (json.dumps(self.make_document(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
		except OSError as exc:
			messagebox.showerror("导出失败", str(exc), parent=self.root)
		else:
			total = sum(len(c["tags"]) for c in self.categories)
			messagebox.showinfo("导出完成", f"已导出全部 {len(self.categories)} 个分类、{total} 条便签。\n包含完整正文，不受当前搜索影响。\n\n{path}", parent=self.root)

	def show_help(self):
		if self.help_window and self.help_window.winfo_exists():
			show_child_window(self.help_window, self.root)
			return
		window = tk.Toplevel(self.root)
		window.withdraw()
		self.help_window = window
		window.title("使用帮助")
		window.geometry("480x460")
		window.transient(self.root)
		window.configure(bg=THEME["panel"])
		panel = tk.Frame(window, bg=THEME["panel"], padx=24, pady=24)
		panel.pack(fill=tk.BOTH, expand=True)
		self.label(panel, "选择分类 → 选择便签 → 直接编辑", size=12, bold=True).pack(anchor="w", pady=(0, 14))
		self.label(panel, "内容自动保存。顶部「导出备份」导出全部记录。\n搜索仅作用于当前分类，不会修改内容。\n拖动分隔线可调整三栏宽度。", fg="muted", justify=tk.LEFT).pack(anchor="w", pady=(0, 18))
		self.label(panel, "Ctrl+N  新建便签       Ctrl+S  立即保存\nCtrl+F  搜索当前分类   Ctrl+E  导出备份\nCtrl+Z / Ctrl+Y  正文撤销 / 重做\nF6 / Shift+F6  切换列表与编辑区\n分类列表中 F2  重命名\n列表中 Shift+F10  打开操作菜单\n正文中 Ctrl+Tab  移到下一个控件", justify=tk.LEFT).pack(anchor="w", pady=(0, 18))
		self.label(panel, "关闭主窗口会隐藏至托盘；从托盘菜单退出。\n最近一次删除可撤销，退出后请从历史备份恢复。", fg="muted", justify=tk.LEFT).pack(anchor="w")
		show_child_window(window, self.root)

	def show_settings(self):
		if self.settings_window and self.settings_window.winfo_exists():
			show_child_window(self.settings_window, self.root)
			return
		window = tk.Toplevel(self.root)
		window.withdraw()
		self.settings_window = window
		window.title("偏好设置")
		window.geometry("440x350")
		window.resizable(False, False)
		window.transient(self.root)
		window.configure(bg=THEME["panel"])
		panel = ttk.Frame(window, style="Panel.TFrame", padding=24)
		panel.pack(fill=tk.BOTH, expand=True)
		ttk.Checkbutton(panel, text="开机自启（静默进入托盘）", variable=self.startup_var, command=self.toggle_startup, style="App.TCheckbutton").pack(anchor="w", pady=(0, 20))
		self.label(panel, "窗口透明度", bold=True).pack(anchor="w")
		ttk.Scale(panel, from_=0.65, to=1.0, variable=self.main_alpha_var, command=self.on_main_alpha_change).pack(fill=tk.X, pady=(8, 16))
		self.label(panel, "自动保留最近 30 个历史版本。\n备份包含完整正文，请妥善保管。\n为保证可读性，建议使用不透明窗口。", fg="muted", justify=tk.LEFT).pack(anchor="w", pady=(0, 18))
		ttk.Button(panel, text="打开数据与备份目录", style="Ghost.TButton", command=self.open_data_dir).pack(anchor="w")
		show_child_window(window, self.root)

	def on_main_alpha_change(self, _value=None):
		self.root.attributes("-alpha", self.main_alpha_var.get())
		self.schedule_persist()

	def open_data_dir(self):
		path = os.path.dirname(self.data_file)
		if os.name == "nt":
			os.startfile(path)
		else:
			messagebox.showinfo("数据目录", path, parent=self.root)

	def hide_to_tray(self):
		if self.flush_pending() and self.save_data() and self.tray_icon:
			self.root.withdraw()

	def show_from_tray(self):
		self.root.deiconify()
		self.root.lift()
		self.root.focus_force()

	def on_close_main(self):
		self.hide_to_tray() if self.tray_icon else self.quit_app()

	def quit_app(self):
		if not self.flush_pending() or not self.save_data():
			self.show_from_tray()
			return
		if self.tray_icon:
			self.tray_icon.stop()
		self.store.close()
		self.root.destroy()

	@staticmethod
	def create_tray_image():
		img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
		draw = ImageDraw.Draw(img)
		draw.rounded_rectangle((3, 3, 61, 61), radius=14, fill=THEME["accent"])
		draw.rounded_rectangle((15, 12, 49, 52), radius=4, fill=THEME["editor_bg"])
		for y, end in ((24, 41), (32, 41), (40, 35)):
			draw.line((22, y, end, y), fill=THEME["accent"], width=3)
		return img

	def create_tray_icon(self):
		def dispatch(action):
			return lambda _icon, _item: self.root.after(0, action)
		def new_note():
			self.show_from_tray()
			self.add_tag()
		menu = pystray.Menu(
			pystray.MenuItem("显示便签", dispatch(self.show_from_tray), default=True),
			pystray.MenuItem("新建便签", dispatch(new_note)),
			pystray.MenuItem("隐藏", dispatch(self.hide_to_tray)), pystray.Menu.SEPARATOR,
			pystray.MenuItem("退出", dispatch(self.quit_app)),
		)
		self.tray_icon = pystray.Icon(APP_NAME, self.create_tray_image(), "桌面便签", menu)
		threading.Thread(target=self.run_tray, daemon=True).start()

	def run_tray(self):
		try:
			self.tray_icon.run()
		except Exception:
			self.root.after(0, self.on_tray_failure)

	def on_tray_failure(self):
		self.tray_icon = None
		self.show_from_tray()
		messagebox.showwarning("托盘不可用", "系统托盘不可用，关闭窗口将保存并退出。", parent=self.root)

	def get_startup_command(self):
		if getattr(sys, "frozen", False):
			return f'"{sys.executable}" --background'
		return f'"{sys.executable}" "{os.path.abspath(__file__)}" --background'

	def is_startup_enabled(self):
		if winreg is None:
			return False
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
				value, _ = winreg.QueryValueEx(key, APP_NAME)
				return bool(value)
		except OSError:
			return False

	def toggle_startup(self):
		if winreg is None:
			messagebox.showerror("不支持", "开机自启设置仅支持 Windows。", parent=self.root)
			self.startup_var.set(False)
			return
		try:
			with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
				if self.startup_var.get():
					winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self.get_startup_command())
				else:
					try:
						winreg.DeleteValue(key, APP_NAME)
					except FileNotFoundError:
						pass
		except OSError as exc:
			messagebox.showerror("设置失败", str(exc), parent=self.root)
			self.startup_var.set(self.is_startup_enabled())


def main():
	root = tk.Tk()
	root.withdraw()
	try:
		StickyNotesApp(root)
	except (OSError, ValueError) as exc:
		messagebox.showerror("无法打开桌面便签", f"{exc}\n\n为保护已有记录，程序不会覆盖原数据文件。\n请检查数据文件或从备份中恢复。", parent=root)
		root.destroy()
		return
	if "--background" not in sys.argv:
		root.deiconify()
	root.mainloop()


if __name__ == "__main__":
	main()
