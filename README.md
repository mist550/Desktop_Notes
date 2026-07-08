# Desktop Sticky Notes

一个基于 Tkinter 的桌面便签工具，支持：

- 便签创建、编辑、删除
- 自动保存便签内容和窗口位置
- 最小化到系统托盘（后台运行）
- 开机自启开关（Windows）
- 打包为独立可执行文件（EXE）

## 运行

```bat
python -m pip install -r requirements.txt
python main.py
```

## 打包为独立 EXE

```bat
build_exe.bat
```

打包产物位置：

- `dist\DesktopStickyNotes.exe`

## 使用说明

- 启动后默认隐藏到托盘，右键托盘图标选"显示"打开主界面
- 左侧先选择分类，再管理该分类内的标签
- 双击分类名可重命名
- 拖动分类或标签可调整排序顺序
- 点击标签可在右侧编辑内容，自动保存
- 关闭主窗口会隐藏到托盘，不会退出程序
- 勾选"开机自启"可自动启动该程序

## 数据存储

所有数据保存在本地用户应用数据目录：

```
C:\Users\{用户名}\AppData\Roaming\DesktopStickyNotes\notes.json
```

或快速访问：`%APPDATA%\DesktopStickyNotes\notes.json`

数据文件包含：
- 分类和标签的名称、内容
- 主窗口透明度设置
- 下次启动时会自动加载
