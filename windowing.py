"""Position application-owned child windows without touching user data."""
import os


def centered_position(parent, size, work_area):
    """Rectangles use absolute desktop coordinates, including negative monitors."""
    left, top, right, bottom = work_area
    width, height = size
    if parent is None:
        x, y = left + (right - left - width) // 2, top + (bottom - top - height) // 2
    else:
        px, py, pw, ph = parent
        x, y = px + (pw - width) // 2, py + (ph - height) // 2
    return max(left, min(x, right - width)), max(top, min(y, bottom - height))


def _windows_bounds(parent, child):
    """Get the parent's monitor work area and actual window-frame dimensions."""
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    parent_hwnd = user.GetAncestor(parent.winfo_id(), 2)
    child_hwnd = user.GetAncestor(child.winfo_id(), 2)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    outer, client, parent_rect = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
    if not (user.GetMonitorInfoW(user.MonitorFromWindow(parent_hwnd, 2), ctypes.byref(info))
            and user.GetWindowRect(child_hwnd, ctypes.byref(outer))
            and user.GetClientRect(child_hwnd, ctypes.byref(client))
            and user.GetWindowRect(parent_hwnd, ctypes.byref(parent_rect))):
        raise OSError("Cannot query monitor bounds")
    area = (info.work.left, info.work.top, info.work.right, info.work.bottom)
    frame = (max(0, outer.right - outer.left - client.right),
             max(0, outer.bottom - outer.top - client.bottom))
    bounds = (parent_rect.left, parent_rect.top,
              parent_rect.right - parent_rect.left, parent_rect.bottom - parent_rect.top)
    return area, frame, bounds


def show_child_window(window, parent):
    """Center on the current parent; clamp the entire frame above the taskbar.

    New windows should be withdrawn immediately on creation, so their first
    visible frame is already positioned. Existing windows are repositioned too.
    """
    window.update_idletasks()
    width, height = window.winfo_width(), window.winfo_height()
    if width <= 1 or height <= 1:
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    left, top = parent.winfo_vrootx(), parent.winfo_vrooty()
    area = (left, top, left + parent.winfo_vrootwidth(), top + parent.winfo_vrootheight())
    bounds = (parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height())
    frame = (0, 0)
    if os.name == "nt":
        try:
            area, frame, bounds = _windows_bounds(parent, window)
        except (OSError, AttributeError):
            pass
    if not parent.winfo_viewable():
        bounds = None
    x, y = centered_position(bounds, (width + frame[0], height + frame[1]), area)
    # '+-700' is an absolute negative coordinate. '-700' anchors to the right.
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.deiconify()
    window.lift()
    window.focus_set()
