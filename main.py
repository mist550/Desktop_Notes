import json
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageDraw
import pystray

try:
	import winreg
except ImportError:
	winreg = None


APP_NAME = "DesktopStickyNotes"

THEME = {
	"bg": "#f4f7fb",
	"panel": "#ffffff",
	"panel_alt": "#eef2f7",
	"text": "#1f2937",
	"muted": "#64748b",
	"accent": "#2563eb",
	"accent_active": "#1d4ed8",
	"editor_bg": "#fffbeb",
	"editor_fg": "#1f2937",
}


class StickyNotesApp:
	def __init__(self, root: tk.Tk):
		self.root = root
		self.root.title("桌面便签")
		self.root.geometry("900x580")
		self.root.minsize(760, 500)
		self.root.protocol("WM_DELETE_WINDOW", self.on_close_main)
		self.root.configure(bg=THEME["bg"])
		self.root.attributes("-topmost", False)
		if os.name == "nt":
			# 工具窗口风格：尽量不以常规任务栏主程序形式出现。
			self.root.wm_attributes("-toolwindow", True)

		self.notes = []
		self.categories = []
		self.next_category_id = 1
		self.next_tag_id = 1
		self.current_category_id = None
		self.current_tag_id = None
		self.loading_editor = False
		self.save_after_id = None
		self.category_drag_index = None
		self.tag_drag_index = None
		self.dragging_category = False
		self.dragging_tag = False

		self.tray_icon = None
		self.settings = {}

		self.startup_var = tk.BooleanVar(value=self.is_startup_enabled())

		self.data_file = os.path.join(self.get_data_dir(), "notes.json")
		self.load_data()

		self.main_alpha_var = tk.DoubleVar(value=self.settings.get("main_alpha", 0.92))
		self.root.attributes("-alpha", self.main_alpha_var.get())

		self.setup_style()
		self.build_ui()
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.pick_initial_selection()
		self.create_tray_icon()
		self.hide_to_tray()

	def setup_style(self):
		style = ttk.Style(self.root)
		style.theme_use("clam")

		style.configure("App.TFrame", background=THEME["bg"])
		style.configure("Panel.TFrame", background=THEME["panel"])
		style.configure("Toolbar.TFrame", background=THEME["panel_alt"])
		style.configure("Title.TLabel", background=THEME["panel"], foreground=THEME["text"], font=("Microsoft YaHei UI", 18, "bold"))
		style.configure("Desc.TLabel", background=THEME["panel"], foreground=THEME["muted"], font=("Microsoft YaHei UI", 10))
		style.configure("Section.TLabel", background=THEME["panel"], foreground=THEME["text"], font=("Microsoft YaHei UI", 10, "bold"))
		style.configure("App.TCheckbutton", background=THEME["panel"], foreground=THEME["text"], font=("Microsoft YaHei UI", 10))
		style.map("App.TCheckbutton", background=[("active", THEME["panel"])])

		style.configure(
			"App.TButton",
			background=THEME["accent"],
			foreground="#ffffff",
			borderwidth=0,
			padding=(8, 4),
			font=("Microsoft YaHei UI", 10, "bold"),
		)
		style.map(
			"App.TButton",
			background=[("active", THEME["accent_active"]), ("pressed", THEME["accent_active"])],
		)

		style.configure(
			"Ghost.TButton",
			background=THEME["panel_alt"],
			foreground=THEME["text"],
			borderwidth=0,
			padding=(8, 4),
			font=("Microsoft YaHei UI", 10, "bold"),
		)
		style.map("Ghost.TButton", background=[("active", "#dbe7fb"), ("pressed", "#dbe7fb")])

	def get_data_dir(self) -> str:
		app_data = os.getenv("APPDATA")
		if app_data:
			path = os.path.join(app_data, APP_NAME)
		else:
			path = os.path.join(os.path.expanduser("~"), f".{APP_NAME}")
		os.makedirs(path, exist_ok=True)
		return path

	def build_ui(self):
		top = ttk.Frame(self.root, style="App.TFrame", padding=8)
		top.pack(fill=tk.BOTH, expand=True)

		panel = ttk.Frame(top, style="Panel.TFrame", padding=8)
		panel.pack(fill=tk.BOTH, expand=True)

		title = ttk.Label(panel, text="桌面便签", style="Title.TLabel")
		title.pack(anchor="w")

		desc = ttk.Label(panel, text="单窗口编辑，左侧分类管理，关闭后可在托盘恢复", style="Desc.TLabel")
		desc.pack(anchor="w", pady=(4, 10))

		startup_check = ttk.Checkbutton(
			panel,
			text="开机自启",
			variable=self.startup_var,
			command=self.toggle_startup,
			style="App.TCheckbutton",
		)
		startup_check.pack(anchor="w", pady=(0, 10))

		ttk.Label(panel, text="主窗口透明度", style="Section.TLabel").pack(anchor="w")
		main_alpha = ttk.Scale(panel, from_=0.65, to=1.0, variable=self.main_alpha_var, command=self.on_main_alpha_change)
		main_alpha.pack(fill=tk.X, pady=(2, 12))

		workspace = ttk.Frame(panel, style="Panel.TFrame")
		workspace.pack(fill=tk.BOTH, expand=True)

		left = ttk.Frame(workspace, style="Toolbar.TFrame", padding=6)
		left.pack(side=tk.LEFT, fill=tk.Y)

		category_header = ttk.Frame(left, style="Toolbar.TFrame")
		category_header.pack(fill=tk.X)
		ttk.Label(category_header, text="分类", style="Section.TLabel").pack(side=tk.LEFT, anchor="w")
		category_actions = ttk.Frame(category_header, style="Toolbar.TFrame")
		category_actions.pack(side=tk.RIGHT)
		ttk.Button(category_actions, text="+", style="Ghost.TButton", command=self.add_category).pack(side=tk.LEFT)
		ttk.Button(category_actions, text="-", style="Ghost.TButton", command=self.delete_selected_category).pack(side=tk.LEFT, padx=(6, 0))

		self.categories_list = tk.Listbox(
			left,
			width=22,
			height=4,
			bg="#ffffff",
			fg=THEME["text"],
			selectbackground="#bfdbfe",
			selectforeground="#0f172a",
			highlightthickness=0,
			bd=0,
			font=("Microsoft YaHei UI", 10),
		)
		self.categories_list.pack(fill=tk.X, pady=(4, 8))
		self.categories_list.bind("<<ListboxSelect>>", self.on_category_select)
		self.categories_list.bind("<Double-Button-1>", self.rename_selected_category)
		self.categories_list.bind("<ButtonPress-1>", self.on_category_drag_start)
		self.categories_list.bind("<B1-Motion>", self.on_category_drag_motion)
		self.categories_list.bind("<ButtonRelease-1>", self.on_category_drag_end)

		tag_header = ttk.Frame(left, style="Toolbar.TFrame")
		tag_header.pack(fill=tk.X)
		ttk.Label(tag_header, text="标签", style="Section.TLabel").pack(side=tk.LEFT, anchor="w")
		tag_actions = ttk.Frame(tag_header, style="Toolbar.TFrame")
		tag_actions.pack(side=tk.RIGHT)
		ttk.Button(tag_actions, text="+", style="Ghost.TButton", command=self.add_tag).pack(side=tk.LEFT)
		ttk.Button(tag_actions, text="-", style="Ghost.TButton", command=self.delete_selected_tag).pack(side=tk.LEFT, padx=(6, 0))

		self.tags_list = tk.Listbox(
			left,
			width=22,
			height=14,
			bg="#ffffff",
			fg=THEME["text"],
			selectbackground="#bfdbfe",
			selectforeground="#0f172a",
			highlightthickness=0,
			bd=0,
			font=("Microsoft YaHei UI", 10),
		)
		self.tags_list.pack(fill=tk.BOTH, expand=True)
		self.tags_list.bind("<<ListboxSelect>>", self.on_tag_select)
		self.tags_list.bind("<ButtonPress-1>", self.on_tag_drag_start)
		self.tags_list.bind("<B1-Motion>", self.on_tag_drag_motion)
		self.tags_list.bind("<ButtonRelease-1>", self.on_tag_drag_end)

		self.feedback_var = tk.StringVar(value="双击分类可重命名，拖动分类/标签可排序")
		feedback = ttk.Label(left, textvariable=self.feedback_var, style="Desc.TLabel", wraplength=180, justify=tk.LEFT)
		feedback.pack(anchor="w", pady=(8, 0))

		right = tk.Frame(workspace, bg=THEME["editor_bg"], padx=10, pady=10)
		right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

		self.note_title_var = tk.StringVar(value="")
		self.note_title_var.trace_add("write", lambda *_: self.schedule_save_current())

		self.note_title_entry = tk.Entry(
			right,
			textvariable=self.note_title_var,
			bg="#fffdf4",
			fg=THEME["editor_fg"],
			relief=tk.FLAT,
			font=("Microsoft YaHei UI", 12, "bold"),
		)
		self.note_title_entry.pack(fill=tk.X, pady=(0, 8))

		self.note_text = tk.Text(
			right,
			wrap=tk.WORD,
			bg="#fffdf7",
			fg=THEME["editor_fg"],
			insertbackground=THEME["editor_fg"],
			relief=tk.FLAT,
			font=("Microsoft YaHei UI", 11),
		)
		self.note_text.pack(fill=tk.BOTH, expand=True)
		self.note_text.bind("<KeyRelease>", lambda _e: self.schedule_save_current())

		desc.configure(text="单窗口编辑，左侧先选分类，再管理分类内的标签，关闭后可在托盘恢复")

	def load_data(self):
		if not os.path.exists(self.data_file):
			self.categories = []
			self.next_category_id = 1
			self.next_tag_id = 1
			self.settings = {}
			self.ensure_default_data()
			return

		try:
			with open(self.data_file, "r", encoding="utf-8") as f:
				data = json.load(f)

			self.categories = self.normalize_categories(data)
			self.next_category_id = data.get("next_category_id", self.infer_next_category_id())
			self.next_tag_id = data.get("next_tag_id", self.infer_next_tag_id())
			self.settings = data.get("settings", {})
		except (OSError, json.JSONDecodeError):
			self.categories = []
			self.next_category_id = 1
			self.next_tag_id = 1
			self.settings = {}

		self.ensure_default_data()

	def normalize_categories(self, data):
		categories = []

		def normalize_tag(tag):
			if isinstance(tag, dict):
				return {
					"id": tag.get("id", 0),
					"title": tag.get("title", tag.get("name", "未命名")),
					"content": tag.get("content", ""),
				}
			return {"id": 0, "title": str(tag) if tag is not None else "未命名", "content": ""}

		if "categories" in data:
			for category in data.get("categories", []):
				items = category.get("tags")
				if items is None:
					items = category.get("notes", [])
				categories.append(
					{
						"id": category.get("id", 0),
						"name": category.get("name", "分类"),
						"tags": [normalize_tag(tag) for tag in items],
					}
				)
		elif "notes" in data:
			categories = [
				{
					"id": 1,
					"name": "默认分类",
					"tags": [normalize_tag(tag) for tag in data.get("notes", [])],
				}
			]

		return categories

	def infer_next_category_id(self):
		max_id = 0
		for category in self.categories:
			max_id = max(max_id, category.get("id", 0))
		return max_id + 1

	def infer_next_tag_id(self):
		max_id = 0
		for category in self.categories:
			for tag in category.get("tags", []):
				max_id = max(max_id, tag.get("id", 0))
		return max_id + 1

	def ensure_default_data(self):
		if not self.categories:
			self.categories = [
				{
					"id": 1,
					"name": "默认分类",
					"tags": [{"id": 1, "title": "标签 1", "content": ""}],
				}
			]
			self.next_category_id = max(self.next_category_id, 2)
			self.next_tag_id = max(self.next_tag_id, 2)
			return

		for category in self.categories:
			category.setdefault("tags", [])

		if self.next_category_id < 1:
			self.next_category_id = self.infer_next_category_id()
		if self.next_tag_id < 1:
			self.next_tag_id = self.infer_next_tag_id()

	def save_data(self):
		data = {
			"categories": self.categories,
			"next_category_id": self.next_category_id,
			"next_tag_id": self.next_tag_id,
			"settings": {
				"main_alpha": round(float(self.main_alpha_var.get()), 2),
			},
		}
		with open(self.data_file, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)

	def on_main_alpha_change(self, _value=None):
		self.root.attributes("-alpha", self.main_alpha_var.get())
		self.root.after(120, self.save_data)

	def get_current_category(self):
		for category in self.categories:
			if category.get("id") == self.current_category_id:
				return category
		return None

	def get_current_tags(self):
		category = self.get_current_category()
		if not category:
			return []
		return category.get("tags", [])

	def get_current_tag(self):
		for tag in self.get_current_tags():
			if tag.get("id") == self.current_tag_id:
				return tag
		return None

	def move_item(self, items, from_index, to_index):
		if from_index == to_index:
			return items
		if from_index < 0 or from_index >= len(items):
			return items
		if to_index < 0:
			to_index = 0
		if to_index >= len(items):
			to_index = len(items) - 1
		item = items.pop(from_index)
		items.insert(to_index, item)
		return items

	def set_drag_feedback(self, active, kind=None):
		if active:
			self.root.configure(cursor="fleur")
			if kind == "category":
				self.feedback_var.set("正在拖动分类，松开鼠标完成排序")
			elif kind == "tag":
				self.feedback_var.set("正在拖动标签，松开鼠标完成排序")
			else:
				self.feedback_var.set("正在拖动中")
		else:
			self.root.configure(cursor="")
			self.feedback_var.set("双击分类可重命名，拖动分类/标签可排序")

	def get_scroll_fraction(self, listbox):
		try:
			return listbox.yview()[0]
		except tk.TclError:
			return 0.0

	def restore_scroll_fraction(self, listbox, fraction):
		try:
			listbox.yview_moveto(max(0.0, min(1.0, fraction)))
		except tk.TclError:
			pass

	def refresh_categories_list(self):
		scroll_fraction = self.get_scroll_fraction(self.categories_list)
		self.categories_list.delete(0, tk.END)
		for category in self.categories:
			self.categories_list.insert(tk.END, category.get("name", "分类"))

		for idx, category in enumerate(self.categories):
			if category.get("id") == self.current_category_id:
				self.categories_list.selection_set(idx)
				self.categories_list.activate(idx)
				break
		self.restore_scroll_fraction(self.categories_list, scroll_fraction)

	def refresh_tags_list(self):
		scroll_fraction = self.get_scroll_fraction(self.tags_list)
		self.tags_list.delete(0, tk.END)
		for tag in self.get_current_tags():
			preview = tag.get("content", "").replace("\n", " ").strip()
			preview = preview[:20] + ("..." if len(preview) > 20 else "")
			title = tag.get("title", "未命名")
			self.tags_list.insert(tk.END, f"{title}  {preview}")

		for idx, tag in enumerate(self.get_current_tags()):
			if tag.get("id") == self.current_tag_id:
				self.tags_list.selection_set(idx)
				self.tags_list.activate(idx)
				break
		self.restore_scroll_fraction(self.tags_list, scroll_fraction)

	def pick_initial_selection(self):
		if not self.categories:
			return
		if self.current_category_id is None:
			self.current_category_id = self.categories[0].get("id")
		current_category = self.get_current_category()
		if current_category and self.current_tag_id is None and current_category.get("tags"):
			self.current_tag_id = current_category.get("tags")[0].get("id")
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()

	def on_category_select(self, _event=None):
		sel = self.categories_list.curselection()
		if not sel:
			return
		idx = sel[0]
		if idx < 0 or idx >= len(self.categories):
			return
		self.current_category_id = self.categories[idx].get("id")
		current_category = self.get_current_category()
		self.current_tag_id = None
		if current_category and current_category.get("tags"):
			self.current_tag_id = current_category.get("tags")[0].get("id")
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()

	def on_tag_select(self, _event=None):
		sel = self.tags_list.curselection()
		if not sel:
			return
		idx = sel[0]
		tags = self.get_current_tags()
		if idx < 0 or idx >= len(tags):
			return
		self.current_tag_id = tags[idx].get("id")
		self.load_current_tag_to_editor()

	def load_current_tag_to_editor(self):
		tag = self.get_current_tag()
		self.loading_editor = True
		if not tag:
			self.note_title_var.set("")
			self.note_text.delete("1.0", tk.END)
			self.note_title_entry.config(state="disabled")
			self.note_text.config(state="disabled")
			self.loading_editor = False
			return

		self.note_title_entry.config(state="normal")
		self.note_text.config(state="normal")
		self.note_title_var.set(tag.get("title", ""))
		self.note_text.delete("1.0", tk.END)
		self.note_text.insert("1.0", tag.get("content", ""))
		self.loading_editor = False

	def add_category(self):
		category = {"id": self.next_category_id, "name": f"分类 {self.next_category_id}", "tags": []}
		self.next_category_id += 1
		self.categories.append(category)
		self.current_category_id = category["id"]
		self.current_tag_id = None
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()
		self.save_data()

	def delete_selected_category(self):
		category = self.get_current_category()
		if not category:
			return

		if len(self.categories) <= 1:
			messagebox.showwarning("提示", "至少保留一个分类。")
			return

		if not messagebox.askyesno("确认", f"确定删除分类「{category.get('name', '分类')}」及其全部标签吗？"):
			return

		self.categories = [item for item in self.categories if item.get("id") != category.get("id")]
		self.current_category_id = self.categories[0].get("id") if self.categories else None
		current_category = self.get_current_category()
		self.current_tag_id = None
		if current_category and current_category.get("tags"):
			self.current_tag_id = current_category.get("tags")[0].get("id")
		self.refresh_categories_list()
		self.refresh_tags_list()
		self.load_current_tag_to_editor()
		self.save_data()

	def rename_selected_category(self, _event=None):
		category = self.get_current_category()
		if not category:
			return

		new_name = simpledialog.askstring("重命名分类", "请输入新的分类名称：", initialvalue=category.get("name", "分类"), parent=self.root)
		if new_name is None:
			return

		new_name = new_name.strip()
		if not new_name:
			messagebox.showwarning("提示", "分类名称不能为空。")
			return

		category["name"] = new_name
		self.refresh_categories_list()
		self.save_data()

	def on_category_drag_start(self, event):
		self.category_drag_index = self.categories_list.nearest(event.y)
		self.dragging_category = True
		self.set_drag_feedback(True, "category")

	def on_category_drag_motion(self, event):
		if self.category_drag_index is None:
			return
		to_index = self.categories_list.nearest(event.y)
		if to_index == self.category_drag_index:
			return
		moved_category = self.categories[self.category_drag_index]
		self.categories = self.move_item(self.categories, self.category_drag_index, to_index)
		self.current_category_id = moved_category.get("id")
		self.category_drag_index = to_index
		self.refresh_categories_list()
		self.refresh_tags_list()

	def on_category_drag_end(self, _event):
		self.category_drag_index = None
		self.dragging_category = False
		if not self.dragging_tag:
			self.set_drag_feedback(False)
		self.save_data()

	def add_tag(self):
		category = self.get_current_category()
		if not category:
			messagebox.showwarning("提示", "请先选择一个分类。")
			return

		tag = {"id": self.next_tag_id, "title": f"标签 {self.next_tag_id}", "content": ""}
		self.next_tag_id += 1
		category.setdefault("tags", []).append(tag)
		self.current_tag_id = tag["id"]
		self.refresh_tags_list()
		self.load_current_tag_to_editor()
		self.save_data()

	def delete_selected_tag(self):
		category = self.get_current_category()
		tag = self.get_current_tag()
		if not category or not tag:
			return

		if not messagebox.askyesno("确认", "确定删除该标签吗？"):
			return

		category["tags"] = [item for item in category.get("tags", []) if item.get("id") != tag.get("id")]
		self.current_tag_id = category["tags"][0].get("id") if category.get("tags") else None
		self.refresh_tags_list()
		self.load_current_tag_to_editor()
		self.save_data()

	def on_tag_drag_start(self, event):
		self.tag_drag_index = self.tags_list.nearest(event.y)
		self.dragging_tag = True
		self.set_drag_feedback(True, "tag")

	def on_tag_drag_motion(self, event):
		if self.tag_drag_index is None:
			return
		category = self.get_current_category()
		if not category:
			return
		to_index = self.tags_list.nearest(event.y)
		if to_index == self.tag_drag_index:
			return
		tags = category.get("tags", [])
		moved_tag = tags[self.tag_drag_index]
		category["tags"] = self.move_item(tags, self.tag_drag_index, to_index)
		self.current_tag_id = moved_tag.get("id")
		self.tag_drag_index = to_index
		self.refresh_tags_list()

	def on_tag_drag_end(self, _event):
		self.tag_drag_index = None
		self.dragging_tag = False
		if not self.dragging_category:
			self.set_drag_feedback(False)
		self.save_data()

	def schedule_save_current(self):
		if self.loading_editor:
			return
		if self.save_after_id:
			self.root.after_cancel(self.save_after_id)
		self.save_after_id = self.root.after(220, self.save_current_note)

	def save_current_note(self):
		self.save_after_id = None
		if self.loading_editor:
			return
		tag = self.get_current_tag()
		if not tag:
			return

		title = self.note_title_var.get().strip()
		tag["title"] = title if title else f"标签 {tag.get('id', 0)}"
		tag["content"] = self.note_text.get("1.0", tk.END).rstrip("\n")
		self.refresh_tags_list()
		self.save_data()

	def hide_to_tray(self):
		self.root.withdraw()

	def show_from_tray(self):
		self.root.deiconify()
		self.root.lift()
		self.root.focus_force()

	def on_close_main(self):
		# 关闭主窗口时默认最小化到托盘，保证后台可继续运行。
		self.hide_to_tray()

	def quit_app(self):
		self.save_data()
		if self.tray_icon:
			self.tray_icon.stop()
		self.root.quit()

	def create_tray_image(self):
		img = Image.new("RGBA", (64, 64), (246, 219, 124, 255))
		draw = ImageDraw.Draw(img)
		draw.rectangle((8, 8, 56, 56), outline=(102, 79, 32, 255), width=3)
		draw.line((16, 22, 48, 22), fill=(102, 79, 32, 255), width=3)
		draw.line((16, 32, 46, 32), fill=(102, 79, 32, 255), width=3)
		draw.line((16, 42, 44, 42), fill=(102, 79, 32, 255), width=3)
		return img

	def create_tray_icon(self):
		menu = pystray.Menu(
			pystray.MenuItem("显示", lambda: self.root.after(0, self.show_from_tray)),
			pystray.MenuItem("新建标签", lambda: self.root.after(0, self.add_tag)),
			pystray.MenuItem("隐藏", lambda: self.root.after(0, self.hide_to_tray)),
			pystray.MenuItem("退出", lambda: self.root.after(0, self.quit_app)),
		)
		self.tray_icon = pystray.Icon(APP_NAME, self.create_tray_image(), "桌面便签", menu)

		thread = threading.Thread(target=self.tray_icon.run, daemon=True)
		thread.start()

	def get_startup_command(self) -> str:
		if getattr(sys, "frozen", False):
			return f'"{sys.executable}"'
		return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

	def is_startup_enabled(self) -> bool:
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
			messagebox.showerror("错误", "当前系统不支持开机自启设置。")
			self.startup_var.set(False)
			return

		try:
			with winreg.OpenKey(
				winreg.HKEY_CURRENT_USER,
				r"Software\Microsoft\Windows\CurrentVersion\Run",
				0,
				winreg.KEY_SET_VALUE,
			) as key:
				if self.startup_var.get():
					winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self.get_startup_command())
				else:
					try:
						winreg.DeleteValue(key, APP_NAME)
					except OSError:
						pass
			messagebox.showinfo("完成", "开机自启设置已更新。")
		except OSError as e:
			messagebox.showerror("错误", f"设置失败: {e}")
			self.startup_var.set(self.is_startup_enabled())


def main():
	root = tk.Tk()
	app = StickyNotesApp(root)

	root.mainloop()


if __name__ == "__main__":
	main()
