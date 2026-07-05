# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sugar's classic home ring layout for the studio home screen."""

import math

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk  # noqa: E402

from sugar3.graphics import style  # noqa: E402


# Sugar's home-ring constants, ported from
# jarabe/desktop/favoriteslayout.py (RingLayout) so the studio's home
# matches the shell's geometry.
_RING_MINIMUM_RADIUS = style.XLARGE_ICON_SIZE / 2 + style.DEFAULT_SPACING
_RING_SPACING_FACTOR = 0.95
_SPIRAL_SPACING_FACTOR = 0.75
_RING_RADIUS_GROWTH_FACTOR = 1.25
_RING_MINIMUM_RADIUS_PADDING_FACTOR = 0.85
_RING_MAXIMUM_RADIUS_PADDING_FACTOR = 1.25
_RING_INITIAL_ANGLE = math.pi


class HomeRingLayout(Gtk.Fixed):
    """Sugar's classic home ring, ported from jarabe's RingLayout.

    A center widget sits in the middle; item widgets are laid out on a
    ring around it, falling back to Sugar's spiral when the ring would
    not fit the allocated height.
    """

    def __init__(self):
        Gtk.Fixed.__init__(self)
        self._center = None
        self.items = []
        self._spiral_mode = False
        self._placed = {}

    def set_center(self, widget):
        if self._center is not None:
            self.remove(self._center)
        self._center = widget
        if widget is not None:
            self.put(widget, 0, 0)
            widget.show()
        self._placed = {}
        self._layout_now()

    def set_items(self, widgets):
        for child in self.items:
            self.remove(child)
        self.items = list(widgets)
        for child in self.items:
            self.put(child, 0, 0)
            child.show()
        self._placed = {}
        self._layout_now()

    def _layout_now(self):
        """Re-place children immediately when they change.

        GTK does not re-emit size-allocate when the container's
        rectangle is unchanged, so adding items to an already-shown
        ring must trigger the layout by hand.
        """
        self.queue_resize()
        if self.get_allocated_width() > 1:
            self._layout_children(self.get_allocation())

    def _calculate_maximum_radius(self, icon_size, height):
        radius = (height - style.GRID_CELL_SIZE) / 2 - \
            style.DEFAULT_SPACING
        return radius - (icon_size * _RING_MAXIMUM_RADIUS_PADDING_FACTOR)

    def _calculate_radius_and_icon_size(self, children_count, height):
        self._spiral_mode = False

        icon_size = style.MEDIUM_ICON_SIZE
        angle_, radius = self._calculate_angle_and_radius(
            children_count, icon_size)
        if radius <= self._calculate_maximum_radius(icon_size, height):
            return radius, icon_size
        while radius > self._calculate_maximum_radius(icon_size, height):
            icon_size -= 1
            if icon_size <= style.STANDARD_ICON_SIZE:
                break
            angle_, radius = self._calculate_angle_and_radius(
                children_count, icon_size)
        if radius <= self._calculate_maximum_radius(icon_size, height):
            return radius, icon_size

        self._spiral_mode = True
        icon_size = style.MEDIUM_ICON_SIZE
        while radius > self._calculate_maximum_radius(icon_size, height):
            if icon_size < style.SMALL_ICON_SIZE:
                break
            angle_, radius = self._calculate_angle_and_radius(
                children_count, icon_size)
            icon_size -= 1
        return radius, icon_size

    def _calculate_angle_and_radius(self, icon_count, icon_size):
        if self._spiral_mode:
            icon_spacing_factor = _SPIRAL_SPACING_FACTOR
        else:
            icon_spacing_factor = _RING_SPACING_FACTOR

        # The diagonal width of an icon stabilises the spacing across a
        # wide range of circle and spiral sizes (same trick as Sugar).
        icon_spacing = math.sqrt(icon_size ** 2 * 2) * \
            icon_spacing_factor + style.DEFAULT_SPACING
        angle = _RING_INITIAL_ANGLE
        radius = _RING_MINIMUM_RADIUS + \
            (icon_spacing * _RING_MINIMUM_RADIUS_PADDING_FACTOR)
        for i_ in range(icon_count):
            circumference = radius * 2 * math.pi
            n = circumference / icon_spacing
            angle += (2 * math.pi / n)
            radius += (float(icon_spacing) *
                       _RING_RADIUS_GROWTH_FACTOR / n)
        return angle, radius

    def _calculate_position(self, radius, icon_size, icon_index,
                            children_count, width, height):
        if self._spiral_mode:
            angle, radius = self._calculate_angle_and_radius(
                icon_index, icon_size)
            x = int(math.sin(angle) * radius)
            y = int(math.cos(angle) * radius)
            x = - x + (width - icon_size) / 2
            y = y + (height - icon_size -
                     (style.GRID_CELL_SIZE / 2)) / 2
        else:
            angle = icon_index * (2 * math.pi / children_count) - \
                math.pi / 2
            x = radius * math.cos(angle) + (width - icon_size) / 2
            y = radius * math.sin(angle) + \
                (height - icon_size - (style.GRID_CELL_SIZE / 2)) / 2
        return int(x), int(y)

    def do_size_allocate(self, allocation):
        # Reposition children BEFORE chaining up: GTK3 ignores resize
        # requests queued from inside the allocation cycle, so moving
        # after the fact leaves icons at stale positions.
        self._layout_children(allocation)
        Gtk.Fixed.do_size_allocate(self, allocation)

    def _layout_children(self, allocation):
        width = allocation.width
        height = allocation.height
        if width <= 1 or height <= 1:
            return

        count = len(self.items)
        if count:
            radius, icon_size = self._calculate_radius_and_icon_size(
                count, height)
            for index, child in enumerate(self.items):
                try:
                    if child.props.pixel_size != icon_size:
                        child.props.pixel_size = icon_size
                except AttributeError:
                    pass
                x, y = self._calculate_position(
                    radius, icon_size, index, count, width, height)
                self._move_child(child, x, y)

        if self._center is not None:
            center_width = self._center.get_preferred_width()[0]
            center_height = self._center.get_preferred_height()[0]
            x = (width - center_width) / 2
            y = (height - style.GRID_CELL_SIZE / 2) / 2 - \
                center_height / 2
            self._move_child(self._center, x, y)

    def _move_child(self, child, x, y):
        position = (int(x), int(y))
        if self._placed.get(child) != position:
            self._placed[child] = position
            self.move(child, position[0], position[1])
