"""Task-oriented Tk interface. No file I/O or note mutation lives here."""
import tkinter as tk
from tkinter import font as tkfont, ttk

FONT = "Microsoft YaHei UI"
THEME = {
    "bg": "#f4f6f8", "panel": "#ffffff", "panel_alt": "#f0f4f5",
    "text": "#20333e", "muted": "#526570", "accent": "#106b63",
    "accent_active": "#08534d", "editor_bg": "#fffefa",
    "editor_fg": "#20333e", "border": "#d3dde1", "selection": "#daeee8",
    "danger": "#a32935", "notice": "#eaf4ef",
}


class NotesUI:
    def setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.list_font = tkfont.Font(root=self.root, family=FONT, size=10)
        for name, bg in (("App", "bg"), ("Panel", "panel"), ("Toolbar", "panel_alt")):
            style.configure(f"{name}.TFrame", background=THEME[bg])
        for name, bg, fg in (
            ("App", "accent", "panel"), ("Ghost", "panel_alt", "text"),
        ):
            style.configure(f"{name}.TButton", background=THEME[bg], foreground=THEME[fg],
                            borderwidth=1, bordercolor=THEME[bg], padding=(12, 9),
                            focusthickness=2, focuscolor=THEME[fg], font=(FONT, 10))
            style.map(f"{name}.TButton", background=[("active", THEME["accent_active"] if name == "App" else THEME["selection"])],
                      bordercolor=[("focus", THEME["accent"])])
        style.configure("Action.TMenubutton", background=THEME["panel_alt"], foreground=THEME["text"],
                        padding=(10, 8), borderwidth=1, bordercolor=THEME["border"],
                        focusthickness=2, focuscolor=THEME["accent"], font=(FONT, 10))
        style.map("Action.TMenubutton", background=[("active", THEME["selection"])],
                  bordercolor=[("focus", THEME["accent"])])
        for name, rowheight, bg in (("Categories", 38, "panel_alt"), ("Notes", 68, "panel")):
            style.configure(f"{name}.Treeview", background=THEME[bg], fieldbackground=THEME[bg],
                            foreground=THEME["text"], font=(FONT, 10), rowheight=rowheight,
                            borderwidth=0, indent=10)
            style.map(f"{name}.Treeview", background=[("selected", THEME["selection"])],
                      foreground=[("selected", THEME["accent_active"])])
        style.configure("App.TCheckbutton", background=THEME["panel"], foreground=THEME["text"], font=(FONT, 10))
        style.map("App.TCheckbutton", background=[("active", THEME["panel"])])
        style.configure("Vertical.TScrollbar", background=THEME["border"], troughcolor=THEME["panel"],
                        bordercolor=THEME["panel"], lightcolor=THEME["border"], darkcolor=THEME["border"],
                        arrowcolor=THEME["muted"], borderwidth=0, arrowsize=14)

    @staticmethod
    def label(parent, text="", variable=None, bg="panel", fg="text", size=10, bold=False, **options):
        return tk.Label(parent, text=text, textvariable=variable, bg=THEME[bg], fg=THEME[fg],
                        font=(FONT, size, "bold" if bold else "normal"), anchor="w", **options)

    def list_panel(self, parent, style):
        shell = tk.Frame(parent, bg=THEME["border"], highlightbackground=THEME["border"],
                         highlightcolor=THEME["accent"], highlightthickness=2, bd=0)
        shell.pack(fill=tk.BOTH, expand=True)
        view = ttk.Treeview(shell, show="tree", selectmode="browse", style=style, height=1, takefocus=True)
        view.column("#0", width=100, minwidth=70, stretch=True)
        view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(shell, command=view.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        view.configure(yscrollcommand=scroll.set)
        view.bind("<FocusIn>", lambda _e: shell.configure(highlightbackground=THEME["accent"]))
        view.bind("<FocusOut>", lambda _e: shell.configure(highlightbackground=THEME["border"]))
        return view

    def build_ui(self):
        self.outer = ttk.Frame(self.root, style="App.TFrame", padding=(16, 12, 16, 8))
        self.outer.pack(fill=tk.BOTH, expand=True)
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(1, weight=1)
        header = ttk.Frame(self.outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.label(header, "桌面便签", bg="bg", size=16, bold=True).pack(side=tk.LEFT)
        self.label(header, "  /  我的记录", bg="bg", fg="muted").pack(side=tk.LEFT, padx=(6, 0))
        self.help_button = ttk.Button(header, text="使用帮助", style="Ghost.TButton", command=self.show_help)
        self.help_button.pack(side=tk.RIGHT)
        ttk.Button(header, text="设置", style="Ghost.TButton", command=self.show_settings).pack(side=tk.RIGHT, padx=(8, 8))
        self.export_button = ttk.Button(header, text="导出备份", style="Ghost.TButton", command=self.export_data)
        self.export_button.pack(side=tk.RIGHT)

        self.workspace = tk.PanedWindow(self.outer, orient=tk.HORIZONTAL, bg=THEME["border"],
                                       sashwidth=6, sashrelief=tk.FLAT, bd=0, opaqueresize=True)
        self.workspace.grid(row=1, column=0, sticky="nsew")
        navigation = tk.Frame(self.workspace, bg=THEME["panel_alt"], padx=12, pady=14)
        browser = tk.Frame(self.workspace, bg=THEME["panel"], padx=14, pady=14)
        editor = tk.Frame(self.workspace, bg=THEME["editor_bg"], padx=22, pady=16)
        self.workspace.add(navigation, width=176, minsize=160, stretch="never")
        self.workspace.add(browser, width=264, minsize=220, stretch="never")
        self.workspace.add(editor, minsize=340, stretch="always")
        self.label(navigation, "分类", bg="panel_alt", bold=True, size=11).pack(anchor="w", pady=(0, 10))
        self.categories_list = self.list_panel(navigation, "Categories.Treeview")
        self.categories_list.configure(columns=("count",))
        self.categories_list.column("count", width=26, minwidth=26, stretch=False, anchor="e")
        self.categories_list.bind("<Configure>", lambda _event: self.refresh_categories_list())
        self.categories_list.bind("<<TreeviewSelect>>", self.on_category_select)
        self.categories_list.bind("<Double-Button-1>", self.rename_selected_category)
        self.bind_drag(self.categories_list, "category")
        self.category_add_button = ttk.Button(navigation, text="＋ 新建分类", style="Ghost.TButton", command=self.add_category)
        self.category_add_button.pack(fill=tk.X, pady=(12, 8))
        self.category_menu_button = ttk.Menubutton(navigation, text="分类操作", style="Action.TMenubutton")
        self.category_menu_button.pack(fill=tk.X)
        self.category_menu = self.build_item_menu(self.category_menu_button, "category")

        heading = tk.Frame(browser, bg=THEME["panel"])
        heading.pack(fill=tk.X, pady=(0, 4))
        self.list_title_var = tk.StringVar()
        self.label(heading, variable=self.list_title_var, size=12, bold=True).pack(anchor="w")
        self.list_count_var = tk.StringVar()
        self.label(browser, variable=self.list_count_var, fg="muted", size=9).pack(anchor="w", pady=(0, 12))
        self.new_note_button = ttk.Button(browser, text="＋ 新建便签", style="App.TButton", command=self.add_tag)
        self.new_note_button.pack(fill=tk.X, pady=(0, 16))
        self.label(browser, "搜索当前分类  ·  Ctrl+F", size=9, fg="muted").pack(anchor="w", pady=(0, 6))
        search = tk.Frame(browser, bg=THEME["panel"])
        search.pack(fill=tk.X, pady=(0, 12))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search, textvariable=self.search_var, bg=THEME["panel"], fg=THEME["text"],
                                     insertbackground=THEME["accent"], font=(FONT, 10), bd=0,
                                     highlightthickness=2, highlightbackground=THEME["border"],
                                     highlightcolor=THEME["accent"], width=8)
        self.search_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipady=7)
        self.clear_search_button = ttk.Button(search, text="清空", width=4, style="Ghost.TButton", command=lambda: self.search_var.set(""))
        self.clear_search_button.pack(side=tk.RIGHT, padx=(4, 0))
        browser_stack = tk.Frame(browser, bg=THEME["panel"])
        browser_stack.pack(fill=tk.BOTH, expand=True)
        browser_stack.rowconfigure(0, weight=1)
        browser_stack.columnconfigure(0, weight=1)
        list_holder = tk.Frame(browser_stack, bg=THEME["panel"])
        list_holder.grid(row=0, column=0, sticky="nsew")
        self.tags_list = self.list_panel(list_holder, "Notes.Treeview")
        self.tags_list.bind("<Configure>", lambda _event: self.refresh_tags_list())
        self.tags_list.bind("<<TreeviewSelect>>", self.on_tag_select)
        self.bind_drag(self.tags_list, "tag")
        self.list_empty = tk.Frame(browser_stack, bg=THEME["panel"], padx=8, pady=28)
        self.list_empty.grid(row=0, column=0, sticky="nsew")
        self.list_empty_var = tk.StringVar()
        self.label(self.list_empty, variable=self.list_empty_var, bold=True, wraplength=190, justify=tk.LEFT).pack(anchor="w")
        self.label(self.list_empty, "可以清空搜索，或新建一条便签。", fg="muted", size=9, wraplength=190, justify=tk.LEFT).pack(anchor="w", pady=(10, 0))
        self.list_holder = list_holder
        self.search_var.trace_add("write", lambda *_: self.refresh_tags_list())

        editor_header = tk.Frame(editor, bg=THEME["editor_bg"])
        editor_header.pack(fill=tk.X, pady=(0, 12))
        self.breadcrumb_var = tk.StringVar()
        self.label(editor_header, variable=self.breadcrumb_var, bg="editor_bg", fg="muted", size=9).pack(side=tk.LEFT)
        self.note_menu_button = ttk.Menubutton(editor_header, text="便签操作", style="Action.TMenubutton")
        self.note_menu_button.pack(side=tk.RIGHT)
        self.note_menu = self.build_item_menu(self.note_menu_button, "tag")
        self.editor_context_var = tk.StringVar()
        self.editor_context_label = self.label(editor, variable=self.editor_context_var, bg="editor_bg", fg="accent", size=9, wraplength=290, justify=tk.LEFT)
        stack = tk.Frame(editor, bg=THEME["editor_bg"])
        self.editor_stack = stack
        stack.pack(fill=tk.BOTH, expand=True)
        stack.rowconfigure(0, weight=1)
        stack.columnconfigure(0, weight=1)
        self.editor_content = tk.Frame(stack, bg=THEME["editor_bg"])
        self.editor_content.grid(row=0, column=0, sticky="nsew")
        self.label(self.editor_content, "标题", bg="editor_bg", fg="muted", size=9).pack(anchor="w", pady=(0, 4))
        self.note_title_var = tk.StringVar()
        self.note_title_entry = tk.Entry(self.editor_content, textvariable=self.note_title_var, bg=THEME["editor_bg"],
                                        fg=THEME["editor_fg"], insertbackground=THEME["accent"], relief=tk.FLAT,
                                        highlightthickness=2, highlightbackground=THEME["border"], highlightcolor=THEME["accent"],
                                        font=(FONT, 17, "bold"), disabledbackground=THEME["editor_bg"], width=8)
        self.note_title_entry.pack(fill=tk.X, ipady=7, pady=(0, 14))
        self.note_title_var.trace_add("write", lambda *_: self.schedule_save_current())
        self.label(self.editor_content, "正文", bg="editor_bg", fg="muted", size=9).pack(anchor="w", pady=(0, 4))
        text_area = tk.Frame(self.editor_content, bg=THEME["editor_bg"])
        text_area.pack(fill=tk.BOTH, expand=True)
        self.note_text = tk.Text(text_area, wrap=tk.WORD, bg=THEME["editor_bg"], fg=THEME["editor_fg"],
                                 insertbackground=THEME["accent"], selectbackground=THEME["selection"], relief=tk.FLAT,
                                 highlightthickness=2, highlightbackground=THEME["border"], highlightcolor=THEME["accent"],
                                 font=(FONT, 11), height=1, width=1, spacing1=3, spacing3=6, padx=12, pady=10,
                                 undo=True, autoseparators=True, maxundo=200)
        self.note_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(text_area, command=self.note_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.note_text.configure(yscrollcommand=scroll.set)
        self.note_text.bind("<<Modified>>", self.on_text_modified)
        self.editor_empty = tk.Frame(stack, bg=THEME["editor_bg"])
        self.editor_empty.grid(row=0, column=0, sticky="nsew")
        empty_center = tk.Frame(self.editor_empty, bg=THEME["editor_bg"])
        empty_center.place(relx=0.5, rely=0.4, anchor="center")
        self.label(empty_center, "这个分类还没有便签", bg="editor_bg", size=14, bold=True).pack(pady=(0, 10))
        self.label(empty_center, "新建一条，开始记录。内容会自动保存。", bg="editor_bg", fg="muted", size=10).pack(pady=(0, 18))
        ttk.Button(empty_center, text="＋ 新建便签", style="App.TButton", command=self.add_tag).pack()

        self.undo_bar = tk.Frame(self.outer, bg=THEME["notice"], padx=12, pady=8)
        self.undo_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.undo_var = tk.StringVar()
        self.label(self.undo_bar, variable=self.undo_var, bg="notice", size=10).pack(side=tk.LEFT)
        self.undo_button = ttk.Button(self.undo_bar, text="撤销删除", style="Ghost.TButton", command=self.undo_delete)
        self.undo_button.pack(side=tk.RIGHT)
        self.undo_bar.grid_remove()
        self.footer = tk.Frame(self.outer, bg=THEME["bg"])
        self.footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.status_var = tk.StringVar(value="自动保存已开启 · 记录仅保存在本机")
        self.status_label = self.label(self.footer, variable=self.status_var, bg="bg", fg="accent", size=9)
        self.status_label.pack(side=tk.LEFT)
        self.count_var = tk.StringVar()
        self.label(self.footer, variable=self.count_var, bg="bg", fg="muted", size=9).pack(side=tk.RIGHT)
        self.bind_item_context(self.categories_list, "category")
        self.bind_item_context(self.tags_list, "tag")

    def build_item_menu(self, button, kind):
        menu = tk.Menu(button, tearoff=False, font=(FONT, 10))
        if kind == "category":
            menu.add_command(label="重命名分类", accelerator="F2", command=self.rename_selected_category)
            menu.add_separator()
        menu.add_command(label="上移", command=lambda: self.move_selected(kind, -1))
        menu.add_command(label="下移", command=lambda: self.move_selected(kind, 1))
        menu.add_separator()
        menu.add_command(label="删除分类及其中的便签…" if kind == "category" else "删除这条便签…",
                         foreground=THEME["danger"], command=self.delete_selected_category if kind == "category" else self.delete_selected_tag)
        button.configure(menu=menu)
        button.configure(direction="below")
        return menu
