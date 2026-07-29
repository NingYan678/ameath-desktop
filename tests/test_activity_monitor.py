from digital_pet.activity_monitor import _Rect, is_true_fullscreen


def rect(left, top, right, bottom):
    return _Rect(left, top, right, bottom)


def test_maximized_work_window_is_not_treated_as_true_fullscreen():
    monitor = rect(0, 0, 1920, 1080)
    assert not is_true_fullscreen(rect(0, 0, 1920, 1040), monitor, maximized=True)


def test_borderless_monitor_sized_window_is_true_fullscreen():
    monitor = rect(0, 0, 1920, 1080)
    assert is_true_fullscreen(rect(1, 0, 1919, 1080), monitor, maximized=False)


def test_large_window_without_full_edges_is_not_true_fullscreen():
    monitor = rect(0, 0, 1920, 1080)
    assert not is_true_fullscreen(rect(0, 0, 1920, 1040), monitor, maximized=False)
