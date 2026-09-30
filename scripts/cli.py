"""Widgets da CLI interativa implementados com a biblioteca curses."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import TypeVar

try:
    import curses
except ImportError:  # pragma: no cover - depende do sistema
    curses = None  # type: ignore[assignment]


T = TypeVar("T")


class Cancelled(Exception):
    pass


def _safe_add(stdscr, row: int, column: int, text: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if 0 <= row < height and column < width:
        try:
            stdscr.addnstr(row, column, text, max(0, width - column - 1), attr)
        except curses.error:
            pass


def _select_screen(stdscr, title: str, items: Sequence[str], multiple: bool, default: int) -> list[int]:
    if not items:
        raise ValueError(f"Nenhum item disponivel em '{title}'.")
    curses.curs_set(0)
    stdscr.keypad(True)
    cursor = min(max(default, 0), len(items) - 1)
    selected: set[int] = set()
    while True:
        stdscr.erase()
        height, _ = stdscr.getmaxyx()
        _safe_add(stdscr, 0, 0, title, curses.A_BOLD)
        help_text = (
            "Setas: mover | Espaco: marcar/desmarcar | Enter: confirmar | Ctrl+C: cancelar"
            if multiple
            else "Setas: mover | Enter: escolher | Ctrl+C: cancelar"
        )
        _safe_add(stdscr, 1, 0, help_text, curses.A_DIM)
        visible = max(1, height - 5)
        first = max(0, min(cursor - visible // 2, max(0, len(items) - visible)))
        for row, index in enumerate(range(first, min(len(items), first + visible)), start=3):
            pointer = ">" if index == cursor else " "
            mark = "[x]" if index in selected else "[ ]"
            prefix = f"{pointer} {mark if multiple else '  '} "
            attr = curses.A_REVERSE if index == cursor else 0
            _safe_add(stdscr, row, 0, prefix + items[index], attr)
        if len(items) > visible:
            _safe_add(stdscr, height - 1, 0, f"Item {cursor + 1} de {len(items)}", curses.A_DIM)
        stdscr.refresh()
        key = stdscr.getch()
        if key in (3, 27):
            raise Cancelled
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(items)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(items)
        elif key == ord(" ") and multiple:
            selected.symmetric_difference_update({cursor})
        elif key in (10, 13, curses.KEY_ENTER):
            return sorted(selected) if multiple and selected else [cursor]


def select(title: str, items: Sequence[str], *, multiple: bool = False, default: int = 0) -> list[int]:
    if curses is None:
        raise RuntimeError(
            "A CLI interativa no Windows requer 'windows-curses'. Execute: py -m pip install -r requirements.txt"
        )
    return curses.wrapper(_select_screen, title, items, multiple, default)


def _input_screen(
    stdscr,
    title: str,
    prompt: str,
    default: str,
    validator: Callable[[str], T],
) -> T:
    curses.curs_set(1)
    stdscr.keypad(True)
    value = default
    error = ""
    while True:
        stdscr.erase()
        _safe_add(stdscr, 0, 0, title, curses.A_BOLD)
        _safe_add(stdscr, 1, 0, prompt, curses.A_DIM)
        _safe_add(stdscr, 3, 0, "> " + value)
        if error:
            _safe_add(stdscr, 5, 0, error, curses.A_BOLD)
        stdscr.move(3, min(2 + len(value), max(2, stdscr.getmaxyx()[1] - 2)))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (3, 27):
            raise Cancelled
        if key in (10, 13, curses.KEY_ENTER):
            try:
                return validator(value)
            except (ValueError, TypeError) as exc:
                error = str(exc)
        elif key in (curses.KEY_BACKSPACE, 8, 127):
            value = value[:-1]
        elif 32 <= key <= 126:
            value += chr(key)


def input_value(title: str, prompt: str, *, default: str, validator: Callable[[str], T]) -> T:
    if curses is None:
        raise RuntimeError(
            "A CLI interativa no Windows requer 'windows-curses'. Execute: py -m pip install -r requirements.txt"
        )
    return curses.wrapper(_input_screen, title, prompt, default, validator)
